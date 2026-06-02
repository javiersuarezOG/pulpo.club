"""Tests for scripts/posthog_setup_csp_alert.py.

PRD P1-8 — the previous script upserted the insight then printed
"PostHog UI step: attach Slack notification". The audit found that
manual step was never walked, so 9 CSP violations landed in production
over 14 days without paging. These tests lock down the contract that
the script now wires the Slack alert via the PostHog Alerts API.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import posthog_setup_csp_alert as csp  # noqa: E402


def _required_env(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "1")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phc_dummy")


def test_alert_payload_carries_slack_integration_id():
    body = csp.alert_payload("ins_42", "slack_int_abc")
    assert body["name"] == csp.ALERT_NAME
    assert body["insight"] == "ins_42"
    assert body["enabled"] is True
    assert body["condition"]["value"] == csp.ALERT_THRESHOLD
    targets = body["notification_targets"]["slack"]
    assert targets and targets[0]["integration_id"] == "slack_int_abc"


def test_main_creates_insight_and_alert(monkeypatch, capsys):
    """End-to-end: insight is upserted AND the alert is wired without
    a manual UI step. Asserts both HTTP calls fire with the right
    payloads."""
    _required_env(monkeypatch)
    monkeypatch.setenv("POSTHOG_SLACK_INTEGRATION_ID", "slack_int_abc")
    monkeypatch.setattr(sys, "argv", ["posthog_setup_csp_alert.py"])

    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method: str, url: str, key: str, payload=None):
        calls.append((method, url, payload))
        # Search returns no existing insight; POST returns new id.
        if method == "GET" and "insights/" in url:
            return {"results": []}
        if method == "POST" and "insights/" in url:
            return {"id": "ins_xyz", "short_id": "abc"}
        # No existing alert; POST returns new alert id.
        if method == "GET" and "alerts/" in url:
            return {"results": []}
        if method == "POST" and "alerts/" in url:
            return {"id": "alert_xyz"}
        return {}

    with patch.object(csp, "request", side_effect=fake_request):
        rc = csp.main()

    assert rc == 0
    methods_urls = [(m, u.rsplit("?", 1)[0]) for m, u, _ in calls]
    assert ("POST", "https://eu.posthog.com/api/projects/1/insights/") in methods_urls
    assert ("POST", "https://eu.posthog.com/api/projects/1/alerts/") in methods_urls

    # Find the alert POST payload and verify Slack integration is set.
    alert_payload = next(
        p for m, u, p in calls if m == "POST" and "alerts/" in u
    )
    assert alert_payload is not None
    assert (alert_payload["notification_targets"]["slack"][0]["integration_id"]
            == "slack_int_abc")
    assert alert_payload["insight"] == "ins_xyz"

    out = capsys.readouterr().out
    assert "Upserted Slack alert" in out


def test_main_hard_fails_without_slack_integration_id(monkeypatch, capsys):
    """The pre-fix script printed a 'PostHog UI step' instructional
    message and exited 0 — that's how the alert silently never got
    wired. The new script must fail loudly so the regression class
    is caught."""
    _required_env(monkeypatch)
    monkeypatch.delenv("POSTHOG_SLACK_INTEGRATION_ID", raising=False)
    monkeypatch.setattr(sys, "argv", ["posthog_setup_csp_alert.py"])

    def fake_request(method: str, url: str, key: str, payload=None):
        if method == "GET" and "insights/" in url:
            return {"results": []}
        if method == "POST" and "insights/" in url:
            return {"id": "ins_xyz", "short_id": "abc"}
        return {}

    with patch.object(csp, "request", side_effect=fake_request):
        rc = csp.main()

    assert rc == 2, "missing integration ID must hard-fail, not silently no-op"
    err_or_out = capsys.readouterr()
    assert "POSTHOG_SLACK_INTEGRATION_ID" in err_or_out.out


def test_insight_only_skips_alert(monkeypatch, capsys):
    """Operator escape hatch: --insight-only keeps the legacy behaviour
    for the rare case the alert is being managed elsewhere."""
    _required_env(monkeypatch)
    monkeypatch.delenv("POSTHOG_SLACK_INTEGRATION_ID", raising=False)
    monkeypatch.setattr(
        sys, "argv",
        ["posthog_setup_csp_alert.py", "--insight-only"],
    )
    calls: list = []

    def fake_request(method: str, url: str, key: str, payload=None):
        calls.append((method, url))
        if method == "GET" and "insights/" in url:
            return {"results": []}
        if method == "POST" and "insights/" in url:
            return {"id": "ins_xyz"}
        return {}

    with patch.object(csp, "request", side_effect=fake_request):
        rc = csp.main()

    assert rc == 0
    # No alerts/ call should fire.
    assert not any("alerts/" in u for _, u in calls)


def test_dry_run_prints_payloads(monkeypatch, capsys):
    """`--dry-run` is the diff-review path; must print both the insight
    payload AND (if integration id present) the alert payload."""
    _required_env(monkeypatch)
    monkeypatch.setenv("POSTHOG_SLACK_INTEGRATION_ID", "slack_int_abc")
    monkeypatch.setattr(sys, "argv", ["posthog_setup_csp_alert.py", "--dry-run"])

    rc = csp.main()
    assert rc == 0
    out = capsys.readouterr().out
    # First JSON dict = insight payload.
    assert "csp.violation" in out
    # Second JSON dict = alert payload with the integration id.
    assert "slack_int_abc" in out
