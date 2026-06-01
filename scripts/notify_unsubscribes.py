#!/usr/bin/env python3
"""Post Slack notifications for new Pulpo newsletter unsubscribes.

Runs every 30 minutes via `.github/workflows/pulpo-unsubscribe-notify.yml`.
Queries PostHog for `newsletter.unsubscribed` events from the past
35 minutes (5-min overlap with the previous tick to avoid losing
events at the boundary) and posts each one to Slack.

Privacy: events carry `recipient_hash` (sha256-truncated), NOT raw
email. Slack message shows only the hash prefix, which is enough to
track trends without exposing PII to a chat history. To resolve a
hash back to an email, cross-reference via Clerk dashboard
(server-side authenticated).

At-most-twice delivery: a 30-min cron + 35-min query window can ping
the same unsub twice if it lands at the boundary. Acceptable — better
than missing one. The Slack message includes the PostHog event ID, so
duplicates are visible (operator can ignore the second).

Exit codes:
  0 — clean run (0 or more unsubs posted)
  2 — pre-flight failure (missing env vars)
  Never exits with a Slack-side failure — telemetry/notification
  failures must not page the cron itself. They log + continue.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_HOST = "https://eu.posthog.com"
# 35 min = 30-min cron tick + 5-min grace for clock skew + a delayed
# run starting up. Each unsub event appears in at most TWO consecutive
# windows; PostHog event IDs in the Slack message make dups visible.
DEFAULT_WINDOW_MIN = 35


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def query_unsubscribes(*, host: str, project: str, key: str, window_min: int) -> list[dict]:
    """Return rows of recent unsubscribe events.

    Each row has keys: recipient_hash, issue_number, source, ts (ISO),
    event_id. Returns [] on any error (PostHog outage, schema drift,
    etc.) — silence beats false-positive Slack noise.
    """
    hogql = (
        "SELECT "
        "  uuid AS event_id, "
        "  timestamp AS ts, "
        "  JSONExtractString(properties, 'recipient_hash') AS recipient_hash, "
        "  JSONExtractString(properties, 'issue_number') AS issue_number, "
        "  JSONExtractString(properties, 'source') AS source "
        "FROM events "
        "WHERE event = 'newsletter.unsubscribed' "
        f"  AND timestamp > now() - toIntervalMinute({int(window_min)}) "
        "ORDER BY timestamp ASC"
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
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
        data = json.loads(body) if body else {}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    rows = data.get("results") or []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            continue
        out.append({
            "event_id": row[0] or "",
            "ts": row[1] or "",
            "recipient_hash": row[2] or "",
            "issue_number": row[3] or "",
            "source": row[4] or "",
        })
    return out


def format_slack_blocks(rows: list[dict]) -> dict | None:
    """Build the Slack payload for a batch of unsubs. None if no rows
    (caller should skip the POST entirely)."""
    if not rows:
        return None
    n = len(rows)
    header = (
        f":outbox_tray: *{n} newsletter unsubscribe{'s' if n != 1 else ''} in the last 30 min*"
    )
    lines = [header, ""]
    for r in rows:
        # Hash prefix only — privacy-safe for Slack. Operator can
        # resolve full hash → user via Clerk dashboard if needed.
        hash_short = (r["recipient_hash"] or "")[:8] or "?"
        issue = r["issue_number"] or "?"
        source = r["source"] or "?"
        ts = r["ts"] or "?"
        # PostHog event ID short tail to spot the at-most-twice
        # duplicate that the 35-min overlap window allows.
        eid_short = (r["event_id"] or "")[-8:] or "?"
        lines.append(
            f"• `hash={hash_short}` · issue {issue} · source={source} · {ts} · evt={eid_short}"
        )
    return {"text": "\n".join(lines)}


def post_slack(webhook_url: str, payload: dict) -> bool:
    """Post to Slack. Returns True on 2xx, False otherwise. Never throws."""
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, TimeoutError):
        return False


def main() -> int:
    host = env("POSTHOG_HOST", DEFAULT_HOST)
    project = env("POSTHOG_PROJECT_ID")
    key = env("POSTHOG_PERSONAL_API_KEY")
    slack = env("SLACK_WEBHOOK_URL")
    window_min = int(env("UNSUBSCRIBE_NOTIFY_WINDOW_MIN", "0") or DEFAULT_WINDOW_MIN)

    missing = [n for n, v in (
        ("POSTHOG_PROJECT_ID", project),
        ("POSTHOG_PERSONAL_API_KEY", key),
        ("SLACK_WEBHOOK_URL", slack),
    ) if not v]
    if missing:
        print(f"[notify_unsubscribes] missing env: {missing}", file=sys.stderr)
        return 2

    rows = query_unsubscribes(
        host=host, project=project, key=key, window_min=window_min,
    )
    if not rows:
        # Clean: no unsubs in the window. Don't spam Slack with "0
        # unsubs" — silence is the desired output here.
        print(f"[notify_unsubscribes] 0 unsubs in last {window_min}m — nothing to post")
        return 0

    payload = format_slack_blocks(rows)
    ok = post_slack(slack, payload) if payload else False
    if not ok:
        print(
            f"[notify_unsubscribes] WARNING: Slack post failed for {len(rows)} unsubs",
            file=sys.stderr,
        )
        # Still exit 0 — Slack outage isn't a cron failure. The unsubs
        # will be reported on the next tick via the 35-min overlap.
    print(f"[notify_unsubscribes] posted {len(rows)} unsub(s) to Slack (ok={ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
