"""Polite-request runtime — UA rotation, jitter, rate-limit, Retry-After.

What this adds on top of ``pulpo/agents/html_crawler.py``
---------------------------------------------------------
The existing ``html_crawler`` module already provides a shared httpx
client (``make_client``), a single-UA ``DEFAULT_HEADERS``, and a
``with_retries`` helper with fixed exponential backoff. That worked
fine for 6 sources. Two gaps surfaced once we started crawling more
aggressively:

1. **Single static UA.** Every nightly request leaves an identical
   fingerprint. Easy for any WAF to learn and block — which is exactly
   what bit realtyelsalvador.
2. **No Retry-After honoring.** ``with_retries`` always sleeps on a
   fixed exponential curve, ignoring the server's hint. When a host
   says "wait 30s," sleeping 1.5s and hammering again is what gets us
   IP-banned.
3. **No per-source rate limit.** Each scraper hand-coded its own
   ``REQUEST_DELAY``. Diverged silently. The token bucket below is one
   instance per source, configured from ``_policy``.

What this module is NOT
-----------------------
- It is not a base class. Existing scrapers can opt in opportunistically.
- It is not a proxy. Real WAF-bypass needs a residential IP pool; we
  don't pay for one. This module is for being a polite citizen so we
  don't get banned in the first place.
"""
from __future__ import annotations
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Optional

from pulpo.agents.html_crawler import HTTPX_OK
from pulpo.scrapers._policy import Policy, get_policy


# ── User-agent pools ──────────────────────────────────────────────────
#
# Realistic, current desktop UAs. Two pools today; add more as needed.
# The "default" pool intentionally includes the legacy pulpo-club UA so
# that opting-in to polite_get from an existing scraper is a no-op for
# logs/server-side analytics that bucket on UA.
UA_POOLS: dict[str, list[str]] = {
    "default": [
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
        ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
    ],
    "safari_macos": [
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"),
    ],
    "chrome_windows": [
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    ],
}


def pick_user_agent(pool: str = "default", rng: Optional[random.Random] = None) -> str:
    """Return a random UA from the named pool. Falls back to ``default`` if
    the pool name is unknown — never raises, so a typo doesn't break a
    nightly."""
    bucket = UA_POOLS.get(pool) or UA_POOLS["default"]
    r = rng or random
    return r.choice(bucket)


# ── Browser-realistic headers ─────────────────────────────────────────
#
# Several WAFs (Cloudflare fingerprint rules + a few SiteGround / Sucuri
# bot pages) 403 plain httpx because the request lacks the Sec-Fetch /
# Sec-CH-UA family that a real browser sends on a top-level navigation.
# Sending them universally is free for compliant sites and unblocks
# fingerprint-based gates without needing Playwright. Pattern lifted from
# events-discovery's http_client (post-2026-05-25 recovery work) and
# adapted to Pulpo's SV locale + multi-UA pool.
#
# Two pieces:
#   • _UNIVERSAL_BROWSER_HEADERS — Accept / Accept-Language / Sec-Fetch-*
#     identical across all UAs.
#   • _client_hints_for_ua(ua)  — Sec-CH-UA + Sec-CH-UA-Platform that ONLY
#     fire when the UA looks like Chrome / Edge / Chromium. Safari and
#     Firefox don't send client hints; matching that absence is part of
#     the realism.
#
# The combined set is applied automatically inside polite_get /
# polite_curl_cffi_get / polite_playwright_goto — no per-scraper wiring
# needed.

_UNIVERSAL_BROWSER_HEADERS: dict[str, str] = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    # SV-leaning locale — broker sites localize content where they can,
    # and "es-SV" reads more native than "en-US" to a Salvadoran WAF
    # rule tuned for tourist-bot traffic.
    "Accept-Language": "es-SV,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
}


def _client_hints_for_ua(user_agent: str) -> dict[str, str]:
    """Return Sec-CH-UA + Sec-CH-UA-Platform + Sec-CH-UA-Mobile for the
    given UA.

    Only Chromium-family browsers (Chrome / Edge / Opera) actually send
    these headers. Returning an empty dict for Safari / Firefox keeps
    the fingerprint coherent — a Safari UA paired with Sec-CH-UA
    headers would be more suspicious than no client hints at all.
    """
    if not isinstance(user_agent, str) or not user_agent:
        return {}
    if "Chrome/" not in user_agent or "Chromium" in user_agent:
        # The "Chromium" check is for the bare-bones Linux Chromium UA
        # which some sites flag separately. Safari / Firefox / Edge
        # (which include "Chrome/" historically) — we only emit hints
        # when the UA looks like vanilla Chrome.
        pass
    is_chrome = "Chrome/" in user_agent and "Safari/537.36" in user_agent
    if not is_chrome:
        return {}
    # Extract major version from "Chrome/121.0.0.0".
    import re as _re
    m = _re.search(r"Chrome/(\d+)", user_agent)
    if not m:
        return {}
    major = m.group(1)
    if "Windows" in user_agent:
        platform = '"Windows"'
    elif "Macintosh" in user_agent:
        platform = '"macOS"'
    elif "Linux" in user_agent:
        platform = '"Linux"'
    else:
        platform = '"Unknown"'
    return {
        "sec-ch-ua": (
            f'"Chromium";v="{major}", "Not?A_Brand";v="24", '
            f'"Google Chrome";v="{major}"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": platform,
    }


def browser_realistic_headers(user_agent: str) -> dict[str, str]:
    """Compose the universal + UA-specific headers a real desktop browser
    would send on a top-level navigation. Includes ``User-Agent`` so the
    caller can dict-merge in one step.
    """
    headers = {"User-Agent": user_agent}
    headers.update(_UNIVERSAL_BROWSER_HEADERS)
    headers.update(_client_hints_for_ua(user_agent))
    return headers


# ── Jitter ────────────────────────────────────────────────────────────


def jitter_sleep(policy: Policy, rng: Optional[random.Random] = None) -> float:
    """Sleep a uniform random duration from ``policy.jitter_ms``.

    Returns the seconds slept (useful for tests / metrics). When
    ``PULPO_DISABLE_JITTER=1`` is set (test env), returns 0 immediately.
    """
    if os.environ.get("PULPO_DISABLE_JITTER") == "1":
        return 0.0
    lo, hi = policy.jitter_ms
    if hi <= 0:
        return 0.0
    r = rng or random
    secs = r.uniform(lo, hi) / 1000.0
    time.sleep(secs)
    return secs


# ── Rate limiter (per-source token bucket) ────────────────────────────


class RateLimiter:
    """Thread-safe token bucket. One instance per source.

    Simple model: minimum interval between acquires = 1 / rps. If a call
    arrives sooner, sleep the remainder. No bursting — Pulpo's nightly
    is single-threaded per source today, but the lock keeps this safe
    if a future scraper goes concurrent.
    """

    def __init__(self, rps: float):
        self._min_interval = (1.0 / rps) if rps > 0 else 0.0
        # ``None`` means "no prior acquire" — first call returns immediately.
        # Initializing to 0.0 would incorrectly block when ``time.monotonic()``
        # is small (e.g. early in a freshly-spawned subprocess).
        self._last_at: Optional[float] = None
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until the next slot is available. Returns seconds waited."""
        if self._min_interval <= 0:
            return 0.0
        with self._lock:
            now = time.monotonic()
            if self._last_at is None:
                self._last_at = now
                return 0.0
            wait = (self._last_at + self._min_interval) - now
            if wait > 0:
                time.sleep(wait)
                self._last_at = now + wait
                return wait
            self._last_at = now
            return 0.0


_LIMITERS: dict[str, RateLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


def get_limiter(source: str, policy: Optional[Policy] = None) -> RateLimiter:
    """Return the singleton RateLimiter for ``source``."""
    p = policy or get_policy(source)
    with _LIMITERS_LOCK:
        lim = _LIMITERS.get(source)
        if lim is None or lim._min_interval != (1.0 / p.rate_limit_rps if p.rate_limit_rps > 0 else 0.0):
            lim = RateLimiter(p.rate_limit_rps)
            _LIMITERS[source] = lim
        return lim


# ── Retry with Retry-After honoring ───────────────────────────────────


@dataclass
class RetryDecision:
    should_retry: bool
    sleep_seconds: float
    reason: str


def _parse_retry_after(value: str) -> Optional[float]:
    """RFC-7231: either delta-seconds or HTTP-date. We only honor the
    delta-seconds form — HTTP-date is rare in practice and adds dep on
    email.utils.parsedate_to_datetime."""
    if not value:
        return None
    try:
        secs = float(value.strip())
        return max(0.0, min(secs, 300.0))  # cap at 5min — sanity guard
    except ValueError:
        return None


def decide_retry(
    *,
    attempt: int,
    policy: Policy,
    status_code: Optional[int] = None,
    retry_after: Optional[str] = None,
    exception: Optional[BaseException] = None,
) -> RetryDecision:
    """Pure function — given attempt N and signals, decide next move.

    Retry budget: ``policy.retry_max`` total attempts (so retry happens
    while ``attempt < retry_max``). Sleep:
      - If ``Retry-After`` present and parseable → honor it.
      - Else exponential: ``base * 2 ** (attempt - 1)``, capped at 60s.

    Retry on: 429, 5xx, transient network exceptions (caller decides
    which exceptions count as transient).
    """
    if attempt >= policy.retry_max:
        return RetryDecision(False, 0.0, "retry_budget_exhausted")

    ra = _parse_retry_after(retry_after or "")
    if ra is not None:
        return RetryDecision(True, ra, f"retry_after_{ra:.1f}s")

    base = policy.retry_backoff_base_s
    sleep = min(60.0, base * (2 ** (attempt - 1)))

    if status_code is not None:
        if status_code == 429:
            return RetryDecision(True, sleep, f"http_429_backoff_{sleep:.1f}s")
        if 500 <= status_code < 600:
            return RetryDecision(True, sleep, f"http_{status_code}_backoff_{sleep:.1f}s")
        return RetryDecision(False, 0.0, f"http_{status_code}_no_retry")

    if exception is not None:
        return RetryDecision(True, sleep, f"exc_{type(exception).__name__}_backoff_{sleep:.1f}s")

    return RetryDecision(False, 0.0, "no_signal")


# ── polite_get — the entry point most scrapers will use ───────────────


def polite_get(
    client,  # httpx.Client
    url: str,
    *,
    source: str,
    policy: Optional[Policy] = None,
    extra_headers: Optional[dict] = None,
    rng: Optional[random.Random] = None,
):
    """Polite GET wrapper for ``httpx.Client``.

    Pipeline per call:
      1. Acquire token from per-source rate limiter.
      2. Sleep jitter.
      3. Build headers: rotate UA from policy's pool, merge ``extra_headers``.
      4. Issue request.
      5. On 429 / 5xx / transient exception → respect Retry-After if
         present, exponential backoff otherwise, up to ``policy.retry_max``.
      6. On non-retryable failure → raise the exception or return the
         non-OK Response (caller decides).

    Returns the final ``httpx.Response``. Callers that need the raw
    exception on failure should wrap in ``try`` themselves — this
    function lets the final exception propagate after the retry budget
    is exhausted, mirroring ``with_retries``' contract.
    """
    if not HTTPX_OK:
        raise RuntimeError("httpx not installed — polite_get cannot run")

    import httpx  # local import: only required when not offline

    p = policy or get_policy(source)
    limiter = get_limiter(source, p)

    last_exc: Optional[BaseException] = None
    last_resp = None

    for attempt in range(1, p.retry_max + 1):
        limiter.acquire()
        jitter_sleep(p, rng)

        # Browser-realistic headers (Sec-Fetch-*, Accept-Language es-SV,
        # Sec-CH-UA when the UA is Chrome) — unblocks Cloudflare /
        # SiteGround fingerprint gates without needing a real browser.
        # Pre-2026-06 we sent only `User-Agent` here, which trips a
        # surprising number of cheap WAFs. extra_headers wins over the
        # defaults so a caller can still pin e.g. a custom Referer.
        headers = browser_realistic_headers(
            pick_user_agent(p.user_agent_pool, rng)
        )
        if extra_headers:
            headers.update(extra_headers)

        try:
            resp = client.get(url, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            last_exc = e
            decision = decide_retry(attempt=attempt, policy=p, exception=e)
            if decision.should_retry:
                time.sleep(decision.sleep_seconds)
                continue
            raise

        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            last_resp = resp
            decision = decide_retry(
                attempt=attempt,
                policy=p,
                status_code=resp.status_code,
                retry_after=resp.headers.get("Retry-After"),
            )
            if decision.should_retry:
                time.sleep(decision.sleep_seconds)
                continue
            return resp  # budget exhausted — let caller see the bad response

        return resp

    if last_resp is not None:
        return last_resp
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("polite_get exited the loop without a result — unreachable")


# ── polite_curl_cffi_get — TLS-impersonating sibling of polite_get ────
#
# Same contract as ``polite_get`` (rate-limit, jitter, retry, Retry-After-
# aware) but uses curl_cffi instead of httpx so the TLS handshake matches
# a real browser. Returns a wrapped object that exposes
# ``status_code``, ``headers``, ``text``, and ``content`` so callers can
# stay transport-agnostic.
#
# Why a wrapper and not "import the curl_cffi Response": curl_cffi's
# Response and httpx's Response are nominally similar but diverge on
# details (header case-insensitivity, ``raise_for_status`` behavior,
# encoding auto-detection). The thin wrapper documents the small surface
# that both transports must support and keeps the call sites in
# scrapers from leaking transport-specific quirks.


class _PoliteResponse:
    """Transport-agnostic Response facade returned by polite_curl_cffi_get.

    Mimics the minimum surface ``polite_get`` callers actually use:
    ``status_code``, ``headers`` (dict-like), ``text`` (decoded),
    ``content`` (bytes), and ``raise_for_status()``. Header lookup is
    case-insensitive on both transports already.
    """

    __slots__ = ("status_code", "headers", "text", "content", "url")

    def __init__(self, status_code: int, headers, text: str, content: bytes, url: str = ""):
        self.status_code = status_code
        self.headers = headers
        self.text = text
        self.content = content
        self.url = url

    def raise_for_status(self):
        """Match httpx.Response.raise_for_status() — raise on 4xx/5xx."""
        if 400 <= self.status_code < 600:
            # Use the stdlib URLError-friendly message — we don't pull
            # httpx here because curl_cffi callers shouldn't have to
            # import httpx just to catch the failure type.
            raise _PoliteHTTPError(
                f"HTTP {self.status_code} for url {self.url!r}",
                response=self,
            )


class _PoliteHTTPError(Exception):
    """Raised by ``_PoliteResponse.raise_for_status`` on 4xx/5xx.

    Mirrors httpx.HTTPStatusError's user-facing shape (a ``.response``
    attribute pointing at the failing response). Existing scrapers that
    catch a bare ``Exception`` around ``resp.raise_for_status()`` keep
    working unchanged; new code can ``except _PoliteHTTPError`` directly.
    """

    def __init__(self, msg: str, *, response: "_PoliteResponse"):
        super().__init__(msg)
        self.response = response


# Module-level handle to the curl_cffi.requests module. Lazy-imported on
# first use so the offline test path doesn't pull the C-extension dep.
_curl_requests = None


def _import_curl_cffi():
    global _curl_requests
    if _curl_requests is not None:
        return _curl_requests
    try:
        from curl_cffi import requests as _r   # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "curl_cffi not installed — polite_curl_cffi_get cannot run. "
            "Add curl_cffi to requirements.txt (already pinned in the "
            "default requirements; this branch fires when running outside "
            "the standard environment)."
        ) from e
    _curl_requests = _r
    return _r


def polite_curl_cffi_get(
    url: str,
    *,
    source: str,
    policy: Optional[Policy] = None,
    extra_headers: Optional[dict] = None,
    rng: Optional[random.Random] = None,
    timeout: float = 20.0,
):
    """Polite GET via curl_cffi (TLS handshake impersonation).

    Same rate-limit + jitter + retry contract as ``polite_get``.  No
    persistent client: each call opens its own connection. Hosts that
    need this transport (Cloudflare-fronted WAFs) are slow-rate-limited
    anyway, so the per-call connection setup cost is in the noise next
    to the polite-cadence sleep budget.

    Returns a ``_PoliteResponse`` with ``status_code``, ``headers``,
    ``text``, ``content`` — matching the subset of the httpx Response
    interface that scrapers actually consume.
    """
    p = policy or get_policy(source)
    if p.transport != "curl_cffi":
        # Defensive guard — calling the wrong polite_get is the kind of
        # bug that produces silent green-with-zero-records empty yields.
        raise RuntimeError(
            f"polite_curl_cffi_get called for source={source!r} whose "
            f"policy.transport is {p.transport!r}; use polite_get instead."
        )

    curl_requests = _import_curl_cffi()
    limiter = get_limiter(source, p)

    last_exc: Optional[BaseException] = None
    last_resp: Optional[_PoliteResponse] = None

    for attempt in range(1, p.retry_max + 1):
        limiter.acquire()
        jitter_sleep(p, rng)

        # Same browser-realistic header set as polite_get. curl_cffi's
        # TLS-impersonation handles JA3 fingerprint gates; these headers
        # handle the *application*-layer fingerprint gates (Cloudflare's
        # "Just a moment", SiteGround pages, etc.). Wearing both is what
        # closes the realistic-browser gap.
        headers = browser_realistic_headers(
            pick_user_agent(p.user_agent_pool, rng)
        )
        if extra_headers:
            headers.update(extra_headers)

        try:
            raw = curl_requests.get(
                url,
                headers=headers,
                impersonate=p.curl_cffi_impersonate,
                timeout=timeout,
            )
        except Exception as e:
            # curl_cffi raises its own exceptions (curl_cffi.curl.CurlError,
            # DNSError, TimeoutError). Treat any non-Response exception as
            # a transient and let the retry decision filter it.
            last_exc = e
            decision = decide_retry(attempt=attempt, policy=p, exception=e)
            if decision.should_retry:
                time.sleep(decision.sleep_seconds)
                continue
            # Out of budget — propagate so the caller's diagnostic-capture
            # path gets a real exception, not a synthetic 500.
            raise

        resp = _PoliteResponse(
            status_code=int(raw.status_code),
            headers=raw.headers,
            text=raw.text,
            content=raw.content,
            url=str(getattr(raw, "url", url) or url),
        )

        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            last_resp = resp
            decision = decide_retry(
                attempt=attempt,
                policy=p,
                status_code=resp.status_code,
                retry_after=(raw.headers.get("Retry-After") if hasattr(raw.headers, "get") else None),
            )
            if decision.should_retry:
                time.sleep(decision.sleep_seconds)
                continue
            return resp

        return resp

    if last_resp is not None:
        return last_resp
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("polite_curl_cffi_get exited the loop without a result — unreachable")


# ── polite_playwright_goto — Playwright equivalent ────────────────────


def polite_playwright_goto(
    page,  # playwright.sync_api.Page
    url: str,
    *,
    source: str,
    policy: Optional[Policy] = None,
    wait_until: str = "networkidle",
    timeout_ms: int = 45_000,
    rng: Optional[random.Random] = None,
):
    """Polite ``page.goto`` for Playwright Pages.

    Applies rate-limit + jitter from ``policy`` before the navigation.
    UA rotation is NOT applied here — Playwright contexts have a fixed
    UA set at context creation, and changing it mid-session is detectable
    (and slower than just rotating the context, which we don't bother
    with for daily runs). Caller controls the context UA via
    ``BrowserContext(user_agent=pick_user_agent(...))``.

    Returns the Playwright ``Response`` from ``page.goto``. On retryable
    failure (TimeoutError) retries per policy.
    """
    p = policy or get_policy(source)
    limiter = get_limiter(source, p)

    last_exc: Optional[BaseException] = None
    for attempt in range(1, p.retry_max + 1):
        limiter.acquire()
        jitter_sleep(p, rng)

        try:
            return page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        except Exception as e:
            # Playwright raises its own TimeoutError class — match by name
            # to avoid importing playwright at module load.
            last_exc = e
            cls = type(e).__name__
            if cls in ("TimeoutError", "PlaywrightTimeoutError", "Error"):
                decision = decide_retry(attempt=attempt, policy=p, exception=e)
                if decision.should_retry:
                    time.sleep(decision.sleep_seconds)
                    continue
            raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("polite_playwright_goto exited without result — unreachable")
