"""Routing + idempotency guards for the resubscribe welcome-back path
in `dispatch_welcome`.

These tests pin the DECISION logic — which variant renders, which
idempotency stamp is read/written, which telemetry fires — without
exercising the full HTML render (covered by
`tests/newsletter/components/test_welcome_back_render.py`) or the real
Clerk/Resend network calls. Every heavy collaborator is monkeypatched
to a marker so the assertions read the branch taken, not the bytes.

Matrix covered:
  • first-timer + allow_resubscribe   → welcome (unchanged)
  • returning + allow_resubscribe     → welcome_back, stamps sub id
  • returning + same sub id (retry)   → skipped already_sent_for_subscription
  • returning, allow_resubscribe=False → skipped already_sent (legacy)
  • force + variant=welcome_back       → welcome_back regardless of stamps
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from automation.newsletter import welcome_dispatch as wd
from automation.newsletter.subscribers import ClerkUser


def _clerk_user(*, welcome_sent_at=None, resub_sub_id=None, plan="pro"):
    return ClerkUser(
        id="user_123",
        email="returning@test.local",
        first_name="Javier",
        plan=plan,
        profile={},
        welcome_sent_at=welcome_sent_at,
        resubscribe_welcome_subscription_id=resub_sub_id,
    )


@pytest.fixture
def harness(monkeypatch):
    """Patch every collaborator dispatch_welcome touches and expose the
    recorded calls (sent payload, stamp calls, captured events). The
    per-test body sets `state['user']` before calling dispatch_welcome."""
    state = {
        "user": None,
        "sent": {},
        "stamps": [],
        "events": [],
    }

    monkeypatch.setattr(wd, "find_clerk_user_by_email", lambda email: state["user"])
    monkeypatch.setattr(wd, "_load_ranked", lambda path: [{"rank": 1}])
    monkeypatch.setattr(wd, "build_issue", lambda **kw: SimpleNamespace(
        recipient=kw["recipient"],
        locale=kw["recipient"].locale,
        picks_top=[object()],
        picks_shortlist=[],
        paywall_target_url=None,
        issue_number=kw["issue_number"],
        issue_date_human="2 JUN 2026",
    ))
    monkeypatch.setattr(wd.pulpo_pro_welcome, "render", lambda issue: "WELCOME_HTML")
    monkeypatch.setattr(wd.pulpo_pro_welcome_back, "render", lambda issue: "WELCOME_BACK_HTML")

    def _fake_send(**kwargs):
        state["sent"] = kwargs
        return SimpleNamespace(
            ok=True, dry_run=False, message_id="msg_1",
            error=None, error_detail=None, latency_ms=5, attempt=1,
        )
    monkeypatch.setattr(wd, "send_issue", _fake_send)

    monkeypatch.setattr(wd, "_stamp_welcome_sent_at",
                        lambda uid, ts: state["stamps"].append(("welcome", uid, ts)) or True)
    monkeypatch.setattr(wd, "_stamp_resubscribe_welcome",
                        lambda uid, ts, sub: state["stamps"].append(("resub", uid, ts, sub)) or True)
    monkeypatch.setattr(wd, "_capture",
                        lambda ev, props: state["events"].append((ev, props)))
    return state


def _event_names(state):
    return [ev for ev, _ in state["events"]]


def test_first_timer_routes_to_welcome(harness):
    """No prior welcome stamp + allow_resubscribe → first-time welcome,
    welcome stamp written, newsletter.welcome_sent fired."""
    harness["user"] = _clerk_user(welcome_sent_at=None)
    res = wd.dispatch_welcome(
        email="returning@test.local", source="stripe.checkout.auth_gated",
        allow_resubscribe=True, subscription_id="sub_first",
    )
    assert res.status == "sent"
    assert harness["sent"]["html"] == "WELCOME_HTML"
    assert harness["sent"]["tags"]["newsletter"] == "pulpo-pro-welcome"
    assert harness["stamps"] == [("welcome", "user_123", harness["stamps"][0][2])]
    assert "newsletter.welcome_sent" in _event_names(harness)
    sent_props = dict(harness["events"])["newsletter.welcome_sent"]
    assert sent_props["variant"] == "welcome"


def test_returning_subscriber_routes_to_welcome_back(harness):
    """Prior welcome stamp + allow_resubscribe + a NEW subscription id →
    welcome-back render, resubscribe stamp keyed on the new sub id,
    newsletter.welcome_back_sent fired with variant=welcome_back."""
    harness["user"] = _clerk_user(welcome_sent_at="2026-01-01T00:00:00+00:00",
                                  resub_sub_id=None)
    res = wd.dispatch_welcome(
        email="returning@test.local", source="stripe.checkout.auth_gated",
        allow_resubscribe=True, subscription_id="sub_new",
    )
    assert res.status == "sent"
    assert harness["sent"]["html"] == "WELCOME_BACK_HTML"
    assert harness["sent"]["tags"]["newsletter"] == "pulpo-pro-welcome-back"
    assert harness["stamps"] == [("resub", "user_123", harness["stamps"][0][2], "sub_new")]
    assert "newsletter.welcome_back_sent" in _event_names(harness)
    assert "newsletter.welcome_sent" not in _event_names(harness)
    sent_props = dict(harness["events"])["newsletter.welcome_back_sent"]
    assert sent_props["variant"] == "welcome_back"
    assert sent_props["subscription_id"] == "sub_new"


def test_same_subscription_id_is_deduped(harness):
    """Webhook retry: prior welcome-back already sent for THIS sub id →
    skipped already_sent_for_subscription, nothing sent or stamped."""
    harness["user"] = _clerk_user(welcome_sent_at="2026-01-01T00:00:00+00:00",
                                  resub_sub_id="sub_dupe")
    res = wd.dispatch_welcome(
        email="returning@test.local", source="stripe.checkout.auth_gated",
        allow_resubscribe=True, subscription_id="sub_dupe",
    )
    assert res.status == "skipped"
    assert res.reason == "already_sent_for_subscription"
    assert harness["sent"] == {}
    assert harness["stamps"] == []
    assert "newsletter.welcome_back_skipped" in _event_names(harness)


def test_new_subscription_after_prior_welcome_back_fires_again(harness):
    """A genuine SECOND resubscription (different sub id from the stored
    one) must fire welcome-back again — that's 'every resubscribe'."""
    harness["user"] = _clerk_user(welcome_sent_at="2026-01-01T00:00:00+00:00",
                                  resub_sub_id="sub_old")
    res = wd.dispatch_welcome(
        email="returning@test.local", source="stripe.checkout.auth_gated",
        allow_resubscribe=True, subscription_id="sub_newer",
    )
    assert res.status == "sent"
    assert harness["sent"]["html"] == "WELCOME_BACK_HTML"
    assert harness["stamps"][0] == ("resub", "user_123", harness["stamps"][0][2], "sub_newer")


def test_already_sent_preserved_when_resubscribe_not_allowed(harness):
    """Legacy behavior intact: a prior-welcome user on a NON-resubscribe
    path (admin/clerk) still skips already_sent — no welcome-back leak."""
    harness["user"] = _clerk_user(welcome_sent_at="2026-01-01T00:00:00+00:00")
    res = wd.dispatch_welcome(
        email="returning@test.local", source="admin",
        allow_resubscribe=False, subscription_id=None,
    )
    assert res.status == "skipped"
    assert res.reason == "already_sent"
    assert harness["sent"] == {}
    assert "newsletter.welcome_skipped" in _event_names(harness)


def test_force_variant_welcome_back_renders_regardless(harness):
    """Admin/test 'send me the welcome-back' — variant pinned explicitly
    + force → welcome-back render even with no prior stamps and no
    subscription id."""
    harness["user"] = _clerk_user(welcome_sent_at=None, resub_sub_id=None)
    res = wd.dispatch_welcome(
        email="returning@test.local", source="test",
        variant="welcome_back", force=True,
    )
    assert res.status == "sent"
    assert harness["sent"]["html"] == "WELCOME_BACK_HTML"
    assert harness["sent"]["tags"]["newsletter"] == "pulpo-pro-welcome-back"


def test_not_pro_still_skips_before_variant_decision(harness):
    """A free-plan user never reaches the variant branch — the not_pro
    gate fires first regardless of allow_resubscribe."""
    harness["user"] = _clerk_user(welcome_sent_at="2026-01-01T00:00:00+00:00",
                                  plan="free")
    res = wd.dispatch_welcome(
        email="returning@test.local", source="stripe.checkout.auth_gated",
        allow_resubscribe=True, subscription_id="sub_x",
    )
    assert res.status == "skipped"
    assert res.reason == "not_pro"
    assert harness["sent"] == {}


def test_forced_send_preserves_existing_welcome_stamp(harness):
    """Regression guard for the Issue-13 suppression (2026-07-05).

    An admin welcome-TEST (force=True) aimed at an already-welcomed
    subscriber must SEND the email but NOT overwrite their existing
    `welcome_newsletter_sent_at`. Moving the stamp forward re-arms the
    weekly cron's 96h first-Sunday skip and silently drops that
    subscriber's next weekly. The send goes out; the stamp is preserved;
    the result + telemetry flag it so the admin UI can warn."""
    harness["user"] = _clerk_user(welcome_sent_at="2026-01-01T00:00:00+00:00")
    res = wd.dispatch_welcome(
        email="returning@test.local", source="admin", force=True,
    )
    assert res.status == "sent"
    # Email actually sent (force bypassed the already_sent skip)…
    assert harness["sent"]["html"] == "WELCOME_HTML"
    # …but the prod welcome stamp was left untouched.
    assert harness["stamps"] == []
    assert res.stamp_preserved is True
    sent_props = dict(harness["events"])["newsletter.welcome_sent"]
    assert sent_props["stamp_preserved"] is True
    assert sent_props["stamped_clerk"] is False


def test_forced_send_to_unwelcomed_pro_still_stamps(harness):
    """The preservation is scoped to an EXISTING stamp. A forced send to a
    Pro who has never been welcomed still writes the first-time stamp — we
    only decline to MOVE a stamp that already exists, never to create one."""
    harness["user"] = _clerk_user(welcome_sent_at=None)
    res = wd.dispatch_welcome(
        email="returning@test.local", source="admin", force=True,
    )
    assert res.status == "sent"
    assert res.stamp_preserved is False
    assert harness["stamps"] == [("welcome", "user_123", harness["stamps"][0][2])]
    sent_props = dict(harness["events"])["newsletter.welcome_sent"]
    assert sent_props["stamp_preserved"] is False
    assert sent_props["stamped_clerk"] is True
