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
