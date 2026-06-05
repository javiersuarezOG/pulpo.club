"""Per-scrape coverage log — appends to scraper_coverage_history.jsonl.

This is the "shadow-mode lite" data emitter. Each scraper run logs:

- ``raw``: candidate count BEFORE validation / type / vacation-gate.
- ``kept``: candidate count AFTER per-scraper finalize_record passes.
- ``target_prd``: the PRD-stated inventory for this source (None when
  unknown).
- ``target_discovered``: the source's own "X listings" UI claim,
  parsed by ``target_discoverer.discover_target`` (None when the
  source doesn't expose a count).
- ``coverage_ratio_vs_discovered``: kept / target_discovered (preferred
  denominator).
- ``coverage_ratio_vs_prd``: kept / target_prd (fallback).
- ``overlap_ratio``: optional — fraction of kept records whose fingerprint
  matched an existing inventory record. Lets the operator decide whether
  a new source is genuinely additive or a duplicate-heavy mirror.
- ``crawl_stop_reason``: PR-S1 — closed-set enum naming why the scraper
  stopped fetching (pagination exhausted, max_pages hit, rate limited,
  parser returned zero, etc.). The audit gap: today "green" means
  "HTTP succeeded" — it does NOT mean "we fetched everything available."
  This field closes that gap.
- ``pages_seen`` / ``pages_attempted``: PR-S1 — index-page counts so a
  silently-truncated paginator is visible without re-reading logs.
- ``limit_hit`` / ``max_pages_hit``: PR-S1 — booleans flagging the two
  most common silent-truncation modes.
- ``last_page_url``: PR-S1 — the final index URL we fetched. Lets a
  human paste it in a browser to verify "is there more here?".
- ``status``: "ok" | "warn" | "degraded" — "warn" when
  coverage_ratio_vs_discovered < 0.8 (or vs_prd as fallback) AND
  target is known. "degraded" (PR-S1) when kept_count is >25% below
  the 7-run median, even when HTTP succeeded.

Format: JSONL. One row per scraper per nightly. The KPI dashboard
(``automation/kpi_dashboard.py``) reads the latest row per source.

KNOWN_CRAWL_STOP_REASONS is the closed-set allowlist (CLAUDE.md
producer-consumer rule, post-2026-06-02). Adding a new value =
adding to the consumer (operator dashboard PR-S7) in the same PR.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional


WARN_RATIO = 0.8

# Degradation threshold (PR-S1). When kept_count is >25% below the
# rolling 7-run median, flip status from "ok"/"warn" to "degraded".
# Catches silent under-scraping (selector decay, pagination cap) that
# the coverage_ratio gates can miss when target_prd/target_discovered
# are unknown — most sources don't expose their own counts.
DEGRADATION_DROP_THRESHOLD = 0.25
DEGRADATION_HISTORY_WINDOW = 7

# Closed set per CLAUDE.md producer-consumer rule (post-2026-06-02).
# Consumer: operator dashboard (PR-S7) renders the per-source pill
# from this enum; the watchdog Slack alerter uses it for the failure
# class. Adding a value here without a dashboard tile + alert hook is
# forbidden — see tests/test_coverage_logger.py for the contract test.
KNOWN_CRAWL_STOP_REASONS: frozenset[str] = frozenset({
    "pagination_exhausted",  # paginator reached the natural end
    "max_pages_hit",         # paginator hit the configured ceiling
    "limit_hit",             # scraper-level LIMIT env var hit
    "http_error",            # an HTTP request raised
    "empty_response",        # listing-index returned 0 cards
    "parser_returned_zero",  # cards present but the parser yielded 0
    "rate_limit",            # 429 or equivalent
    "timeout",               # request or job-level timeout
    "unknown",               # explicit "I don't know" — better than null
})


def _ratio(numer: int, denom: Optional[int]) -> Optional[float]:
    if denom is None or denom <= 0:
        return None
    return round(numer / denom, 4)


def _classify_status(
    discovered_ratio: Optional[float],
    prd_ratio: Optional[float],
) -> str:
    """Status: 'warn' when whichever denominator we have produced a ratio
    below WARN_RATIO. 'ok' when at least one ratio is >= WARN_RATIO, or
    when both are None (we don't know what 'full coverage' means)."""
    ratios = [r for r in (discovered_ratio, prd_ratio) if r is not None]
    if not ratios:
        return "ok"
    # Use discovered_ratio first if present; else prd_ratio.
    primary = discovered_ratio if discovered_ratio is not None else prd_ratio
    if primary is not None and primary < WARN_RATIO:
        return "warn"
    return "ok"


def _detect_degradation(
    slug: str,
    kept_count: int,
    path: Path,
) -> Optional[int]:
    """Return the 7-run median of prior kept counts for this source if
    ``kept_count`` is >25% below it, else None.

    Reads the existing history file BEFORE the new row is appended.
    Missing/short history returns None (need at least 3 prior runs to
    establish a meaningful median).
    """
    if not path.exists():
        return None
    prior_counts: list[int] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("source") != slug:
                continue
            kept = row.get("kept")
            if isinstance(kept, int):
                prior_counts.append(kept)
    except OSError:
        return None

    # Keep the most recent window-worth.
    prior_counts = prior_counts[-DEGRADATION_HISTORY_WINDOW:]
    if len(prior_counts) < 3:
        return None

    s = sorted(prior_counts)
    mid = len(s) // 2
    if len(s) % 2 == 1:
        median = s[mid]
    else:
        median = (s[mid - 1] + s[mid]) // 2

    if median <= 0:
        return None

    drop_ratio = (median - kept_count) / median
    if drop_ratio > DEGRADATION_DROP_THRESHOLD:
        return median
    return None


def log_coverage(
    slug: str,
    *,
    raw_count: int,
    kept_count: int,
    target_prd: Optional[int] = None,
    target_discovered: Optional[int] = None,
    overlap_count: Optional[int] = None,
    # PR-S1 exhaustiveness fields. All optional so existing callers
    # don't break; the values default to None / sensible-blank.
    crawl_stop_reason: Optional[str] = None,
    pages_seen: Optional[int] = None,
    pages_attempted: Optional[int] = None,
    limit_hit: Optional[bool] = None,
    max_pages_hit: Optional[bool] = None,
    last_page_url: Optional[str] = None,
    path: Optional[Path] = None,
) -> dict:
    """Append a coverage row to ``scraper_coverage_history.jsonl``.

    Returns the row dict so callers can log a summary line.

    Args:
        slug: scraper slug (e.g. "encuentra24").
        raw_count: candidates before validation.
        kept_count: candidates kept after validation.
        target_prd: PRD-stated inventory (None if unknown).
        target_discovered: source's own UI claim (None if unparseable).
        overlap_count: optional count of fingerprints already in
            inventory (lets us measure cross-source overlap).
        crawl_stop_reason: PR-S1 — closed-set enum. MUST be one of
            ``KNOWN_CRAWL_STOP_REASONS`` or None. Producers should
            prefer the specific reason ("pagination_exhausted") over
            "unknown" wherever derivable.
        pages_seen: actual number of index pages parsed.
        pages_attempted: number of index pages requested (may differ
            from pages_seen if some failed).
        limit_hit: True if the scraper stopped because the per-source
            ENV-var limit was reached.
        max_pages_hit: True if the scraper stopped because the
            configured max_pages was reached.
        last_page_url: final index URL fetched. Useful for paste-into-
            browser verification.
        path: optional output path. Default
            ``<repo>/web/data/scraper_coverage_history.jsonl``.

    Raises:
        ValueError if ``crawl_stop_reason`` is set and not in
        ``KNOWN_CRAWL_STOP_REASONS``. The contract test
        ``tests/test_coverage_logger_contract.py`` enforces this.
    """
    if crawl_stop_reason is not None and crawl_stop_reason not in KNOWN_CRAWL_STOP_REASONS:
        raise ValueError(
            f"crawl_stop_reason={crawl_stop_reason!r} not in "
            f"KNOWN_CRAWL_STOP_REASONS. Allowed: "
            f"{sorted(KNOWN_CRAWL_STOP_REASONS)}"
        )

    discovered_ratio = _ratio(kept_count, target_discovered)
    prd_ratio = _ratio(kept_count, target_prd)
    overlap_ratio: Optional[float] = None
    if isinstance(overlap_count, int) and kept_count > 0:
        overlap_ratio = round(overlap_count / kept_count, 4)

    if path is None:
        repo_root = Path(__file__).resolve().parents[3]
        path = repo_root / "web" / "data" / "scraper_coverage_history.jsonl"

    # Degradation check reads history BEFORE we append the new row.
    degraded_vs_median = _detect_degradation(slug, kept_count, path)
    base_status = _classify_status(discovered_ratio, prd_ratio)
    if degraded_vs_median is not None:
        status = "degraded"
    else:
        status = base_status

    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": slug,
        "raw": raw_count,
        "kept": kept_count,
        "target_prd": target_prd,
        "target_discovered": target_discovered,
        "coverage_ratio_vs_discovered": discovered_ratio,
        "coverage_ratio_vs_prd": prd_ratio,
        "overlap_ratio": overlap_ratio,
        # PR-S1 exhaustiveness fields.
        "crawl_stop_reason": crawl_stop_reason,
        "pages_seen": pages_seen,
        "pages_attempted": pages_attempted,
        "limit_hit": limit_hit,
        "max_pages_hit": max_pages_hit,
        "last_page_url": last_page_url,
        "prior_median": degraded_vs_median,
        "status": status,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    return row
