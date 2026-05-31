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

DEFAULT_HOST = "https://eu.posthog.com"


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
