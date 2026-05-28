"""Cohort + build_issue contract tests."""

from __future__ import annotations

from datetime import datetime, timezone

from automation.newsletter.build_issue import (
    build_issue,
    detect_cohort,
    fallback_preference,
)
from automation.newsletter.types import Preference


ISSUE_DATE = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)


def test_cohort_detection_anon(anonymous):
    assert detect_cohort(anonymous) == "anonymous"


def test_cohort_detection_pro_with_prefs(pro_with_prefs):
    assert detect_cohort(pro_with_prefs) == "pro_prefs"


def test_cohort_detection_free_with_prefs(free_with_prefs):
    assert detect_cohort(free_with_prefs) == "free_prefs"


def test_cohort_detection_logged_no_prefs(logged_no_prefs):
    assert detect_cohort(logged_no_prefs) == "logged_no_prefs"


def test_fallback_preference_picks_top_quartile_department(ranked_pool):
    pref = fallback_preference(ranked_pool)
    # The fixture's top-10 (ranks 1-10) are all in La Libertad / el-zonte.
    # fallback_preference anchors on the dominant department in the top quartile.
    assert pref.departments == ["La Libertad"]


def test_pro_with_prefs_uses_recipient_preference(pro_with_prefs, ranked_pool):
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    # La Libertad + land → never any La Paz listings
    all_picks = list(issue.picks_top) + list(issue.picks_shortlist)
    # All picks should be in La Libertad zones; the fixture's La Libertad pool
    # has 10 land listings priced under $500k, so we get 10 total.
    assert len(all_picks) == 10
    assert issue.paywall_banner is False  # Pro tier never sees the banner


def test_free_with_prefs_paywalls_after_pick_one(free_with_prefs, ranked_pool):
    issue = build_issue(
        recipient=free_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.paywall_banner is True
    # First top pick stays unlocked; everything else is paywalled
    assert issue.picks_top[0].paywalled is False
    if len(issue.picks_top) > 1:
        assert issue.picks_top[1].paywalled is True
    for p in issue.picks_shortlist:
        assert p.paywalled is True


def test_logged_no_prefs_uses_fallback_and_includes_chips(logged_no_prefs, ranked_pool):
    issue = build_issue(
        recipient=logged_no_prefs,
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.cohort == "logged_no_prefs"
    assert issue.welcome_prefs_url is None     # only anon gets the welcome link
    # No prefs in commentary chips means we still rendered the issue without
    # crashing; chips can be empty.
    assert isinstance(issue.commentary.filter_chips, list)


def test_anonymous_carries_welcome_url(anonymous, ranked_pool):
    issue = build_issue(
        recipient=anonymous,
        ranked_listings=ranked_pool,
        issue_number=2,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.cohort == "anonymous"
    assert issue.welcome_prefs_url is not None
    assert anonymous.email_hash in issue.welcome_prefs_url
    assert "newsletter_issue_2" in issue.welcome_prefs_url


def test_tight_filter_tops_up_from_fallback(make_listing):
    """When the user filter starves the cut, build_issue tops up from a
    broader pool so we never ship a near-empty issue."""
    pool = [make_listing(rank=i + 1, zone="costa-del-sol", department="La Paz")
            for i in range(20)]
    # Add one el-zonte listing that matches the recipient's tight filter
    pool.append(make_listing(rank=21, zone="el-zonte", department="La Libertad"))
    from automation.newsletter.types import Recipient
    from automation.newsletter.store import email_hash
    rec = Recipient(
        email_hash=email_hash("starve@test.local"),
        display_name="Test",
        locale="en",
        tier="pro",
        has_account=True,
        preference=Preference(zones=["el-zonte"]),
    )
    issue = build_issue(
        recipient=rec,
        ranked_listings=pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    all_picks = list(issue.picks_top) + list(issue.picks_shortlist)
    # Without top-up there's only 1 listing; with top-up we should get >= 6.
    assert len(all_picks) >= 6


def test_locale_propagates_through_commentary(pro_with_prefs, ranked_pool):
    pro_with_prefs.locale = "es"
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.locale == "es"
    # Lede should be the Spanish version
    assert "Pulpo revisó" in issue.commentary.lede_hero


def test_repriced_listing_can_repeat(make_listing, pro_with_prefs):
    """Verifies the 'price moved' exception to the 90-day exclusion."""
    repriced = make_listing(rank=1, is_repriced=True, source_id="REPEAT")
    pool = [repriced] + [make_listing(rank=i + 2) for i in range(15)]
    # Simulate the recipient having seen this very listing recently
    from automation.newsletter.store import HistoryRow
    hist = [HistoryRow(
        recipient_hash=pro_with_prefs.email_hash,
        issue_id="2026-05-04",
        sent_at="2026-05-04T14:00:00+00:00",
        cohort="pro_prefs",
        source_ids=["remax:REPEAT"],
    )]
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=pool,
        issue_number=2,
        issue_date=ISSUE_DATE,
        history_rows=hist,
    )
    all_sids = [p.source_id for p in (list(issue.picks_top) + list(issue.picks_shortlist))]
    assert "remax:REPEAT" in all_sids


# ── PR-NL-5 ── chip generator + canonical Pulpo URLs ─────────────────
#
# These tests cover the new fields on IssuePick (`chips`, `pulpo_url`,
# `save_url`) added in PR-NL-5. The chip generator is a pure function of
# the listing dict — no recipient, no history — so we can exercise it
# directly without building a full Issue.

def test_pulpo_urls_canonical_form():
    """The /listing/<source>:<source_id> URL pattern matches what vercel.json
    rewrites and what the SPA expects. The `?save=1` variant carries the
    same path plus the save hint for PR-NL-8."""
    from automation.newsletter.build_issue import _pulpo_urls
    listing = {"source": "remax", "source_id": "001461165132"}
    see_url, save_url = _pulpo_urls(listing, issue_number=5, site_root="https://pulpo.club")
    assert see_url == "https://pulpo.club/listing/remax:001461165132?ref=newsletter_issue_5"
    assert save_url == see_url + "&save=1"


def test_chips_warm_price_drop():
    """A repriced listing with previous_price set should produce a warm
    'Just dropped' chip — leading dollar amount for small drops, percent
    for large drops."""
    from automation.newsletter.build_issue import _chips_for_listing
    small_drop = {
        "is_repriced": True, "previous_price": 155000, "price_usd": 150000,
    }
    chips = _chips_for_listing(small_drop, rank=14, locale="en")
    labels = [c.label for c in chips]
    assert any("Just dropped −$5,000" in lbl for lbl in labels)
    assert chips[0].kind == "warm"  # warm always leads

    large_drop = {
        "is_repriced": True, "previous_price": 200000, "price_usd": 140000,
    }
    chips = _chips_for_listing(large_drop, rank=14, locale="en")
    labels = [c.label for c in chips]
    assert any("Just dropped −30%" in lbl for lbl in labels)


def test_chips_cool_top_pick_below_zone_build_ready():
    """A rank-1 listing 78% below zone with full readiness should
    produce: Top pick + Below area + Build ready (all cool)."""
    from automation.newsletter.build_issue import _chips_for_listing
    listing = {
        "price_vs_zone_pct": -78,
        "readiness_score": 3,
    }
    chips = _chips_for_listing(listing, rank=1, locale="en")
    labels = " | ".join(c.label for c in chips)
    assert "Top pick" in labels
    assert "−78% under area average" in labels
    assert "Build ready" in labels
    # All three should be cool (positive signals)
    assert all(c.kind == "cool" for c in chips[:3])


def test_chips_neutral_walk_to_beach_and_new():
    """Neutral context chips: walk to beach + new this week."""
    from automation.newsletter.build_issue import _chips_for_listing
    listing = {
        "is_walk_to_beach": True,
        "days_listed": 3,
    }
    chips = _chips_for_listing(listing, rank=8, locale="en")
    labels = [c.label for c in chips]
    assert any("Walk to beach" in lbl for lbl in labels)
    assert any("New this week" in lbl for lbl in labels)


def test_chips_capped_at_four():
    """ISSUE_CHIPS_PER_PICK trims the list. Warm > cool > neutral
    priority is preserved by the order chips are appended."""
    from automation.newsletter.build_issue import _chips_for_listing, ISSUE_CHIPS_PER_PICK
    # A listing with every signal at once — should be trimmed.
    listing = {
        "is_repriced": True, "previous_price": 200000, "price_usd": 150000,
        "price_vs_zone_pct": -60,
        "readiness_score": 3,
        "is_walk_to_beach": True,
        "days_listed": 2,
    }
    chips = _chips_for_listing(listing, rank=1, locale="en")
    assert len(chips) == ISSUE_CHIPS_PER_PICK
    # First chip is the warm price drop (highest priority).
    assert chips[0].kind == "warm"


def test_chips_spanish_locale():
    """Chip labels translate to Spanish when locale='es'."""
    from automation.newsletter.build_issue import _chips_for_listing
    listing = {
        "is_repriced": True, "previous_price": 155000, "price_usd": 150000,
        "is_walk_to_beach": True,
    }
    chips = _chips_for_listing(listing, rank=1, locale="es")
    labels = " | ".join(c.label for c in chips)
    assert "Acaba de bajar" in labels
    assert "A pie de la playa" in labels


def test_pick_includes_pulpo_url_and_chips(pro_with_prefs, ranked_pool):
    """Smoke: the IssuePicks coming out of build_issue have pulpo_url +
    save_url + chips populated. Sanity check on the wiring."""
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=5,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    for pick in (list(issue.picks_top) + list(issue.picks_shortlist)):
        assert pick.pulpo_url.startswith("https://pulpo.club/listing/")
        assert "ref=newsletter_issue_5" in pick.pulpo_url
        assert pick.save_url == pick.pulpo_url + "&save=1"
        assert isinstance(pick.chips, list)


def test_top_picks_rich_bumped_to_three():
    """ISSUE_TOP_PICKS_RICH was 2 pre PR-NL-5 — now 3. The hero pick
    layout in v2.4 expects three with big photos before the compact
    shortlist begins."""
    from automation.newsletter.build_issue import ISSUE_TOP_PICKS_RICH
    assert ISSUE_TOP_PICKS_RICH == 3
