#!/usr/bin/env python3
"""Print per-shelf visible counts + activation status (6-shelf model).

Reads ``web/data/kpi_dashboard.json`` and renders the operator-facing
shelf rundown:

  • Per-shelf visible count.
  • PASS / FAIL against the ``min_real_listings`` threshold the
    dashboard recorded (mirrors the FE's HomeShelf.jsx gate).
  • Sorted by deficit so the most-under-supplied shelf is on top —
    the operator looking for "what should I work on next" sees it
    first.

Why this script vs. reading kpi_dashboard.json directly: the canonical
JSON's ``per_shelf_visible`` block is fine for dashboards but reads
poorly in a job log. This produces a single ~10-line block any operator
can paste into Slack or the PR body during inventory triage.

Always exits 0. Missing dashboard is reported as a hint to run the
nightly first; never blocks the workflow.

Usage::

    python3 scripts/show_shelf_counts.py                          # web/data/...
    python3 scripts/show_shelf_counts.py path/to/kpi_dashboard.json
    python3 scripts/show_shelf_counts.py --json                   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parents[1]
DEFAULT_DASHBOARD = REPO / "web" / "data" / "kpi_dashboard.json"


def load_dashboard(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def shelf_rundown(dashboard: dict) -> tuple[list[dict], int]:
    """Return ``(rows, min_real_listings)``.

    Each row: ``{shelf, count, renders, deficit}``. ``deficit`` is
    ``max(0, min_real_listings - count)`` — sorted descending so the
    operator sees the biggest gap first.
    """
    kpi = dashboard.get("kpi") or {}
    per_shelf = kpi.get("per_shelf_visible") or {}
    min_real = int(dashboard.get("min_real_listings") or 0)
    rows: list[dict] = []
    for shelf, info in per_shelf.items():
        count = int((info or {}).get("count") or 0)
        renders = bool((info or {}).get("renders_on_homepage"))
        rows.append({
            "shelf": shelf,
            "count": count,
            "renders": renders,
            "deficit": max(0, min_real - count),
        })
    # Largest deficit first; ties broken by alpha for stability.
    rows.sort(key=lambda r: (-r["deficit"], r["shelf"]))
    return rows, min_real


def format_block(rows: list[dict], min_real: int) -> str:
    """Render the shelf rundown as a plain-text block."""
    if not rows:
        return "SHELF RUNDOWN: no kpi_dashboard.json per_shelf data available."
    lines = [f"SHELF RUNDOWN (threshold ≥ {min_real})"]
    rendering = sum(1 for r in rows if r["renders"])
    total = len(rows)
    lines.append(f"  {rendering}/{total} shelves activate the homepage.")
    lines.append("")
    longest = max(len(r["shelf"]) for r in rows)
    for r in rows:
        mark = "✓" if r["renders"] else "✗"
        if r["renders"]:
            note = ""
        else:
            note = f"  (need +{r['deficit']} to activate)"
        lines.append(
            f"  {mark} {r['shelf']:<{longest}}  count={r['count']:<4}{note}"
        )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print per-shelf visible counts + activation status (6-shelf model).",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to kpi_dashboard.json (defaults to web/data/kpi_dashboard.json).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the per-shelf rundown as JSON instead of a plain-text block. "
             "Useful for downstream automation (e.g. PostHog ingestion).",
    )
    args = parser.parse_args(argv)

    path = Path(args.path) if args.path else DEFAULT_DASHBOARD
    dashboard = load_dashboard(path)
    if dashboard is None:
        # Print a hint, but always exit 0 — never block the workflow.
        print(
            f"[shelf-counts] {path} not found or unreadable. "
            "Run a nightly first to produce kpi_dashboard.json."
        )
        return 0

    rows, min_real = shelf_rundown(dashboard)

    if args.json:
        print(json.dumps({
            "min_real_listings": min_real,
            "shelves": rows,
            "activating": [r["shelf"] for r in rows if r["renders"]],
            "below_threshold": [r["shelf"] for r in rows if not r["renders"]],
        }, indent=2))
        return 0

    print(format_block(rows, min_real))
    return 0


if __name__ == "__main__":
    sys.exit(main())
