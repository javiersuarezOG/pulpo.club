"""One-glance dashboard for the goals/ optimization registry.

Prints one row per goal: status, cadence, surface, last journal action,
iteration count, and the next decision date (from the most recent
`change` entry). This is the human review surface named in
goals/README.md — check it weekly.

Usage:
  python3 scripts/goal_status.py
  python3 scripts/goal_status.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from goal_registry import (  # noqa: E402
    active_surface_locks,
    goal_names,
    load_journal,
    load_spec,
)


def summarize(name: str) -> dict:
    spec = load_spec(name)
    journal = load_journal(name)
    last = journal[-1] if journal else {}
    changes = [e for e in journal if e.get("action") == "change"]
    last_change = changes[-1] if changes else {}
    return {
        "goal": name,
        "status": spec.get("status"),
        "cadence": spec.get("cadence"),
        "surface": spec.get("surface"),
        "owner_goal": spec.get("owner_goal"),
        "iterations": max((e.get("iter", 0) for e in journal), default=0),
        "last_action": last.get("action"),
        "last_ts": last.get("ts"),
        "in_flight_variable": last_change.get("variable")
        if last.get("action") == "change"
        else None,
        "decision_due": last_change.get("decision_due")
        if last.get("action") == "change"
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    rows = [summarize(name) for name in goal_names()]
    locks = active_surface_locks()

    if args.json:
        print(json.dumps({"goals": rows, "surface_locks": locks}, indent=2))
        return 0

    if not rows:
        print("No goals registered under goals/.")
        return 0

    header = (
        f"{'GOAL':<24} {'STATUS':<7} {'CADENCE':<9} {'ITER':>4} "
        f"{'LAST ACTION':<12} {'DECISION DUE':<13} SURFACE"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['goal']:<24} {r['status'] or '?':<7} {r['cadence'] or '?':<9} "
            f"{r['iterations']:>4} {r['last_action'] or '-':<12} "
            f"{r['decision_due'] or '-':<13} {r['surface'] or '?'}"
        )
    if locks:
        print("\nIn-flight surface locks:")
        for surface, goal in sorted(locks.items()):
            print(f"  {surface}  <-  {goal}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
