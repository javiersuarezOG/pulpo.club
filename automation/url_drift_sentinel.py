"""Source URL drift sentinel — PR-D1.

Daily HEAD-probe every source's ``health_probe_url`` (from
``pulpo/scrapers/_metadata.SCRAPER_METADATA``). Classifies the response
into one of 5 drift states and persists baseline state per-source under
``web/data/url_drift/<source>.json``.

Why this exists
---------------
A source can silently change its URL structure (artis-style /agenda →
/nl/agenda move; festileaks-style redirect to a blog) BEFORE the next
nightly's scraper returns zero listings. The 6-day 2026-05-26 freeze
surfaced exactly this gap: realtyelsalvador's WAF block was caught by
"zero listings" telemetry, but only after a full nightly run. The
sentinel catches the same class of failure one layer earlier (an HTTP
HEAD takes <1s vs ~60-min nightly).

Drift states
------------
- ``unreachable``    — HTTP status < 200 or >= 400 (or the request raised)
- ``redirect_drift`` — final URL post-normalize differs from baseline
- ``size_drift``     — |current_size - baseline_size| / baseline_size > 0.5
- ``status_drift``   — status code differs but both are 2xx
- ``ok``             — matches baseline; refreshes the saved baseline

Only ``ok`` refreshes the baseline. That's the self-healing property:
persistent drift keeps the baseline intact so the alert keeps firing
until a human looks. A transient 502 followed by 200 → ok → baseline
refreshed.

The classifier is a pure function over ``(probe_result, baseline)`` so
the tests at ``tests/test_url_drift_classifier.py`` cover every state
without touching the network.

Consumers (per CLAUDE.md producer-consumer rule, post-2026-06-02)
-----------------------------------------------------------------
- ``.github/workflows/pulpo-url-drift.yml`` runs this every 6h on the
  GitHub Actions cron and Slacks on any non-``ok`` state via
  ``SLACK_WEBHOOK_URL``.
- The operator dashboard (PR-S7) reads the JSON state files for the
  per-source drift pill.
- ``scripts/check_source_urls.py`` is the manual CLI wrapper.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import typing as t
import urllib.parse
from pathlib import Path


# ---------- Constants ----------

KNOWN_DRIFT_STATES: frozenset[str] = frozenset({
    "ok",
    "unreachable",
    "redirect_drift",
    "size_drift",
    "status_drift",
})
"""Closed set; producers must only emit these values. Contract test:
``tests/test_url_drift_classifier.py::test_known_states_contract``."""

SIZE_DRIFT_THRESHOLD = 0.5
"""±50% size delta vs baseline. Below this is normal page-content churn
(promo banner refresh, dynamic listing count); above this is structural
(template rewrite, redirect to a 4xx-style minimal error page)."""


# ---------- Data model ----------

@dataclasses.dataclass
class ProbeResult:
    """The raw output of a single HEAD probe — what the sentinel saw.

    Persistence: only the parts of this that the classifier needs to
    compare against baseline live in the on-disk state file.
    """

    source: str
    probed_url: str
    status_code: int | None
    final_url: str | None
    response_size_bytes: int | None
    duration_ms: int
    error: str | None  # populated only when the HTTP layer raised

    @property
    def reachable(self) -> bool:
        return (
            self.error is None
            and self.status_code is not None
            and 200 <= self.status_code < 400
        )


@dataclasses.dataclass
class Baseline:
    """The last ``ok`` snapshot for this source. Refreshed only on
    ``ok``. A persistent non-``ok`` state keeps the baseline intact so
    the comparison stays anchored to a known-good moment."""

    source: str
    probed_url: str
    final_url: str
    status_code: int
    response_size_bytes: int | None
    last_ok_at: str  # ISO-8601 UTC

    @classmethod
    def from_dict(cls, d: dict) -> "Baseline":
        return cls(
            source=d["source"],
            probed_url=d["probed_url"],
            final_url=d["final_url"],
            status_code=d["status_code"],
            response_size_bytes=d.get("response_size_bytes"),
            last_ok_at=d["last_ok_at"],
        )

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ClassifiedProbe:
    """Pure-function output of ``classify``. Combines the raw probe
    with its drift state + a human-readable reason."""

    source: str
    drift_state: str  # one of KNOWN_DRIFT_STATES
    reason: str
    probe: ProbeResult
    baseline: Baseline | None  # None on first run

    def to_state_record(self) -> dict:
        """Shape written to ``web/data/url_drift/<source>.json``."""
        return {
            "source": self.source,
            "drift_state": self.drift_state,
            "reason": self.reason,
            "probed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "last_probe": {
                "probed_url": self.probe.probed_url,
                "status_code": self.probe.status_code,
                "final_url": self.probe.final_url,
                "response_size_bytes": self.probe.response_size_bytes,
                "duration_ms": self.probe.duration_ms,
                "error": self.probe.error,
            },
            "baseline": self.baseline.to_dict() if self.baseline else None,
        }


# ---------- Classifier (pure function) ----------

def _normalize_url(url: str) -> str:
    """Collapse trivial differences (trailing slash, fragment, default
    port) so a baseline ``https://x.com`` matches a probed final URL of
    ``https://x.com/`` — but a path move ``/agenda`` → ``/nl/agenda``
    still triggers redirect_drift."""
    if not url:
        return url
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return url
    # Drop fragment + lowercase host + strip trailing slash on path-root.
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path == "/":
        path = ""
    # Strip default ports.
    if parsed.scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    if parsed.scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    return urllib.parse.urlunsplit(
        (parsed.scheme, netloc, path, parsed.query, "")
    )


def classify(probe: ProbeResult, baseline: Baseline | None) -> ClassifiedProbe:
    """Pure function over (probe, baseline) → classified drift state.

    Cases:
    - No baseline yet → if reachable, treat as ``ok`` (this run becomes
      the baseline). If unreachable, ``unreachable``.
    - probe.error or status >= 400 / < 200 → ``unreachable``.
    - Final URL post-normalize differs from baseline → ``redirect_drift``.
    - Both 2xx but status code differs → ``status_drift``.
    - Size delta > 50% of baseline (when baseline size is known) →
      ``size_drift``.
    - Else ``ok``.
    """
    # 1. Unreachable beats everything.
    if not probe.reachable:
        reason = (
            f"http_error: {probe.error}"
            if probe.error
            else f"http_status={probe.status_code}"
        )
        return ClassifiedProbe(
            source=probe.source,
            drift_state="unreachable",
            reason=reason,
            probe=probe,
            baseline=baseline,
        )

    # 2. No baseline → adopt this as the new baseline. State is ok.
    if baseline is None:
        return ClassifiedProbe(
            source=probe.source,
            drift_state="ok",
            reason="first_probe_seeds_baseline",
            probe=probe,
            baseline=baseline,
        )

    # 3. Final URL differs (after normalization) → redirect_drift.
    norm_current = _normalize_url(probe.final_url or probe.probed_url)
    norm_baseline = _normalize_url(baseline.final_url)
    if norm_current != norm_baseline:
        return ClassifiedProbe(
            source=probe.source,
            drift_state="redirect_drift",
            reason=f"final_url {baseline.final_url!r} → {probe.final_url!r}",
            probe=probe,
            baseline=baseline,
        )

    # 4. Both 2xx but status code shifted (e.g. 200 → 204, 301 chain change).
    if probe.status_code != baseline.status_code:
        return ClassifiedProbe(
            source=probe.source,
            drift_state="status_drift",
            reason=f"status {baseline.status_code} → {probe.status_code}",
            probe=probe,
            baseline=baseline,
        )

    # 5. Size delta > threshold.
    if (
        baseline.response_size_bytes
        and probe.response_size_bytes is not None
        and baseline.response_size_bytes > 0
    ):
        delta = abs(probe.response_size_bytes - baseline.response_size_bytes)
        ratio = delta / baseline.response_size_bytes
        if ratio > SIZE_DRIFT_THRESHOLD:
            return ClassifiedProbe(
                source=probe.source,
                drift_state="size_drift",
                reason=(
                    f"size {baseline.response_size_bytes} → "
                    f"{probe.response_size_bytes} ({ratio:.1%} delta)"
                ),
                probe=probe,
                baseline=baseline,
            )

    # 6. Everything matches — ok. Caller will refresh the baseline.
    return ClassifiedProbe(
        source=probe.source,
        drift_state="ok",
        reason="matches_baseline",
        probe=probe,
        baseline=baseline,
    )


def refresh_baseline(probe: ProbeResult) -> Baseline:
    """Produce a new baseline from an ``ok`` probe. Only callers that
    have already checked ``classified.drift_state == "ok"`` should call
    this — the function does no validation."""
    return Baseline(
        source=probe.source,
        probed_url=probe.probed_url,
        final_url=probe.final_url or probe.probed_url,
        status_code=probe.status_code or 0,
        response_size_bytes=probe.response_size_bytes,
        last_ok_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )


# ---------- State persistence ----------

def state_path_for(source: str, drift_dir: Path) -> Path:
    """``web/data/url_drift/<source>.json``. Slug is sanitized to prevent
    path traversal — only ``[a-z0-9_-]`` allowed."""
    safe = re.sub(r"[^a-z0-9_-]+", "_", source.lower())
    return drift_dir / f"{safe}.json"


def load_baseline(source: str, drift_dir: Path) -> Baseline | None:
    """Read the last ok-state baseline. Returns None if the file does
    not exist or is malformed — both cases mean "first probe, seed."""
    p = state_path_for(source, drift_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    baseline_data = data.get("baseline")
    if not baseline_data:
        return None
    try:
        return Baseline.from_dict(baseline_data)
    except (KeyError, TypeError):
        return None


def write_state(classified: ClassifiedProbe, drift_dir: Path) -> None:
    """Write the full state record. If drift_state is ``ok``, refresh
    the baseline; otherwise keep the prior baseline intact."""
    p = state_path_for(classified.source, drift_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = classified.to_state_record()
    if classified.drift_state == "ok":
        # Refresh baseline from this probe.
        record["baseline"] = refresh_baseline(classified.probe).to_dict()
    p.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


# ---------- HEAD probe (network — separated for testability) ----------

def probe_url(source: str, url: str, timeout_s: float = 10.0) -> ProbeResult:
    """Single HEAD probe with a fallback GET range request for sources
    that 405 on HEAD (some CDNs).

    Caller controls timeout; default 10s is generous for a HEAD on a
    landing page. Network exceptions are caught + reported via the
    ``error`` field — the classifier handles ``error is not None`` as
    ``unreachable``."""
    import time as _time

    import httpx

    start = _time.monotonic()
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout_s,
            headers={"User-Agent": _ua_for_probe()},
        ) as client:
            try:
                resp = client.head(url)
                if resp.status_code in {405, 501}:
                    # HEAD not implemented; try GET with Range: bytes=0-0
                    # so we still get headers without downloading the body.
                    resp = client.get(url, headers={"Range": "bytes=0-0"})
            except httpx.HTTPError as e:
                duration_ms = int((_time.monotonic() - start) * 1000)
                return ProbeResult(
                    source=source,
                    probed_url=url,
                    status_code=None,
                    final_url=None,
                    response_size_bytes=None,
                    duration_ms=duration_ms,
                    error=f"{e.__class__.__name__}: {e}",
                )

            duration_ms = int((_time.monotonic() - start) * 1000)
            content_length = resp.headers.get("Content-Length")
            try:
                size = int(content_length) if content_length else None
            except ValueError:
                size = None
            return ProbeResult(
                source=source,
                probed_url=url,
                status_code=resp.status_code,
                final_url=str(resp.url),
                response_size_bytes=size,
                duration_ms=duration_ms,
                error=None,
            )
    except Exception as e:  # noqa: BLE001 — defensive; never crash the sentinel
        duration_ms = int((_time.monotonic() - start) * 1000)
        return ProbeResult(
            source=source,
            probed_url=url,
            status_code=None,
            final_url=None,
            response_size_bytes=None,
            duration_ms=duration_ms,
            error=f"{e.__class__.__name__}: {e}",
        )


def _ua_for_probe() -> str:
    """Single static UA for sentinel probes. Identifying ourselves is
    legitimate (we're checking our own integration health, not scraping
    content). Some WAFs are stricter on requests with no UA at all."""
    return (
        "PulpoClubURLDriftSentinel/1.0 "
        "(+https://pulpo.club; ops-alert@pulpo.club)"
    )


# ---------- Orchestration ----------

def probe_all_sources(
    drift_dir: Path,
    sources_metadata: t.Mapping[str, dict] | None = None,
    *,
    timeout_s: float = 10.0,
) -> list[ClassifiedProbe]:
    """Probe every source in ``SCRAPER_METADATA`` whose
    ``health_probe_url`` is not None. Returns the classified results;
    side-effect: writes the per-source state files.

    The caller decides what to do with non-ok states (Slack page, exit
    code, etc.)."""
    if sources_metadata is None:
        # Lazy import so the unit tests can pass an in-memory dict
        # without dragging the whole scraper registry through import.
        from pulpo.scrapers._metadata import SCRAPER_METADATA
        sources_metadata = SCRAPER_METADATA

    results: list[ClassifiedProbe] = []
    for source, meta in sorted(sources_metadata.items()):
        url = meta.get("health_probe_url")
        if not url:
            continue
        baseline = load_baseline(source, drift_dir)
        probe = probe_url(source, url, timeout_s=timeout_s)
        classified = classify(probe, baseline)
        write_state(classified, drift_dir)
        results.append(classified)
    return results
