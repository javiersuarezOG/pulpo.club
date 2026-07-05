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
DEFAULT_INGEST_HOST = "https://eu.i.posthog.com"
DEFAULT_RUNBOOK = "https://github.com/javiersuarezOG/pulpo.club/actions/workflows/pulpo-webhook-health.yml"

# Sidecar dir read at heartbeat time — `scripts/check_stuck_invitations.py`
# and (Phase 1B) the Vercel-cron-backed monitors drop `{monitor}.json` files
# here with `{status, ts, ...}`. Missing files surface as `unknown` so a
# crashed monitor produces a `monitor.webhook_health_completed` row with
# `clerk_status="unknown"` rather than a green-by-omission heartbeat.
MONITOR_STATUS_DIR_DEFAULT = "/tmp/pulpo_monitor_status"

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
        # Audit 2026-06-02 (PRD P0-4): the old `startsWith(event,
        # 'newsletter.')` matched internal cron events
        # (newsletter.commentary_generated, newsletter.issue_built,
        # newsletter.welcome_reconcile_completed, newsletter.send_succeeded)
        # which kept the Resend heartbeat green even when the actual
        # /api/resend-webhook stopped firing. Pin the heartbeat to real
        # Resend lifecycle webhook events (and the dedicated
        # resend.webhook_received heartbeat emitted by the handler).
        "label": "Resend lifecycle webhook",
        "where": (
            "event = 'resend.webhook_received' "
            "OR event IN ("
            "'newsletter.sent','newsletter.delivered','newsletter.opened',"
            "'newsletter.clicked','newsletter.bounced','newsletter.complained',"
            "'newsletter.delivery_delayed'"
            ")"
        ),
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
    # Welcome reconcile cron — fires hourly per the workflow's
    # `15 * * * *` schedule. Each tick captures
    # `newsletter.welcome_reconcile_completed` exactly once. A gap >
    # 2h means GH Actions stopped honoring the cron OR the script
    # threw before the capture — both are operator-visible failures
    # that need investigation. 2h = 1 hourly tick + 1 cron grace.
    "welcome_reconcile": {
        "label": "Welcome reconcile cron (newsletter.welcome_reconcile_completed)",
        "where": "event = 'newsletter.welcome_reconcile_completed'",
        "max_age_hours": 2.0,
    },
    # Free-welcome reconcile cron — hourly at :25. Same 2h staleness rule
    # as the Pro reconcile above. A gap means the free-welcome backstop
    # stopped running (cron broken or the script threw pre-capture).
    "free_welcome_reconcile": {
        "label": "Free-welcome reconcile cron (newsletter.free_welcome_reconcile_completed)",
        "where": "event = 'newsletter.free_welcome_reconcile_completed'",
        "max_age_hours": 2.0,
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
    # ── Welcome dispatch failure rate ────────────────────────────────
    # Welcome dispatches that returned `status=failed` from the Python
    # dispatcher. Numerator is `newsletter.welcome_failed`; denominator
    # is `newsletter.welcome_sent` (successful dispatches).
    #
    # 24h window — welcomes fire on signups, so the volume scales with
    # daily new-Pro signups (currently ~1-10/day). min_denominator=5
    # avoids alarming when a single failure on a 2-recipient day
    # produces 50% failure rate.
    #
    # 10% threshold — failures should be rare; sustained > 10% over
    # a day points at a real upstream issue (Resend outage, Clerk
    # auth broken, ranked.json missing). Lower than the newsletter
    # bounce-rate threshold (2%) because welcome failures include
    # dispatcher errors, not just delivery — we want to know about
    # both. Tighten as volume grows.
    "welcome_failure_rate": {
        "label": "Welcome dispatch failure rate",
        "numerator_where": "event = 'newsletter.welcome_failed'",
        "denominator_where": "event = 'newsletter.welcome_sent'",
        "window_hours": 24.0,
        "threshold": 0.10,               # 10%
        "min_denominator": 5,
    },
    # ── Vercel Python fallback rate ──────────────────────────────────
    # When the Vercel Python instant path is unreachable (timeout,
    # 5xx, fetch fail), the webhook falls back to GH Actions
    # (`newsletter.welcome_internal_unreachable`). Healthy state: the
    # primary handles ~all welcomes, fallback is < 5%.
    #
    # 6h window for fast detection — a Vercel Python outage that
    # lasts hours means every welcome takes 30-75s instead of <5s.
    # Customer-visible degradation worth alerting on.
    #
    # 25% threshold — set high enough that occasional cold-start
    # timeouts don't cry wolf; low enough that a real Vercel
    # function outage fires. min_denominator=4 = need ~one welcome
    # every 90 min before the rate is meaningful.
    "welcome_internal_fallback_rate": {
        "label": "Welcome Vercel Python fallback rate (instant path unreachable)",
        "numerator_where": "event = 'newsletter.welcome_internal_unreachable'",
        "denominator_where": (
            "event IN ("
            "'newsletter.welcome_internal_responded', "
            "'newsletter.welcome_internal_unreachable'"
            ")"
        ),
        "window_hours": 6.0,
        "threshold": 0.25,               # 25%
        "min_denominator": 4,
    },
    # ── Unsubscribe rate (audience-fit signal) ───────────────────────
    # Healthy newsletter unsubscribe rate per send is 0.2-0.5%;
    # cumulative over 30 days settles around 1-2%. Sustained > 2%
    # over 30 days = audience-fit issue (wrong content, wrong
    # frequency, or audience drift). Alert on that signal.
    #
    # Numerator: `newsletter.unsubscribed` from api/unsubscribe.js
    # (one-click List-Unsubscribe + the manual /unsubscribe page).
    # Denominator: `newsletter.delivered` from the Resend webhook.
    # Both filter to email_type=newsletter so activation-email
    # unsubscribes (rare; activation has its own unsub flow) don't
    # mix into the rate.
    #
    # min_denominator=50 matches the bounce/complaint rate checks —
    # below that, the rate is too noisy to act on (one unsub on a
    # 30-recipient send = 3% but proves nothing).
    "newsletter_unsubscribe_rate": {
        "label": "Newsletter unsubscribe rate (audience-fit signal)",
        "numerator_where": (
            "event = 'newsletter.unsubscribed'"
        ),
        "denominator_where": (
            "event = 'newsletter.delivered' "
            "AND JSONExtractString(properties, 'email_type') = 'newsletter'"
        ),
        "window_hours": 720.0,           # 30 days
        "threshold": 0.02,               # 2%
        "min_denominator": 50,
    },
    # ── Weekly Pro digest send failure rate ──────────────────────────
    # Same shape as the welcome failure rate but for the weekly cron
    # (Sunday 10 AM SV). Numerator = `newsletter.send_failed`,
    # denominator = `newsletter.send_succeeded`, both filtered to
    # non-dry-run sends.
    #
    # 192h (8-day) window covers one full Sunday send cycle + 1 day
    # of grace. min_denominator=20 because the Pro audience is
    # typically > 50 recipients per send.
    #
    # 5% threshold — a Sunday send that fails for >5% of recipients
    # is a real reliability issue (likely a domain reputation hit or
    # ranked.json corruption, not a one-off bounce).
    "weekly_send_failure_rate": {
        "label": "Weekly Pro digest send failure rate (non-dry-run)",
        "numerator_where": (
            "event = 'newsletter.send_failed' "
            "AND JSONExtractBool(properties, 'dry_run') = false"
        ),
        "denominator_where": (
            "event = 'newsletter.send_succeeded' "
            "AND JSONExtractBool(properties, 'dry_run') = false"
        ),
        "window_hours": 192.0,
        "threshold": 0.05,               # 5%
        "min_denominator": 20,
    },
    # ── Resend lifecycle classification health ───────────────────────
    # Audit 2026-06-02 (PRD P0-3): live PostHog showed nearly every
    # newsletter.delivered row with email_type='unknown' because
    # api/contact.js sent untagged emails. With the PR-1A contact-form
    # fix in place, this rate should drop to near-zero. Alert when >5%
    # of lifecycle events arrive without a recognisable email_type —
    # that's the smoking gun for "a new sender shipped without tags".
    #
    # 24h window for fast feedback. min_denominator=10 to avoid
    # alarming on a single contact-form-burst weekend.
    "resend_unknown_email_type_rate": {
        "label": "Resend lifecycle events with email_type='unknown'",
        "numerator_where": (
            "event IN ("
            "'newsletter.sent','newsletter.delivered','newsletter.opened',"
            "'newsletter.clicked','newsletter.bounced','newsletter.complained',"
            "'newsletter.delivery_delayed'"
            ") AND JSONExtractString(properties, 'email_type') = 'unknown'"
        ),
        "denominator_where": (
            "event IN ("
            "'newsletter.sent','newsletter.delivered','newsletter.opened',"
            "'newsletter.clicked','newsletter.bounced','newsletter.complained',"
            "'newsletter.delivery_delayed'"
            ")"
        ),
        "window_hours": 24.0,
        "threshold": 0.05,               # 5%
        "min_denominator": 10,
    },
    # ── Pro welcome HARD-SKIP rate (the 2026-07-04 blind spot) ───────
    # The `welcome_failure_rate` check above watches `welcome_failed`,
    # but the 7-day Pro-welcome outage (0 sent / 540 skipped) manifested
    # as `welcome_skipped reason=clerk_lookup_failed` — the dispatcher
    # returned status="skipped", NOT "failed", so failure-rate stayed 0%
    # and every freshness check stayed green (the reconcile cron ran fine,
    # it just skipped everyone). This catches that class: a HARD skip is
    # one where the dispatcher WANTED to deliver but couldn't
    # (clerk_lookup_failed / ranked_missing / no_picks_available) — as
    # opposed to a benign skip (already_sent / not_pro), which is correct
    # behaviour. Denominator = genuine delivery attempts (sent + hard
    # skips), EXCLUDING benign skips so they can't dilute the ratio.
    #
    # During the outage this reads 100% (540/540). Healthy steady state
    # is ~0%. Covers welcome + welcome-back (both route through
    # dispatch_welcome → find_clerk_user_by_email). 24h window,
    # min_denominator=3 (welcomes are low-volume; a single hard skip on a
    # 2-attempt day shouldn't page).
    "welcome_hard_skip_rate": {
        "label": "Pro welcome hard-skip rate (dispatcher couldn't deliver — clerk_lookup_failed / ranked_missing / no_picks)",
        "numerator_where": (
            "event IN ('newsletter.welcome_skipped','newsletter.welcome_back_skipped') "
            "AND JSONExtractString(properties, 'reason') IN "
            "('clerk_lookup_failed','ranked_missing','no_picks_available')"
        ),
        "denominator_where": (
            "event IN ('newsletter.welcome_sent','newsletter.welcome_back_sent') "
            "OR (event IN ('newsletter.welcome_skipped','newsletter.welcome_back_skipped') "
            "AND JSONExtractString(properties, 'reason') IN "
            "('clerk_lookup_failed','ranked_missing','no_picks_available'))"
        ),
        "window_hours": 24.0,
        "threshold": 0.20,               # >20% of genuine attempts hard-failing = broken
        "min_denominator": 3,
    },
    # ── Free welcome HARD-SKIP rate ──────────────────────────────────
    # Same class for the DB-free free dispatcher. It has no Clerk lookup,
    # so `clerk_lookup_failed` can't occur — but `ranked_missing` /
    # `no_picks_available` (a data-pipeline break) would silently zero out
    # free welcomes exactly the same way. Same shape + thresholds.
    "free_welcome_hard_skip_rate": {
        "label": "Free welcome hard-skip rate (ranked_missing / no_picks)",
        "numerator_where": (
            "event IN ('newsletter.free_welcome_skipped','newsletter.free_welcome_back_skipped') "
            "AND JSONExtractString(properties, 'reason') IN "
            "('ranked_missing','no_picks_available')"
        ),
        "denominator_where": (
            "event IN ('newsletter.free_welcome_sent','newsletter.free_welcome_back_sent') "
            "OR (event IN ('newsletter.free_welcome_skipped','newsletter.free_welcome_back_skipped') "
            "AND JSONExtractString(properties, 'reason') IN "
            "('ranked_missing','no_picks_available'))"
        ),
        "window_hours": 24.0,
        "threshold": 0.20,
        "min_denominator": 3,
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


def read_monitor_status(monitor: str) -> dict | None:
    """Return the per-monitor sidecar dict, or None if absent/malformed.

    The heartbeat treats `None` as `unknown`. Never raises.
    """
    out_dir = env("MONITOR_STATUS_DIR", MONITOR_STATUS_DIR_DEFAULT)
    path = os.path.join(out_dir, f"{monitor}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def capture_posthog_event(event: str, properties: dict) -> None:
    """Emit a single PostHog event via the ingest API.

    Mirrors scripts/check_stuck_invitations.py's capture_posthog. Used for
    the monitor.webhook_health_completed heartbeat; bails silently when
    `POSTHOG_PROJECT_TOKEN` is unset (the dry-run/local-debug case).
    """
    token = env("POSTHOG_PROJECT_TOKEN")
    if not token:
        return
    host = env("POSTHOG_INGEST_HOST", DEFAULT_INGEST_HOST)
    try:
        post_json(
            f"{host.rstrip('/')}/capture/",
            {},
            {
                "api_key": token,
                "event": event,
                "distinct_id": "server:webhook_health",
                "properties": properties,
            },
            parse_response=False,
        )
    except RuntimeError:
        # Telemetry must not block the workflow — same posture as the
        # Slack helper above.
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Check webhook event heartbeats in PostHog.")
    parser.add_argument("--dry-run", action="store_true")
    # Optional global override. When set, applies to every family —
    # useful for the "force a test alert" path (`--max-age-hours 0`).
    # When unset, per-family thresholds from FAMILIES win.
    parser.add_argument("--max-age-hours", type=float, default=None,
                        help="Global override; if unset, per-family thresholds from FAMILIES apply.")
    parser.add_argument("--runbook-url", default=env("WEBHOOK_HEALTH_RUNBOOK_URL", DEFAULT_RUNBOOK))
    parser.add_argument("--test-slack", action="store_true",
                        help="Post ONE test ping to Slack and exit 0 — verifies the alert "
                             "channel is wired. Needs no PostHog creds. Use --dry-run to "
                             "print the message without posting.")
    args = parser.parse_args()

    # Legacy env var still respected for the workflow file's existing
    # test-fire pattern. Per-family env vars (WEBHOOK_HEALTH_MAX_AGE_RESEND
    # etc.) take precedence when defined.
    legacy_global = env("WEBHOOK_HEALTH_MAX_AGE_HOURS", "")

    host = env("POSTHOG_HOST", DEFAULT_HOST)
    project = env("POSTHOG_PROJECT_ID")
    key = env("POSTHOG_PERSONAL_API_KEY")
    slack_url = env("SLACK_WEBHOOK_URL")

    # Operator "is my alert channel wired?" path. Posts exactly one message
    # and exits 0 — deliberately BEFORE the PostHog-cred requirement, since a
    # Slack-wiring test needs no PostHog. slack() safely prints instead of
    # posting when --dry-run is set or SLACK_WEBHOOK_URL is unset.
    if args.test_slack:
        slack(
            slack_url,
            ":white_check_mark: *Pulpo webhook-health — Slack test ping.* "
            "Alert channel is live (manual test, not a real alert). "
            + args.runbook_url,
            args.dry_run,
        )
        print("test-slack: posted to Slack" if (slack_url and not args.dry_run)
              else "test-slack: printed only (no SLACK_WEBHOOK_URL or --dry-run)")
        return 0

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

    # PRD P0-1 — positive heartbeat. Composes per-monitor status from the
    # `/tmp/pulpo_monitor_status/` sidecars written by sibling scripts.
    # Missing sidecar → `unknown`, so a monitor that died before writing
    # its status still surfaces on dashboards.
    def _status_for(monitor: str) -> str:
        row = read_monitor_status(monitor)
        if row is None:
            return "unknown"
        return str(row.get("status") or "unknown")

    heartbeat_props = {
        "clerk_status": _status_for("clerk"),
        "resend_status": _status_for("resend"),
        "stripe_status": _status_for("stripe"),
        "failures_count": len(failures),
        "runbook": args.runbook_url,
    }
    print(f"heartbeat: {json.dumps(heartbeat_props)}")
    capture_posthog_event("monitor.webhook_health_completed", heartbeat_props)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
