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
    """PR-NL-9 (audience scope): only Pro/Agency Clerk-matched contacts
    land in the queue. The anonymous contact is dropped — Free users
    will be served by a different system."""
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
    assert len(recipients) == 1
    javier = recipients[0]
    assert javier.display_name == "Javier"
    assert javier.tier == "pro"
    assert javier.has_account is True
    assert javier.locale == "es"
    assert javier.preference.departments == ["La Libertad"]
    assert javier.preference.property_types == ["land"]
    assert javier.preference.max_price_usd == 500_000


def test_join_excludes_unsubscribed_by_default():
    """Subscribers with `unsubscribed=True` are dropped even when their
    Clerk record makes them Pro-eligible."""
    contacts = [
        subs.ResendContact(id="c1", email="ok@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="off@pulpo.club", unsubscribed=True, created_at=None),
    ]
    pros = [
        subs._parse_clerk_user(_clerk_user("ok@pulpo.club", plan="pro")),
        subs._parse_clerk_user(_clerk_user("off@pulpo.club", plan="pro")),
    ]
    recipients = subs.join_recipients(contacts=contacts, clerk_users=pros)
    assert len(recipients) == 1
    assert recipients[0].email_hash == subs.email_hash("ok@pulpo.club")


def test_join_only_emails_filters():
    """`only_emails` further restricts the Pro-eligible queue — passing
    a Free or anonymous-only address through this seam still drops them."""
    contacts = [
        subs.ResendContact(id="c1", email="javier@suarez.ventures",
                           unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="someone@other.com",
                           unsubscribed=False, created_at=None),
    ]
    pro = subs._parse_clerk_user(_clerk_user("javier@suarez.ventures", plan="pro"))
    recipients = subs.join_recipients(
        contacts=contacts,
        clerk_users=[pro],
        only_emails={"javier@suarez.ventures"},
    )
    assert len(recipients) == 1


def test_join_dedupes_duplicate_contacts():
    """Duplicate Resend contacts collapse to one Pro recipient."""
    contacts = [
        subs.ResendContact(id="c1", email="dup@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="dup@pulpo.club", unsubscribed=False, created_at=None),
    ]
    pro = subs._parse_clerk_user(_clerk_user("dup@pulpo.club", plan="pro"))
    assert len(subs.join_recipients(contacts=contacts, clerk_users=[pro])) == 1


def test_join_drops_free_tier_clerk_users():
    """PR-NL-9 audience scope: Free-tier Clerk users (signed up but
    haven't upgraded) are dropped — they belong to a different product."""
    contacts = [
        subs.ResendContact(id="c1", email="free@pulpo.club",
                           unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="pro@pulpo.club",
                           unsubscribed=False, created_at=None),
    ]
    clerk_users = [
        subs._parse_clerk_user(_clerk_user("free@pulpo.club", plan="free")),
        subs._parse_clerk_user(_clerk_user("pro@pulpo.club", plan="pro")),
    ]
    recipients = subs.join_recipients(contacts=contacts, clerk_users=clerk_users)
    assert len(recipients) == 1
    assert recipients[0].tier == "pro"


def test_join_drops_anonymous_resend_only_contacts():
    """PR-NL-9 audience scope: contacts in Resend with no Clerk record
    (anonymous email-only signups) are dropped — they used to receive a
    fallback variant; that variant is gone."""
    contacts = [
        subs.ResendContact(id="c1", email="anon@example.com",
                           unsubscribed=False, created_at=None),
    ]
    recipients = subs.join_recipients(contacts=contacts, clerk_users=[])
    assert recipients == []


def test_join_keeps_agency_tier():
    """Agency tier is also part of the Pro audience."""
    contacts = [
        subs.ResendContact(id="c1", email="agency@pulpo.club",
                           unsubscribed=False, created_at=None),
    ]
    agency = subs._parse_clerk_user(_clerk_user("agency@pulpo.club", plan="agency"))
    recipients = subs.join_recipients(contacts=contacts, clerk_users=[agency])
    assert len(recipients) == 1
    assert recipients[0].tier == "agency"


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


def test_synthesize_preview_recipients_yields_pro_prefs_only():
    """PR-NL-9 audience scope: the preview is the Pro-with-prefs
    variant only. The earlier anonymous + free_prefs variants are gone
    because Free / anonymous users don't receive this newsletter."""
    from automation.newsletter.build_issue import detect_cohort

    queue = subs.synthesize_preview_recipients("Preview@Pulpo.Club")
    assert len(queue) == 1
    recipient, email = queue[0]
    assert email == "preview@pulpo.club"           # normalized
    assert detect_cohort(recipient) == "pro_prefs"
    assert recipient.tier == "pro"
    assert recipient.has_account is True
    # Preference is wide enough to find picks but narrow enough to
    # exercise the "filter applied" branch.
    assert recipient.preference.departments == ["La Libertad"]


def test_synthesize_preview_recipients_rejects_bad_email():
    import pytest
    with pytest.raises(ValueError):
        subs.synthesize_preview_recipients("not-an-email")
    with pytest.raises(ValueError):
        subs.synthesize_preview_recipients("   ")


def test_synthesize_preview_recipients_honours_locale():
    """Admin widget passes the operator-selected locale through so the
    EN/ES toggle actually renders the matching language."""
    import pytest

    en_queue = subs.synthesize_preview_recipients("preview@pulpo.club")
    assert en_queue[0][0].locale == "en"

    es_queue = subs.synthesize_preview_recipients(
        "preview@pulpo.club", locale="es"
    )
    assert es_queue[0][0].locale == "es"

    with pytest.raises(ValueError):
        subs.synthesize_preview_recipients("preview@pulpo.club", locale="fr")


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


def test_resend_locale_sidechannel_still_parses_for_audience():
    """PR-NL-9 audience scope: anonymous Resend contacts no longer flow
    through to recipients, but the locale side-channel parser stays
    relevant — when a Pro user's Clerk record is missing a locale, we
    used to fall through to the Resend first_name. Keep the parser
    test in place to guard the parser itself; the join-time behaviour
    is now exercised in test_join_drops_anonymous_resend_only_contacts."""
    contacts = [
        subs.ResendContact(id="c1", email="anon-es@example.com",
                           unsubscribed=False, created_at=None, locale="es"),
        subs.ResendContact(id="c2", email="anon-en@example.com",
                           unsubscribed=False, created_at=None, locale="en"),
        subs.ResendContact(id="c3", email="anon-legacy@example.com",
                           unsubscribed=False, created_at=None),
    ]
    # No Clerk users → all three are dropped (anonymous-only contacts
    # have no Pro account).
    assert subs.join_recipients(contacts=contacts, clerk_users=[]) == []
