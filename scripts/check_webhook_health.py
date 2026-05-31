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
    # Cadence drift specifically for the newsletter SEND pipeline.
    # The `resend` family above passes 12h easily even when the cron
    # has stopped, because Resend webhook events for activation emails
    # (account signup) also fire `newsletter.*` PostHog events. We
    # need a separate, narrower query that ONLY counts the send-side
    # captures from scripts/send_newsletter.py, filtered to real
    # (non-dry-run) sends. Weekly cadence + 1-day grace = 8 days.
    "newsletter_cron": {
        "label": "Newsletter send pipeline (newsletter.send_succeeded, non-dry-run)",
        "where": (
            "event = 'newsletter.send_succeeded' "
            "AND JSONExtractBool(properties, 'dry_run') = false"
        ),
        "max_age_hours": 192.0,
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


# Rolling-rate checks for sender-reputation guardrails. Each check
# computes `numerator / denominator` over a window and Slack-alerts
# when the rate exceeds `threshold`. The `min_denominator` floor
# prevents false alarms at low volume (one bounce on a 3-recipient
# send = 33% bounce rate, but that's a single bad email, not a
# reputation problem). Tighten min_denominator as the audience grows.
#
# Industry thresholds:
#   • Bounce rate > 2% → ESPs start throttling
#   • Complaint rate > 0.1% → ESPs blacklist domains
#
# Both numerator and denominator filter `email_type = 'newsletter'`
# so activation-email bounces don't pollute the newsletter rates
# (api/resend-webhook.js stamps `email_type` from the X-Pulpo-Email-Type
# header set in scripts/send_newsletter.py + api/_activation_email.js).
RATE_CHECKS = {
    "newsletter_bounce_rate": {
        "label": "Newsletter bounce rate",
        "numerator_where": (
            "event = 'newsletter.bounced' "
            "AND JSONExtractString(properties, 'email_type') = 'newsletter'"
        ),
        "denominator_where": (
            "event = 'newsletter.delivered' "
            "AND JSONExtractString(properties, 'email_type') = 'newsletter'"
        ),
        "window_hours": 720.0,           # 30 days
        "threshold": 0.02,               # 2%
        "min_denominator": 50,
    },
    "newsletter_complaint_rate": {
        "label": "Newsletter complaint rate",
        "numerator_where": (
            "event = 'newsletter.complained' "
            "AND JSONExtractString(properties, 'email_type') = 'newsletter'"
        ),
        "denominator_where": (
            "event = 'newsletter.delivered' "
            "AND JSONExtractString(properties, 'email_type') = 'newsletter'"
        ),
        "window_hours": 720.0,
        "threshold": 0.001,              # 0.1%
        "min_denominator": 50,
    },
}


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def post_json(url: str, headers: dict[str, str], payload: dict, parse_response: bool = True) -> dict:
    # Slack's incoming-webhooks endpoint replies with the literal string "ok"
    # on success, not JSON — so parse_response=False from the slack() caller
    # avoids JSONDecodeError after a successful post.
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
            if not parse_response:
                return {}
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed: {exc.code} {detail}") from exc


def query_count_window(host: str, project: str, key: str, where: str, window_hours: float) -> int:
    """Count events matching `where` within the last `window_hours`.

    Returns 0 for empty result sets and on any PostHog response error so a
    transient query failure never produces a misleading rate.
    """
    hogql = f"""
        SELECT count() AS n
        FROM events
        WHERE {where}
          AND timestamp > now() - toIntervalHour({int(window_hours)})
    """
    try:
        data = post_json(
            f"{host.rstrip('/')}/api/projects/{project}/query/",
            {"Authorization": f"Bearer {key}"},
            {"query": {"kind": "HogQLQuery", "query": hogql}},
        )
    except RuntimeError:
        return 0
    rows = data.get("results") or []
    if not rows or not rows[0] or rows[0][0] is None:
        return 0
    try:
        return int(rows[0][0])
    except (TypeError, ValueError):
        return 0


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
    post_json(webhook_url, {}, {"text": text}, parse_response=False)


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

    # Rolling-rate checks (bounce / complaint over 30d). Independent of
    # the heartbeat loop above — these fire whenever the rate exceeds
    # threshold AND the denominator is large enough to make the rate
    # meaningful. Low-volume sends (one bounce on three sends) intentionally
    # do not alert.
    for name, cfg in RATE_CHECKS.items():
        # Per-rate overrides — useful for the "force a test alert" path
        # (WEBHOOK_HEALTH_THRESHOLD_NEWSLETTER_BOUNCE_RATE=0).
        threshold_env = env(f"WEBHOOK_HEALTH_THRESHOLD_{name.upper()}", "")
        threshold = float(threshold_env) if threshold_env else float(cfg["threshold"])
        min_denom_env = env(f"WEBHOOK_HEALTH_MIN_DENOMINATOR_{name.upper()}", "")
        min_denom = int(min_denom_env) if min_denom_env else int(cfg["min_denominator"])

        denominator = query_count_window(
            host, project, key, cfg["denominator_where"], cfg["window_hours"]
        )
        numerator = query_count_window(
            host, project, key, cfg["numerator_where"], cfg["window_hours"]
        )
        rate = (numerator / denominator) if denominator > 0 else 0.0
        print(
            f"{name}: numerator={numerator} denominator={denominator} "
            f"rate={rate * 100:.3f}% threshold={threshold * 100:.3f}% "
            f"min_denominator={min_denom}"
        )
        if denominator < min_denom:
            # Not enough volume to make the rate meaningful — skip silently.
            # The next check in 6h will pick it up if the audience has grown.
            continue
        if rate > threshold:
            failures.append(
                f"{cfg['label']} = {rate * 100:.2f}% over last "
                f"{int(cfg['window_hours'] / 24)}d "
                f"({numerator} of {denominator}) — threshold {threshold * 100:.2f}%"
            )

    for failure in failures:
        slack(slack_url, f":warning: {failure}. {args.runbook_url}", args.dry_run)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
