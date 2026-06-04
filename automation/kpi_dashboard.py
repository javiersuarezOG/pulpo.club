"""KPI dashboard — emits web/data/kpi_dashboard.json each nightly.

Single source of truth for the four PRD sign-off KPIs:

  1. Total visible listings — listings the user can actually see on shelves.
  2. Per-category counts — six numbers, one per (master, sub) shelf, plus
     a renders_on_homepage boolean (>= MIN_REAL_LISTINGS).
  3. Active sites scraped — sources that contributed inventory last night.
  4. % coverage per site — kept / target_discovered (preferred) or
     kept / target_prd (fallback for sources without a self-discovered count).

The before/after diff between two nightly snapshots of this file is the
acceptance deliverable. PR A1 copies the FIRST nightly snapshot to
``docs/acceptance/2026-06-kpi-baseline.json`` as the immutable
before-state; PR D3 copies the LAST snapshot to
``docs/acceptance/2026-06-kpi-final.json`` and the delta renders into the
acceptance markdown.

This module is read-only telemetry. It does not change ranking or filtering;
it reports what the existing pipeline produced.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Iterable

from automation._atomic import atomic_write_json
from automation.shelf_audit import SHELF_KEYS, _shelf_key
from pulpo.derived_rules import _g


# Mirror of MIN_REAL_LISTINGS in web/app/home/HomeShelf.jsx. Kept in sync
# manually until PR A5 raises both sides to 10.
MIN_REAL_LISTINGS = 5


# PRD-stated inventory hints per source (the PRD's "stated number to aim
# for"). Used as the fallback denominator when a source doesn't expose a
# discoverable count on its own UI. ``None`` means we have no PRD claim
# for this source.
PRD_TARGETS: dict[str, int | None] = {
    "encuentra24":      2947,
    "remax":            None,
    "century21":        None,
    "citymax":          None,
    "elagente":         None,
    "essurf":           None,
    "goodlife":         None,
    "nexo":             None,
    "oceanside":        None,
    "realtyelsalvador": None,
    "bienesraices":     None,
    # Phase C additions (Phase B adds them as scrapers land):
    "xitios":           None,
    "agentiz":          None,
    "santizo":          150,
    "citymax_sc":       300,
    "vivolatam":        400,
    "csbr":             100,
    "realtor_intl_sv":  633,
    "jamesedition":     50,
}


def _is_visible(li: Any) -> bool:
    """Mirrors the FE eligibility predicate at HomeShelf.jsx::isShelfEligible
    in spirit: visible = not is_incomplete AND not is_agricultural.

    Photo presence is NOT checked here — Phase A3 introduces shelf-aware
    photo waivers that decouple "visible in data" from "rendered with
    a photo." This KPI counts the strict-visible cohort; the shelf-audit
    JSON breaks out the loose-vs-strict deltas.
    """
    if _g(li, "is_incomplete") is True:
        return False
    if _g(li, "is_agricultural") is True:
        return False
    return True


def _read_last_source_health(
    source_health_path: Path,
) -> dict[str, dict[str, Any]]:
    """Walks source_health_history.jsonl and returns the most-recent row per
    source. JSONL ordered chronologically; later rows overwrite earlier.
    Returns ``{}`` when the file is absent or unreadable — KPI gracefully
    reports zero active sources rather than crashing the nightly.
    """
    if not source_health_path.exists():
        return {}
    latest: dict[str, dict[str, Any]] = {}
    try:
        with source_health_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                source = row.get("source")
                if source:
                    latest[source] = row
    except OSError:
        return {}
    return latest


def _read_last_coverage(
    coverage_path: Path,
) -> dict[str, dict[str, Any]]:
    """Walks scraper_coverage_history.jsonl and returns the most-recent row
    per source. Lands populated once PR B1 ships ``lib/coverage_logger``.
    Empty dict until then.
    """
    if not coverage_path.exists():
        return {}
    latest: dict[str, dict[str, Any]] = {}
    try:
        with coverage_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                source = row.get("source")
                if source:
                    latest[source] = row
    except OSError:
        return {}
    return latest


def compute_kpi(
    listings: Iterable[Any],
    *,
    source_health: dict[str, dict[str, Any]] | None = None,
    coverage: dict[str, dict[str, Any]] | None = None,
    registered_sources: Iterable[str] | None = None,
    min_real_listings: int = MIN_REAL_LISTINGS,
    active_level: str = "moderate",
) -> dict[str, Any]:
    """Pure compute — no I/O. Same shape as the JSON ``write`` produces.

    Args:
        listings: iterable of ranked listings (dicts or Listing objects).
        source_health: latest source_health row per source. Used to compute
            active_sources (sources where kept_count or count > 0).
        coverage: latest coverage row per source from
            scraper_coverage_history.jsonl. Used for
            coverage_pct_vs_discovered.
        registered_sources: iterable of every registered scraper slug
            (typically ``pulpo.agents.SOURCES.keys()``). Used to compute
            ``registered_sources`` count and to enumerate per_source_coverage
            even for sources that didn't contribute last night.
        min_real_listings: shelf-render threshold mirrored from
            HomeShelf.jsx::MIN_REAL_LISTINGS.
        active_level: PULPO_FILTER_STRICTNESS at compute time, for traceability.
    """
    source_health = source_health or {}
    coverage = coverage or {}
    registered = list(registered_sources or [])

    materialized = list(listings)
    total_in_dataset = len(materialized)

    per_shelf_counts: dict[str, int] = {key: 0 for key in SHELF_KEYS}
    total_visible = 0
    per_source_kept: dict[str, int] = {}

    for li in materialized:
        if _is_visible(li):
            total_visible += 1
            shelf = _shelf_key(li)
            if shelf is not None:
                per_shelf_counts[shelf] += 1
        source = _g(li, "source")
        if isinstance(source, str):
            per_source_kept[source] = per_source_kept.get(source, 0) + 1

    per_shelf_visible = {
        key: {
            "count": count,
            "renders_on_homepage": count >= min_real_listings,
        }
        for key, count in per_shelf_counts.items()
    }

    all_sources = sorted(set(registered) | set(per_source_kept.keys()) | set(source_health.keys()))
    active_sources = 0
    per_source_coverage: dict[str, dict[str, Any]] = {}
    for source in all_sources:
        kept = per_source_kept.get(source, 0)
        health_row = source_health.get(source, {})
        if kept > 0:
            active_sources += 1
        coverage_row = coverage.get(source, {})
        target_discovered = coverage_row.get("target_discovered")
        target_prd = PRD_TARGETS.get(source)
        denom = target_discovered if isinstance(target_discovered, int) and target_discovered > 0 else target_prd
        coverage_pct = None
        if isinstance(denom, int) and denom > 0:
            coverage_pct = round(100.0 * kept / denom, 1)
        per_source_coverage[source] = {
            "kept":              kept,
            "target_prd":        target_prd,
            "target_discovered": target_discovered if isinstance(target_discovered, int) else None,
            "coverage_pct_vs_discovered": coverage_pct,
            "status":            health_row.get("status"),
        }

    shelves_rendering = sum(1 for v in per_shelf_visible.values() if v["renders_on_homepage"])

    return {
        "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "filter_strictness": active_level,
        "min_real_listings": min_real_listings,
        "kpi": {
            "total_visible_listings": total_visible,
            "total_in_dataset":       total_in_dataset,
            "per_shelf_visible":      per_shelf_visible,
            "shelves_rendering":      shelves_rendering,
            "shelves_total":          len(SHELF_KEYS),
            "active_sources":         active_sources,
            "registered_sources":     len(registered),
            "per_source_coverage":    per_source_coverage,
            "recovered_from_hidden":  None,  # populated by PR A2 onward
        },
    }


def write(
    listings: Iterable[Any],
    web_data_dir: Path,
    *,
    registered_sources: Iterable[str] | None = None,
    active_level: str | None = None,
) -> dict[str, Any]:
    """Compute KPI and write to ``<web_data_dir>/kpi_dashboard.json``.

    Reads ``source_health_history.jsonl`` and
    ``scraper_coverage_history.jsonl`` from the same directory.
    """
    level = active_level or os.environ.get("PULPO_FILTER_STRICTNESS", "moderate")
    source_health = _read_last_source_health(Path(web_data_dir) / "source_health_history.jsonl")
    coverage = _read_last_coverage(Path(web_data_dir) / "scraper_coverage_history.jsonl")
    payload = compute_kpi(
        listings,
        source_health=source_health,
        coverage=coverage,
        registered_sources=registered_sources,
        active_level=level,
    )
    atomic_write_json(
        Path(web_data_dir) / "kpi_dashboard.json",
        payload,
        indent=2,
        sort_keys=True,
        trailing_newline=True,
    )
    return payload
