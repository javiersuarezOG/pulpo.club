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

    source_status = _compute_source_status(sources, per_source_count, source_errors)
    meta = _build_meta(
        ranked=ranked, ranked_dicts=ranked_dicts,
        sources=sources, per_source_count=per_source_count,
        source_meta=source_meta, source_status=source_status,
        errors=errors, started=started, finished=finished,
        offline=offline, fixture_fallback_active=fixture_fallback_active,
        dropped=dropped, validation_by_type=validation_by_type,
    )
    with (web_data_dir / "last_updated.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

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
    with path.open("w", encoding="utf-8") as f:
        json.dump(ranked_dicts, f, indent=2, ensure_ascii=False, default=str)


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
    with path.open("w", encoding="utf-8") as f:
        json.dump(history, f)


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
