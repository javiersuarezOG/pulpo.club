#!/usr/bin/env python3
"""Create Pulpo ops dashboards for activation, webhooks, CSP, and subscriptions."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict


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
        with urllib.request.urlopen(req, timeout=25) as r:
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


def find_dashboard(host: str, project: str, key: str, name: str) -> dict | None:
    url = f"{host.rstrip('/')}/api/projects/{project}/dashboards/?search={urllib.parse.quote(name)}"
    data = request("GET", url, key)
    for item in data.get("results", []):
        if item.get("name") == name:
            return item
    return None


def insight_payload(name: str, description: str, hogql: str) -> dict:
    return {
        "name": name,
        "description": description,
        "query": {
            "kind": "DataTableNode",
            "source": {"kind": "HogQLQuery", "query": hogql},
            "full": True,
        },
    }


def upsert_insight(host: str, project: str, key: str, payload: dict) -> dict:
    existing = find_insight(host, project, key, payload["name"])
    if existing:
        return request(
            "PATCH",
            f"{host.rstrip('/')}/api/projects/{project}/insights/{existing['id']}/",
            key,
            payload,
        )
    return request("POST", f"{host.rstrip('/')}/api/projects/{project}/insights/", key, payload)


def upsert_dashboard(host: str, project: str, key: str, name: str, description: str, insight_ids: list[int]) -> dict:
    existing = find_dashboard(host, project, key, name)
    payload = {"name": name, "description": description}
    if existing:
        dash = request(
            "PATCH",
            f"{host.rstrip('/')}/api/projects/{project}/dashboards/{existing['id']}/",
            key,
            payload,
        )
    else:
        dash = request("POST", f"{host.rstrip('/')}/api/projects/{project}/dashboards/", key, payload)
    dash_id = dash.get("id") or (existing and existing.get("id"))
    if not dash_id:
        return dash
    for insight_id in insight_ids:
        insight = request("GET", f"{host.rstrip('/')}/api/projects/{project}/insights/{insight_id}/", key)
        dashboards = insight.get("dashboards") or []
        if dash_id not in dashboards:
            request(
                "PATCH",
                f"{host.rstrip('/')}/api/projects/{project}/insights/{insight_id}/",
                key,
                {"dashboards": [*dashboards, dash_id]},
            )
    return dash


INSIGHTS = [
    (
        "Pulpo Ops - Activation funnel",
        "Ops - Activation funnel drop-off (auto)",
        "Drop-off across start, checkout, webhook, email delivery, ticket consumption, and signup.",
        """
        SELECT event, count() AS events
        FROM events
        WHERE event IN (
          'start.viewed',
          'start.checkout_redirected',
          'webhook.checkout_completed',
          'newsletter.delivered',
          'invitation.ticket_consumed',
          'signup.completed'
        )
        GROUP BY event
        ORDER BY events DESC
        """,
    ),
    (
        "Pulpo Ops - Subscription lifecycle",
        "Ops - Subscription status over time (auto)",
        "Subscription status and account subscription rendering signals.",
        """
        SELECT event, properties.status AS status, count() AS events
        FROM events
        WHERE event IN (
          'webhook.subscription_changed',
          'account.sub_block_rendered',
          'account.sub_resubscribe_clicked'
        )
        GROUP BY event, status
        ORDER BY events DESC
        """,
    ),
    (
        "Pulpo Ops - Webhook health overview",
        "Ops - Webhook last seen (auto)",
        "Last-seen timestamps for Resend, Clerk, and Stripe webhook families.",
        """
        SELECT
          multiIf(
            startsWith(event, 'newsletter.'), 'resend',
            startsWith(event, 'clerk.'), 'clerk',
            event = 'webhook.received' AND properties.provider = 'stripe', 'stripe',
            'other'
          ) AS family,
          max(timestamp) AS last_seen
        FROM events
        WHERE startsWith(event, 'newsletter.')
           OR startsWith(event, 'clerk.')
           OR (event = 'webhook.received' AND properties.provider = 'stripe')
        GROUP BY family
        ORDER BY family ASC
        """,
    ),
    (
        "Pulpo Ops - Stuck invitations",
        "Ops - Stuck invitation alerts (auto)",
        "Historical stuck-invitation alert payloads emitted by scripts/check_stuck_invitations.py.",
        """
        SELECT toStartOfHour(timestamp) AS hour,
               max(JSONExtractFloat(properties, 'pending_count')) AS pending_count,
               max(JSONExtractFloat(properties, 'age_hours')) AS max_age_hours
        FROM events
        WHERE event = 'invitation.stuck_alert'
        GROUP BY hour
        ORDER BY hour DESC
        LIMIT 168
        """,
    ),
    (
        "Pulpo Ops - CSP violations",
        "Ops - CSP violations recent samples (auto)",
        "Recent CSP violation samples from /api/csp-report.",
        """
        SELECT timestamp,
               properties.violated_directive AS directive,
               properties.blocked_uri AS blocked_uri,
               properties.document_uri AS document_uri
        FROM events
        WHERE event = 'csp.violation'
        ORDER BY timestamp DESC
        LIMIT 50
        """,
    ),
]


DASHBOARD_DESCRIPTIONS = {
    "Pulpo Ops - Activation funnel": "Checkout and activation drop-off signals.",
    "Pulpo Ops - Subscription lifecycle": "Subscription status, rendering, and reactivation signals.",
    "Pulpo Ops - Webhook health overview": "External webhook heartbeat last-seen board.",
    "Pulpo Ops - Stuck invitations": "Pending activation invitation alert history.",
    "Pulpo Ops - CSP violations": "CSP violation count and samples. Pair with PostHog Slack notification.",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Upsert Pulpo ops dashboards in PostHog.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    host = env("POSTHOG_HOST", "https://eu.posthog.com")
    project = env("POSTHOG_PROJECT_ID")
    key = env("POSTHOG_PERSONAL_API_KEY")
    if not args.dry_run and (not project or not key):
        raise SystemExit("POSTHOG_PROJECT_ID and POSTHOG_PERSONAL_API_KEY are required")

    grouped: dict[str, list[int]] = defaultdict(list)
    for dashboard_name, insight_name, description, hogql in INSIGHTS:
        payload = insight_payload(insight_name, description, hogql)
        if args.dry_run:
            print(f"\n# {dashboard_name} / {insight_name}\n{json.dumps(payload, indent=2)}")
            continue
        result = upsert_insight(host, project, key, payload)
        grouped[dashboard_name].append(result["id"])
        print(f"upserted insight: {insight_name}")

    if args.dry_run:
        return 0

    for dashboard_name, ids in grouped.items():
        dash = upsert_dashboard(
            host,
            project,
            key,
            dashboard_name,
            DASHBOARD_DESCRIPTIONS.get(dashboard_name, "Pulpo ops dashboard."),
            ids,
        )
        print(f"upserted dashboard: {dashboard_name} ({dash.get('id')})")
    print("PostHog UI step: add Slack notifications for profile_save_no_consumer and invitation_metadata_missing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
