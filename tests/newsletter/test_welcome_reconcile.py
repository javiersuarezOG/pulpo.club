"""Tests for the welcome reconciliation cron at
automation/newsletter/welcome_reconcile.py.

Two surfaces under test:
  • `fetch_eligible_pros` — the Clerk query + filter. Pure given a
    deterministic `now` and a stubbed Clerk getter.
  • `run_reconcile` — the dispatch loop. Stubs both the Clerk getter
    AND `dispatch_welcome` so no httpx / Resend / Clerk-write side
    effects happen.

These tests intentionally don't exercise the full HTTP/Vercel/Resend
pipeline — that's covered by the per-component test suites already.
The reconcile tests cover the orchestration: eligibility filter,
backlog ordering, dry-run vs. live mode, error handling, and the
ReconcileResult counters.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from automation.newsletter import welcome_reconcile
from automation.newsletter.welcome_reconcile import (
    ReconcileResult,
    fetch_eligible_pros,
    run_reconcile,
)


# Anchor "now" so all tests work against a deterministic clock. Tue
# 2026-06-09 12:00 UTC — middle of the week, no DST edge cases.
NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _clerk_user_row(
    *,
    user_id: str,
    email: str,
    plan: str = "pro",
    welcome_sent_at: str | None = None,
    created_at_ms: int | None = None,
) -> dict:
    """Synth a Clerk /v1/users row matching the real payload shape.
    `_parse_clerk_user` reads from snake_case `public_metadata`."""
    public = {"plan": plan}
    if welcome_sent_at:
        public["welcome_newsletter_sent_at"] = welcome_sent_at
    return {
        "id": user_id,
        "first_name": "Test",
        "email_addresses": [{"id": "ea_1", "email_address": email}],
        "primary_email_address_id": "ea_1",
        "public_metadata": public,
        "private_metadata": {},
        "created_at": created_at_ms or int(NOW.timestamp() * 1000),
    }


def _stub_clerk_getter(rows: list[dict]):
    """Build a `get_override` callable that returns `rows` then empty.
    Mirrors Clerk's pagination protocol (one page returns the rows,
    subsequent pages return [] to signal end-of-list)."""
    state = {"called": 0}

    def getter(url, headers=None, params=None):
        state["called"] += 1
        if state["called"] == 1:
            return rows
        return []

    return getter, state


# ── fetch_eligible_pros — pure filter tests ──────────────────────────


def test_fetch_filters_to_pro_plan_only():
    rows = [
        _clerk_user_row(user_id="user_pro", email="pro@p.club", plan="pro"),
        _clerk_user_row(user_id="user_free", email="free@p.club", plan="free"),
        _clerk_user_row(user_id="user_agency", email="agency@p.club", plan="agency"),
    ]
    getter, _ = _stub_clerk_getter(rows)
    result = fetch_eligible_pros(
        secret_key="sk_test",
        now=NOW,
        get_override=getter,
    )
    ids = [u.id for u in result]
    assert ids == ["user_pro"]
    # Agency is intentionally NOT included — welcome is Pro-specific
    # editorial framing; agency users get a different onboarding (or
    # nothing, today).


def test_fetch_skips_users_with_welcome_stamp_already_set():
    rows = [
        _clerk_user_row(user_id="user_stamped",
                        email="stamped@p.club",
                        welcome_sent_at="2026-06-08T10:00:00Z"),
        _clerk_user_row(user_id="user_orphan", email="orphan@p.club"),
    ]
    getter, _ = _stub_clerk_getter(rows)
    result = fetch_eligible_pros(
        secret_key="sk_test", now=NOW, get_override=getter,
    )
    assert [u.id for u in result] == ["user_orphan"]


def test_fetch_caps_at_limit():
    rows = [
        _clerk_user_row(user_id=f"user_{i}", email=f"u{i}@p.club")
        for i in range(50)
    ]
    getter, _ = _stub_clerk_getter(rows)
    result = fetch_eligible_pros(
        secret_key="sk_test", now=NOW, get_override=getter, limit=20,
    )
    assert len(result) == 20
    # First 20 in input order — Clerk's `order_by=+created_at` puts
    # oldest first so the cron drains the oldest backlog first.
    assert result[0].id == "user_0"
    assert result[-1].id == "user_19"


def test_fetch_returns_empty_when_no_clerk_secret(monkeypatch):
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    getter, state = _stub_clerk_getter([])
    result = fetch_eligible_pros(now=NOW, get_override=getter)
    assert result == []
    # Critically: we did NOT call the getter — short-circuited at the
    # secret check, no wasted Clerk API request.
    assert state["called"] == 0


def test_fetch_uses_created_at_window_params():
    """The query MUST scope to a created_at window — otherwise the
    cron pages through every Pro user ever, blowing the GH Actions
    timeout. Locking the param contract here so a future "simplify"
    that removes them gets caught immediately."""
    captured_params: dict = {}

    def getter(url, headers=None, params=None):
        captured_params.update(params or {})
        return []

    fetch_eligible_pros(
        secret_key="sk_test",
        now=NOW,
        min_age_hours=1,
        max_age_days=7,
        get_override=getter,
    )
    # 1h ago = NOW - 1 hour
    expected_before = int((NOW - timedelta(hours=1)).timestamp() * 1000)
    # 7d ago = NOW - 7 days
    expected_after = int((NOW - timedelta(days=7)).timestamp() * 1000)
    assert captured_params["created_at_before_epoch_ms"] == expected_before
    assert captured_params["created_at_after_epoch_ms"] == expected_after
    assert captured_params["order_by"] == "+created_at"


def test_fetch_returns_empty_on_malformed_clerk_response():
    """Clerk occasionally returns non-list payloads (rate-limited,
    error envelope). Defensive degrade — the cron retries next hour,
    not a crash."""
    def getter(url, headers=None, params=None):
        return {"error": "rate_limited"}  # not a list
    result = fetch_eligible_pros(
        secret_key="sk_test", now=NOW, get_override=getter,
    )
    assert result == []


# ── run_reconcile — orchestration tests ──────────────────────────────


def test_dry_run_does_not_call_dispatcher():
    rows = [
        _clerk_user_row(user_id="user_1", email="u1@p.club"),
        _clerk_user_row(user_id="user_2", email="u2@p.club"),
    ]
    getter, _ = _stub_clerk_getter(rows)
    with patch.object(welcome_reconcile, "dispatch_welcome") as mock_dispatch:
        result = run_reconcile(
            dry_run=True,
            secret_key="sk_test",
            now=NOW,
            get_override=getter,
        )
    assert mock_dispatch.call_count == 0
    assert result.found == 2
    assert result.skipped == 2  # dry-run counts as skipped
    assert result.sent == 0
    assert result.failed == 0
    assert result.dry_run is True


def test_live_run_dispatches_per_user():
    rows = [
        _clerk_user_row(user_id="user_1", email="u1@p.club"),
        _clerk_user_row(user_id="user_2", email="u2@p.club"),
    ]
    getter, _ = _stub_clerk_getter(rows)
    with patch.object(welcome_reconcile, "dispatch_welcome") as mock_dispatch:
        mock_dispatch.return_value = SimpleNamespace(
            status="sent", reason=None, dry_run=False, message_id="re_1", recipient_hash="abc",
        )
        result = run_reconcile(
            dry_run=False,
            secret_key="sk_test",
            now=NOW,
            get_override=getter,
        )
    assert mock_dispatch.call_count == 2
    # Each call passes the user's email + source tag.
    for call in mock_dispatch.call_args_list:
        assert call.kwargs["source"] == "reconcile_cron"
        assert call.kwargs["force"] is False  # never force on reconcile
    assert result.sent == 2
    assert result.skipped == 0


def test_live_run_counts_per_status():
    rows = [
        _clerk_user_row(user_id="user_sent", email="sent@p.club"),
        _clerk_user_row(user_id="user_skip", email="skip@p.club"),
        _clerk_user_row(user_id="user_fail", email="fail@p.club"),
    ]
    getter, _ = _stub_clerk_getter(rows)
    statuses = iter([
        SimpleNamespace(status="sent", reason=None, dry_run=False, message_id="re_a", recipient_hash="h1"),
        SimpleNamespace(status="skipped", reason="already_sent", dry_run=False, message_id=None, recipient_hash="h2"),
        SimpleNamespace(status="failed", reason="send_failed", dry_run=False, message_id=None, recipient_hash="h3"),
    ])
    with patch.object(welcome_reconcile, "dispatch_welcome", side_effect=lambda **kwargs: next(statuses)):
        result = run_reconcile(
            dry_run=False, secret_key="sk_test", now=NOW, get_override=getter,
        )
    assert result.found == 3
    assert result.sent == 1
    assert result.skipped == 1
    assert result.failed == 1


def test_live_run_continues_after_per_user_dispatcher_exception():
    """A single user's dispatch throw must NOT abort the whole cron.
    Mark the user as failed + keep going."""
    rows = [
        _clerk_user_row(user_id="user_throw", email="throw@p.club"),
        _clerk_user_row(user_id="user_ok", email="ok@p.club"),
    ]
    getter, _ = _stub_clerk_getter(rows)
    call_count = {"n": 0}

    def dispatch_side_effect(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated Clerk lookup failure")
        return SimpleNamespace(status="sent", reason=None, dry_run=False,
                               message_id="re_ok", recipient_hash="hh")

    with patch.object(welcome_reconcile, "dispatch_welcome", side_effect=dispatch_side_effect):
        result = run_reconcile(
            dry_run=False, secret_key="sk_test", now=NOW, get_override=getter,
        )
    assert result.found == 2
    assert result.failed == 1   # user_throw
    assert result.sent == 1     # user_ok continued
    assert result.skipped == 0


def test_returns_empty_result_when_no_eligible_users():
    getter, _ = _stub_clerk_getter([])
    with patch.object(welcome_reconcile, "dispatch_welcome") as mock_dispatch:
        result = run_reconcile(
            dry_run=False, secret_key="sk_test", now=NOW, get_override=getter,
        )
    assert mock_dispatch.call_count == 0
    assert result.found == 0
    assert result.sent == result.skipped == result.failed == 0


def test_max_users_enforced():
    """Per-run cap defends against Resend rate limits + GH Actions
    timeout. A backlog of 100 orphans must NOT all dispatch in one
    tick."""
    rows = [
        _clerk_user_row(user_id=f"user_{i}", email=f"u{i}@p.club")
        for i in range(40)
    ]
    getter, _ = _stub_clerk_getter(rows)
    with patch.object(welcome_reconcile, "dispatch_welcome") as mock_dispatch:
        mock_dispatch.return_value = SimpleNamespace(
            status="sent", reason=None, dry_run=False, message_id="re_x", recipient_hash="hh",
        )
        result = run_reconcile(
            dry_run=False,
            secret_key="sk_test",
            now=NOW,
            max_users=10,
            get_override=getter,
        )
    assert mock_dispatch.call_count == 10
    assert result.found == 10
