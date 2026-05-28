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


def test_synthesize_preview_recipients_covers_three_cohorts():
    from automation.newsletter.build_issue import detect_cohort

    queue = subs.synthesize_preview_recipients("Preview@Pulpo.Club")
    assert len(queue) == 3
    emails = {email for _, email in queue}
    assert emails == {"preview@pulpo.club"}        # normalized + same address everywhere
    cohorts = [detect_cohort(r) for r, _ in queue]
    assert cohorts == ["anonymous", "free_prefs", "pro_prefs"]


def test_synthesize_preview_recipients_rejects_bad_email():
    import pytest
    with pytest.raises(ValueError):
        subs.synthesize_preview_recipients("not-an-email")
    with pytest.raises(ValueError):
        subs.synthesize_preview_recipients("   ")


# ── locale side-channel (pulpo-locale: prefix on Resend first_name) ──────
def test_parse_locale_first_name_extracts_known_locales():
    assert subs._parse_locale_first_name("pulpo-locale:es") == "es"
    assert subs._parse_locale_first_name("pulpo-locale:en") == "en"
    assert subs._parse_locale_first_name("pulpo-locale:ES") == "es"
    # Surrounding whitespace tolerated (defensive)
    assert subs._parse_locale_first_name("pulpo-locale:  es ") == "es"


def test_parse_locale_first_name_rejects_garbage():
    assert subs._parse_locale_first_name(None) is None
    assert subs._parse_locale_first_name("") is None
    assert subs._parse_locale_first_name("Javier") is None
    assert subs._parse_locale_first_name("pulpo-locale:") is None
    assert subs._parse_locale_first_name("pulpo-locale:fr") is None
    # Wrong prefix
    assert subs._parse_locale_first_name("locale:es") is None
    # Wrong type
    assert subs._parse_locale_first_name(42) is None


def test_list_audience_extracts_locale_from_first_name(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_AUDIENCE_ID", "aud-123")

    def fake_get(url, headers=None, params=None, timeout=None):
        return _resend_payload([
            {"id": "c1", "email": "es@pulpo.club", "unsubscribed": False,
             "first_name": "pulpo-locale:es"},
            {"id": "c2", "email": "en@pulpo.club", "unsubscribed": False,
             "first_name": "pulpo-locale:en"},
            {"id": "c3", "email": "legacy@pulpo.club", "unsubscribed": False},
            # camelCase variant from SDK; should still parse
            {"id": "c4", "email": "camel@pulpo.club", "unsubscribed": False,
             "firstName": "pulpo-locale:es"},
            # Garbage prefix → None (falls back to "en" downstream)
            {"id": "c5", "email": "bogus@pulpo.club", "unsubscribed": False,
             "first_name": "Some Person"},
        ])

    contacts = {c.email: c for c in subs.list_audience(get_override=fake_get)}
    assert contacts["es@pulpo.club"].locale == "es"
    assert contacts["en@pulpo.club"].locale == "en"
    assert contacts["legacy@pulpo.club"].locale is None
    assert contacts["camel@pulpo.club"].locale == "es"
    assert contacts["bogus@pulpo.club"].locale is None


def test_join_uses_contact_locale_for_anonymous_when_present():
    contacts = [
        subs.ResendContact(id="c1", email="anon-es@example.com",
                           unsubscribed=False, created_at=None, locale="es"),
        subs.ResendContact(id="c2", email="anon-en@example.com",
                           unsubscribed=False, created_at=None, locale="en"),
        subs.ResendContact(id="c3", email="anon-legacy@example.com",
                           unsubscribed=False, created_at=None),
    ]
    recipients = subs.join_recipients(contacts=contacts, clerk_users=[])
    # Locale persisted from the side-channel wins for anonymous contacts.
    locales = [r.locale for r in recipients]
    assert locales[0] == "es"             # anon-es
    assert locales[1] == "en"             # anon-en
    assert locales[2] == "en"             # legacy (no prefix → default)
