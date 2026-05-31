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


def test_rate_thresholds_match_industry_norms():
    """Bounce > 2%, complaint > 0.1% — the ESP-throttling / domain-
    blacklist thresholds. If these change, dashboards downstream
    expect to know. Lock the magnitude."""
    assert health.RATE_CHECKS["newsletter_bounce_rate"]["threshold"] == 0.02
    assert health.RATE_CHECKS["newsletter_complaint_rate"]["threshold"] == 0.001


def test_rate_checks_have_min_denominator_floor():
    """Without min_denominator, one bounce on 3 sends = 33% rate and
    a false alarm. Both checks need a floor."""
    assert health.RATE_CHECKS["newsletter_bounce_rate"]["min_denominator"] >= 10
    assert health.RATE_CHECKS["newsletter_complaint_rate"]["min_denominator"] >= 10


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
