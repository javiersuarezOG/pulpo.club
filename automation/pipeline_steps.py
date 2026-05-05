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

from pulpo.normalize import normalize as _normalize
from pulpo.cli import _row, CSV_FIELDS
from automation.validation import validate as _validate
from automation.field_audit import build_completeness_block


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

    counts dict: {"pass": N, "flag": N, "drop": N}
    drop_count: number dropped (to add to running total in main)
    """
    val_pass = val_flag = val_drop = 0
    val_log_entries: list[dict] = []
    kept: list = []
    for li in listings:
        result = _validate(li.to_dict())
        val_log_entries.append({
            "source_id":   li.source_id,
            "source":      li.source,
            "url":         li.url,
            "title":       li.title,
            "disposition": result.disposition,
            "reasons":     result.reasons,
        })
        if result.disposition == "DROP":
            val_drop += 1
        elif result.disposition == "FLAG":
            val_flag += 1
            li.validation_status = "flagged"
            li.validation_warnings = result.reasons
            kept.append(li)
        else:
            val_pass += 1
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

    counts = {"pass": val_pass, "flag": val_flag, "drop": val_drop}
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
) -> dict:
    """Write all output files: ranked.json, ranked-public.json, samples/ranked.csv,
    last_updated.json, run_history.json. Returns the meta dict for further use.
    """
    # CSV
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    with samples_path.open("w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for li in ranked:
            w.writerow(_row(li))

    # JSON output. ranked-public.json was historically generated for an
    # auth-gated split that was never built; the frontend reads ranked.json
    # directly. Dropped to save ~1.1 MB per nightly commit.
    web_data_dir.mkdir(parents=True, exist_ok=True)
    ranked_dicts = [li.to_dict() for li in ranked]
    with (web_data_dir / "ranked.json").open("w", encoding="utf-8") as f:
        json.dump(ranked_dicts, f, indent=2, ensure_ascii=False, default=str)

    # Per-source health status — green if pulled > 0 and no error, else red.
    source_status: dict[str, str] = {}
    for src in sources:
        count = per_source_count.get(src)
        if src in source_errors or count is None or count == 0:
            source_status[src] = "red"
        else:
            source_status[src] = "green"

    coverage = {
        src: {
            "supplier": None,
            "pulled": per_source_count.get(src, 0),
            "max_pages_hit": source_meta.get(src, {}).get("max_pages_hit", False),
        }
        for src in sources
    }

    field_completeness = build_completeness_block(ranked_dicts)

    # V-leg fallback diagnostics
    from collections import Counter as _Counter
    property_type_counts = dict(_Counter(li.property_type for li in ranked))
    v_fallback_no_price = sum(1 for li in ranked if li.price_per_m2 is None)
    v_fallback_no_comps = sum(
        1 for li in ranked
        if li.price_per_m2 is not None and li.zone_percentile is None
    )

    meta = {
        "last_updated": finished.isoformat(),
        "started_at": started.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 2),
        "total_listings": len(ranked),
        "dropped": dropped,
        "per_source_raw": per_source_count,
        "source_status": source_status,
        "coverage": coverage,
        "field_completeness": field_completeness,
        "property_type_counts": property_type_counts,
        "v_fallback_no_price": v_fallback_no_price,
        "v_fallback_no_comps": v_fallback_no_comps,
        "sources": sources,
        "offline": offline,
        "fixture_fallback_active": fixture_fallback_active,
        "errors": errors,
    }
    with (web_data_dir / "last_updated.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # Run history (last 60 entries)
    history_path = web_data_dir / "run_history.json"
    try:
        history = json.loads(history_path.read_text()) if history_path.exists() else []
    except Exception:
        history = []
    history.append({
        "ts":              finished.isoformat(),
        "total":           len(ranked),
        "dropped":         dropped,
        "duration":        round((finished - started).total_seconds(), 2),
        "error_count":     len(errors),
        "per_source_raw":  per_source_count,
        "source_status":   source_status,
    })
    history = history[-60:]
    with history_path.open("w", encoding="utf-8") as f:
        json.dump(history, f)

    return meta


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
