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
#
# `max_age_hours` per family — calibrated against Pulpo's actual event
# rates rather than a single global threshold:
#   • Resend fires on every newsletter generation (twice/fortnight) AND on
#     every user signup. Quiet > 12h = something's wrong.
#   • Clerk fires on user actions (signin, signup, invitation accept).
#     Overnight gaps of 12-18h are normal on a small subscriber base; 24h
#     is the right "still nothing? investigate" threshold.
#   • Stripe webhook.received fires on subscription state changes — most
#     accounts go 30 days between renewal events. 48h is generous; tighten
#     once we're > 100 paying users.
# These can be overridden per family via WEBHOOK_HEALTH_MAX_AGE_<FAMILY>
# env vars; the legacy WEBHOOK_HEALTH_MAX_AGE_HOURS still works as a
# global override for the workflow-dispatch test-fire path.
FAMILIES = {
    "resend": {
        "label": "Resend newsletter.*",
        "where": "startsWith(event, 'newsletter.')",
        "max_age_hours": 12.0,
    },
    "clerk": {
        "label": "Clerk clerk.*",
        "where": "startsWith(event, 'clerk.')",
        "max_age_hours": 24.0,
    },
    "stripe": {
        "label": "Stripe webhook.received",
        "where": "event = 'webhook.received'",
        "max_age_hours": 48.0,
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
    # Optional global override. When set, applies to every family —
    # useful for the "force a test alert" path (`--max-age-hours 0`).
    # When unset, per-family thresholds from FAMILIES win.
    parser.add_argument("--max-age-hours", type=float, default=None,
                        help="Global override; if unset, per-family thresholds from FAMILIES apply.")
    parser.add_argument("--runbook-url", default=env("WEBHOOK_HEALTH_RUNBOOK_URL", DEFAULT_RUNBOOK))
    args = parser.parse_args()

    # Legacy env var still respected for the workflow file's existing
    # test-fire pattern. Per-family env vars (WEBHOOK_HEALTH_MAX_AGE_RESEND
    # etc.) take precedence when defined.
    legacy_global = env("WEBHOOK_HEALTH_MAX_AGE_HOURS", "")

    host = env("POSTHOG_HOST", DEFAULT_HOST)
    project = env("POSTHOG_PROJECT_ID")
    key = env("POSTHOG_PERSONAL_API_KEY")
    slack_url = env("SLACK_WEBHOOK_URL")
    if not project or not key:
        raise SystemExit("POSTHOG_PROJECT_ID and POSTHOG_PERSONAL_API_KEY are required")

    now = dt.datetime.now(dt.timezone.utc)
    failures: list[str] = []
    for name, cfg in FAMILIES.items():
        # Resolution order: CLI > per-family env > legacy global env > FAMILIES default.
        per_family_env = env(f"WEBHOOK_HEALTH_MAX_AGE_{name.upper()}", "")
        if args.max_age_hours is not None:
            threshold = args.max_age_hours
        elif per_family_env:
            threshold = float(per_family_env)
        elif legacy_global:
            threshold = float(legacy_global)
        else:
            threshold = float(cfg["max_age_hours"])

        last_seen = query_last_seen(host, project, key, cfg["where"])
        if last_seen is None:
            failures.append(f"{cfg['label']} has never been seen")
            continue
        age_hours = (now - last_seen).total_seconds() / 3600
        print(f"{name}: last_seen={last_seen.isoformat()} age_hours={age_hours:.2f} threshold={threshold:.1f}h")
        if age_hours > threshold:
            failures.append(
                f"{cfg['label']} silent for {age_hours:.1f}h (threshold {threshold:.0f}h) - last event {last_seen.isoformat()}"
            )

    for failure in failures:
        slack(slack_url, f":warning: {failure}. {args.runbook_url}", args.dry_run)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
