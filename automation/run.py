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

    # Phase 2: price-outlier sanity check.
    # price_usd < 1000 AND area_m2 > 1000 is almost certainly a parser error
    # (e.g. stray numeric code near a listing title parsed as price).
    # Log to parser_errors.log so the root causes can be fixed in a follow-up.
    PRICE_OUTLIER_MAX_PRICE = 1000.0
    PRICE_OUTLIER_MIN_AREA  = 1000.0
    price_outliers: list[dict] = []
    clean_listings: list = []
    for li in listings:
        if (li.price_usd is not None
                and li.price_usd < PRICE_OUTLIER_MAX_PRICE
                and li.area_m2 is not None
                and li.area_m2 > PRICE_OUTLIER_MIN_AREA):
            price_outliers.append({
                "source": li.source,
                "source_id": li.source_id,
                "url": li.url,
                "title": li.title,
                "price_usd": li.price_usd,
                "area_m2": li.area_m2,
            })
            dropped += 1
        else:
            clean_listings.append(li)
    listings = clean_listings

    if price_outliers:
        web_data_dir = REPO / "web" / "data"
        web_data_dir.mkdir(parents=True, exist_ok=True)
        log_path = web_data_dir / "parser_errors.log"
        with log_path.open("w", encoding="utf-8") as f:
            f.write(f"# parser_errors.log — generated {datetime.now(timezone.utc).isoformat()}\n")
            f.write(f"# Listings dropped by price-outlier check (price<{PRICE_OUTLIER_MAX_PRICE}, area>{PRICE_OUTLIER_MIN_AREA}m²)\n")
            f.write("# Fix the underlying parser bug in a separate PR; do not edit this file manually.\n\n")
            for entry in price_outliers:
                f.write(
                    f"[{entry['source']}] ${entry['price_usd']} / {entry['area_m2']}m²\n"
                    f"  title: {entry['title']}\n"
                    f"  url:   {entry['url']}\n\n"
                )
        print(f"[price-outlier] {len(price_outliers)} listings dropped and logged to {log_path.name}")

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
