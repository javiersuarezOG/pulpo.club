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


# ── free_only audience (free weekly) ──────────────────────────────────────
def test_free_only_includes_free_and_anon_excludes_pro():
    """The free-tier audience is the inverse of the default: free Clerk
    users + anonymous contacts are IN, Pro/Agency are OUT."""
    contacts = [
        subs.ResendContact(id="c1", email="free@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="pro@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c3", email="anon@example.com", unsubscribed=False, created_at=None),
    ]
    clerk_users = [
        subs._parse_clerk_user(_clerk_user("free@pulpo.club", plan="free")),
        subs._parse_clerk_user(_clerk_user("pro@pulpo.club", plan="pro")),
    ]
    recipients = subs.join_recipients(contacts=contacts, clerk_users=clerk_users, free_only=True)
    tiers = sorted(r.tier for r in recipients)
    emails = {r.email_hash for r in recipients}
    assert tiers == ["free", "free"]                          # free Clerk + anon (synth free)
    assert subs.email_hash("pro@pulpo.club") not in emails    # Pro excluded
    assert subs.email_hash("anon@example.com") in emails      # anon included
    assert subs.email_hash("free@pulpo.club") in emails


def test_default_audience_still_pro_only():
    """Regression guard: with neither flag, the Pro/Agency gate holds."""
    contacts = [
        subs.ResendContact(id="c1", email="free@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="pro@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c3", email="anon@example.com", unsubscribed=False, created_at=None),
    ]
    clerk_users = [
        subs._parse_clerk_user(_clerk_user("free@pulpo.club", plan="free")),
        subs._parse_clerk_user(_clerk_user("pro@pulpo.club", plan="pro")),
    ]
    recipients = subs.join_recipients(contacts=contacts, clerk_users=clerk_users)
    assert len(recipients) == 1
    assert recipients[0].tier == "pro"


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


# ── allow_non_pro escape hatch (launch sends) ────────────────────────────


def test_allow_non_pro_keeps_anonymous_and_free():
    """The launch escape hatch lets anonymous + free contacts through.
    Anonymous synthesises a Recipient with has_account=False; free
    Clerk users keep their actual tier + Clerk profile."""
    contacts = [
        subs.ResendContact(id="c1", email="anon@example.com",
                           unsubscribed=False, created_at=None, locale="es"),
        subs.ResendContact(id="c2", email="free@pulpo.club",
                           unsubscribed=False, created_at=None),
        subs.ResendContact(id="c3", email="pro@pulpo.club",
                           unsubscribed=False, created_at=None),
    ]
    clerk_users = [
        subs._parse_clerk_user(_clerk_user("free@pulpo.club", plan="free")),
        subs._parse_clerk_user(_clerk_user("pro@pulpo.club", plan="pro")),
    ]
    recipients = subs.join_recipients(
        contacts=contacts, clerk_users=clerk_users, allow_non_pro=True,
    )
    # All three contacts land in the queue.
    assert len(recipients) == 3
    tiers = sorted(r.tier for r in recipients)
    assert tiers == ["free", "free", "pro"]
    # Anonymous recipient (no Clerk match) has has_account=False and
    # picked up the Resend-side-channel locale.
    anon = next(r for r in recipients if not r.has_account)
    assert anon.locale == "es"
    assert anon.saved_count == 0
    assert anon.saves == []
    assert anon.preference_source == "none"


def test_allow_non_pro_off_by_default_keeps_existing_gate():
    """Regression guard: PR-NL-9 audience scope still in force when
    allow_non_pro is not explicitly set. Free + anonymous dropped."""
    contacts = [
        subs.ResendContact(id="c1", email="anon@example.com",
                           unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="free@pulpo.club",
                           unsubscribed=False, created_at=None),
        subs.ResendContact(id="c3", email="pro@pulpo.club",
                           unsubscribed=False, created_at=None),
    ]
    clerk_users = [
        subs._parse_clerk_user(_clerk_user("free@pulpo.club", plan="free")),
        subs._parse_clerk_user(_clerk_user("pro@pulpo.club", plan="pro")),
    ]
    recipients = subs.join_recipients(contacts=contacts, clerk_users=clerk_users)
    assert len(recipients) == 1
    assert recipients[0].tier == "pro"


def test_allow_non_pro_still_respects_unsubscribed_flag():
    """The launch escape hatch widens the tier gate, NOT the
    unsubscribed gate. An unsubscribed contact still must not receive."""
    contacts = [
        subs.ResendContact(id="c1", email="anon@example.com",
                           unsubscribed=True, created_at=None),
        subs.ResendContact(id="c2", email="anon2@example.com",
                           unsubscribed=False, created_at=None),
    ]
    recipients = subs.join_recipients(
        contacts=contacts, clerk_users=[], allow_non_pro=True,
    )
    assert len(recipients) == 1
    # The non-unsubscribed one made it through; the unsubscribed one
    # did not.
    assert recipients[0].email_hash != subs.email_hash("anon@example.com")


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


# ── P3 — DiscoverFilter → Preference translation ─────────────────────
# The Discover panel (web/app/pages.jsx) writes its filter state to
# publicMetadata.profile.discover_filters via the P2a-2 hook. The cron
# now consumes that blob first and falls back to the legacy `newsletter`
# blob (P1-era shape) when the user hasn't migrated yet.

def test_preference_from_discover_filters_empty():
    """Empty / non-dict input → empty Preference (cohort fallback in
    build_issue then picks the broad cut)."""
    assert subs._preference_from_discover_filters({}) == Preference()
    assert subs._preference_from_discover_filters(None) == Preference()  # type: ignore[arg-type]


def test_preference_from_discover_filters_full_translation():
    """Every axis with a defined mapping translates; departments stays
    empty (Discover panel uses zones, not departments)."""
    pref = subs._preference_from_discover_filters({
        "zones": ["el-tunco", "el-zonte"],
        "subcategory": "land",
        "price_min": 50_000,
        "price_max": 500_000,
        "features": ["beachfront", "water_body", "ocean_view"],
        "discovery_tags": ["under_250k", "top_rated"],
        # Axes that get dropped (Discover-only browsing controls):
        "land_types": ["residential"],
        "infra": ["water", "power"],
        "status": ["new"],
        "size_min": 1000,
        "readiness": 3,
        "rank_max": 10,
        "master_category": "beach",
    })
    assert pref.zones == ["el-tunco", "el-zonte"]
    assert pref.departments == []
    assert pref.property_types == ["land"]
    assert pref.max_price_usd == 500_000
    assert pref.min_price_usd == 50_000
    # categories preserves insertion order: features first, then tags,
    # deduped. ocean_view + top_rated are dropped (no cron mapping).
    assert pref.categories == ["beachfront", "water_features", "under_250k"]


def test_preference_from_discover_filters_subcategory_homes_and_condos():
    """homes → house, condos → condo (cron's vocabulary uses singular)."""
    assert subs._preference_from_discover_filters({"subcategory": "homes"}).property_types == ["house"]
    assert subs._preference_from_discover_filters({"subcategory": "condos"}).property_types == ["condo"]
    assert subs._preference_from_discover_filters({"subcategory": "land"}).property_types == ["land"]
    # Bogus value gracefully drops.
    assert subs._preference_from_discover_filters({"subcategory": "yurts"}).property_types == []


def test_preference_from_discover_filters_waterfront_aliases_to_beachfront():
    """The Discover 'waterfront' pill is the broad beachfront/water-body
    bucket; cron's 'beachfront' category captures it."""
    pref = subs._preference_from_discover_filters({"discovery_tags": ["waterfront"]})
    assert pref.categories == ["beachfront"]


def test_preference_from_discover_filters_dedupes_overlapping_inputs():
    """features + discovery_tags can both surface 'beachfront' — dedupe
    so the cron's category predicate doesn't run twice."""
    pref = subs._preference_from_discover_filters({
        "features": ["beachfront"],
        "discovery_tags": ["waterfront"],
    })
    assert pref.categories == ["beachfront"]


def test_preference_from_discover_filters_drops_zero_price_min():
    """price_min == 0 is the default state — don't surface it as a real
    minimum (apply_preference would reject every $0 listing, but the
    intent is 'no opinion')."""
    pref = subs._preference_from_discover_filters({"price_min": 0, "price_max": 500_000})
    assert pref.min_price_usd is None
    assert pref.max_price_usd == 500_000


def test_preference_from_profile_prefers_discover_filters_over_newsletter():
    """When both blobs are present, discover_filters wins — the user
    moved to the unified UI and we should trust that signal."""
    pref = subs._preference_from_profile({
        "discover_filters": {
            "zones": ["el-zonte"],
            "subcategory": "land",
            "price_max": 250_000,
        },
        "newsletter": {
            # Legacy values that would lose if both blobs landed.
            "departments": ["La Paz"],
            "property_types": ["house"],
            "max_price_usd": 500_000,
        },
    })
    assert pref.zones == ["el-zonte"]
    assert pref.departments == []
    assert pref.property_types == ["land"]
    assert pref.max_price_usd == 250_000


def test_preference_from_profile_falls_back_to_newsletter_when_discover_empty():
    """Users who haven't touched the new UI still have only the legacy
    newsletter blob — the cron must keep delivering until P3 dashboards
    confirm migration."""
    pref = subs._preference_from_profile({
        "newsletter": {
            "departments": ["La Libertad"],
            "property_types": ["land"],
            "max_price_usd": 500_000,
        },
        # Empty {} dict for discover_filters is treated as "user has not
        # interacted" and falls through to the legacy blob.
        "discover_filters": {},
    })
    assert pref.departments == ["La Libertad"]
    assert pref.property_types == ["land"]
    assert pref.max_price_usd == 500_000


def test_preference_from_profile_empty_when_neither_blob_present():
    """No Clerk profile data at all → empty Preference; cohort fallback
    in build_issue picks the broad cut."""
    assert subs._preference_from_profile({}) == Preference()
    assert subs._preference_from_profile({"something_unrelated": 1}) == Preference()


# ── P3-cleanup telemetry: preference_source ──────────────────────────
# Stamped onto every Recipient so `newsletter.issue_built` can carry
# it on the PostHog event — that's how we'll know when it's safe to
# drop the legacy newsletter-blob fallback in _preference_from_profile.

def test_preference_source_discover_filters_wins_when_present():
    assert subs._preference_source_from_profile({
        "discover_filters": {"zones": ["el-tunco"]},
        "newsletter": {"departments": ["La Libertad"]},
    }) == "discover_filters"


def test_preference_source_newsletter_when_only_legacy_blob():
    assert subs._preference_source_from_profile({
        "newsletter": {"departments": ["La Libertad"]},
    }) == "newsletter"


def test_preference_source_none_when_empty_or_missing_blobs():
    assert subs._preference_source_from_profile({}) == "none"
    assert subs._preference_source_from_profile({"discover_filters": {}}) == "none"
    assert subs._preference_source_from_profile({
        "discover_filters": {},
        "newsletter": {},
    }) == "none"


def test_preference_source_stays_in_lockstep_with_preference_from_profile():
    """Belt-and-suspenders: if the source helper ever diverges from the
    precedence logic in _preference_from_profile, the telemetry would
    silently lie about which blob the cron actually consumed."""
    cases = [
        {},
        {"discover_filters": {"zones": ["el-tunco"]}},
        {"newsletter": {"departments": ["La Libertad"]}},
        {"discover_filters": {}, "newsletter": {"departments": ["La Paz"]}},
        {"discover_filters": {"subcategory": "land"}, "newsletter": {"departments": ["La Paz"]}},
    ]
    for profile in cases:
        source = subs._preference_source_from_profile(profile)
        pref = subs._preference_from_profile(profile)
        if source == "none":
            assert pref == Preference(), f"source=none but pref non-empty for {profile!r}"
        elif source == "discover_filters":
            # `departments` is always empty when discover_filters drives
            # the read (Discover panel uses zones, not departments).
            assert pref.departments == [], f"source=discover but departments={pref.departments} for {profile!r}"
        elif source == "newsletter":
            assert pref.departments == [x for x in profile.get("newsletter", {}).get("departments", []) if isinstance(x, str)]
        else:
            raise AssertionError(f"unknown source {source!r}")


def test_join_recipients_stamps_preference_source_per_user():
    """End-to-end: join_recipients reads each user's Clerk profile and
    sets preference_source on the Recipient."""
    contacts = [
        subs.ResendContact(id="c1", email="discover@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="legacy@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c3", email="empty@pulpo.club", unsubscribed=False, created_at=None),
    ]
    pros = [
        subs._parse_clerk_user(_clerk_user(
            "discover@pulpo.club", plan="pro",
            profile={"discover_filters": {"zones": ["el-tunco"]}},
        )),
        subs._parse_clerk_user(_clerk_user(
            "legacy@pulpo.club", plan="pro",
            profile={"newsletter": {"departments": ["La Libertad"]}},
        )),
        subs._parse_clerk_user(_clerk_user(
            "empty@pulpo.club", plan="pro",
            profile={},
        )),
    ]
    recipients = subs.join_recipients(contacts=contacts, clerk_users=pros)
    by_hash = {r.email_hash: r for r in recipients}
    assert by_hash[subs.email_hash("discover@pulpo.club")].preference_source == "discover_filters"
    assert by_hash[subs.email_hash("legacy@pulpo.club")].preference_source == "newsletter"
    assert by_hash[subs.email_hash("empty@pulpo.club")].preference_source == "none"


# ── Pro Welcome — 24h weekly-skip filter ──────────────────────────────
# Locked 2026-06-01: a Pro recipient whose welcome shipped in the past
# 24h is dropped from the weekly queue to avoid back-to-back welcome +
# weekly with the same 10 picks. Stamp lives on
# publicMetadata.welcome_newsletter_sent_at (ISO-8601 UTC).

def _clerk_user_with_welcome(email, *, welcome_sent_at):
    return {
        "id": f"user_{email.split('@')[0]}",
        "first_name": None,
        "email_addresses": [{"id": "ea_1", "email_address": email}],
        "primary_email_address_id": "ea_1",
        "public_metadata": {
            "plan": "pro",
            "profile": {},
            "welcome_newsletter_sent_at": welcome_sent_at,
        },
    }


def test_welcome_within_24h_helper_handles_recent_stamp():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 6, 1, 16, 0, 0, tzinfo=timezone.utc)
    # 6h ago — within window
    recent = (now - timedelta(hours=6)).isoformat()
    assert subs._welcome_within_24h(recent, now=now) is True
    # 30h ago — outside window
    stale = (now - timedelta(hours=30)).isoformat()
    assert subs._welcome_within_24h(stale, now=now) is False
    # 23h59m ago — just barely inside
    edge = (now - timedelta(hours=23, minutes=59)).isoformat()
    assert subs._welcome_within_24h(edge, now=now) is True


def test_welcome_within_24h_helper_handles_z_suffix_and_garbage():
    from datetime import datetime, timezone
    now = datetime(2026, 6, 1, 16, 0, 0, tzinfo=timezone.utc)
    # `Z` suffix is the spec-compliant UTC marker; we tolerate it.
    assert subs._welcome_within_24h("2026-06-01T10:00:00Z", now=now) is True
    # Garbage strings degrade to False (don't crash the weekly send
    # over an upstream metadata format change).
    assert subs._welcome_within_24h("not-a-date", now=now) is False
    assert subs._welcome_within_24h("", now=now) is False
    assert subs._welcome_within_24h(None, now=now) is False


def test_parse_clerk_user_reads_welcome_sent_at():
    """ClerkUser.welcome_sent_at carries the publicMetadata stamp.
    Tolerates both snake_case + camelCase; empty/missing → None."""
    user = subs._parse_clerk_user(
        _clerk_user_with_welcome("javi@pulpo.club", welcome_sent_at="2026-05-31T10:00:00Z")
    )
    assert user.welcome_sent_at == "2026-05-31T10:00:00Z"

    no_stamp = subs._parse_clerk_user(_clerk_user("javi@pulpo.club", plan="pro"))
    assert no_stamp.welcome_sent_at is None


def test_join_recipients_drops_user_with_recent_welcome(monkeypatch):
    """Pro user whose welcome shipped 6h ago must NOT land in the
    weekly queue. Without this filter the user gets two emails with
    the same 10 picks on a same-day collision."""
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 6, 1, 16, 0, 0, tzinfo=timezone.utc)
    recent_stamp = (now - timedelta(hours=6)).isoformat()
    # Patch the helper's wall-clock so the test is deterministic.
    monkeypatch.setattr(
        subs, "_welcome_within_24h",
        lambda iso, now=None: subs._welcome_within_24h.__wrapped__(iso, now=now) if hasattr(subs._welcome_within_24h, "__wrapped__") else (iso is not None and "2026-06-01" in (iso or "")),
    )
    # Simpler: just verify the integration via the date constants.
    contacts = [
        subs.ResendContact(id="c1", email="recent@pulpo.club", unsubscribed=False, created_at=None),
        subs.ResendContact(id="c2", email="old@pulpo.club", unsubscribed=False, created_at=None),
    ]
    users = [
        subs._parse_clerk_user(
            _clerk_user_with_welcome("recent@pulpo.club", welcome_sent_at=recent_stamp)
        ),
        subs._parse_clerk_user(
            _clerk_user_with_welcome("old@pulpo.club", welcome_sent_at="2025-01-01T10:00:00Z")
        ),
    ]
    # Reset the monkeypatch — we want the real helper now.
    monkeypatch.undo()
    # We can't easily inject `now=` into join_recipients, so use a
    # `welcome_sent_at` that's guaranteed-recent (just now).
    fresh = datetime.now(timezone.utc).isoformat()
    users[0] = subs._parse_clerk_user(
        _clerk_user_with_welcome("recent@pulpo.club", welcome_sent_at=fresh)
    )
    recipients = subs.join_recipients(contacts=contacts, clerk_users=users)
    emails_in_queue = {r.email_hash for r in recipients}
    assert subs.email_hash("recent@pulpo.club") not in emails_in_queue
    assert subs.email_hash("old@pulpo.club") in emails_in_queue


def test_allow_all_subscribers_bypasses_welcome_skip():
    """Operator launch broadcasts use --allow-all-subscribers to bypass
    gates wholesale. The welcome 24h skip MUST be bypassed too — the
    operator is deliberately overriding cohort filters."""
    from datetime import datetime, timezone
    fresh = datetime.now(timezone.utc).isoformat()
    contacts = [
        subs.ResendContact(id="c1", email="recent@pulpo.club", unsubscribed=False, created_at=None),
    ]
    users = [
        subs._parse_clerk_user(
            _clerk_user_with_welcome("recent@pulpo.club", welcome_sent_at=fresh)
        ),
    ]
    recipients = subs.join_recipients(
        contacts=contacts, clerk_users=users, allow_non_pro=True
    )
    # With allow_non_pro=True (the --allow-all-subscribers flag), the
    # recent-welcome recipient should still be in the queue.
    assert len(recipients) == 1
    assert recipients[0].email_hash == subs.email_hash("recent@pulpo.club")
