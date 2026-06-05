#!/usr/bin/env python3
"""Probe audit driver — PR-S3b.

Loads the probe seed file, the current ranked.json, and the supporting
state files (source_health_history.jsonl, listings_ledger.json), runs
the matcher from PR-S3a, and emits:

  * stdout — human-readable per-probe table + summary
  * web/data/probe_audit_history.jsonl — append-only audit history
    (one row per probe per run)
  * web/data/probe_audit_latest.json — latest run's summary (for the
    operator dashboard)

Usage:
    python3 scripts/run_probe_audit.py                # SV probes
    python3 scripts/run_probe_audit.py --country sv   # explicit
    python3 scripts/run_probe_audit.py --fail-on-low-match  # exit 1 if match_rate < 0.5
    python3 scripts/run_probe_audit.py --probes-path config/probes/custom.json

The runner is offline-safe: every file it reads tolerates absence
(empty result, no crash).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
# Make `automation.*` and `pulpo.*` importable when run as a script.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_PROBES_DIR = REPO_ROOT / "config" / "probes"
DEFAULT_RANKED = REPO_ROOT / "web" / "data" / "ranked.json"
DEFAULT_HEALTH = REPO_ROOT / "web" / "data" / "source_health_history.jsonl"
DEFAULT_LEDGER = REPO_ROOT / "web" / "data" / "listings_ledger.json"
DEFAULT_HISTORY = REPO_ROOT / "web" / "data" / "probe_audit_history.jsonl"
DEFAULT_LATEST = REPO_ROOT / "web" / "data" / "probe_audit_latest.json"

MIN_MATCH_RATE_FOR_FAIL = 0.50


def _load_ranked(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--country", default="sv",
        help="Country code; selects config/probes/<cc>.json. Default sv.",
    )
    parser.add_argument(
        "--probes-path", type=Path, default=None,
        help="Override probe file path. Default config/probes/<country>.json.",
    )
    parser.add_argument(
        "--ranked", type=Path, default=DEFAULT_RANKED,
        help=f"Path to ranked.json (default {DEFAULT_RANKED}).",
    )
    parser.add_argument(
        "--history", type=Path, default=DEFAULT_HISTORY,
        help=f"Append-only history JSONL (default {DEFAULT_HISTORY}).",
    )
    parser.add_argument(
        "--latest", type=Path, default=DEFAULT_LATEST,
        help=f"Latest-run summary (default {DEFAULT_LATEST}).",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.55,
        help="match_probe threshold (default 0.55).",
    )
    parser.add_argument(
        "--fail-on-low-match", action="store_true",
        help=(
            "Exit 1 if match_rate < 0.50. CI uses this to surface a "
            "regression where pulpo's coverage of sampled external "
            "listings has dropped."
        ),
    )
    parser.add_argument(
        "--no-write", action="store_true",
        help="Skip persistence; print only.",
    )
    args = parser.parse_args()

    # Lazy imports so --help works without the matcher dep loaded.
    from automation.probe_audit import match_probes, summarize
    from automation.probe_loader import (
        build_matcher_inputs, load_probes_from_file,
    )
    from pulpo.scrapers._metadata import SCRAPER_METADATA

    probes_path = args.probes_path or (DEFAULT_PROBES_DIR / f"{args.country}.json")
    probes = load_probes_from_file(probes_path)
    if not probes:
        print(f"[probe_audit] no probes loaded from {probes_path}; nothing to do.")
        return 0

    listings = _load_ranked(args.ranked)
    print(f"[probe_audit] loaded {len(probes)} probes vs {len(listings)} ranked listings")

    match_kwargs = build_matcher_inputs(
        scraper_metadata=SCRAPER_METADATA,
        source_health_history_path=DEFAULT_HEALTH,
        ledger_path=DEFAULT_LEDGER,
    )

    results = match_probes(
        probes, listings,
        threshold=args.threshold,
        **match_kwargs,
    )
    summary = summarize(results)

    # Print compact table.
    print(f"\n{'probe':<60} {'status':<28} score")
    print("-" * 100)
    for r in results:
        title = (r.probe.title or "")[:58]
        status = (
            f"matched ({r.matched_key})"
            if r.matched_key
            else (r.miss_classification or "?")
        )
        print(f"{title:<60} {status:<28} {r.matched_score:.2f}")

    print()
    print(
        f"summary: total={summary['total_probed']} "
        f"matched={summary['matched']} "
        f"match_rate={summary['match_rate']:.1%}"
    )
    if summary["by_miss_classification"]:
        print("misses by class:")
        for cls, n in sorted(summary["by_miss_classification"].items(), key=lambda x: -x[1]):
            print(f"  {cls}: {n}")

    if not args.no_write:
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        args.history.parent.mkdir(parents=True, exist_ok=True)
        with args.history.open("a", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps({"ts": now_iso, **r.to_dict()}) + "\n")
        latest_record = {
            "ts": now_iso,
            "country": args.country,
            **summary,
        }
        args.latest.parent.mkdir(parents=True, exist_ok=True)
        args.latest.write_text(
            json.dumps(latest_record, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nWrote {args.history} + {args.latest}")

    if args.fail_on_low_match and summary["match_rate"] < MIN_MATCH_RATE_FOR_FAIL:
        print(
            f"\n[probe_audit] FAIL: match_rate={summary['match_rate']:.1%} "
            f"< {MIN_MATCH_RATE_FOR_FAIL:.0%} threshold",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
