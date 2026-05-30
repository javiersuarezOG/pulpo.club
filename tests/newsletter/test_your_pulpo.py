"""PR-NL-8 — Your Pulpo block + filter humanizer + Clerk saves count."""

from __future__ import annotations

from datetime import datetime, timezone

from automation.newsletter.build_issue import _filter_summary_human, build_issue
from automation.newsletter.subscribers import _parse_clerk_user
from automation.newsletter.types import Preference, Recipient, YourPulpoState
from automation.newsletter.store import email_hash


ISSUE_DATE = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)


# ── filter humanizer ──────────────────────────────────────────────────

def test_filter_summary_full_combo_en():
    pref = Preference(
        departments=["La Libertad"],
        property_types=["land"],
        max_price_usd=500000,
    )
    s = _filter_summary_human(pref, "en", cohort="pro_prefs")
    assert s == "La Libertad · land · under $500k"


def test_filter_summary_full_combo_es():
    pref = Preference(
        departments=["La Libertad"],
        property_types=["land"],
        max_price_usd=500000,
    )
    s = _filter_summary_human(pref, "es", cohort="pro_prefs")
    assert "La Libertad" in s
    assert "terreno" in s
    assert "menos de $500k" in s


def test_filter_summary_zone_only_when_no_department():
    """Zones expand only when no department is set — they'd otherwise
    repeat what the department row already conveys."""
    pref = Preference(zones=["el-zonte"], categories=["beachfront"])
    s = _filter_summary_human(pref, "en", cohort="pro_prefs")
    assert "El Zonte" in s
    assert "Beachfront" in s


def test_filter_summary_price_compact_format():
    """The mockup uses '$500k' / '$1M', not '$500,000' or '$1,000,000'."""
    pref_500 = Preference(max_price_usd=500000)
    assert "$500k" in _filter_summary_human(pref_500, "en", cohort="free_prefs")
    pref_1m = Preference(max_price_usd=1_000_000)
    assert "$1M" in _filter_summary_human(pref_1m, "en", cohort="free_prefs")
    pref_750 = Preference(max_price_usd=750)
    assert "$750" in _filter_summary_human(pref_750, "en", cohort="free_prefs")


def test_filter_summary_anonymous_returns_empty():
    """Anonymous cohorts don't have a filter yet — the renderer swaps in
    welcome copy when this is empty."""
    pref = Preference(departments=["La Libertad"])
    assert _filter_summary_human(pref, "en", cohort="anonymous") == ""


def test_filter_summary_empty_pref():
    assert _filter_summary_human(Preference(), "en", cohort="logged_no_prefs") == ""


# ── Clerk saves_count parsing ────────────────────────────────────────

def test_clerk_user_parses_saves_count_from_private_metadata():
    """The saves array lives in privateMetadata per api/saves.js."""
    raw = {
        "id": "user_x",
        "email_addresses": [{"id": "e1", "email_address": "a@b.c"}],
        "primary_email_address_id": "e1",
        "public_metadata": {"plan": "pro"},
        "private_metadata": {"saves": ["id1", "id2", "id3"]},
    }
    user = _parse_clerk_user(raw)
    assert user is not None
    assert user.saved_count == 3


def test_clerk_user_missing_private_metadata_defaults_zero():
    """Anonymous-of-Clerk and old accounts without saves degrade to 0."""
    raw = {
        "id": "user_x",
        "email_addresses": [{"id": "e1", "email_address": "a@b.c"}],
        "primary_email_address_id": "e1",
        "public_metadata": {"plan": "free"},
    }
    user = _parse_clerk_user(raw)
    assert user is not None
    assert user.saved_count == 0


def test_clerk_user_wrong_shaped_saves_defaults_zero():
    """Defensive — if some pipeline writes saves as a non-list, we don't
    crash the audience send."""
    raw = {
        "id": "user_x",
        "email_addresses": [{"id": "e1", "email_address": "a@b.c"}],
        "primary_email_address_id": "e1",
        "private_metadata": {"saves": "not-a-list"},
    }
    user = _parse_clerk_user(raw)
    assert user is not None
    assert user.saved_count == 0


# ── build_issue plumbs Your Pulpo state ──────────────────────────────

def test_build_issue_populates_your_pulpo(pro_with_prefs, ranked_pool):
    """The hero blocks need the YourPulpoState filled in for the renderer."""
    # Bump saved_count on the recipient — it's the new PR-NL-8 field.
    pro_with_prefs.saved_count = 4
    issue = build_issue(
        recipient=pro_with_prefs, ranked_listings=ranked_pool,
        issue_number=8, issue_date=ISSUE_DATE,
    )
    yp = issue.your_pulpo
    assert isinstance(yp, YourPulpoState)
    assert yp.saved_count == 4
    assert yp.filter_match_count > 0           # ranked_pool has matching La Libertad land
    assert "La Libertad" in yp.filter_summary_human


def test_build_issue_your_pulpo_anonymous_softened():
    """Anonymous cohort: no saves count, no filter summary, but a
    filter_match_count of the whole pool (so the 'Browse all' row still
    has something to say)."""
    anon = Recipient(
        email_hash=email_hash("anon@example.com"),
        display_name=None, locale="en", tier="free", has_account=False,
        preference=Preference(),
    )
    from tests.newsletter.conftest import _listing
    pool = [_listing(rank=i + 1) for i in range(15)]
    issue = build_issue(
        recipient=anon, ranked_listings=pool,
        issue_number=8, issue_date=ISSUE_DATE,
    )
    yp = issue.your_pulpo
    assert yp.saved_count == 0
    assert yp.filter_summary_human == ""
    assert yp.filter_match_count == len(pool)


# ── render contract ──────────────────────────────────────────────────

def test_renderer_emits_your_pulpo_panel(pro_with_prefs, ranked_pool):
    """The dark panel renders with all three URL targets and the
    `?ref=newsletter_issue_NN` attribution param."""
    from automation.newsletter import render_html
    pro_with_prefs.saved_count = 2
    issue = build_issue(
        recipient=pro_with_prefs, ranked_listings=ranked_pool,
        issue_number=8, issue_date=ISSUE_DATE,
    )
    html = render_html(issue)
    # v4: dark `.yp-panel` table was replaced with 3 stacked cream
    # action cards. Anchor on stable markers — title class + URLs.
    assert 'class="yp-title"' in html
    # Three URLs present + carry the ref param
    assert "/saved?ref=newsletter_issue_08" in html
    assert "/account/newsletter?ref=newsletter_issue_08" in html
    assert "/browse?ref=newsletter_issue_08" in html
    # Eyebrow + title rendered
    assert "Your Pulpo" in html
    # Filter summary shown
    assert "La Libertad" in html


def test_renderer_skips_saved_row_when_zero():
    """0-saved recipients shouldn't see a misleading '0 saved listings'
    row — the renderer drops the row entirely."""
    from automation.newsletter import render_html
    from tests.newsletter.conftest import _listing
    r = Recipient(
        email_hash=email_hash("new@example.com"),
        display_name=None, locale="en", tier="free", has_account=True,
        preference=Preference(departments=["La Libertad"]),
        saved_count=0,
    )
    pool = [_listing(rank=i + 1) for i in range(15)]
    issue = build_issue(
        recipient=r, ranked_listings=pool,
        issue_number=8, issue_date=ISSUE_DATE,
    )
    html = render_html(issue)
    # 0-saved row gone; the saved CTA shouldn't appear at all
    assert "Open your favorites" not in html
    # But the browse row IS still there
    assert "/browse?ref=" in html
