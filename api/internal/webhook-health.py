"""GET /api/internal/webhook-health — Vercel Python serverless function.

Provider-API monitor that runs from the Vercel runtime instead of the
GitHub Actions runner. PRD P0-1 + P0-2: `api.clerk.com/v1/invitations`
and `api.resend.com/domains` both return Cloudflare 1010 ("Access
denied — browser signature") to the GH-Actions runner, so the legacy
GitHub-Actions cron crashes on every tick. The Vercel runtime is
allowed; routing the check through here restores positive observability.

Two upstream calls per invocation:

  1. Clerk `/v1/invitations?status=pending&limit=100` — counts pending
     activation invitations. Same `is signup completed?` PostHog join
     as the legacy `scripts/check_stuck_invitations.py`.
  2. Resend `/domains` — reads each domain's verification status and
     reports unverified DNS records / risky sender overrides.

Auth: shared secret via `Authorization: Bearer ${PULPO_CRON_SECRET}`.
Vercel cron triggers carry the project's `CRON_SECRET` in the
`Authorization` header automatically when the route is registered in
`vercel.json`'s `crons:` array; this function accepts either env name
for forward-compat.

Response shape:

  {
    "clerk":  { "status": "ok" | "unavailable" | "degraded",
                "pending_invitations": N, "stuck_count": M, ... },
    "resend": { "status": "ok" | "unavailable" | "degraded",
                "issues": [...] },
    "heartbeat_at": "<iso8601>",
    "runbook": "<url>"
  }

Status codes:
  • 200 — checks ran; payload reports per-monitor status.
  • 401 — missing/wrong Authorization.
  • 500 — function-level error (uncaught). Per-monitor upstream errors
          surface as `status="unavailable"` in the 200 body so the
          heartbeat still records a row.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler

# Vercel's Python runtime adds the deployment root to sys.path
# automatically — `from automation.monitors import ...` resolves through
# the import tracer. Module-level import: runs once per cold start.
from automation.monitors import (  # noqa: E402
    HTTPCallError,
    capture_posthog,
    env,
    post_slack,
    request_json,
)


RUNBOOK = (
    "https://github.com/javiersuarezOG/pulpo.club/actions/workflows/"
    "pulpo-webhook-health.yml"
)

# Per-monitor thresholds — match the legacy GH-Actions scripts so the
# move doesn't quietly relax alerting.
STUCK_INVITATION_HOURS_DEFAULT = 6.0


def _log(fields: dict) -> None:
    parts = ["[api]", "internal.webhook-health"]
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    print(" ".join(parts), flush=True)


def _parse_time(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
    raw = str(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _check_clerk() -> dict:
    """List pending Clerk invitations and report stuck ones."""
    clerk_secret = env("CLERK_SECRET_KEY")
    if not clerk_secret:
        return {"status": "unavailable", "reason": "missing_secret"}

    url = "https://api.clerk.com/v1/invitations?" + urllib.parse.urlencode({
        "status": "pending", "limit": "100",
    })
    try:
        data = request_json("GET", url, {"Authorization": f"Bearer {clerk_secret}"})
    except HTTPCallError as exc:
        return {
            "status": "unavailable",
            "reason": f"clerk_{exc.status}",
            "detail": exc.detail[:500],
        }
    invitations = data.get("data") if isinstance(data, dict) else data
    if not isinstance(invitations, list):
        invitations = []

    threshold_h = float(env("STUCK_INVITATION_HOURS",
                            str(STUCK_INVITATION_HOURS_DEFAULT)))
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=threshold_h)
    stuck = []
    for inv in invitations:
        if not isinstance(inv, dict):
            continue
        created = _parse_time(inv.get("created_at") or inv.get("createdAt"))
        if not created or created > cutoff:
            continue
        stuck.append({
            "id": inv.get("id") or "",
            "created_at": created.isoformat(),
        })

    status = "degraded" if stuck else "ok"
    return {
        "status": status,
        "pending_invitations": len(invitations),
        "stuck_count": len(stuck),
        "threshold_hours": threshold_h,
    }


def _domain_issues(domain: dict) -> list[str]:
    """Flatten Resend domain row into operator-readable issue strings."""
    name = (
        domain.get("name") or domain.get("domain") or domain.get("id")
        or "unknown-domain"
    )
    issues: list[str] = []
    status = str(domain.get("status") or "").lower()
    if status and status not in {"verified", "success"}:
        issues.append(f"{name}: domain status is {status}")
    records = domain.get("records") or domain.get("dns_records") or []
    for record in records:
        record_status = str(record.get("status") or "").lower()
        record_type = record.get("record") or record.get("type") or "record"
        if record_status and record_status not in {"verified", "success"}:
            issues.append(f"{name}: DNS {record_type} status is {record_status}")
    return issues


def _check_resend() -> dict:
    """Read Resend `/domains` + flag sender-config overrides."""
    api_key = env("RESEND_API_KEY")
    if not api_key:
        return {"status": "unavailable", "reason": "missing_secret"}

    try:
        data = request_json(
            "GET", "https://api.resend.com/domains",
            {"Authorization": f"Bearer {api_key}"},
        )
    except HTTPCallError as exc:
        return {
            "status": "unavailable",
            "reason": f"resend_{exc.status}",
            "detail": exc.detail[:500],
        }
    domains = data.get("data") if isinstance(data, dict) else data
    if not isinstance(domains, list):
        domains = []

    issues: list[str] = []
    for domain in domains:
        if isinstance(domain, dict):
            issues.extend(_domain_issues(domain))

    sender = env("PULPO_ACTIVATION_FROM_EMAIL")
    if sender and "noreply@" in sender.lower():
        issues.append(
            "PULPO_ACTIVATION_FROM_EMAIL uses noreply@; prefer hello@ for activation mail"
        )
    if env("RESEND_FROM_NOREPLY").lower() in {"1", "true", "yes"}:
        issues.append("RESEND_FROM_NOREPLY is enabled")

    return {
        "status": "degraded" if issues else "ok",
        "issue_count": len(issues),
        "issues": issues[:20],  # cap so the JSON response stays small
    }


class handler(BaseHTTPRequestHandler):
    """Vercel Python entry point."""

    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _authorized(self) -> bool:
        # PULPO_CRON_SECRET is set in the Vercel project env. Vercel's
        # built-in cron header (when wired via vercel.json `crons:`)
        # also uses `Authorization: Bearer <CRON_SECRET>`; accept the
        # `CRON_SECRET` env name as a forward-compat alias.
        expected = env("PULPO_CRON_SECRET") or env("CRON_SECRET")
        if not expected:
            return False
        provided = self.headers.get("Authorization", "")
        return provided == f"Bearer {expected}"

    def do_GET(self) -> None:
        t0 = time.monotonic()
        if not self._authorized():
            _log({"status": 401, "reason": "bad_token"})
            return self._send_json(401, {"error": "unauthorized"})

        slack_url = env("SLACK_WEBHOOK_URL")
        try:
            clerk = _check_clerk()
        except Exception:  # noqa: BLE001
            _log({"status": 200, "reason": "clerk_uncaught",
                  "trace": traceback.format_exc()[:500]})
            clerk = {"status": "unavailable", "reason": "uncaught_exception"}
        try:
            resend = _check_resend()
        except Exception:  # noqa: BLE001
            _log({"status": 200, "reason": "resend_uncaught",
                  "trace": traceback.format_exc()[:500]})
            resend = {"status": "unavailable", "reason": "uncaught_exception"}

        heartbeat_at = dt.datetime.now(dt.timezone.utc).isoformat()
        payload = {
            "clerk": clerk,
            "resend": resend,
            "heartbeat_at": heartbeat_at,
            "runbook": RUNBOOK,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }

        # PRD P0-1 / P0-2: every monitor outcome lands on Slack and
        # PostHog. The GH-Actions runner can poll the response code, but
        # the PostHog event + Slack post are the load-bearing alerts.
        capture_posthog("monitor.webhook_health_completed", {
            "clerk_status": clerk.get("status"),
            "clerk_stuck_count": clerk.get("stuck_count"),
            "resend_status": resend.get("status"),
            "resend_issue_count": resend.get("issue_count"),
            "runbook": RUNBOOK,
            "execution_plane": "vercel_cron",
        })

        # Slack on `unavailable` (monitor itself broke) — the loudest
        # signal class. `degraded` (stuck invitations / domain issues)
        # is also worth pinging but only once per state transition; the
        # PostHog properties carry the count for downstream dashboards.
        if clerk.get("status") == "unavailable":
            post_slack(
                slack_url,
                f":warning: Clerk monitor unavailable from Vercel cron "
                f"({clerk.get('reason')}). {RUNBOOK}",
            )
        if resend.get("status") == "unavailable":
            post_slack(
                slack_url,
                f":warning: Resend deliverability monitor unavailable from Vercel cron "
                f"({resend.get('reason')}). {RUNBOOK}",
            )
        if clerk.get("stuck_count"):
            post_slack(
                slack_url,
                f":warning: {clerk['stuck_count']} pending activation invitation(s) "
                f"older than {clerk.get('threshold_hours', '?')}h. {RUNBOOK}",
            )
        if resend.get("issues"):
            issues_block = "\n".join(f"- {i}" for i in resend["issues"])
            post_slack(
                slack_url,
                f":warning: Resend deliverability recommendations need attention:\n"
                f"{issues_block}",
            )

        _log({
            "status": 200,
            "ms": int((time.monotonic() - t0) * 1000),
            "clerk_status": clerk.get("status"),
            "resend_status": resend.get("status"),
        })
        return self._send_json(200, payload)

    # Vercel cron sends a GET; reject anything else loudly.
    def do_POST(self) -> None:
        return self._send_json(405, {"error": "method_not_allowed"})
