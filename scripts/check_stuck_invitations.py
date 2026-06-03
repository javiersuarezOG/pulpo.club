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

# Per-monitor status sidecar — written by each check_* script before exit and
# consumed by scripts/check_webhook_health.py's heartbeat to compose
# monitor.webhook_health_completed { clerk_status, resend_status, stripe_status }.
# Path is intentionally /tmp so it never touches the repo and survives only
# inside a single workflow run.
MONITOR_STATUS_DIR_DEFAULT = "/tmp/pulpo_monitor_status"


def _write_monitor_status(monitor: str, status: str, extra: dict | None = None) -> None:
    """Drop a `{monitor}.json` sidecar with `{status, ts, ...}` for the heartbeat.

    Never raises — the heartbeat treats a missing sidecar as `unknown`, so
    monitor-script failure modes are observable rather than silenced.
    """
    out_dir = env("MONITOR_STATUS_DIR", MONITOR_STATUS_DIR_DEFAULT)
    try:
        os.makedirs(out_dir, exist_ok=True)
        payload = {
            "monitor": monitor,
            "status": status,
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        if extra:
            payload.update(extra)
        with open(os.path.join(out_dir, f"{monitor}.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError:
        # Sidecar IO failure does not block the monitor itself.
        pass


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


class HTTPCallError(RuntimeError):
    """request_json failure carrying the HTTP status separately from the message."""

    def __init__(self, method: str, url: str, status: int, detail: str) -> None:
        super().__init__(f"{method} {url} failed: {status} {detail}")
        self.method = method
        self.url = url
        self.status = status
        self.detail = detail


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
        raise HTTPCallError(method, url, exc.code, detail) from exc


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

    # The Clerk REST API for `/v1/invitations` requires backend-secret scope
    # that the current GH-Actions secret doesn't carry — `/v1/users` works
    # (welcome_reconcile.py proves it), but listing invitations returns 403.
    # Until the key is re-scoped or the script switches to the users-based
    # detection path, we want this workflow to stay green so the upstream
    # heartbeat step (check_webhook_health.py) remains observable, AND we
    # want the silent gap itself to surface in PostHog so dashboards can
    # raise it. Hard-failing every 6h reverts both signals to noise.
    try:
        invitations = list_pending_invitations(clerk_secret)
    except HTTPCallError as exc:
        if exc.status in (401, 403):
            capture_posthog("invitation.stuck_check_unavailable", {
                "reason": f"clerk_{exc.status}",
                "endpoint": "/v1/invitations",
                "detail": exc.detail[:500],  # cap so PostHog payload stays small
                "runbook": args.runbook_url,
            })
            print(
                f"[stuck-invitations] Clerk /v1/invitations returned {exc.status}. "
                "CLERK_SECRET_KEY likely lacks invitation-list scope (other endpoints "
                "like /v1/users still work — see welcome_reconcile cron). "
                "Stuck-invitation alerting paused until the key is re-scoped. "
                f"Runbook: {args.runbook_url}",
                file=sys.stderr,
            )
            # Slack on monitor unavailability per PRD P0-1: a downgrade-into-silence
            # is itself the incident class we are guarding against. The heartbeat
            # in scripts/check_webhook_health.py also picks this up as
            # `clerk_status=unavailable`; the Slack message here lets oncall see
            # the cause immediately without opening PostHog.
            slack(
                slack_url,
                f":warning: Clerk stuck-invitation monitor unavailable "
                f"({exc.status} from /v1/invitations). "
                f"Stuck-invitation alerting paused until CLERK_SECRET_KEY is re-scoped "
                f"or the monitor moves off the GH runner. {args.runbook_url}",
                args.dry_run,
            )
            _write_monitor_status("clerk", "unavailable", {
                "reason": f"clerk_{exc.status}",
                "endpoint": "/v1/invitations",
            })
            # Exit 0 so the workflow stays green for the upstream heartbeat
            # step. The silent gap is observable via the PostHog event above.
            return 0
        raise

    _write_monitor_status("clerk", "ok", {
        "pending_invitations": len(invitations),
    })

    stuck: list[dict] = []
    for inv in invitations:
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
        _write_monitor_status("clerk", "degraded", {
            "stuck_count": len(stuck),
            "max_age_hours": max_age,
        })
        return 1

    print("No stuck invitations over threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
