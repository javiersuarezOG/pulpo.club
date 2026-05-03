"""
Single-command pipeline runner for automation (cron, GitHub Actions, etc.).

Runs all configured scrapers, normalizes, ranks, and writes:
    samples/ranked.csv         (committed for human review)
    web/data/ranked.json       (consumed by web/index.html dashboard)
    web/data/last_updated.json (timestamp + counts for the dashboard header)

Exit code 0 on success, 1 on failure.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is on sys.path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.agents import SOURCES as REGISTRY  # noqa: E402
import pulpo.scrapers  # noqa: F401,E402 — triggers registration of all sources
from pulpo.agents.html_crawler import HTTPX_OK, SELECTOLAX_OK  # noqa: E402
from pulpo.normalize import normalize  # noqa: E402
from pulpo.ranker import rank  # noqa: E402
from automation.validation import validate  # noqa: E402
from automation.field_audit import build_completeness_block  # noqa: E402
from pulpo.cli import _row, CSV_FIELDS  # noqa: E402

import csv  # noqa: E402

def main() -> int:
    offline = os.environ.get("PULPO_OFFLINE") == "1"
    limit = int(os.environ.get("PULPO_LIMIT", "30"))
    sources = (os.environ.get("PULPO_SOURCES") or ",".join(REGISTRY.keys())).split(",")

    started = datetime.now(timezone.utc)
    raw: list[dict] = []
    per_source_count: dict[str, int] = {}
    errors: list[str] = []

    # Fixture-fallback guard. BaseScraper auto-flips to fixture mode when
    # httpx or selectolax aren't importable. That's fine when PULPO_OFFLINE=1
    # is explicit, but if we expected a live run and the deps are missing
    # we'd happily serve stale fixture data while reporting offline=false in
    # last_updated.json — invisible to monitoring. Surface it loudly instead.
    fixture_fallback_active = (not offline) and not (HTTPX_OK and SELECTOLAX_OK)
    if fixture_fallback_active:
        missing = []
        if not HTTPX_OK:
            missing.append("httpx")
        if not SELECTOLAX_OK:
            missing.append("selectolax")
        msg = (
            f"deps missing ({', '.join(missing)}); BaseScraper will fall back "
            f"to fixtures despite PULPO_OFFLINE=0. Live data will NOT be fetched. "
            f"Install with `pip install -r requirements.txt` (use httpx[socks] "
            f"behind a SOCKS proxy)."
        )
        print(f"WARNING: {msg}", file=sys.stderr)
        errors.append(msg)

    source_errors: dict[str, str] = {}   # src -> error message
    source_meta: dict[str, dict] = {}    # src -> {max_pages_hit, limit_hit}

    for src in sources:
        src = src.strip()
        mod = REGISTRY.get(src)
        if not mod:
            err = f"unknown source: {src}"
            errors.append(err)
            source_errors[src] = err
            continue
        try:
            if hasattr(mod, "crawl_with_meta"):
                result = mod.crawl_with_meta(limit=limit, offline=offline or None)
                recs = result["records"]
                source_meta[src] = {
                    "max_pages_hit": result["max_pages_hit"],
                    "limit_hit": result["limit_hit"],
                }
            else:
                recs = mod.crawl(limit=limit, offline=offline or None)
                source_meta[src] = {"max_pages_hit": False, "limit_hit": False}
        except Exception as e:
            err = repr(e)
            errors.append(f"{src}: {err}")
            source_errors[src] = err
            continue
        per_source_count[src] = len(recs)
        for r in recs:
            r.setdefault("source", src)
            raw.append(r)

    # Normalize
    listings = []
    dropped = 0
    for r in raw:
        li = normalize(r, source=r.get("source") or "unknown")
        if li:
            listings.append(li)
        else:
            dropped += 1

    # Validation layer — runs before the ranker.
    # DROP'd listings are excluded entirely. FLAG'd listings pass to the ranker
    # but get validation_status/validation_warnings fields set.
    # Writes web/data/validation_log.jsonl for auditing.
    val_pass = val_flag = val_drop = 0
    val_log_entries: list[dict] = []
    validated_listings: list = []
    for li in listings:
        li_dict = li.to_dict()
        result  = validate(li_dict)
        entry   = {
            "source_id":   li.source_id,
            "source":      li.source,
            "url":         li.url,
            "title":       li.title,
            "disposition": result.disposition,
            "reasons":     result.reasons,
        }
        val_log_entries.append(entry)
        if result.disposition == "DROP":
            val_drop += 1
            dropped  += 1
        elif result.disposition == "FLAG":
            val_flag += 1
            li.validation_status   = "flagged"
            li.validation_warnings = result.reasons
            validated_listings.append(li)
        else:
            val_pass += 1
            validated_listings.append(li)
    listings = validated_listings

    print(
        f"[validation] PASS={val_pass} FLAG={val_flag} DROP={val_drop} "
        f"(total in={val_pass+val_flag+val_drop})"
    )

    # Write validation log for auditability
    web_data_dir = REPO / "web" / "data"
    web_data_dir.mkdir(parents=True, exist_ok=True)
    val_log_path = web_data_dir / "validation_log.jsonl"
    with val_log_path.open("w", encoding="utf-8") as f:
        for entry in val_log_entries:
            import json as _json
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")

    # Legacy price-outlier log (kept for backward compat with the commit step)
    log_path = web_data_dir / "parser_errors.log"
    with log_path.open("w", encoding="utf-8") as f:
        f.write(f"# parser_errors.log — generated {datetime.now(timezone.utc).isoformat()}\n")
        f.write("# Replaced by validation_log.jsonl. Kept empty for git history continuity.\n")

    # First-seen tracking. Persistent sidecar keyed by "<source>|<source_id>"
    # so that "Newest first" sort and the NEW badge survive re-scrapes —
    # `scraped_at` rewrites every run and can't tell a 1-day-old listing
    # apart from a 6-month-old one we just re-fetched. Idempotent: existing
    # keys keep their original timestamp; new keys get the current run's
    # start time. Same pattern as run_history.json below.
    listings_history_path = web_data_dir / "listings_history.json"
    try:
        first_seen = (
            json.loads(listings_history_path.read_text())
            if listings_history_path.exists() else {}
        )
        if not isinstance(first_seen, dict):
            first_seen = {}
    except Exception:
        first_seen = {}
    started_iso = started.isoformat()
    for li in listings:
        key = f"{li.source}|{li.source_id}"
        if key not in first_seen:
            first_seen[key] = started_iso
        li.first_seen_at = first_seen[key]
    with listings_history_path.open("w", encoding="utf-8") as f:
        json.dump(first_seen, f, ensure_ascii=False)

    # Rank
    ranked = rank(listings)

    # Write CSV
    samples_path = REPO / "samples" / "ranked.csv"
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    with samples_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for li in ranked:
            w.writerow(_row(li))

    # Write web JSON. Two files:
    #   ranked.json        — full records, served only by /api/members behind auth
    #   ranked-public.json — broker/url/exact-price fields stripped, safe to serve statically
    web_data_dir = REPO / "web" / "data"
    web_data_dir.mkdir(parents=True, exist_ok=True)
    ranked_dicts = [li.to_dict() for li in ranked]
    with (web_data_dir / "ranked.json").open("w", encoding="utf-8") as f:
        json.dump(ranked_dicts, f, indent=2, ensure_ascii=False, default=str)
    with (web_data_dir / "ranked-public.json").open("w", encoding="utf-8") as f:
        json.dump([li.to_public_dict() for li in ranked], f, indent=2, ensure_ascii=False, default=str)

    # Derive per-source health status for the dashboard status strip.
    #   green  — returned > 0 listings, no exception
    #   yellow — returned > 0 listings but with a caught exception (partial)
    #   red    — returned 0 listings OR raised an exception
    source_status: dict[str, str] = {}
    for src in sources:
        count = per_source_count.get(src)
        had_error = src in source_errors
        if had_error:
            source_status[src] = "red"
        elif count is None or count == 0:
            source_status[src] = "red"
        else:
            source_status[src] = "green"

    # Coverage block: pulled counts + pagination flags per source.
    # supplier is null here (run.py doesn't make extra requests to fetch
    # advertised totals — use automation/coverage_audit.py for that).
    coverage = {
        src: {
            "supplier": None,
            "pulled": per_source_count.get(src, 0),
            "max_pages_hit": source_meta.get(src, {}).get("max_pages_hit", False),
        }
        for src in sources
    }

    # Field completeness snapshot — populated % per field per source.
    field_completeness = build_completeness_block(ranked_dicts)

    # Last-updated metadata
    finished = datetime.now(timezone.utc)
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
        "sources": sources,
        "offline": offline,
        "fixture_fallback_active": fixture_fallback_active,
        "errors": errors,
    }
    with (web_data_dir / "last_updated.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # Append lightweight summary to run history (keep last 60 runs ≈ 15 months weekly).
    history_path = web_data_dir / "run_history.json"
    try:
        history = json.loads(history_path.read_text()) if history_path.exists() else []
    except Exception:
        history = []
    history.append({
        "ts": finished.isoformat(),
        "total": len(ranked),
        "dropped": dropped,
        "duration": round((finished - started).total_seconds(), 2),
        "error_count": len(errors),
        "per_source_raw": per_source_count,
        "source_status": source_status,
    })
    history = history[-60:]
    with history_path.open("w", encoding="utf-8") as f:
        json.dump(history, f)

    # Summary line for CI logs
    print(
        f"pulpo run | {finished.isoformat()} | "
        f"{len(ranked)} listings | sources={','.join(sources)} | "
        f"errors={len(errors)} | offline={offline}"
    )
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        # Don't fail the run on partial failures — partial data is better than no data
    return 0

if __name__ == "__main__":
    sys.exit(main())
