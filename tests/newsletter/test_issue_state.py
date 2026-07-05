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


# ── authoritative committed counter (P1) — all use tmp files ───────────
# NOTE: these MUST pass an explicit tmp path; never touch the real
# web/data/newsletter_issue_state.json (a default-path call would mutate
# the committed seed).

import json as _json  # noqa: E402
from datetime import date  # noqa: E402


def _seed(tmp_path, issue_number=13, iso_week="2026-W27"):
    p = tmp_path / "issue_state.json"
    p.write_text(_json.dumps({"issue_number": issue_number, "iso_week": iso_week}))
    return p


def test_current_issue_number_reads_committed_file(tmp_path):
    assert issue_state.current_issue_number(_seed(tmp_path, 13)) == 13


def test_read_is_fail_closed_when_missing(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(issue_state.IssueStateError):
        issue_state.current_issue_number(missing)


def test_read_is_fail_closed_on_corrupt_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{{{ not json")
    with pytest.raises(issue_state.IssueStateError):
        issue_state.current_issue_number(p)


@pytest.mark.parametrize("bad", [0, -3, "5", 1.5, True, None])
def test_read_is_fail_closed_on_invalid_issue_number(tmp_path, bad):
    p = tmp_path / "bad.json"
    p.write_text(_json.dumps({"issue_number": bad, "iso_week": "2026-W27"}))
    with pytest.raises(issue_state.IssueStateError):
        issue_state.current_issue_number(p)


def test_advance_is_noop_within_same_iso_week(tmp_path):
    p = _seed(tmp_path, 13, "2026-W27")
    state, changed = issue_state.advance_issue_state_for_week(p, today=date(2026, 7, 5))  # Sun W27
    assert changed is False
    assert state["issue_number"] == 13
    # file unchanged
    assert issue_state.current_issue_number(p) == 13


def test_advance_bumps_once_on_new_iso_week(tmp_path):
    p = _seed(tmp_path, 13, "2026-W27")
    state, changed = issue_state.advance_issue_state_for_week(p, today=date(2026, 7, 6))  # Mon W28
    assert changed is True
    assert state["issue_number"] == 14
    assert state["iso_week"] == "2026-W28"
    assert issue_state.current_issue_number(p) == 14


def test_advance_is_idempotent_across_the_week(tmp_path):
    """Mon advances; Tue–Sun of the same week are no-ops — the number never
    double-advances even though the nightly runs daily."""
    p = _seed(tmp_path, 13, "2026-W27")
    issue_state.advance_issue_state_for_week(p, today=date(2026, 7, 6))   # Mon W28 → 14
    for d in (date(2026, 7, 7), date(2026, 7, 10), date(2026, 7, 12)):    # Tue, Fri, Sun
        _, changed = issue_state.advance_issue_state_for_week(p, today=d)
        assert changed is False
    assert issue_state.current_issue_number(p) == 14


def test_pro_and_free_read_the_same_number(tmp_path):
    """The core 'shared Pro/Free' guarantee: two independent reads of the
    same committed file that week return the identical number."""
    p = _seed(tmp_path, 13, "2026-W27")
    pro = issue_state.current_issue_number(p)
    free = issue_state.current_issue_number(p)  # 1h later, same file
    assert pro == free == 13
