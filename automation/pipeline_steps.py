"""
Pipeline phase helpers extracted from automation/run.py::main().

Each phase is a pure-ish function with a clear input/output contract.
main() composes them in order. This file exists so main() reads as a
script of phase calls rather than a 400-line wall of inline logic.

Phases live here only when they have a clean boundary (no shared mutation
back into main's locals). Phases that mutate listings in place or share
many local variables stay inline in main() — moving them here would just
be relocation, not abstraction.
"""
from __future__ import annotations
import csv as _csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pulpo.normalize import normalize as _normalize
from pulpo.cli import _row, CSV_FIELDS
from automation.validation import validate as _validate
from automation.field_audit import build_completeness_block
from automation._atomic import atomic_write_json


# ── Phase: normalize ──────────────────────────────────────────────────

def phase_normalize(raw: list[dict]) -> tuple[list, int]:
    """Convert raw scraper dicts → Listing objects. Returns (listings, dropped_count).

    Dropped count is the number of raw records that normalize() rejected
    (returned None) — typically because both price and area were missing,
    or the listing failed property-type filters.
    """
    listings: list = []
    dropped = 0
    for r in raw:
        li = _normalize(r, source=r.get("source") or "unknown")
        if li:
            listings.append(li)
        else:
            dropped += 1
    return listings, dropped


# ── Phase: validate ───────────────────────────────────────────────────

def phase_validate(
    listings: list, web_data_dir: Path
) -> tuple[list, dict, int]:
    """Apply validate() to each listing. Returns (kept, counts, drop_count).

    DROP'd listings are excluded; FLAG'd are kept but get
    validation_status / validation_warnings populated. Writes
    web/data/validation_log.jsonl with one entry per listing.

    counts dict: {"pass": N, "flag": N, "drop": N,
                  "by_type": {pt: {"pass": N, "flag": N, "drop": N}, ...}}
    drop_count: number dropped (to add to running total in main)
    """
    val_pass = val_flag = val_drop = 0
    # Per-type breakdown for last_updated.json — surfaces "houses passed
    # 47/50, condos 7/7" at a glance instead of one flat aggregate.
    by_type: dict[str, dict[str, int]] = {}
    val_log_entries: list[dict] = []
    kept: list = []
    for li in listings:
        result = _validate(li.to_dict())
        pt = li.property_type or "land"
        bucket = by_type.setdefault(pt, {"pass": 0, "flag": 0, "drop": 0})
        val_log_entries.append({
            "source_id":     li.source_id,
            "source":        li.source,
            "url":           li.url,
            "title":         li.title,
            "property_type": pt,
            "disposition":   result.disposition,
            "reasons":       result.reasons,
        })
        if result.disposition == "DROP":
            val_drop += 1
            bucket["drop"] += 1
        elif result.disposition == "FLAG":
            val_flag += 1
            bucket["flag"] += 1
            li.validation_status = "flagged"
            li.validation_warnings = result.reasons
            kept.append(li)
        else:
            val_pass += 1
            bucket["pass"] += 1
            kept.append(li)

    # Write validation log
    web_data_dir.mkdir(parents=True, exist_ok=True)
    val_log_path = web_data_dir / "validation_log.jsonl"
    with val_log_path.open("w", encoding="utf-8") as f:
        for entry in val_log_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Legacy price-outlier log stub (kept so the commit step's git add
    # doesn't fail — file existed before validation_log.jsonl took over).
    log_path = web_data_dir / "parser_errors.log"
    with log_path.open("w", encoding="utf-8") as f:
        f.write(f"# parser_errors.log — generated {datetime.now(timezone.utc).isoformat()}\n")
        f.write("# Replaced by validation_log.jsonl. Kept empty for git history continuity.\n")

    counts = {"pass": val_pass, "flag": val_flag, "drop": val_drop, "by_type": by_type}
    return kept, counts, val_drop


# ── Phase: write outputs (CSV + JSON files + metadata) ────────────────

def phase_write_outputs(
    *,
    ranked: list,
    web_data_dir: Path,
    samples_path: Path,
    sources: list[str],
    per_source_count: dict[str, int],
    source_errors: dict[str, str],
    source_meta: dict[str, dict],
    errors: list[str],
    started: datetime,
    finished: datetime,
    offline: bool,
    fixture_fallback_active: bool,
    dropped: int,
    validation_by_type: Optional[dict] = None,
) -> dict:
    """Write all output files. Returns the meta dict for further use.

    Composed from the smaller helpers below, each of which writes one file
    or computes one block. Keep this function thin; add new outputs as new
    helpers, not as more inline statements.
    """
    web_data_dir.mkdir(parents=True, exist_ok=True)
    ranked_dicts = [li.to_dict() for li in ranked]

    _write_csv(ranked, samples_path)
    _write_ranked_json(ranked_dicts, web_data_dir / "ranked.json")
    # PR-perf-3b — emit a slim projection of ranked.json with ONLY the
    # fields the web/app/data/listings.ts adapter consumes. Drops broker
    # contact, validation metadata, hires sidecar fields, raw scraper
    # text, geocoding metadata, and the granular `is_*` booleans that
    # are redundant with the backend-derived enums. Browse + Discover
    # + Saved fetch this file instead of the full 6.7 MB ranked.json,
    # cutting first-paint payload ~40-60%. The detail view still needs
    # the full record (description, USPs); the next PR adds a lazy
    # detail-fetch path. Until then, the client's adapter handles the
    # slim shape — heavy fields it reads (description, reasons_to_buy)
    # stay in the slim file.
    _write_ranked_list_json(ranked_dicts, web_data_dir / "ranked.list.json")

    source_status = _compute_source_status(sources, per_source_count, source_errors)
    meta = _build_meta(
        ranked=ranked, ranked_dicts=ranked_dicts,
        sources=sources, per_source_count=per_source_count,
        source_meta=source_meta, source_status=source_status,
        errors=errors, started=started, finished=finished,
        offline=offline, fixture_fallback_active=fixture_fallback_active,
        dropped=dropped, validation_by_type=validation_by_type,
    )
    atomic_write_json(web_data_dir / "last_updated.json", meta, indent=2)

    _append_run_history(
        web_data_dir / "run_history.json",
        finished=finished, ranked_count=len(ranked), dropped=dropped,
        started=started, errors=errors, per_source_count=per_source_count,
        source_status=source_status,
    )
    return meta


def _write_csv(ranked: list, samples_path: Path) -> None:
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    with samples_path.open("w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for li in ranked:
            w.writerow(_row(li))


def _write_ranked_json(ranked_dicts: list, path: Path) -> None:
    """Write ranked.json. ranked-public.json was historically generated for
    an auth-gated split that was never built; frontend reads ranked.json
    directly so the public version was dropped (saved ~1.1 MB per commit).
    """
    atomic_write_json(path, ranked_dicts, indent=2, default=str)


# PR-perf-3b — slim projection of ranked.json. Listed fields are the
# strict union of what `web/app/data/listings.ts#adaptListing` reads
# from each raw record. Adding a new field-read in the adapter MUST
# also add the field name here, otherwise the live app will silently
# treat that field as missing for slim-file loads.
_RANKED_LIST_FIELDS: frozenset[str] = frozenset({
    # Identity
    "source", "source_id", "url",
    # Title + description + USPs (kept — adapter & detail page read these)
    "title", "title_canonical",
    "description", "short_description_canonical",
    "reasons_to_buy", "url_language",
    # Location
    "zone", "department", "country",
    # Land type / property
    "land_type", "property_type", "bedrooms",
    # Price + size
    "area_m2", "price_usd", "previous_price", "price_per_m2",
    # Photos
    "photo_urls", "hero_photo_path", "photos_count",
    "hero_photo_quality_score", "has_text_overlay",
    "hero_eligible", "card_eligible",
    # Timing
    "first_seen_at", "days_listed", "is_repriced",
    # Source classification
    "source_type",
    # Features
    "beachfront_tier", "is_beachfront",
    "has_ocean_view", "has_mountain_view", "has_water_body", "is_flat",
    "has_water", "has_power", "has_sewage",
    "has_paved_access", "road_access_type",
    "readiness_score", "zoning_use",
    # Distance + geo (lat/lng → only the truthy-test reaches the FE)
    "dist_beach_km", "dist_airport_km", "dist_nearest_town_km",
    "lat", "lng", "geocoding_confidence",
    # State
    "is_sold",
    # Ranking
    "rank", "rank_score",
    "value_score", "location_score", "momentum_score",
    # IA-axis derivatives
    "master_category", "subcategory",
    "discovery_tags", "star_rating", "is_incomplete",
})


def _write_ranked_list_json(ranked_dicts: list, path: Path) -> None:
    """Emit a slim projection of ranked.json for the list-view fetch
    path. Whitelist-based, see _RANKED_LIST_FIELDS for the rule.
    The full ranked.json stays in place for the detail-view fetch.
    """
    slim: list[dict] = []
    for record in ranked_dicts:
        if not isinstance(record, dict):
            continue
        slim.append({k: v for k, v in record.items() if k in _RANKED_LIST_FIELDS})
    atomic_write_json(path, slim, indent=2, default=str)


def _compute_source_status(sources: list[str], per_source_count: dict[str, int], source_errors: dict[str, str]) -> dict[str, str]:
    """green = pulled > 0 and no error; red otherwise."""
    out: dict[str, str] = {}
    for src in sources:
        count = per_source_count.get(src)
        if src in source_errors or count is None or count == 0:
            out[src] = "red"
        else:
            out[src] = "green"
    return out


def check_population_regression(
    prev_meta: Optional[dict],
    new_rates: dict[str, float],
    threshold: float = 0.20,
) -> list[str]:
    """PR-7 — population-rate regression guard.

    Compare the just-computed `derived_field_population` rates against the
    previous run's `last_updated.json`. Returns a list of human-readable
    regression messages; an empty list means the run is clean. Caller
    decides whether to fail the pipeline or just warn.

    Logic:
      - First run after this lands → `prev_meta` lacks `derived_field_population`;
        skip the check (no baseline). Return [].
      - For each field present in BOTH the previous and the new rates,
        flag a regression if (prev - new) / max(prev, 0.001) > threshold.
        Use prev as the denominator so a 20% relative drop is the threshold
        regardless of absolute level.
      - Fields newly added in the current run (not in prev) are skipped —
        no baseline to compare against. They become baseline for the next
        run.

    Threshold defaults to 20% per plan. Can be tightened later via env override
    in the caller.
    """
    if not isinstance(prev_meta, dict):
        return []
    prev_rates = prev_meta.get("derived_field_population")
    if not isinstance(prev_rates, dict) or not prev_rates:
        return []
    regressions: list[str] = []
    for field, prev in prev_rates.items():
        if not isinstance(prev, (int, float)) or prev <= 0:
            continue
        new = new_rates.get(field)
        if not isinstance(new, (int, float)):
            continue
        relative_drop = (prev - new) / max(prev, 0.001)
        if relative_drop > threshold:
            regressions.append(
                f"{field}: {prev:.1%} → {new:.1%} "
                f"(relative drop {relative_drop:.1%} > threshold {threshold:.0%})"
            )
    return regressions


def compute_derived_population(ranked) -> dict[str, float]:
    """PR-7 — population rates for derived fields, used by the regression
    guard and surfaced in last_updated.json.

    Returns a flat dict of `field_or_label: rate_in_[0,1]`. Adding a new
    derive in PR-8/9? Add its rate here. Keys map 1:1 to the regression
    threshold check.
    """
    n = max(len(ranked), 1)
    off_market = sum(1 for li in ranked if getattr(li, "source_type", None) == "off_market")
    on_market  = sum(1 for li in ranked if getattr(li, "source_type", None) == "on_market")
    prev_price = sum(1 for li in ranked if getattr(li, "previous_price", None) is not None)
    # PR-8 — NLP-derived fields.
    bt_on    = sum(1 for li in ranked if getattr(li, "beachfront_tier", None) == "on_beach")
    bt_walk  = sum(1 for li in ranked if getattr(li, "beachfront_tier", None) == "walk_to_beach")
    bt_near  = sum(1 for li in ranked if getattr(li, "beachfront_tier", None) == "near_beach")
    lt_comm  = sum(1 for li in ranked if getattr(li, "land_type", None) == "commercial")
    lt_tour  = sum(1 for li in ranked if getattr(li, "land_type", None) == "tourist")
    lt_resi  = sum(1 for li in ranked if getattr(li, "land_type", None) == "residential")
    motiv    = sum(1 for li in ranked if getattr(li, "is_motivated", False) is True)
    return {
        "source_type_off_market":    round(off_market / n, 4),
        "source_type_on_market":     round(on_market / n, 4),
        "previous_price":            round(prev_price / n, 4),
        "beachfront_tier_on_beach":      round(bt_on   / n, 4),
        "beachfront_tier_walk_to_beach": round(bt_walk / n, 4),
        "beachfront_tier_near_beach":    round(bt_near / n, 4),
        "land_type_commercial":          round(lt_comm / n, 4),
        "land_type_tourist":             round(lt_tour / n, 4),
        "land_type_residential":         round(lt_resi / n, 4),
        "is_motivated":                  round(motiv   / n, 4),
    }


def _build_meta(*, ranked, ranked_dicts, sources, per_source_count, source_meta,
                source_status, errors, started, finished, offline,
                fixture_fallback_active, dropped,
                validation_by_type: Optional[dict] = None) -> dict:
    """Assemble the last_updated.json meta dict (single source of truth for the
    dashboard header + watchdog)."""
    from collections import Counter as _Counter
    coverage = {
        src: {
            "supplier": None,
            "pulled": per_source_count.get(src, 0),
            "max_pages_hit": source_meta.get(src, {}).get("max_pages_hit", False),
        }
        for src in sources
    }
    return {
        "last_updated":       finished.isoformat(),
        "started_at":         started.isoformat(),
        "duration_seconds":   round((finished - started).total_seconds(), 2),
        "total_listings":     len(ranked),
        "dropped":            dropped,
        "per_source_raw":     per_source_count,
        "source_status":      source_status,
        "coverage":           coverage,
        "derived_field_population": compute_derived_population(ranked),
        "field_completeness": build_completeness_block(ranked_dicts),
        "property_type_counts": dict(_Counter(li.property_type for li in ranked)),
        # Per-type pass/flag/drop breakdown — empty {} when only land
        # exists (the historical state); populated as soon as houses or
        # condos appear in ingestion. Surfaces type-specific quality
        # issues that the flat aggregate would hide.
        "validation_by_type": validation_by_type or {},
        # V-leg fallback diagnostics — listings with no price (neutral 35
        # default) or no comp pool (zone_percentile=None). High counts mean
        # the V leg is mostly noise that week.
        "v_fallback_no_price": sum(1 for li in ranked if li.price_per_m2 is None),
        "v_fallback_no_comps": sum(
            1 for li in ranked
            if li.price_per_m2 is not None and li.zone_percentile is None
        ),
        "sources":                sources,
        "offline":                offline,
        "fixture_fallback_active": fixture_fallback_active,
        "errors":                  errors,
    }


def _append_run_history(path: Path, *, finished, ranked_count, dropped,
                        started, errors, per_source_count, source_status) -> None:
    """Append one entry to run_history.json, capped at last 60 runs."""
    try:
        history = json.loads(path.read_text()) if path.exists() else []
    except Exception:
        history = []
    history.append({
        "ts":             finished.isoformat(),
        "total":          ranked_count,
        "dropped":        dropped,
        "duration":       round((finished - started).total_seconds(), 2),
        "error_count":    len(errors),
        "per_source_raw": per_source_count,
        "source_status":  source_status,
    })
    history = history[-60:]
    atomic_write_json(path, history)


# ── Phase: print summary (stdout for CI logs) ─────────────────────────

def phase_print_summary(
    *,
    finished: datetime,
    ranked_count: int,
    sources: list[str],
    errors: list[str],
    offline: bool,
) -> None:
    print(
        f"pulpo run | {finished.isoformat()} | "
        f"{ranked_count} listings | sources={','.join(sources)} | "
        f"errors={len(errors)} | offline={offline}"
    )
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        # Don't fail the run on partial failures — partial data is better than no data
