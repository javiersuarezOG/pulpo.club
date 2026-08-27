"""GEO-1 — HTTP plumbing for the geospatial enrichment providers.

Two things live here and nothing else: how we call an external API, and
what we do when that call fails. Provider modules stay pure fetch+parse.

Timeouts
--------
Every call passes an explicit five-phase ``httpx.Timeout``. A bare float
sets the total-ish budget but leaves the between-bytes read timer free to
reset forever: on 2026-06-13 a ``timeout=3.0`` against Cloudinary's
on-demand derivative endpoint hung the nightly 90s+ and froze three runs
(see ``pulpo/scrapers/_photo_url_upgrade.py``). NASA POWER in particular
dribbles a slow response, so this is not theoretical here.

``follow_redirects`` is off. A redirect chain was itself a hang vector in
that incident, and none of our providers legitimately redirect.

Retries
-------
``call_with_retry`` delegates the *decision* to
``pulpo.scrapers._runtime.decide_retry`` — a pure, unit-tested function
that honors ``Retry-After`` (SoilGrids sends it), retries 429/5xx and
transient exceptions, and refuses to retry other 4xx. We reuse it rather
than growing a second backoff implementation; the scraper ``Policy``
dataclass supplies the two fields it reads (``retry_max``,
``retry_backoff_base_s``) and nothing about scraping leaks in.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from pulpo.scrapers._policy import Policy
from pulpo.scrapers._runtime import decide_retry


# Descriptive UA, matching automation/geocoding_nominatim.py. Overpass and
# Nominatim require one; the rest tolerate it. A contactable UA is the
# difference between a rate-limit and a ban.
USER_AGENT = "pulpo.club/0.1 (sebastian@pulpo.club)"

# Attempt budget for a single cell fetch. Deliberately small: a cell that
# fails today is simply refetched tomorrow (failures are never cached), so
# there is no reason to spend the run's wall clock grinding on one cell.
GEO_RETRY_POLICY = Policy(retry_max=3, retry_backoff_base_s=1.5)


def _timeout(timeout_s: float):
    import httpx
    return httpx.Timeout(
        timeout_s,
        connect=timeout_s,
        read=timeout_s,
        write=timeout_s,
        pool=timeout_s,
    )


def default_http_get(url: str,
                     params: dict,
                     headers: dict,
                     timeout_s: float):
    """Real httpx.get — separated so tests can inject a stub."""
    import httpx
    return httpx.get(
        url,
        params=params,
        headers=headers,
        timeout=_timeout(timeout_s),
        follow_redirects=False,
    )


def default_http_post(url: str,
                      data: Any,
                      headers: dict,
                      timeout_s: float):
    """Real httpx.post — Overpass wants the query in the body."""
    import httpx
    return httpx.post(
        url,
        data=data,
        headers=headers,
        timeout=_timeout(timeout_s),
        follow_redirects=False,
    )


def headers(extra: Optional[dict] = None) -> dict:
    base = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if extra:
        base.update(extra)
    return base


class HttpError(RuntimeError):
    """Non-retryable (or retry-exhausted) HTTP failure.

    Carries ``status_code`` so the orchestrator can classify an auth /
    quota problem as global — one bad key should disable a provider, not
    burn the whole budget one cell at a time.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def with_retry(http_fn: Callable,
               *,
               policy: Policy = GEO_RETRY_POLICY,
               sleep_fn: Optional[Callable[[float], None]] = None) -> Callable:
    """Wrap an HTTP callable so it retries transient failures transparently.

    Retry belongs HERE — under the provider, not around it. A provider's
    ``fetch()`` returns a parsed payload, and ``None`` from it is a
    meaningful answer ("no data for this cell"), not a failure to retry.
    Only the transport layer knows the difference, so the orchestrator
    hands providers an already-retrying ``http_get`` and they stay free of
    retry logic entirely.

    The returned callable has the same signature as the one passed in and
    only ever yields a 2xx response: anything else raises ``HttpError``
    (carrying ``status_code``) or the underlying transport exception.
    """
    import time as _time
    sleep = sleep_fn if sleep_fn is not None else _time.sleep

    def _wrapped(*args, **kwargs):
        attempt = 0
        while True:
            attempt += 1
            status: Optional[int] = None
            retry_after: Optional[str] = None
            exc: Optional[BaseException] = None

            try:
                resp = http_fn(*args, **kwargs)
                status = getattr(resp, "status_code", None)
                if status is None or 200 <= status < 300:
                    return resp
                hdrs = getattr(resp, "headers", None) or {}
                try:
                    retry_after = hdrs.get("Retry-After")
                except Exception:
                    retry_after = None
            except Exception as e:  # noqa: BLE001 — any transport error is a signal
                exc = e

            decision = decide_retry(
                attempt=attempt,
                policy=policy,
                status_code=status,
                retry_after=retry_after,
                exception=exc,
            )
            if decision.should_retry:
                if decision.sleep_seconds > 0:
                    sleep(decision.sleep_seconds)
                continue

            if exc is not None:
                raise exc
            raise HttpError(f"HTTP {status} ({decision.reason})",
                            status_code=status)

    return _wrapped
