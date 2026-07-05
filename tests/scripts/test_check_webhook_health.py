"""Tests for scripts/check_webhook_health.py — the Tier-1 newsletter
observability surface.

Covers the additions made for newsletter ops:
  • `newsletter_cron` family (cadence-drift detector)
  • RATE_CHECKS (bounce / complaint rate alerts with min-denominator)
  • query_count_window helper

The heartbeat loop's existing behavior (silent → alert) is covered
implicitly via the family iteration; we don't re-test the loop wiring
since the original module shipped without unit tests and re-deriving
that coverage is out of scope.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_webhook_health as health  # noqa: E402


# ── FAMILIES + RATE_CHECKS registration ──────────────────────────────


def test_newsletter_cron_family_registered():
    """Cadence-drift detector for the send pipeline — separate from the
    `resend` heartbeat which conflates with activation-email webhook
    events. 8-day threshold = weekly cadence + 1-day grace."""
    assert "newsletter_cron" in health.FAMILIES
    cfg = health.FAMILIES["newsletter_cron"]
    assert "newsletter.send_succeeded" in cfg["where"]
    assert "dry_run" in cfg["where"]  # excludes test sends
    assert cfg["max_age_hours"] == 192.0


def test_rate_checks_registered():
    """Both reputation-guardrail rates need to be in the registry —
    bounce + complaint. Both filter on email_type=newsletter so
    activation-email bounces don't pollute the rate."""
    assert "newsletter_bounce_rate" in health.RATE_CHECKS
    assert "newsletter_complaint_rate" in health.RATE_CHECKS
    for name in ("newsletter_bounce_rate", "newsletter_complaint_rate"):
        cfg = health.RATE_CHECKS[name]
        assert "newsletter.delivered" in cfg["denominator_where"]
        assert "email_type" in cfg["denominator_where"]
        assert "email_type" in cfg["numerator_where"]


def test_welcome_hard_skip_checks_registered():
    """The 2026-07-04 blind spot: the Pro welcome broke for 7 days
    (0 sent / 540 skipped, reason=clerk_lookup_failed) and NO alert
    fired — every check was freshness-based and the reconcile cron ran
    fine, it just skipped everyone. These two checks close that gap by
    watching the SKIP reasons, not just `_failed`.

    Contract:
      • target the PATHOLOGICAL reasons (dispatcher wanted to deliver
        but couldn't) — clerk_lookup_failed / ranked_missing / no_picks;
      • must NOT include the BENIGN reasons (already_sent / not_pro),
        which are correct behaviour and would make the alert noisy;
      • denominator must EXCLUDE benign skips so they can't dilute the
        ratio to below threshold during a real outage.
    """
    for name in ("welcome_hard_skip_rate", "free_welcome_hard_skip_rate"):
        assert name in health.RATE_CHECKS, f"{name} missing from RATE_CHECKS"
        cfg = health.RATE_CHECKS[name]
        num = cfg["numerator_where"]
        den = cfg["denominator_where"]
        # Pathological reasons present.
        assert "ranked_missing" in num and "no_picks_available" in num
        # Benign reasons must never appear (either where clause).
        assert "already_sent" not in num and "already_sent" not in den
        assert "not_pro" not in num and "not_pro" not in den
        # Denominator counts real delivery attempts (sent side present).
        assert "_sent'" in den or "_sent" in den

    # The Pro check specifically watches the clerk_lookup_failed reason
    # (the exact 7-day-outage signal); the free dispatcher has no Clerk
    # lookup so its check must NOT.
    assert "clerk_lookup_failed" in health.RATE_CHECKS["welcome_hard_skip_rate"]["numerator_where"]
    assert "clerk_lookup_failed" not in health.RATE_CHECKS["free_welcome_hard_skip_rate"]["numerator_where"]


def test_rate_thresholds_match_industry_norms():
    """Bounce > 2%, complaint > 0.1% — the ESP-throttling / domain-
    blacklist thresholds. If these change, dashboards downstream
    expect to know. Lock the magnitude."""
    assert health.RATE_CHECKS["newsletter_bounce_rate"]["threshold"] == 0.02
    assert health.RATE_CHECKS["newsletter_complaint_rate"]["threshold"] == 0.001


# ── PRD P0-3 — resend_unknown_email_type_rate ───────────────────────


def test_resend_unknown_email_type_rate_registered():
    """The classifier-health rate must exist so the heartbeat catches
    the regression class where a new sender ships without tags. The
    audit found 100% of contact-form lifecycle events landing as
    `email_type='unknown'`."""
    assert "resend_unknown_email_type_rate" in health.RATE_CHECKS
    cfg = health.RATE_CHECKS["resend_unknown_email_type_rate"]
    assert "'unknown'" in cfg["numerator_where"]
    assert "email_type" in cfg["numerator_where"]
    # Denominator is the same set of lifecycle events — no email_type
    # filter so the rate measures classification health, not delivery.
    assert "newsletter.delivered" in cfg["denominator_where"]
    assert cfg["window_hours"] == 24.0
    assert cfg["threshold"] == 0.05
    assert cfg["min_denominator"] == 10


# ── PRD P0-4 — Resend heartbeat is lifecycle-only ───────────────────


def test_resend_family_does_not_match_internal_cron_events():
    """Pre-2026-06-02 the Resend heartbeat matched every event
    starting with `newsletter.`, including internal cron rows like
    newsletter.commentary_generated / .issue_built. Lock down the
    restricted where clause so the heartbeat detects the actual
    `/api/resend-webhook` going silent."""
    where = health.FAMILIES["resend"]["where"]
    assert "startsWith(event, 'newsletter.')" not in where
    # Must accept resend.webhook_received (the dedicated heartbeat).
    assert "'resend.webhook_received'" in where
    # Must enumerate the seven Resend lifecycle event names directly.
    for ev in (
        "'newsletter.sent'", "'newsletter.delivered'", "'newsletter.opened'",
        "'newsletter.clicked'", "'newsletter.bounced'",
        "'newsletter.complained'", "'newsletter.delivery_delayed'",
    ):
        assert ev in where
    # Must NOT accept the internal cron-progress events.
    assert "send_succeeded" not in where
    assert "commentary_generated" not in where
    assert "welcome_reconcile_completed" not in where


def test_rate_checks_have_min_denominator_floor():
    """Without min_denominator, one bounce on 3 sends = 33% rate and
    a false alarm. Both checks need a floor."""
    assert health.RATE_CHECKS["newsletter_bounce_rate"]["min_denominator"] >= 10
    assert health.RATE_CHECKS["newsletter_complaint_rate"]["min_denominator"] >= 10


# ── Welcome system observability (2026-06-01) ─────────────────────────


def test_welcome_reconcile_family_registered():
    """Hourly reconcile cron heartbeat — if no welcome_reconcile_completed
    in 2h, GH Actions stopped honoring the cron OR the script threw before
    capture. Either is operator-visible. 2h = 1 hourly tick + 1 grace."""
    assert "welcome_reconcile" in health.FAMILIES
    cfg = health.FAMILIES["welcome_reconcile"]
    assert "newsletter.welcome_reconcile_completed" in cfg["where"]
    assert cfg["max_age_hours"] == 2.0


def test_welcome_failure_rate_check_registered():
    """welcome_failed / welcome_sent — 10% threshold, 5-recipient floor.
    Failures should be rare; sustained > 10% points at an upstream issue
    (Resend outage, Clerk auth broken, ranked.json missing)."""
    assert "welcome_failure_rate" in health.RATE_CHECKS
    cfg = health.RATE_CHECKS["welcome_failure_rate"]
    assert "newsletter.welcome_failed" in cfg["numerator_where"]
    assert "newsletter.welcome_sent" in cfg["denominator_where"]
    assert cfg["threshold"] == 0.10
    assert cfg["min_denominator"] >= 5
    assert cfg["window_hours"] == 24.0


def test_welcome_internal_fallback_rate_check_registered():
    """Vercel Python instant-path unreachability — alerts when the
    primary path falls back to GH Actions > 25% over 6h. Customer-visible
    degradation: welcomes go from <5s to 30-75s."""
    assert "welcome_internal_fallback_rate" in health.RATE_CHECKS
    cfg = health.RATE_CHECKS["welcome_internal_fallback_rate"]
    assert "newsletter.welcome_internal_unreachable" in cfg["numerator_where"]
    # Denominator counts BOTH outcomes — reached + unreachable — so
    # the rate is "what fraction of attempts couldn't reach Vercel
    # Python." A numerator-only check would alarm whenever traffic
    # exists, even at a low fallback rate.
    assert "newsletter.welcome_internal_responded" in cfg["denominator_where"]
    assert "newsletter.welcome_internal_unreachable" in cfg["denominator_where"]
    assert cfg["threshold"] == 0.25
    assert cfg["window_hours"] == 6.0


def test_weekly_send_failure_rate_check_registered():
    """Weekly Pro digest send failures > 5% across a Sunday cycle is
    a real reliability issue. Filters non-dry-run so test sends don't
    pollute the numerator/denominator."""
    assert "weekly_send_failure_rate" in health.RATE_CHECKS
    cfg = health.RATE_CHECKS["weekly_send_failure_rate"]
    assert "newsletter.send_failed" in cfg["numerator_where"]
    assert "newsletter.send_succeeded" in cfg["denominator_where"]
    # CRITICAL: both must filter to non-dry-run so a smoke-test send
    # to one operator address doesn't dominate the rate. Without this
    # filter, dry-run failures would inflate the alarm.
    assert "dry_run" in cfg["numerator_where"]
    assert "dry_run" in cfg["denominator_where"]
    assert cfg["threshold"] == 0.05
    # min_denominator=20 means we need a real Sunday send completed
    # before the rate is meaningful — avoids false-alarming on a
    # 3-recipient operator test.
    assert cfg["min_denominator"] >= 20
    assert cfg["window_hours"] == 192.0  # 8 days = weekly cadence + grace


def test_welcome_rate_checks_share_window_consistency():
    """Welcome failure rate uses 24h, fallback rate uses 6h. Different
    windows are intentional (different failure-mode time constants),
    but both must be > 1h to avoid alarming on a single bad event."""
    assert health.RATE_CHECKS["welcome_failure_rate"]["window_hours"] >= 1.0
    assert health.RATE_CHECKS["welcome_internal_fallback_rate"]["window_hours"] >= 1.0


def test_unsubscribe_rate_check_registered():
    """Unsubscribe rate > 2% over 30 days = audience-fit signal.
    Per-event notification lives in scripts/notify_unsubscribes.py;
    this rate check is the slower backstop for sustained drift."""
    assert "newsletter_unsubscribe_rate" in health.RATE_CHECKS
    cfg = health.RATE_CHECKS["newsletter_unsubscribe_rate"]
    assert "newsletter.unsubscribed" in cfg["numerator_where"]
    # Denominator filters to email_type=newsletter so activation-email
    # unsubscribes (rare; they have their own unsub flow) don't
    # pollute the newsletter rate.
    assert "newsletter.delivered" in cfg["denominator_where"]
    assert "email_type" in cfg["denominator_where"]
    assert cfg["threshold"] == 0.02              # 2% — matches bounce rate threshold
    assert cfg["window_hours"] == 720.0          # 30 days
    # Same min_denominator floor as bounce/complaint — one unsub on
    # a 30-recipient send is 3% but proves nothing.
    assert cfg["min_denominator"] >= 50


# ── query_count_window ────────────────────────────────────────────────


def _ok_count_response(n):
    return {"results": [[n]] if n is not None else []}


def test_query_count_window_returns_int_on_success():
    with patch.object(health, "post_json", return_value=_ok_count_response(42)):
        assert health.query_count_window(
            "https://eu.posthog.com", "proj", "key", "event = 'x'", 720.0
        ) == 42


def test_query_count_window_returns_zero_on_empty_result():
    with patch.object(health, "post_json", return_value=_ok_count_response(None)):
        assert health.query_count_window(
            "https://eu.posthog.com", "proj", "key", "event = 'x'", 720.0
        ) == 0


def test_query_count_window_returns_zero_on_runtime_error():
    """A PostHog query failure must never produce a misleading rate.
    Better to under-report (rate=0) than to alert on a phantom rate."""
    with patch.object(health, "post_json", side_effect=RuntimeError("boom")):
        assert health.query_count_window(
            "https://eu.posthog.com", "proj", "key", "event = 'x'", 720.0
        ) == 0


def test_query_count_window_returns_zero_on_non_integer_value():
    """Schema drift safety: PostHog returning a string or null in [0]
    must degrade to 0, not crash the health check."""
    with patch.object(health, "post_json", return_value={"results": [["not-a-number"]]}):
        assert health.query_count_window(
            "https://eu.posthog.com", "proj", "key", "event = 'x'", 720.0
        ) == 0


def test_query_count_window_injects_window_filter():
    """The HogQL query must include the time-window filter — without
    it a 30-day rate becomes an all-time rate, which would mask
    recent regressions."""
    captured = {}
    def _capture_call(url, headers, payload, parse_response=True):
        captured["query"] = payload["query"]["query"]
        return _ok_count_response(1)
    with patch.object(health, "post_json", side_effect=_capture_call):
        health.query_count_window(
            "https://eu.posthog.com", "proj", "key", "event = 'x'", 720.0
        )
    assert "toIntervalHour(720)" in captured["query"]
    assert "now() -" in captured["query"]


# ── PRD P0-1 — monitor.webhook_health_completed heartbeat ───────────────
#
# The heartbeat composer reads per-monitor status sidecars from
# `MONITOR_STATUS_DIR` (written by check_stuck_invitations.py + the
# Phase-1B Vercel-cron-backed monitors). Missing sidecar must surface
# as status="unknown" so a crashed monitor is observable rather than
# silently green.


def test_read_monitor_status_returns_dict_when_sidecar_present(monkeypatch, tmp_path):
    (tmp_path / "clerk.json").write_text(json.dumps({
        "monitor": "clerk", "status": "ok", "ts": "2026-06-03T00:00:00+00:00",
        "pending_invitations": 0,
    }))
    monkeypatch.setenv("MONITOR_STATUS_DIR", str(tmp_path))
    row = health.read_monitor_status("clerk")
    assert row is not None
    assert row["status"] == "ok"
    assert row["pending_invitations"] == 0


def test_read_monitor_status_missing_sidecar_is_none(monkeypatch, tmp_path):
    """Absence of the sidecar surfaces as None so the heartbeat composer
    can translate it to status='unknown' — the explicit 'monitor never
    ran' signal we want on dashboards."""
    monkeypatch.setenv("MONITOR_STATUS_DIR", str(tmp_path))
    assert health.read_monitor_status("clerk") is None


def test_read_monitor_status_malformed_json_is_none(monkeypatch, tmp_path):
    """A broken JSON sidecar must not crash the composer (defensive)."""
    (tmp_path / "clerk.json").write_text("not json {")
    monkeypatch.setenv("MONITOR_STATUS_DIR", str(tmp_path))
    assert health.read_monitor_status("clerk") is None


def _stub_env(monkeypatch):
    for k, v in {
        "POSTHOG_PROJECT_ID": "1",
        "POSTHOG_PERSONAL_API_KEY": "phc_dummy",
    }.items():
        monkeypatch.setenv(k, v)


def test_main_emits_heartbeat_with_three_statuses(monkeypatch, tmp_path, capsys):
    """End-to-end heartbeat: composer fires `monitor.webhook_health_completed`
    with clerk/resend/stripe statuses derived from sidecars. PRD P0-1
    requires this event to be present regardless of whether families
    are alerting, so failures_count=0 must still emit a heartbeat."""
    (tmp_path / "clerk.json").write_text(json.dumps({"status": "ok"}))
    (tmp_path / "resend.json").write_text(json.dumps({"status": "ok"}))
    # No stripe sidecar → status='unknown'.

    _stub_env(monkeypatch)
    monkeypatch.setenv("MONITOR_STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_capture_dummy")
    monkeypatch.setattr(sys, "argv", ["check_webhook_health.py", "--dry-run"])

    import datetime as dt
    fresh = dt.datetime.now(dt.timezone.utc)
    captured: list[tuple[str, dict]] = []

    with patch.object(health, "query_last_seen", return_value=fresh), \
         patch.object(health, "query_count_window", return_value=0), \
         patch.object(health, "capture_posthog_event",
                      side_effect=lambda e, p: captured.append((e, p))):
        rc = health.main()

    assert rc == 0
    assert captured, "heartbeat must fire — PRD P0-1"
    event, props = captured[0]
    assert event == "monitor.webhook_health_completed"
    assert props["clerk_status"] == "ok"
    assert props["resend_status"] == "ok"
    assert props["stripe_status"] == "unknown"
    assert props["failures_count"] == 0
    assert "runbook" in props

    # Heartbeat dict is printed to stdout so the GH log has the composed
    # status without requiring PostHog access at debug time.
    out = capsys.readouterr().out
    assert "heartbeat:" in out


def test_heartbeat_carries_failures_count_when_family_silent(monkeypatch, tmp_path):
    """When `query_last_seen` returns None (family never seen), the
    heartbeat must surface failures_count >= 1 so the alert and the
    observability event are coupled."""
    (tmp_path / "clerk.json").write_text(json.dumps({"status": "ok"}))

    _stub_env(monkeypatch)
    monkeypatch.setenv("MONITOR_STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_capture_dummy")
    monkeypatch.setattr(sys, "argv", ["check_webhook_health.py", "--dry-run"])

    captured: list[tuple[str, dict]] = []
    with patch.object(health, "query_last_seen", return_value=None), \
         patch.object(health, "query_count_window", return_value=0), \
         patch.object(health, "capture_posthog_event",
                      side_effect=lambda e, p: captured.append((e, p))):
        rc = health.main()

    assert rc == 1
    _, props = captured[0]
    assert props["failures_count"] >= 1
