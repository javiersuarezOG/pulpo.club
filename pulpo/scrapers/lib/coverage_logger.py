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
- ``status``: "ok" / "warn" — "warn" when
  coverage_ratio_vs_discovered < 0.8 (or vs_prd as fallback) AND
  target is known. Reads as a warning in the nightly log but does NOT
  block the run.

Format: JSONL. One row per scraper per nightly. The KPI dashboard
(``automation/kpi_dashboard.py``) reads the latest row per source.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional


WARN_RATIO = 0.8


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


def log_coverage(
    slug: str,
    *,
    raw_count: int,
    kept_count: int,
    target_prd: Optional[int] = None,
    target_discovered: Optional[int] = None,
    overlap_count: Optional[int] = None,
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
        path: optional output path. Default
            ``<repo>/web/data/scraper_coverage_history.jsonl``.
    """
    discovered_ratio = _ratio(kept_count, target_discovered)
    prd_ratio = _ratio(kept_count, target_prd)
    overlap_ratio: Optional[float] = None
    if isinstance(overlap_count, int) and kept_count > 0:
        overlap_ratio = round(overlap_count / kept_count, 4)

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
        "status": _classify_status(discovered_ratio, prd_ratio),
    }

    if path is None:
        repo_root = Path(__file__).resolve().parents[3]
        path = repo_root / "web" / "data" / "scraper_coverage_history.jsonl"

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    return row
