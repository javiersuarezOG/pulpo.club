#!/usr/bin/env python3
"""Alert when an external webhook family goes silent.

This is a positive heartbeat: each family must have at least one recent
PostHog event. Absence is the outage signal.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_HOST = "https://eu.posthog.com"
DEFAULT_RUNBOOK = "https://github.com/javiersuarezOG/pulpo.club/actions/workflows/pulpo-webhook-health.yml"

# `webhook.received` is captured exclusively by api/stripe/webhook.js. The
# `provider: "stripe"` tag was added alongside this script in the same PR
# for forward-compat (if/when a second webhook source is added we re-add
# the filter), but filtering by it today would skip every existing event
# that pre-dates the deploy — false-alarming on healthy systems until the
# next Stripe webhook fires post-merge. Match all `webhook.received` rows
# while it's still single-source.
FAMILIES = {
    "resend": {
        "label": "Resend newsletter.*",
        "where": "startsWith(event, 'newsletter.')",
    },
    "clerk": {
        "label": "Clerk clerk.*",
        "where": "startsWith(event, 'clerk.')",
    },
    "stripe": {
        "label": "Stripe webhook.received",
        "where": "event = 'webhook.received'",
    },
}


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed: {exc.code} {detail}") from exc


def query_last_seen(host: str, project: str, key: str, where: str) -> dt.datetime | None:
    hogql = f"""
        SELECT max(timestamp) AS last_seen
        FROM events
        WHERE {where}
    """
    data = post_json(
        f"{host.rstrip('/')}/api/projects/{project}/query/",
        {"Authorization": f"Bearer {key}"},
        {"query": {"kind": "HogQLQuery", "query": hogql}},
    )
    rows = data.get("results") or []
    if not rows or not rows[0] or not rows[0][0]:
        return None
    raw = str(rows[0][0]).replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def slack(webhook_url: str, text: str, dry_run: bool) -> None:
    if dry_run or not webhook_url:
        print(text)
        return
    post_json(webhook_url, {}, {"text": text})


def main() -> int:
    parser = argparse.ArgumentParser(description="Check webhook event heartbeats in PostHog.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-age-hours", type=float, default=float(env("WEBHOOK_HEALTH_MAX_AGE_HOURS", "6")))
    parser.add_argument("--runbook-url", default=env("WEBHOOK_HEALTH_RUNBOOK_URL", DEFAULT_RUNBOOK))
    args = parser.parse_args()

    host = env("POSTHOG_HOST", DEFAULT_HOST)
    project = env("POSTHOG_PROJECT_ID")
    key = env("POSTHOG_PERSONAL_API_KEY")
    slack_url = env("SLACK_WEBHOOK_URL")
    if not project or not key:
        raise SystemExit("POSTHOG_PROJECT_ID and POSTHOG_PERSONAL_API_KEY are required")

    now = dt.datetime.now(dt.timezone.utc)
    failures: list[str] = []
    for name, cfg in FAMILIES.items():
        last_seen = query_last_seen(host, project, key, cfg["where"])
        if last_seen is None:
            failures.append(f"{cfg['label']} has never been seen")
            continue
        age_hours = (now - last_seen).total_seconds() / 3600
        print(f"{name}: last_seen={last_seen.isoformat()} age_hours={age_hours:.2f}")
        if age_hours > args.max_age_hours:
            failures.append(
                f"{cfg['label']} silent for {age_hours:.1f}h - last event {last_seen.isoformat()}"
            )

    for failure in failures:
        slack(slack_url, f":warning: {failure}. {args.runbook_url}", args.dry_run)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
