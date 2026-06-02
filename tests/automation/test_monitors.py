"""Tests for the shared monitor helpers at automation/monitors/__init__.py.

The shared module backs both the legacy GitHub-Actions scripts and the
new Vercel-cron handler at api/internal/webhook-health.py, so the
helpers must behave the same in both planes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from automation.monitors import (  # noqa: E402
    HTTPCallError,
    capture_posthog,
    env,
    post_slack,
)


def test_env_strips_and_returns_default(monkeypatch):
    monkeypatch.setenv("X", "  hello  ")
    assert env("X") == "hello"
    monkeypatch.setenv("X", "   ")
    assert env("X", "fallback") == "fallback"


def test_http_call_error_carries_status_and_detail():
    err = HTTPCallError("GET", "https://example.com", 403, "forbidden")
    assert err.status == 403
    assert err.method == "GET"
    assert err.detail == "forbidden"
    assert "403" in str(err)


def test_post_slack_dry_run_prints(capsys, monkeypatch):
    """`webhook_url=""` (dry-run mode) falls through to stdout so the
    monitor still surfaces the message in local debug runs."""
    post_slack("", "test line", dry_run=False)
    out = capsys.readouterr().out
    assert "test line" in out


def test_post_slack_swallows_outage(capsys, monkeypatch):
    """Slack outage must not raise — the monitor outcome is the
    load-bearing signal."""
    def fail(*_args, **_kwargs):
        raise HTTPCallError("POST", "https://hooks.slack.test", 500, "down")
    with patch("automation.monitors.post_json", side_effect=fail):
        post_slack("https://hooks.slack.test", "hi")
    out = capsys.readouterr().out
    assert "[slack] post failed" in out


def test_capture_posthog_silent_without_token(monkeypatch):
    """No `POSTHOG_PROJECT_TOKEN` → silent no-op (dry-run / local case)."""
    monkeypatch.delenv("POSTHOG_PROJECT_TOKEN", raising=False)
    captured = []
    def fake_post(*args, **kwargs):
        captured.append(args)
        return {}
    with patch("automation.monitors.post_json", side_effect=fake_post):
        capture_posthog("test.event", {"k": "v"})
    assert captured == [], "no token → no POST"


def test_capture_posthog_includes_captured_at(monkeypatch):
    """Every PostHog event carries a `captured_at` ISO timestamp so the
    composer can prove the event came from the function, not a replay."""
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
    seen: list = []
    def fake_post(url, headers, payload, parse_response=True, timeout=20.0):
        seen.append(payload)
        return {}
    with patch("automation.monitors.post_json", side_effect=fake_post):
        capture_posthog("monitor.demo", {"clerk_status": "ok"})
    assert seen, "POST should fire"
    body = seen[0]
    assert body["event"] == "monitor.demo"
    assert body["properties"]["clerk_status"] == "ok"
    assert "captured_at" in body["properties"]


def test_capture_posthog_swallows_outage(monkeypatch):
    """PostHog ingest outage must not raise."""
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
    def fail(*_args, **_kwargs):
        raise HTTPCallError("POST", "https://eu.i.posthog.com/capture/", 502, "down")
    with patch("automation.monitors.post_json", side_effect=fail):
        # Should not raise.
        capture_posthog("monitor.demo", {"ok": True})
