"""subscribers.py — Resend × Clerk join + Recipient cohort assignment."""

from __future__ import annotations

from automation.newsletter import subscribers as subs
from automation.newsletter.types import Preference


# ── Fixtures (literal dicts mimicking the API shapes) ────────────────────
def _resend_payload(rows):
    return {"data": rows}


def _clerk_user(email, *, plan="free", first_name=None, profile=None):
    return {
        "id": f"user_{email.split('@')[0]}",
        "first_name": first_name,
        "email_addresses": [
            {"id": "ea_1", "email_address": email}
        ],
        "primary_email_address_id": "ea_1",
        "public_metadata": {
            "plan": plan,
            "profile": profile or {},
        },
    }


# ── list_audience ────────────────────────────────────────────────────────
def test_list_audience_filters_unsubscribed_default(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_AUDIENCE_ID", "aud-123")

    def fake_get(url, headers=None, params=None, timeout=None):
        return _resend_payload([
            {"id": "c1", "email": "Active@Pulpo.Club", "unsubscribed": False},
            {"id": "c2", "email": "out@pulpo.club", "unsubscribed": True},
            {"id": "c3", "email": "not-an-email", "unsubscribed": False},
            {"id": "c4", "email": "second@pulpo.club", "unsubscribed": False},
        ])

    contacts = subs.list_audience(get_override=fake_get)
    emails = sorted(c.email for c in contacts)
    # Normalised (lowercased + stripped), invalid filtered out, unsubscribed kept
    # in the list but with the flag preserved (join_recipients decides whether
    # to send).
    assert emails == ["active@pulpo.club", "out@pulpo.club", "second@pulpo.club"]
    unsub_flag = {c.email: c.unsubscribed for c in contacts}
    assert unsub_flag["out@pulpo.club"] is True
    assert unsub_flag["active@pulpo.club"] is False


def test_list_audience_no_env_returns_empty(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_AUDIENCE_ID", raising=False)
    assert subs.list_audience() == []


# ── list_clerk_users + pagination ────────────────────────────────────────
def test_list_clerk_users_paginates(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test")

    pages = [
        [_clerk_user("a@b.com", plan="pro"), _clerk_user("c@d.com", plan="free")],
        [_clerk_user("e@f.com", plan="agency")],
        [],
    ]
    page_idx = {"i": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        i = page_idx["i"]
        page_idx["i"] += 1
        if i < len(pages):
            return pages[i]
        return []

    users = subs.list_clerk_users(get_override=fake_get, page_size=2)
    emails = sorted(u.email for u in users)
    assert emails == ["a@b.com", "c@d.com", "e@f.com"]
    plans = {u.email: u.plan for u in users}
    assert plans["a@b.com"] == "pro"
    assert plans["e@f.com"] == "agency"


def test_list_clerk_users_no_secret_quiet_no_op(monkeypatch):
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    assert subs.list_clerk_users() == []


# ── join_recipients ──────────────────────────────────────────────────────
def test_join_promotes_clerk_matched_to_full_cohort():
    contacts = [
        subs.ResendContact(id="c1", email="javier@suarez.ventures",
                           unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="anon@example.com",
                           unsubscribed=False, created_at=None),
    ]
    clerk_user = subs._parse_clerk_user(_clerk_user(
        "javier@suarez.ventures",
        plan="pro",
        first_name="Javier",
        profile={
            "newsletter": {
                "departments": ["La Libertad"],
                "property_types": ["land"],
                "max_price_usd": 500_000,
                "locale": "es",
            },
        },
    ))
    recipients = subs.join_recipients(contacts=contacts, clerk_users=[clerk_user])
    assert len(recipients) == 2
    javier = next(r for r in recipients if r.display_name == "Javier")
    assert javier.tier == "pro"
    assert javier.has_account is True
    assert javier.locale == "es"
    assert javier.preference.departments == ["La Libertad"]
    assert javier.preference.property_types == ["land"]
    assert javier.preference.max_price_usd == 500_000

    anon = next(r for r in recipients if r.display_name is None)
    assert anon.tier == "free"
    assert anon.has_account is False
    assert anon.preference == Preference()


def test_join_excludes_unsubscribed_by_default():
    contacts = [
        subs.ResendContact(id="c1", email="ok@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="off@pulpo.club", unsubscribed=True, created_at=None),
    ]
    recipients = subs.join_recipients(contacts=contacts, clerk_users=[])
    assert len(recipients) == 1


def test_join_only_emails_filters():
    contacts = [
        subs.ResendContact(id="c1", email="javier@suarez.ventures",
                           unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="someone@other.com",
                           unsubscribed=False, created_at=None),
    ]
    recipients = subs.join_recipients(
        contacts=contacts,
        clerk_users=[],
        only_emails={"javier@suarez.ventures"},
    )
    assert len(recipients) == 1


def test_join_dedupes_duplicate_contacts():
    contacts = [
        subs.ResendContact(id="c1", email="dup@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="dup@pulpo.club", unsubscribed=False, created_at=None),
    ]
    assert len(subs.join_recipients(contacts=contacts, clerk_users=[])) == 1


def test_preference_from_profile_tolerates_garbage():
    p = subs._preference_from_profile({"newsletter": {
        "zones": ["el-zonte", 7, None],          # mixed types — strings only kept
        "property_types": "land",                # wrong shape — empty
        "max_price_usd": "five hundred",         # wrong type — dropped
        "categories": ["beachfront"],
    }})
    assert p.zones == ["el-zonte"]
    assert p.property_types == []                # not coerced from string
    assert p.max_price_usd is None
    assert p.categories == ["beachfront"]


def test_preference_from_missing_newsletter_block():
    p = subs._preference_from_profile({})
    assert p == Preference()
    p2 = subs._preference_from_profile({"newsletter": "not-a-dict"})
    assert p2 == Preference()
