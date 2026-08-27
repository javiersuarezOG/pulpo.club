#!/usr/bin/env python3
"""Backfill geospatial enrichment over the committed catalog.

The nightly already backfills on its own — the cell cache is the resume
state, so each run continues where the last one's budget ran out. This
script exists for when you don't want to wait for N nightlies: it drives
the SAME ``enrich_listings`` orchestrator against ``web/data/ranked.json``
with the caps lifted, so there is exactly one implementation of "fetch a
cell" in the codebase.

Usage:
    # what would we fetch? (no network, no writes)
    python3 scripts/backfill_geo_enrichment.py --dry-run

    # a controlled slice
    python3 scripts/backfill_geo_enrichment.py --limit 50

    # one provider, unbounded
    python3 scripts/backfill_geo_enrichment.py --provider nasa_power

This never writes ranked.json — enrichment lives entirely in its own
sidecar. Commit the resulting web/data changes as their own data PR.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from automation.geo_enrichment import REGISTRY, enrich_listings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0,
                    help="only process the first N listings with coords (0 = all)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be fetched; no network, no writes")
    ap.add_argument("--provider", action="append", default=[],
                    metavar="NAME",
                    help=f"restrict to a provider (repeatable). "
                         f"Known: {', '.join(sorted(REGISTRY))}")
    ap.add_argument("--deadline-s", type=float, default=0.0,
                    help="wall-clock budget in seconds (0 = unlimited)")
    ap.add_argument("--max-calls", type=int, default=0,
                    help="cap total API calls (0 = the module default)")
    ap.add_argument("--data-dir", default=str(REPO / "web" / "data"),
                    help="where ranked.json and the geo sidecars live")
    args = ap.parse_args()

    unknown = [p for p in args.provider if p not in REGISTRY]
    if unknown:
        print(f"error: unknown provider(s) {unknown}; "
              f"known: {sorted(REGISTRY)}", file=sys.stderr)
        return 2

    # The orchestrator no-ops under PULPO_OFFLINE=1 (so the pipeline smoke
    # stays hermetic). A human running a backfill explicitly wants network.
    if os.environ.get("PULPO_OFFLINE") == "1":
        print("PULPO_OFFLINE=1 is set — unsetting it for this backfill.")
        os.environ.pop("PULPO_OFFLINE", None)

    data_dir = Path(args.data_dir)
    ranked_path = data_dir / "ranked.json"
    if not ranked_path.exists():
        print(f"error: {ranked_path} not found", file=sys.stderr)
        return 2

    listings = json.loads(ranked_path.read_text(encoding="utf-8"))
    if not isinstance(listings, list):
        print(f"error: {ranked_path} is not a JSON array", file=sys.stderr)
        return 2
    print(f"loaded {len(listings)} listings from {ranked_path}")

    deadline = (time.monotonic() + args.deadline_s) if args.deadline_s > 0 else None
    metrics = enrich_listings(
        listings,
        cells_path=data_dir / "geo_cells.json",
        sidecar_path=data_dir / "geo_enrichment.json",
        history_path=None if args.dry_run else data_dir / "geo_enrichment_history.jsonl",
        providers=args.provider or None,
        deadline=deadline,
        max_listings=args.limit,
        max_calls=args.max_calls,
        dry_run=args.dry_run,
    )

    per_provider = metrics.pop("per_provider", {})
    print(json.dumps(metrics, indent=2, sort_keys=True))
    for name, pm in sorted(per_provider.items()):
        print(f"  {name}: needed={pm['cells_needed']} calls={pm['api_calls']} "
              f"ok={pm['ok']} na={pm['na']} failed={pm['failed']}"
              + (f" DISABLED({pm.get('disabled_reason')})" if pm.get("disabled") else ""))

    if args.dry_run:
        print("\ndry run — nothing fetched, nothing written.")
    elif metrics.get("listings_pending"):
        print(f"\n{metrics['listings_pending']} listing(s) still have pending "
              f"providers — re-run to continue, or let the nightly finish it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
