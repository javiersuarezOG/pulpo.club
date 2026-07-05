"""Auto-increment newsletter issue numbers from PostHog telemetry.

The send pipeline already fires `newsletter.send_succeeded` per recipient
with `issue_number` + `dry_run` properties (see
scripts/send_newsletter.py). Querying the max of those is the cheapest
"what was the last real issue I sent" signal we have — no new
persistence layer (no state file, no Vercel Blob, no PR per send),
nothing to keep in sync with git.

Auto-bump is only safe for the audience-wide broadcast path. Smoke-test
sends (`--only-email`) and operator previews (`--preview-cohorts`) MUST
pass an explicit `--issue-number`; otherwise a tester send to one
address would bump production state. The CLI in send_newsletter.py
enforces this; this module just answers "what's the next number".

Falls back to `default` (1) on any error — a PostHog outage must never
block a real send.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_HOST = "https://eu.posthog.com"

# ── Authoritative committed issue-number counter ──────────────────────────
# The number a real send uses is read from this committed file — NOT from a
# PostHog query that fails open to Issue 1 (launch audit P1). Git history is
# the audit trail. The nightly advances it once per ISO week (a hardened
# web/data commit path already exists); the Pro AND Free Sunday sends read
# it read-only, so both editions get the SAME number that week.
ISSUE_STATE_PATH = Path("web/data/newsletter_issue_state.json")


class IssueStateError(RuntimeError):
    """The committed issue-state file is missing, unreadable, or malformed.

    Callers on the send path MUST treat this as fail-closed — abort the
    send rather than fall back to a guessed number. Guessing is exactly the
    bug this replaces (a PostHog outage shipped Issue 1)."""


def _iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def read_issue_state(path: Path = ISSUE_STATE_PATH) -> dict:
    """Load + validate the committed issue-state. Raises IssueStateError
    (fail-closed) on any missing/corrupt/invalid condition."""
    if not path.exists():
        raise IssueStateError(f"issue-state file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise IssueStateError(f"issue-state file unreadable ({path}): {e}") from e
    if not isinstance(data, dict):
        raise IssueStateError(f"issue-state is not an object: {type(data).__name__}")
    n = data.get("issue_number")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise IssueStateError(f"issue-state issue_number invalid: {n!r}")
    return data


def current_issue_number(path: Path = ISSUE_STATE_PATH) -> int:
    """The issue number for THIS week's send. Fail-closed (see read_issue_state).

    Both the Pro and Free weekly sends call this, so they share one number
    per week. The nightly advance below is what moves it forward."""
    return read_issue_state(path)["issue_number"]


def advance_issue_state_for_week(
    path: Path = ISSUE_STATE_PATH,
    *,
    today: Optional[date] = None,
) -> tuple[dict, bool]:
    """Bump issue_number by 1 iff `today` falls in a later ISO week than the
    file records; otherwise leave it untouched. Idempotent within a week —
    the first nightly of a new ISO week advances, the rest are no-ops, and a
    re-run never double-advances. Writes the file only when it changes.

    Called by the NIGHTLY (which commits web/data), never the send path.
    Returns (state, changed).
    """
    today = today or datetime.now(timezone.utc).date()
    state = read_issue_state(path)
    wk = _iso_week(today)
    if state.get("iso_week") == wk:
        return state, False
    new_state = {
        "issue_number": state["issue_number"] + 1,
        "iso_week": wk,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "note": state.get("note", "Newsletter issue counter — advanced weekly by the nightly; read by the Pro+Free Sunday sends. Do not hand-edit unless resetting the sequence."),
    }
    path.write_text(
        json.dumps(new_state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return new_state, True


def _cli(argv: list[str]) -> int:
    """`python -m automation.newsletter.issue_state --advance` — the nightly
    hook. Prints a one-line breadcrumb; never raises past the boundary so a
    malformed file surfaces as a clear nonzero exit, not a traceback."""
    if "--advance" not in argv:
        print("[issue-state] usage: python -m automation.newsletter.issue_state --advance")
        return 2
    try:
        state, changed = advance_issue_state_for_week()
    except IssueStateError as e:
        print(f"[issue-state] ERROR: {e}")
        return 1
    verb = "advanced to" if changed else "unchanged at"
    print(f"[issue-state] {verb} issue_number={state['issue_number']} (week {state.get('iso_week')})")
    return 0


def next_issue_number(default: int = 1) -> int:
    """Return the next issue number to send.

    Computed as `max(properties.issue_number) + 1` from
    `newsletter.send_succeeded` events where `dry_run = false`.
    Returns `default` when:

      • POSTHOG_PROJECT_ID or POSTHOG_PERSONAL_API_KEY are unset
      • PostHog query errors, times out, or returns no rows
      • Stored value isn't an int (corruption / property-shape change)
    """
    host = (os.environ.get("POSTHOG_HOST") or "").strip() or DEFAULT_HOST
    project = (os.environ.get("POSTHOG_PROJECT_ID") or "").strip()
    key = (os.environ.get("POSTHOG_PERSONAL_API_KEY") or "").strip()
    if not project or not key:
        return default
    hogql = (
        "SELECT max(toInt(JSONExtractString(properties, 'issue_number'))) AS max_issue "
        "FROM events "
        "WHERE event = 'newsletter.send_succeeded' "
        "AND JSONExtractBool(properties, 'dry_run') = false"
    )
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/projects/{project}/query/",
        data=json.dumps({"query": {"kind": "HogQLQuery", "query": hogql}}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError):
        return default
    try:
        data = json.loads(body)
        rows = data.get("results") or []
        if not rows or not rows[0] or rows[0][0] is None:
            return default
        return int(rows[0][0]) + 1
    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
        return default


if __name__ == "__main__":
    import sys

    raise SystemExit(_cli(sys.argv[1:]))
