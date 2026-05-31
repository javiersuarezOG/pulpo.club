"""Tests for automation/newsletter/issue_state.py — the auto-increment
helper that reads max(issue_number) from PostHog telemetry.

The function MUST degrade to `default` on every error path so a
PostHog outage never blocks a real newsletter send.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from automation.newsletter import issue_state


# ── happy path ────────────────────────────────────────────────────────


def _ok_response(max_issue):
    """Build a fake urlopen response yielding PostHog's HogQL result shape."""
    class _Resp:
        def __init__(self, body):
            self._body = body.encode("utf-8")
        def read(self):
            return self._body
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
    body = json.dumps({"results": [[max_issue]] if max_issue is not None else []})
    return _Resp(body)


def test_returns_max_plus_one_when_posthog_responds(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "proj-test")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    with patch.object(issue_state.urllib.request, "urlopen", return_value=_ok_response(7)):
        assert issue_state.next_issue_number() == 8


def test_returns_default_when_no_events_ever(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "proj-test")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    with patch.object(issue_state.urllib.request, "urlopen", return_value=_ok_response(None)):
        assert issue_state.next_issue_number(default=1) == 1


def test_custom_default_used_when_no_events(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "proj-test")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    with patch.object(issue_state.urllib.request, "urlopen", return_value=_ok_response(None)):
        assert issue_state.next_issue_number(default=42) == 42


# ── fallback paths — must NEVER raise ──────────────────────────────────


def test_returns_default_when_project_id_missing(monkeypatch):
    monkeypatch.delenv("POSTHOG_PROJECT_ID", raising=False)
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    assert issue_state.next_issue_number(default=1) == 1


def test_returns_default_when_api_key_missing(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "proj-test")
    monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
    assert issue_state.next_issue_number(default=5) == 5


def test_returns_default_on_empty_env_strings(monkeypatch):
    """Whitespace-only env values should be treated as unset."""
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "   ")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "")
    assert issue_state.next_issue_number(default=1) == 1


def test_returns_default_on_network_error(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "proj-test")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    def _raise(*_a, **_kw):
        raise issue_state.urllib.error.URLError("network down")
    with patch.object(issue_state.urllib.request, "urlopen", side_effect=_raise):
        assert issue_state.next_issue_number(default=1) == 1


def test_returns_default_on_malformed_json(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "proj-test")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    class _Resp:
        def read(self): return b"not json {{{"
        def __enter__(self): return self
        def __exit__(self, *_): return False
    with patch.object(issue_state.urllib.request, "urlopen", return_value=_Resp()):
        assert issue_state.next_issue_number(default=1) == 1


def test_returns_default_on_non_integer_max(monkeypatch):
    """A schema-drift safety: if PostHog returns a non-int for max_issue,
    degrade rather than crash."""
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "proj-test")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    with patch.object(issue_state.urllib.request, "urlopen", return_value=_ok_response("not-a-number")):
        assert issue_state.next_issue_number(default=1) == 1
