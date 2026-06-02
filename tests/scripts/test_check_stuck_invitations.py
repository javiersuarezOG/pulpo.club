"""Tests for scripts/check_stuck_invitations.py — specifically the
auth-failure fallback added after the workflow had been red every 6h
since 2026-05-27 because Clerk's /v1/invitations endpoint returns 403
for the current GH-Actions CLERK_SECRET_KEY.

The contract: when Clerk responds 401/403 to the invitations listing,
the script (a) fires `invitation.stuck_check_unavailable` so PostHog
dashboards see the gap, (b) prints a clear operator diagnostic, and
(c) exits 0 so the workflow stays green for the upstream heartbeat
step (check_webhook_health.py).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_stuck_invitations as stuck  # noqa: E402


def _required_env() -> dict[str, str]:
    return {
        "CLERK_SECRET_KEY": "sk_test_dummy",
        "POSTHOG_PROJECT_ID": "1",
        "POSTHOG_PERSONAL_API_KEY": "phc_dummy",
    }


def test_clerk_403_exits_zero_and_captures_telemetry(capsys, monkeypatch, tmp_path):
    """The workflow had been silent for 6 days because every cron tick
    crashed on the Clerk 403. Confirm the fix exits 0 instead, emits the
    observability event, fires a Slack alert (PRD P0-1: a downgrade-into-
    silence is itself the incident class) and drops a `clerk.json`
    sidecar with status=unavailable so the heartbeat step can compose it.
    """
    for k, v in _required_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.setenv("MONITOR_STATUS_DIR", str(tmp_path))

    monkeypatch.setattr(sys, "argv", ["check_stuck_invitations.py"])

    err = stuck.HTTPCallError(
        method="GET",
        url="https://api.clerk.com/v1/invitations?status=pending&limit=100",
        status=403,
        detail='{"errors":[{"code":"authentication_invalid"}]}',
    )

    captured: list[tuple[str, dict]] = []
    slack_messages: list[tuple[str, str, bool]] = []

    def fake_capture(event: str, properties: dict) -> None:
        captured.append((event, properties))

    def fake_slack(webhook_url: str, text: str, dry_run: bool) -> None:
        slack_messages.append((webhook_url, text, dry_run))

    with patch.object(stuck, "list_pending_invitations", side_effect=err), \
         patch.object(stuck, "capture_posthog", side_effect=fake_capture), \
         patch.object(stuck, "slack", side_effect=fake_slack):
        rc = stuck.main()

    assert rc == 0, "Workflow must stay green so the heartbeat step's signal isn't eclipsed"
    assert captured, "PostHog event must fire so dashboards see the silent gap"
    event_name, props = captured[0]
    assert event_name == "invitation.stuck_check_unavailable"
    assert props["reason"] == "clerk_403"
    assert props["endpoint"] == "/v1/invitations"
    # Detail capped at 500 chars to keep PostHog payloads small.
    assert len(props["detail"]) <= 500
    err_output = capsys.readouterr().err
    assert "Clerk" in err_output and "403" in err_output
    assert "Runbook" in err_output

    # PRD P0-1 acceptance: forced Clerk failure posts to Slack with runbook URL.
    assert slack_messages, "Slack must fire on Clerk auth failure — PRD P0-1"
    _, slack_text, _ = slack_messages[0]
    assert "Clerk stuck-invitation monitor unavailable" in slack_text
    assert "403" in slack_text
    assert "workflows/pulpo-webhook-health" in slack_text  # runbook URL

    # Sidecar feeds the heartbeat composer.
    import json
    sidecar = tmp_path / "clerk.json"
    assert sidecar.exists(), "clerk.json sidecar must exist for the heartbeat step"
    payload = json.loads(sidecar.read_text())
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "clerk_403"


def test_clerk_401_exits_zero_and_captures_telemetry(monkeypatch):
    """401 (token entirely invalid) is the same operator action: re-scope
    the secret. Fall through the same path."""
    for k, v in _required_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sys, "argv", ["check_stuck_invitations.py"])

    err = stuck.HTTPCallError(
        method="GET",
        url="https://api.clerk.com/v1/invitations?status=pending&limit=100",
        status=401,
        detail="unauthorized",
    )

    captured: list[tuple[str, dict]] = []
    with patch.object(stuck, "list_pending_invitations", side_effect=err), \
         patch.object(stuck, "capture_posthog", side_effect=lambda e, p: captured.append((e, p))):
        rc = stuck.main()

    assert rc == 0
    assert captured[0][1]["reason"] == "clerk_401"


def test_clerk_500_still_raises(monkeypatch):
    """Non-auth Clerk errors (5xx, transient) should still raise so we
    don't silently swallow real Clerk outages."""
    for k, v in _required_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sys, "argv", ["check_stuck_invitations.py"])

    err = stuck.HTTPCallError(
        method="GET",
        url="https://api.clerk.com/v1/invitations",
        status=500,
        detail="upstream error",
    )

    with patch.object(stuck, "list_pending_invitations", side_effect=err):
        try:
            stuck.main()
        except stuck.HTTPCallError as raised:
            assert raised.status == 500
        else:
            raise AssertionError("5xx must propagate, not swallow")


def test_http_call_error_carries_status():
    """The new typed exception preserves the status code so callers can
    branch without parsing the message string."""
    err = stuck.HTTPCallError("GET", "https://example.com", 403, "forbidden")
    assert err.status == 403
    assert err.method == "GET"
    assert err.detail == "forbidden"
    # Still string-serializable for backward-compat with code that just
    # prints the exception.
    assert "403" in str(err)
