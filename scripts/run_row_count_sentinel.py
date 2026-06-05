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
    args = parser.parse_args()

    from automation.row_count_sentinel import any_critical, run_tick

    ranked_paths = {"sv": args.sv_ranked}
    if args.pa_ranked.exists():
        ranked_paths["pa"] = args.pa_ranked

    verdicts = run_tick(
        ranked_paths=ranked_paths,
        history_path=args.history_path,
    )

    # Print a compact table.
    print(f"{'level':<10} {'country':<8} {'source':<22} prev → curr (delta)")
    print("-" * 80)
    for v in verdicts:
        pct = f"{v.pct:+.1%}"
        print(
            f"{v.level:<10} {v.country:<8} {v.source:<22} "
            f"{v.prev_count} → {v.curr_count} (Δ{v.delta}, {pct})"
        )

    print(f"\nWrote {len(verdicts)} ticks to {args.history_path}")

    if args.fail_on_crit and any_critical(verdicts):
        print("\n[row_count] at least one source is CRITICAL — exiting 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
