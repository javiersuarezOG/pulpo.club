"""Tests for the free-welcome reconcile backstop.

Focus on the SAFETY guards (PostHog-failure abort + dark-path guard + cap),
since the PostHog welcomed-set is the only dedup and getting it wrong spams
real people.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from automation.newsletter import free_welcome_reconcile as fr
from automation.newsletter.store import email_hash

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


def _contact(email: str, *, days_ago: float = 2.0, unsubscribed: bool = False, locale: str = "en") -> dict:
    created = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {
        "id": f"c_{email}",
        "email": email,
        "unsubscribed": unsubscribed,
        "created_at": created,
        "first_name": f"pulpo-locale:{locale}",
    }


def _audience(*contacts: dict):
    def get_override(_url, headers=None):  # noqa: ARG001
        return {"data": list(contacts)}
    return get_override


def _welcomed(*emails: str):
    """post_override returning the welcomed recipient_hashes for these emails."""
    hashes = [[email_hash(e)] for e in emails]

    def post_override(_host, _project, _key, _body):  # noqa: ARG001
        return {"results": hashes}
    return post_override


@pytest.fixture(autouse=True)
def _resend_env(monkeypatch):
    # list_audience returns [] unless these are set (before get_override runs).
    monkeypatch.setenv("RESEND_AUDIENCE_ID", "aud_test")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")


# ── fetch_recent_free_contacts — window + unsubscribed + FIFO ──────────────

def test_window_excludes_too_new_too_old_and_unsubscribed():
    contacts = [
        _contact("toonew@x.com", days_ago=0.01),     # < 1h grace → excluded
        _contact("inwindow@x.com", days_ago=2),       # included
        _contact("tooold@x.com", days_ago=9),         # > 7d → excluded
        _contact("unsub@x.com", days_ago=2, unsubscribed=True),  # excluded
    ]
    out = fr.fetch_recent_free_contacts(now=NOW, get_override=_audience(*contacts))
    assert [c.email for c in out] == ["inwindow@x.com"]


def test_window_is_fifo_oldest_first():
    contacts = [
        _contact("b@x.com", days_ago=2),
        _contact("a@x.com", days_ago=5),
        _contact("c@x.com", days_ago=3),
    ]
    out = fr.fetch_recent_free_contacts(now=NOW, get_override=_audience(*contacts))
    assert [c.email for c in out] == ["a@x.com", "c@x.com", "b@x.com"]


# ── query_welcomed_hashes ──────────────────────────────────────────────────

def test_query_raises_without_creds(monkeypatch):
    monkeypatch.delenv("POSTHOG_PROJECT_ID", raising=False)
    monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
    with pytest.raises(fr.PostHogUnavailable):
        fr.query_welcomed_hashes(now=NOW)


def test_query_raises_on_query_error():
    def boom(_h, _p, _k, _b):
        raise RuntimeError("posthog 500")
    with pytest.raises(fr.PostHogUnavailable):
        fr.query_welcomed_hashes(now=NOW, post_override=boom)


def test_query_parses_hashes():
    got = fr.query_welcomed_hashes(now=NOW, post_override=_welcomed("a@x.com", "b@x.com"))
    assert got == {email_hash("a@x.com"), email_hash("b@x.com")}


# ── run_reconcile — the safety guards ──────────────────────────────────────

def _no_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(fr, "dispatch_free_welcome", lambda **kw: calls.append(kw) or _Sent())
    return calls


class _Sent:
    status = "sent"
    reason = None
    message_id = "m1"


def test_aborts_on_posthog_failure(monkeypatch):
    calls = _no_dispatch(monkeypatch)

    def boom(_h, _p, _k, _b):
        raise RuntimeError("down")

    res = fr.run_reconcile(
        dry_run=False, now=NOW,
        get_override=_audience(_contact("a@x.com")),
        post_override=boom,
    )
    assert res.aborted_reason == "posthog_unavailable"
    assert res.sent == 0 and calls == []


def test_dark_path_guard_refuses_mass_send(monkeypatch):
    calls = _no_dispatch(monkeypatch)
    # 10 recent contacts, NONE welcomed → ratio 1.0 > 0.6 → abort.
    contacts = [_contact(f"u{i}@x.com") for i in range(10)]
    res = fr.run_reconcile(
        dry_run=False, now=NOW,
        get_override=_audience(*contacts),
        post_override=_welcomed(),  # empty welcomed set
    )
    assert res.aborted_reason == "welcome_path_dark"
    assert res.sent == 0 and calls == []


def test_resends_only_unwelcomed_when_live(monkeypatch):
    calls = _no_dispatch(monkeypatch)
    # 3 contacts (< dark-path floor), 2 welcomed, 1 not → only the 1 re-sends.
    contacts = [_contact("done1@x.com"), _contact("done2@x.com"), _contact("miss@x.com")]
    res = fr.run_reconcile(
        dry_run=False, now=NOW,
        get_override=_audience(*contacts),
        post_override=_welcomed("done1@x.com", "done2@x.com"),
    )
    assert res.found_recent == 3 and res.unwelcomed == 1
    assert res.sent == 1 and res.aborted_reason is None
    assert len(calls) == 1
    assert calls[0]["email"] == "miss@x.com"
    assert calls[0]["force"] is True and calls[0]["is_new_contact"] is False
    assert calls[0]["source"] == "free_reconcile_cron"


def test_dry_run_skips_without_dispatch(monkeypatch):
    calls = _no_dispatch(monkeypatch)
    contacts = [_contact("miss@x.com")]
    res = fr.run_reconcile(
        dry_run=True, now=NOW,
        get_override=_audience(*contacts),
        post_override=_welcomed(),  # 1 recent, 0 welcomed — below dark-path floor (need >=8)
    )
    assert res.unwelcomed == 1 and res.sent == 0 and res.skipped == 1
    assert calls == []


def test_respects_per_run_cap(monkeypatch):
    calls = _no_dispatch(monkeypatch)
    # 10 recent, 5 welcomed (ratio 0.5 ≤ 0.6 → no dark-path abort), cap=3.
    contacts = [_contact(f"u{i}@x.com") for i in range(10)]
    welcomed = _welcomed(*[f"u{i}@x.com" for i in range(5)])
    res = fr.run_reconcile(
        dry_run=False, now=NOW, max_contacts=3,
        get_override=_audience(*contacts),
        post_override=welcomed,
    )
    assert res.unwelcomed == 5 and res.sent == 3
    assert len(calls) == 3
