#!/usr/bin/env python3
"""Row-count sentinel CLI — PR-D2.

Usage:
    python3 scripts/run_row_count_sentinel.py                  # run + print verdicts
    python3 scripts/run_row_count_sentinel.py --fail-on-crit   # exit 1 on CRIT

Output:
- Per-source verdicts to stdout (human-readable)
- New ticks appended to ``web/data/row_count_history.jsonl``
- Exit code 1 (with --fail-on-crit) if any source is CRIT — used by
  the cron + nightly to trigger the Slack-on-failure step.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history-path",
        type=Path,
        default=REPO_ROOT / "web" / "data" / "row_count_history.jsonl",
        help="Path to the append-only history JSONL.",
    )
    parser.add_argument(
        "--sv-ranked",
        type=Path,
        default=REPO_ROOT / "web" / "data" / "ranked.json",
        help="SV ranked.json path.",
    )
    parser.add_argument(
        "--pa-ranked",
        type=Path,
        default=REPO_ROOT / "web" / "data" / "ranked.PA.json",
        help="PA ranked.PA.json path (skipped silently if absent).",
    )
    parser.add_argument(
        "--fail-on-crit",
        action="store_true",
        help="Exit 1 if any source has level=critical. CI uses this.",
    )
    parser.add_argument(
        "--no-append",
        action="store_true",
        help=(
            "Classify without appending to row_count_history.jsonl. "
            "Use for pre-commit candidate gates."
        ),
    )
    parser.add_argument(
        "--floor",
        type=int,
        default=None,
        help=(
            "Catalogue count floor. When set, a per-source CRITICAL drop no "
            "longer blocks the commit if the sv __total__ is healthy (>= floor "
            "and not itself critical) — a single dead source can't freeze a "
            "healthy catalogue. Only a catastrophic total collapse blocks."
        ),
    )
    args = parser.parse_args()

    from automation.row_count_sentinel import (
        downgrade_experimental,
        gate_decision,
        load_history,
        run_tick,
    )
    from pulpo.scrapers._metadata import SCRAPER_METADATA

    ranked_paths = {"sv": args.sv_ranked}
    if args.pa_ranked.exists():
        ranked_paths["pa"] = args.pa_ranked

    verdicts = run_tick(
        ranked_paths=ranked_paths,
        history_path=args.history_path,
        record=not args.no_append,
    )
    verdicts = downgrade_experimental(verdicts, SCRAPER_METADATA)

    # Print a compact table.
    print(f"{'level':<10} {'country':<8} {'source':<22} prev → curr (delta)")
    print("-" * 80)
    for v in verdicts:
        pct = f"{v.pct:+.1%}"
        print(
            f"{v.level:<10} {v.country:<8} {v.source:<22} "
            f"{v.prev_count} → {v.curr_count} (Δ{v.delta}, {pct})"
        )

    if args.no_append:
        if not load_history(args.history_path):
            print("\n[row_count] no baseline history; gate skipped by first_observation semantics")
        print(f"\nClassified {len(verdicts)} counts without appending to {args.history_path}")
    else:
        print(f"\nWrote {len(verdicts)} ticks to {args.history_path}")

    if args.fail_on_crit:
        should_block, msg = gate_decision(verdicts, floor=args.floor)
        if msg:
            print(f"\n[row_count] {msg}")
        return 1 if should_block else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
