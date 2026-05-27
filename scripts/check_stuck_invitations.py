#!/usr/bin/env python3
"""Alert when Clerk invitations stay pending after payment."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


POSTHOG_HOST_DEFAULT = "https://eu.posthog.com"
POSTHOG_INGEST_DEFAULT = "https://eu.i.posthog.com"
RUNBOOK_DEFAULT = "https://github.com/javiersuarezOG/pulpo.club/actions/workflows/pulpo-webhook-health.yml"


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def request_json(method: str, url: str, headers: dict[str, str] | None = None, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={**(headers or {}), **({"Content-Type": "application/json"} if payload is not None else {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]


def parse_time(value: str | int | float | None) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Clerk timestamps may be milliseconds.
        seconds = value / 1000 if value > 10_000_000_000 else value
        return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
    raw = str(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def list_pending_invitations(secret: str) -> list[dict]:
    url = "https://api.clerk.com/v1/invitations?" + urllib.parse.urlencode({
        "status": "pending",
        "limit": "100",
    })
    data = request_json("GET", url, {"Authorization": f"Bearer {secret}"})
    if isinstance(data, list):
        return data
    return data.get("data") or []


def has_signup_completed(host: str, project: str, key: str, distinct_id: str, since: dt.datetime) -> bool:
    hogql = """
        SELECT count()
        FROM events
        WHERE event = 'signup.completed'
          AND distinct_id = {distinct_id}
          AND timestamp >= {since}
    """
    payload = {
        "query": {
            "kind": "HogQLQuery",
            "query": hogql,
            "values": {
                "distinct_id": distinct_id,
                "since": since.isoformat(),
            },
        }
    }
    data = request_json(
        "POST",
        f"{host.rstrip('/')}/api/projects/{project}/query/",
        {"Authorization": f"Bearer {key}"},
        payload,
    )
    rows = data.get("results") or []
    return bool(rows and rows[0] and int(rows[0][0] or 0) > 0)


def capture_posthog(event: str, properties: dict) -> None:
    token = env("POSTHOG_PROJECT_TOKEN")
    if not token:
        return
    host = env("POSTHOG_INGEST_HOST", POSTHOG_INGEST_DEFAULT)
    request_json(
        "POST",
        f"{host.rstrip('/')}/capture/",
        {},
        {
            "api_key": token,
            "event": event,
            "distinct_id": "server:stuck-invitations",
            "properties": properties,
        },
    )


def slack(webhook_url: str, text: str, dry_run: bool) -> None:
    if dry_run or not webhook_url:
        print(text)
        return
    request_json("POST", webhook_url, {}, {"text": text})


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for paid activation invitations stuck pending.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--threshold-hours", type=float, default=float(env("STUCK_INVITATION_HOURS", "6")))
    parser.add_argument("--runbook-url", default=env("STUCK_INVITATION_RUNBOOK_URL", RUNBOOK_DEFAULT))
    args = parser.parse_args()

    clerk_secret = env("CLERK_SECRET_KEY")
    ph_host = env("POSTHOG_HOST", POSTHOG_HOST_DEFAULT)
    ph_project = env("POSTHOG_PROJECT_ID")
    ph_key = env("POSTHOG_PERSONAL_API_KEY")
    slack_url = env("SLACK_WEBHOOK_URL")
    if not clerk_secret or not ph_project or not ph_key:
        raise SystemExit("CLERK_SECRET_KEY, POSTHOG_PROJECT_ID, and POSTHOG_PERSONAL_API_KEY are required")

    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=args.threshold_hours)
    stuck: list[dict] = []
    for inv in list_pending_invitations(clerk_secret):
        email = inv.get("email_address") or inv.get("emailAddress") or ""
        created = parse_time(inv.get("created_at") or inv.get("createdAt"))
        if not email or not created or created > cutoff:
            continue
        distinct_id = f"email:{email_hash(email)}"
        if not has_signup_completed(ph_host, ph_project, ph_key, distinct_id, created):
            stuck.append({
                "id": inv.get("id") or "",
                "email_hash": email_hash(email),
                "age_hours": round((now - created).total_seconds() / 3600, 1),
                "created_at": created.isoformat(),
            })

    if stuck:
        max_age = max(item["age_hours"] for item in stuck)
        capture_posthog("invitation.stuck_alert", {
            "pending_count": len(stuck),
            "age_hours": max_age,
            "oldest_created_at": min(item["created_at"] for item in stuck),
        })
        sample = ", ".join(f"{item['email_hash']}:{item['age_hours']}h" for item in stuck[:5])
        slack(
            slack_url,
            f":warning: {len(stuck)} pending activation invitation(s) older than "
            f"{args.threshold_hours:.0f}h. Oldest {max_age:.1f}h. Sample {sample}. {args.runbook_url}",
            args.dry_run,
        )
        return 1

    print("No stuck invitations over threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
