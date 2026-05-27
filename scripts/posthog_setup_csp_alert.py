#!/usr/bin/env python3
"""Create the CSP violation PostHog insight used by alerting."""

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Upsert PostHog CSP violation alert insight.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    host = env("POSTHOG_HOST", "https://eu.posthog.com")
    project = env("POSTHOG_PROJECT_ID")
    key = env("POSTHOG_PERSONAL_API_KEY")

    body = payload()
    if args.dry_run:
        print(json.dumps(body, indent=2))
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
    print("PostHog UI step: attach a Slack notification when the value is > 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
