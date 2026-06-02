#!/usr/bin/env python3
"""Upsert the CSP violation PostHog insight AND wire its Slack alert.

PRD P1-8 (audit 2026-06-02) — the previous version of this script
upserted the insight then printed "PostHog UI step: attach Slack
notification". Nobody walked that manual step, so 9 CSP violations
landed in production over 14 days without paging oncall. This revision
calls the PostHog Alerts API directly so the Slack integration is
attached without manual intervention.

Env vars:
  POSTHOG_HOST                 — defaults to https://eu.posthog.com
  POSTHOG_PROJECT_ID           — required
  POSTHOG_PERSONAL_API_KEY     — required
  POSTHOG_SLACK_INTEGRATION_ID — required for `--with-alert`; UUID of
                                  the existing PostHog Slack integration.
                                  Get this from PostHog → Project →
                                  Apps → Slack → Integration ID.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request


INSIGHT_NAME = "Alert - CSP violations > 0 (auto)"
DESCRIPTION = "Count of csp.violation in the last hour. Configure Slack notification when count > 0."


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def request(method: str, url: str, key: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc


def find_insight(host: str, project: str, key: str, name: str) -> dict | None:
    url = f"{host.rstrip('/')}/api/projects/{project}/insights/?search={urllib.parse.quote(name)}"
    data = request("GET", url, key)
    for item in data.get("results", []):
        if item.get("name") == name:
            return item
    return None


def payload() -> dict:
    return {
        "name": INSIGHT_NAME,
        "description": DESCRIPTION,
        "query": {
            "kind": "DataTableNode",
            "source": {
                "kind": "HogQLQuery",
                "query": """
                    SELECT count() AS violations
                    FROM events
                    WHERE event = 'csp.violation'
                      AND timestamp >= now() - INTERVAL 1 HOUR
                """,
            },
            "full": True,
        },
    }


ALERT_NAME = "Alert - CSP violations > 0 (auto)"
ALERT_THRESHOLD = 1  # any violation pages oncall


def find_alert(host: str, project: str, key: str, insight_id: str) -> dict | None:
    """Return the alert config attached to an insight, or None.

    PostHog Alerts API: `GET /api/projects/{id}/alerts/?insight={id}`.
    """
    url = (
        f"{host.rstrip('/')}/api/projects/{project}/alerts/"
        f"?insight_id={urllib.parse.quote(str(insight_id))}"
    )
    try:
        data = request("GET", url, key)
    except RuntimeError as exc:
        # If the alerts endpoint isn't enabled on this PostHog plan,
        # surface the situation rather than swallowing it silently.
        print(f"[csp-alert] alerts API check failed: {exc}")
        return None
    for item in data.get("results", []):
        if item.get("name") == ALERT_NAME:
            return item
    return None


def alert_payload(insight_id: str, slack_integration_id: str) -> dict:
    """Body shape for POST/PATCH `/api/projects/{id}/alerts/`."""
    return {
        "name": ALERT_NAME,
        "insight": insight_id,
        "enabled": True,
        # The "absolute" condition fires when the configured aggregation
        # over the insight exceeds `value`. For our single-cell HogQL
        # count this is the simplest mapping.
        "condition": {
            "type": "absolute_value",
            "operator": "greater_than",
            "value": ALERT_THRESHOLD,
        },
        "config": {
            "type": "TrendsAlertConfig",
            "series_index": 0,
        },
        "notification_targets": {
            "slack": [
                {"integration_id": slack_integration_id},
            ],
        },
        "subscribed_users": [],
    }


def upsert_alert(host: str, project: str, key: str,
                 insight_id: str, slack_integration_id: str) -> dict:
    """Create or patch the Slack-routed alert tied to `insight_id`."""
    body = alert_payload(insight_id, slack_integration_id)
    existing = find_alert(host, project, key, insight_id)
    if existing:
        return request(
            "PATCH",
            f"{host.rstrip('/')}/api/projects/{project}/alerts/{existing['id']}/",
            key,
            body,
        )
    return request(
        "POST",
        f"{host.rstrip('/')}/api/projects/{project}/alerts/",
        key,
        body,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Upsert PostHog CSP violation alert insight.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--with-alert",
        action="store_true",
        default=True,
        help=(
            "Also create/patch the Slack-routed alert. Requires "
            "POSTHOG_SLACK_INTEGRATION_ID. Default: true (PRD P1-8 "
            "fix — no more manual UI step)."
        ),
    )
    parser.add_argument(
        "--insight-only",
        action="store_true",
        help="Skip the alert wiring even if --with-alert was passed.",
    )
    args = parser.parse_args()

    host = env("POSTHOG_HOST", "https://eu.posthog.com")
    project = env("POSTHOG_PROJECT_ID")
    key = env("POSTHOG_PERSONAL_API_KEY")
    slack_integration_id = env("POSTHOG_SLACK_INTEGRATION_ID")

    body = payload()
    if args.dry_run:
        print(json.dumps(body, indent=2))
        if not args.insight_only:
            if not slack_integration_id:
                print("[dry-run] POSTHOG_SLACK_INTEGRATION_ID unset — alert payload skipped.")
            else:
                print(json.dumps(alert_payload("INSIGHT_ID", slack_integration_id), indent=2))
        return 0

    if not project or not key:
        raise SystemExit("POSTHOG_PROJECT_ID and POSTHOG_PERSONAL_API_KEY are required")

    existing = find_insight(host, project, key, INSIGHT_NAME)
    if existing:
        result = request(
            "PATCH",
            f"{host.rstrip('/')}/api/projects/{project}/insights/{existing['id']}/",
            key,
            body,
        )
    else:
        result = request("POST", f"{host.rstrip('/')}/api/projects/{project}/insights/", key, body)
    print(f"Upserted {INSIGHT_NAME}: {result.get('short_id') or result.get('id')}")

    if args.insight_only or not args.with_alert:
        print("Skipping alert wiring (--insight-only).")
        return 0

    if not slack_integration_id:
        # Hard-fail so this never silently regresses into the
        # pre-2026-06-02 "manual UI step" trap. PRD P1-8.
        print(
            "POSTHOG_SLACK_INTEGRATION_ID is required for alert wiring. "
            "Find it in PostHog → Project → Apps → Slack. "
            "Set it as a GitHub/Vercel env var and re-run.",
        )
        return 2

    insight_id = result.get("id") or (existing and existing.get("id"))
    if not insight_id:
        print("Could not resolve insight_id; cannot upsert alert.")
        return 2

    alert = upsert_alert(host, project, key, str(insight_id), slack_integration_id)
    print(f"Upserted Slack alert: {alert.get('id') or alert.get('short_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
