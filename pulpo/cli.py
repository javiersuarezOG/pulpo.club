"""
Command-line entry point.

Examples:
    # Run all sources offline against fixtures, write samples/ranked.csv
    python -m pulpo.cli --offline

    # Run goodlife only against the live site, top 20
    python -m pulpo.cli --source goodlife --limit 20

    # Specify output path
    python -m pulpo.cli --offline --out /tmp/ranked.csv
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path

from .agents import SOURCES as REGISTRY
import pulpo.scrapers  # noqa: F401 — triggers registration of all sources
from .normalize import normalize
from .ranker import rank
from .units import fmt_area
from .models import Listing

CSV_FIELDS = [
    "rank", "rank_score",
    "value_score", "quality_score", "liquidity_score", "upside_score",
    "zone_percentile",
    "source", "source_id", "title",
    "zone", "municipality", "department",
    "area_m2", "area_display",
    "price_usd", "price_per_m2",
    "is_beachfront", "has_paved_access", "is_repriced",
    "days_listed", "photos_count",
    "url", "rank_reasons_short",
]

def _row(li: Listing) -> dict:
    area_display = fmt_area(li.area_m2) if li.area_m2 else ""
    return {
        "rank": li.rank,
        "rank_score": li.rank_score,
        "value_score": li.value_score,
        "quality_score": li.quality_score,
        "liquidity_score": li.liquidity_score,
        "upside_score": li.upside_score,
        "zone_percentile": li.zone_percentile,
        "source": li.source,
        "source_id": li.source_id,
        "title": li.title,
        "zone": li.zone or "",
        "municipality": li.municipality or "",
        "department": li.department or "",
        "area_m2": li.area_m2,
        "area_display": area_display,
        "price_usd": li.price_usd,
        "price_per_m2": li.price_per_m2,
        "is_beachfront": li.is_beachfront,
        "has_paved_access": li.has_paved_access,
        "is_repriced": li.is_repriced,
        "days_listed": li.days_listed,
        "photos_count": li.photos_count,
        "url": li.url,
        "rank_reasons_short": " | ".join(li.rank_reasons),
    }

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pulpo", description="pulpo.club aggregator pipeline")
    p.add_argument("--source", action="append", default=None,
                   help="Source slug, repeatable. Default: all (goodlife,oceanside,kazu).")
    p.add_argument("--limit", type=int, default=30, help="Max listings per source")
    p.add_argument("--offline", action="store_true", help="Use fixtures, skip network")
    p.add_argument("--out", type=str, default="samples/ranked.csv",
                   help="Output CSV path (relative to repo root)")
    p.add_argument("--json-out", type=str, default=None,
                   help="Optional JSON output path for full Listing records")
    args = p.parse_args(argv)

    sources = args.source or list(REGISTRY.keys())
    repo_root = Path(__file__).resolve().parents[1]

    # Crawl
    all_raw: list[dict] = []
    for src in sources:
        mod = REGISTRY.get(src)
        if not mod:
            print(f"unknown source: {src}", file=sys.stderr)
            continue
        recs = mod.crawl(limit=args.limit, offline=args.offline or None)
        print(f"[{src}] crawled {len(recs)} raw records")
        for r in recs:
            r.setdefault("source", src)
            all_raw.append(r)

    # Normalize
    listings: list[Listing] = []
    dropped = 0
    for r in all_raw:
        li = normalize(r, source=r.get("source") or "unknown")
        if li:
            listings.append(li)
        else:
            dropped += 1
    print(f"normalized {len(listings)} listings ({dropped} dropped)")

    # Rank
    ranked = rank(listings)
    print(f"ranked {len(ranked)} listings")

    # Write CSV
    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for li in ranked:
            w.writerow(_row(li))
    print(f"wrote {out_path.relative_to(repo_root)}")

    if args.json_out:
        jp = repo_root / args.json_out
        jp.parent.mkdir(parents=True, exist_ok=True)
        with jp.open("w", encoding="utf-8") as f:
            json.dump([li.to_dict() for li in ranked], f, indent=2, default=str)
        print(f"wrote {jp.relative_to(repo_root)}")

    # Print top 5 to stdout
    print("\nTop 5 (rank | composite | V/Q/U | zone | price | $/m² | title):")
    for li in ranked[:5]:
        print(
            f" #{li.rank:<2} {li.rank_score:>5.1f}  "
            f"V{li.value_score:>4.0f} Q{li.quality_score:>4.0f} "
            f"U{li.upside_score:>4.0f}  "
            f"{li.zone or '?':<13} "
            f"${(li.price_usd or 0):>10,.0f}  "
            f"${li.price_per_m2 or 0:>7.2f}/m²  "
            f"{li.title[:50]}"
        )
    return 0

if __name__ == "__main__":
    sys.exit(main())
