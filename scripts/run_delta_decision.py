#!/usr/bin/env python3
"""Post the per-source delta DECISION to Slack — the operational
runbook layer on top of the row-count gate.

The gate (``scripts/run_row_count_sentinel.py --fail-on-crit``) answers
"did a source crater?" and blocks the commit. This script answers the
next question — "what KIND of failure, and what's the action?" — and
turns the raw verdict into one of the runbook buckets
(``source_failed`` / ``source_partial`` / ``validation_collapse`` /
``expected_change`` / ``unknown``). See
``automation/delta_decision.KNOWN_DELTA_DECISIONS``.

Consumer note (CLAUDE.md producer/consumer rule, post-2026-06-02): this
script is THE consumer of ``automation/delta_decision`` — the classifier
landed in PR #780 and this wires it into the nightly so it is not a
tombstone.

Design:
- Reads the same candidate ``ranked.fresh.json`` (fallback
  ``ranked.json``) the gate reads, classifies per-source deltas with
  ``record=False`` so the 7-tick baseline is untouched.
- Derives ``succeeded_sources`` from ``source_health_history.jsonl``:
  a source whose latest row is NOT ``status=red`` ran successfully
  (a degraded source still scraped, just fewer rows → ``source_partial``;
  a red/zero source → ``source_failed``).
- ``validation_collapse`` fires when health shows ``scraped>0`` but
  ``kept==0`` — the scrape worked, validation dropped everything.
- Best-effort: always exits 0. This is informational; the gate already
  blocks. A Slack outage must never mask the underlying failure. Runs
  with ``if: always()`` in the nightly so the decision lands even when
  the gate blocked the commit.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _latest_status_by_source(rows: list[dict]) -> dict[str, str]:
    """Latest ``status`` per source by timestamp."""
    latest_ts: dict[str, str] = {}
    status: dict[str, str] = {}
    for row in rows:
        src = row.get("source")
        if not isinstance(src, str) or not src:
            continue
        ts = row.get("ts") or ""
        if src not in latest_ts or ts > latest_ts[src]:
            latest_ts[src] = ts
            status[src] = str(row.get("status") or "")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sv-ranked", type=Path, default=Path("web/data/ranked.json"))
    parser.add_argument("--fresh-ranked", type=Path, default=Path("web/data/ranked.fresh.json"))
    parser.add_argument("--pa-ranked", type=Path, default=Path("web/data/ranked.PA.json"))
    parser.add_argument("--history-path", type=Path, default=Path("web/data/row_count_history.jsonl"))
    parser.add_argument("--data-dir", type=Path, default=Path("web/data"))
    parser.add_argument("--run-url", default=os.environ.get("RUN_URL", ""))
    parser.add_argument("--dry-run", action="store_true", help="Classify + print, never POST.")
    args = parser.parse_args(argv)

    from automation.delta_decision import decide_deltas, format_slack_decision
    from automation.row_count_sentinel import run_tick
    from automation.watchdog import _read_source_history
    from pulpo.scrapers._metadata import SCRAPER_METADATA

    # Prefer the fresh-only snapshot the gate uses — carry-forward must
    # never influence the decision.
    sv_ranked = args.fresh_ranked if args.fresh_ranked.is_file() and args.fresh_ranked.stat().st_size > 0 else args.sv_ranked
    if not sv_ranked.is_file():
        print(f"[delta-decision] no candidate ranked file at {sv_ranked} — nothing to decide.")
        return 0

    ranked_paths = {"sv": sv_ranked}
    if args.pa_ranked.is_file():
        ranked_paths["pa"] = args.pa_ranked

    verdicts = run_tick(ranked_paths=ranked_paths, history_path=args.history_path, record=False)

    health_rows = list(_read_source_history(args.data_dir))
    latest_status = _latest_status_by_source(health_rows)
    succeeded = {src for src, st in latest_status.items() if st != "red"}

    decisions = decide_deltas(
        verdicts,
        source_health_rows=health_rows,
        succeeded_sources=succeeded,
        metadata=SCRAPER_METADATA,
    )

    text = format_slack_decision(decisions, run_url=args.run_url or None)
    print(text)

    actionable = [d for d in decisions if d.level in {"critical", "warn"}]
    if not actionable or args.dry_run:
        if args.dry_run:
            print("[delta-decision] --dry-run: not posting.")
        return 0

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        print("[delta-decision] SLACK_WEBHOOK_URL unset — skipping POST.")
        return 0

    from scripts.check_source_health import _post_slack
    _post_slack(webhook_url, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
