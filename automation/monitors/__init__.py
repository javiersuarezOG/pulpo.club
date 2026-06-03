"""Shared HTTP / Slack / PostHog helpers for monitor scripts.

Pre-2026-06-02 these helpers were duplicated across
`scripts/check_stuck_invitations.py`, `scripts/check_webhook_health.py`,
and `scripts/check_email_deliverability_recommendations.py`. Moving them
here lets both the legacy GitHub-Actions wrappers and the Vercel-cron
serverless function at `api/internal/webhook-health.py` share the same
behaviour — important because the audit (PRD P0-1 / P0-2) found that
the GH-Actions runner gets Cloudflare 1010-blocked from `api.clerk.com`
and `api.resend.com`. The Vercel runtime can hit those APIs, but only
if we route through the same Slack/PostHog primitives so the same
runbook works from either plane.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request


__all__ = [
    "HTTPCallError",
    "request_json",
    "post_json",
    "post_slack",
    "capture_posthog",
    "env",
    "POSTHOG_HOST_DEFAULT",
    "POSTHOG_INGEST_DEFAULT",
]


POSTHOG_HOST_DEFAULT = "https://eu.posthog.com"
POSTHOG_INGEST_DEFAULT = "https://eu.i.posthog.com"


class HTTPCallError(RuntimeError):
    """request_json failure carrying the HTTP status separately from the message.

    Callers branch on `.status` rather than parsing the exception string.
    Audit 2026-06-02 — the Clerk 403 path relies on this typed exception
    to distinguish "Cloudflare blocks the runner" from "Clerk is down".
    """

    def __init__(self, method: str, url: str, status: int, detail: str) -> None:
        super().__init__(f"{method} {url} failed: {status} {detail}")
        self.method = method
        self.url = url
        self.status = status
        self.detail = detail


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def request_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    payload: dict | None = None,
    timeout: float = 25.0,
) -> dict:
    """JSON-in/JSON-out HTTP call. Raises HTTPCallError on non-2xx.

    Mirrors the existing helper in `scripts/check_stuck_invitations.py`
    so the call sites read identically when the script is moved to the
    Vercel runtime.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            **(headers or {}),
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPCallError(method, url, exc.code, detail) from exc


def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict,
    parse_response: bool = True,
    timeout: float = 20.0,
) -> dict:
    """POST a JSON body, optionally parsing the response.

    `parse_response=False` is for endpoints (Slack, PostHog capture)
    that reply with literal text rather than JSON — without this guard
    a successful Slack post raises JSONDecodeError.
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            if not parse_response:
                return {}
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPCallError("POST", url, exc.code, detail) from exc


def post_slack(webhook_url: str, text: str, dry_run: bool = False) -> None:
    """Post a single line to the Slack incoming webhook.

    `dry_run=True` or `webhook_url=""` falls through to stdout so the
    CLI/local-debug case still surfaces the message. Telemetry-failure-
    is-not-handler-failure: a Slack outage must not break the monitor.
    """
    if dry_run or not webhook_url:
        print(text)
        return
    try:
        post_json(webhook_url, {}, {"text": text}, parse_response=False)
    except HTTPCallError as exc:
        # Slack outage is itself a signal, but the caller must keep
        # running so the heartbeat composer can still emit `slack_status`.
        print(f"[slack] post failed: {exc.status} {exc.detail[:200]}")


def capture_posthog(event: str, properties: dict, distinct_id: str = "server:monitor") -> None:
    """Emit a single PostHog event via the ingest API.

    Bails silently when `POSTHOG_PROJECT_TOKEN` is unset so dry-run/
    local invocations don't spam errors. Telemetry-failure is also
    swallowed because the monitor itself is the consumer this guards.
    """
    token = env("POSTHOG_PROJECT_TOKEN")
    if not token:
        return
    host = env("POSTHOG_INGEST_HOST", POSTHOG_INGEST_DEFAULT)
    try:
        post_json(
            f"{host.rstrip('/')}/capture/",
            {},
            {
                "api_key": token,
                "event": event,
                "distinct_id": distinct_id,
                "properties": {
                    **properties,
                    "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
            },
            parse_response=False,
        )
    except HTTPCallError:
        # See above — monitor outcome is the load-bearing signal.
        pass
