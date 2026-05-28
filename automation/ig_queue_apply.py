"""ig_queue_apply.py — apply operator approve/skip decisions to the queue.

The /admin/ig-review widget collects decisions in localStorage and posts
them as a single JSON payload to /api/admin/ig-queue-apply, which
dispatches the `pulpo-ig-queue-apply` GitHub workflow with the decisions
on the `decisions_json` input.  That workflow runs this module to mutate
`web/data/ig_queue.json` and commit the change back to main via
pulpo-bot — same persistence path the publisher uses for the
`posted_at` flip.

Why a workflow dispatch rather than a direct write from Vercel: the
queue lives in git, not a database, and the only write path to main is
the bot PAT used inside Actions.  Reusing the same channel keeps a
single source of truth + a single audit trail (the workflow run, the
commit, the diff).

Decisions schema:

    {
      "1": "approve",   # day N → "approve" | "skip"
      "2": "skip",
      ...
    }

Mutation rules (all idempotent — re-running with the same payload is a
no-op on disk):

  - approve  →  item.approved = true,  item.skipped removed
  - skip     →  item.approved = false, item.skipped = true
  - unknown decision value or unknown day  →  recorded as `ignored`
  - item that is already posted (posted_at != null)  →  recorded as
    `frozen` and left untouched. Reversing a post via decision is never
    a safe operation; if the operator needs to back out a published
    post they edit by hand.

CLI:

    python3 -m automation.ig_queue_apply \\
        --batch drop_01 \\
        --decisions '{"1":"approve","2":"skip"}' \\
        [--queue web/data/ig_queue.json] [--dry-run]

Exit codes:
    0  applied (or dry-run printed without writing)
    2  bad input (missing/invalid batch, bad decisions JSON)
    3  queue file missing or unreadable
    4  batch mismatch — queue.batch != --batch arg (operator submitted
       against a stale drop; safer to bail than to mutate the wrong file)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation._atomic import atomic_write_json


VALID_DECISIONS = {"approve", "skip"}
DEFAULT_QUEUE_PATH = Path("web/data/ig_queue.json")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_decisions(raw: str) -> dict[int, str]:
    """Parse the `--decisions` JSON string into {day_int: decision_str}.

    Raises ValueError on any malformed input.  Tolerant of string OR
    int keys (the frontend uses strings; tests are easier to write
    with ints), but values must be exactly "approve" or "skip".
    """
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"decisions is not valid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("decisions must be a JSON object")

    out: dict[int, str] = {}
    for k, v in obj.items():
        try:
            day = int(k)
        except (TypeError, ValueError) as e:
            raise ValueError(f"decision key {k!r} is not an integer day") from e
        if v not in VALID_DECISIONS:
            raise ValueError(
                f"decision value {v!r} for day {day} is not one of {sorted(VALID_DECISIONS)}"
            )
        out[day] = v
    return out


def apply_decisions(
    payload: dict[str, Any], decisions: dict[int, str], *, now_iso: str | None = None
) -> dict[str, Any]:
    """Mutate `payload['items']` in place per decisions; return a summary.

    Summary shape:
        {
          "approved":  [day, day, ...],   # newly + already approved
          "skipped":   [day, ...],
          "frozen":    [day, ...],        # already posted, untouched
          "ignored":   [{day, reason}, ...],  # day not in queue
          "unchanged": True/False,        # whether disk write is needed
        }
    """
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("queue payload has no items list")

    when = now_iso or _utcnow_iso()
    by_day: dict[int, dict[str, Any]] = {}
    for it in items:
        d = it.get("day")
        if isinstance(d, int):
            by_day[d] = it

    summary: dict[str, Any] = {
        "approved": [],
        "skipped": [],
        "frozen": [],
        "ignored": [],
    }
    any_change = False

    for day, decision in sorted(decisions.items()):
        item = by_day.get(day)
        if item is None:
            summary["ignored"].append({"day": day, "reason": "unknown_day"})
            continue
        if item.get("posted_at"):
            summary["frozen"].append(day)
            continue

        if decision == "approve":
            if item.get("approved") is not True:
                item["approved"] = True
                item["approved_at"] = when
                any_change = True
            else:
                item.setdefault("approved_at", when)
            if item.pop("skipped", None) is not None:
                any_change = True
            item.pop("skipped_at", None)
            summary["approved"].append(day)

        elif decision == "skip":
            if item.get("approved") is True:
                item["approved"] = False
                any_change = True
            if item.get("skipped") is not True:
                item["skipped"] = True
                item["skipped_at"] = when
                any_change = True
            item.pop("approved_at", None)
            summary["skipped"].append(day)

    summary["unchanged"] = not any_change
    return summary


def _read_queue(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise FileNotFoundError(f"queue not found at {path}") from e
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"queue JSON parse error at {path}: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError(f"queue at {path} is not a JSON object")
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply operator decisions to the IG queue.")
    parser.add_argument("--batch", required=True, help="Expected payload.batch (safety check)")
    parser.add_argument("--decisions", required=True, help='JSON object: {"1":"approve",...}')
    parser.add_argument(
        "--queue",
        type=Path,
        default=DEFAULT_QUEUE_PATH,
        help="Path to ig_queue.json (default: web/data/ig_queue.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary; do not write to disk.",
    )
    args = parser.parse_args(argv)

    try:
        decisions = parse_decisions(args.decisions)
    except ValueError as e:
        print(f"[ig_queue_apply] bad --decisions: {e}", file=sys.stderr)
        return 2

    if not decisions:
        print("[ig_queue_apply] decisions is empty — nothing to do.")
        return 0

    try:
        payload = _read_queue(args.queue)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ig_queue_apply] {e}", file=sys.stderr)
        return 3

    payload_batch = payload.get("batch")
    if payload_batch != args.batch:
        print(
            f"[ig_queue_apply] batch mismatch: queue.batch={payload_batch!r} "
            f"but --batch={args.batch!r}",
            file=sys.stderr,
        )
        return 4

    summary = apply_decisions(payload, decisions)

    print(
        "[ig_queue_apply] "
        f"batch={args.batch} "
        f"approved={len(summary['approved'])} "
        f"skipped={len(summary['skipped'])} "
        f"frozen={len(summary['frozen'])} "
        f"ignored={len(summary['ignored'])} "
        f"unchanged={summary['unchanged']}"
    )
    if summary["ignored"]:
        for row in summary["ignored"]:
            print(f"  ignored day={row['day']} reason={row['reason']}")

    if args.dry_run:
        print("[ig_queue_apply] dry-run — disk untouched.")
        return 0

    if summary["unchanged"]:
        print("[ig_queue_apply] no changes to write.")
        return 0

    atomic_write_json(args.queue, payload, indent=2)
    print(f"[ig_queue_apply] wrote {args.queue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
