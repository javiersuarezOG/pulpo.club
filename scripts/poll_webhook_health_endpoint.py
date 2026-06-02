#!/usr/bin/env python3
"""Thin GH-Actions wrapper around the Vercel-cron webhook-health endpoint.

PRD P0-1 + P0-2: provider-side checks now run on Vercel so they survive
Cloudflare 1010. This script just GETs the deployed endpoint, posts to
Slack on outage, and exits non-zero so the workflow badge surfaces
red. The Vercel function already posted its own Slack lines for
`status=unavailable`/`degraded`; this script's Slack post is the
backstop for "the Vercel cron itself never ran" (HTTPError) which the
function can't self-report.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_URL = "https://pulpo.club/api/internal/webhook-health"


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def post_slack(webhook_url: str, text: str) -> None:
    """Best-effort Slack post — never raises."""
    if not webhook_url:
        print(text)
        return
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                webhook_url,
                data=json.dumps({"text": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            timeout=15,
        )
    except urllib.error.URLError as exc:
        print(f"[slack] post failed: {exc}", file=sys.stderr)


def main() -> int:
    url = env("PULPO_HEALTH_URL", DEFAULT_URL)
    token = env("PULPO_CRON_SECRET")
    slack_url = env("SLACK_WEBHOOK_URL")
    if not token:
        print("[poll] PULPO_CRON_SECRET unset — cannot authenticate", file=sys.stderr)
        return 1

    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
            payload = json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"[poll] {url} returned {exc.code}: {detail[:300]}", file=sys.stderr)
        post_slack(
            slack_url,
            f":warning: Vercel webhook-health endpoint returned {exc.code}. {url}",
        )
        return 1
    except urllib.error.URLError as exc:
        print(f"[poll] {url} unreachable: {exc}", file=sys.stderr)
        post_slack(
            slack_url,
            f":warning: Vercel webhook-health endpoint unreachable ({exc}). {url}",
        )
        return 1

    clerk_status = (payload.get("clerk") or {}).get("status")
    resend_status = (payload.get("resend") or {}).get("status")
    print(json.dumps({
        "clerk": clerk_status,
        "resend": resend_status,
        "heartbeat_at": payload.get("heartbeat_at"),
        "elapsed_ms": payload.get("elapsed_ms"),
    }))

    # `unavailable` means the upstream provider blocked the call or the
    # Vercel function couldn't reach it. Both warrant a red badge so
    # oncall investigates. `degraded` (stuck invitations / domain
    # issues) keeps the workflow green — the Vercel function already
    # posted those lines to Slack.
    if clerk_status == "unavailable" or resend_status == "unavailable":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
