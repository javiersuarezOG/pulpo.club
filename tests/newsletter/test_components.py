"""Per-component visual lock — asserts the markers from the v4 design
contract are present in each component's rendered output.

These tests pin the locked design at the component boundary. If a
component module silently changes its output (someone refactors the
function body, swaps a class name, drops the Pulpo brand mark, etc.),
the matching test fails red and the operator + reviewer see exactly
which component drifted.

These are NOT exhaustive snapshot tests — they assert the
load-bearing visual markers that the operator + Sebas would notice
on every send. If you change a marker on purpose, update the test in
the same PR + bump the `TEMPLATE_VERSION` in `_common.py`.
"""

from __future__ import annotations

import importlib

import pytest


def test_components_package_is_importable_and_exposes_modules():
    """The top-level package init lists every component module — IDE
    autocomplete and future templates rely on the list being complete.
    Each module must also be importable on its own."""
    components = importlib.import_module("automation.newsletter.components")
    expected = {"_common", "brand", "editorial", "favorites", "hero", "paywall", "personal", "picks"}
    assert set(components.__all__) == expected, (
        f"components.__all__ drifted: {set(components.__all__) ^ expected}"
    )
    for name in expected:
        importlib.import_module(f"automation.newsletter.components.{name}")


def test_common_exports_template_version_and_css():
    from automation.newsletter.components import _common
    assert isinstance(_common.TEMPLATE_VERSION, str)
    assert _common.TEMPLATE_VERSION.startswith("newsletter-v"), (
        f"TEMPLATE_VERSION drifted from the 'newsletter-v…' convention: "
        f"{_common.TEMPLATE_VERSION!r}"
    )
    # CSS block has the v4 sage color + the forest brand token.
    assert "#DDE9DC" in _common.CSS  # sage — top-deal card background
    assert "#1F3D31" in _common.CSS  # forest — brand primary


def test_common_exports_last_updated():
    """LAST_UPDATED is surfaced in component docs + admin so collaborators
    can see the template's revision timestamp at a glance."""
    from automation.newsletter.components import _common
    assert isinstance(_common.LAST_UPDATED, str)
    # ISO yyyy-mm-dd; cheap regex guard so a typo doesn't ship.
    import re
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", _common.LAST_UPDATED), (
        f"LAST_UPDATED should be ISO yyyy-mm-dd, got {_common.LAST_UPDATED!r}"
    )


def test_picks_exposes_pick_card_and_section_intros():
    from automation.newsletter.components import picks
    expected = {
        "pick_card_html",
        "section_intro_top3_html",
        "section_intro_rest_html",
        "why_block_html",
        "state_pill_html",
        "pick_state_pill_html",
        "pick_ppm_from_keytable",
    }
    assert expected.issubset(set(picks.__all__))


def test_favorites_exposes_block_and_card_helpers():
    from automation.newsletter.components import favorites
    assert {"favorites_html", "favorite_card_html", "favorites_editorial_summary"}.issubset(
        set(favorites.__all__)
    )


def test_editorial_exposes_market_and_spotlight():
    from automation.newsletter.components import editorial
    assert {"market_html", "weekly_news_spotlight_html", "hydrate_pick_urls"}.issubset(
        set(editorial.__all__)
    )


def test_personal_exposes_your_pulpo():
    from automation.newsletter.components import personal
    assert "your_pulpo_html" in personal.__all__


def test_paywall_exposes_banner():
    from automation.newsletter.components import paywall
    assert "paywall_banner_html" in paywall.__all__


def test_brand_exposes_footer():
    from automation.newsletter.components import brand
    assert "footer_html" in brand.__all__


def test_hero_exposes_filter_chips():
    from automation.newsletter.components import hero
    assert "filter_chips_html" in hero.__all__


@pytest.fixture
def rendered_pro_general_html(pro_with_prefs, ranked_pool):
    """Render the Pulpo Pro General template once for marker assertions."""
    from datetime import datetime, timezone
    from automation.newsletter import build_issue
    from automation.newsletter.templates import TEMPLATES
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=99,
        issue_date=datetime(2026, 5, 31, 14, 0, tzinfo=timezone.utc),
        history_rows=[],
    )
    return TEMPLATES["pulpo-pro-general"](issue)


def test_pro_general_template_in_registry():
    from automation.newsletter.templates import TEMPLATES
    assert "pulpo-pro-general" in TEMPLATES
    assert callable(TEMPLATES["pulpo-pro-general"])


def test_pro_general_renders_hidden_preheader(rendered_pro_general_html):
    """The inbox-preview snippet must come from a hidden div at the
    top of the body — not the visible header chrome. Asserts both
    the hide-styling and that the preheader text references real
    content (top pick + remaining count), so a stale operator render
    won't ship the generic fallback."""
    html = rendered_pro_general_html
    assert "mso-hide:all" in html
    assert "display:none" in html
    # Real-content tease, not generic boilerplate. Pool fixture has
    # 30 listings under the Pro filter so there's always picks_top[0]
    # + at least one shortlist pick.
    assert "more picks this week" in html
    # The generic fallback should NOT render when picks_top is populated.
    assert "10 hand-picked listings from El Salvador" not in html
    # Cadence guard: never reintroduce the fortnight/quincena copy now
    # that we ship weekly.
    assert "fortnight" not in html
    assert "quincena" not in html


def test_pro_general_footer_carries_postal_address(rendered_pro_general_html):
    """CAN-SPAM § 5(a)(5) requires every commercial email to include the
    sender's physical postal address. Today's minimum is the city +
    country line; refine when a registered street address exists."""
    html = rendered_pro_general_html
    assert "San Salvador, El Salvador" in html


def test_pro_general_renders_locked_v4_markers(rendered_pro_general_html):
    html = rendered_pro_general_html
    # Pro branding (the gold pill next to the wordmark)
    assert ">PRO<" in html
    # Locked card component
    assert 'class="pick-card"' in html
    assert "Top deal · 01" in html
    # v4 section intros (big serif headers)
    assert "Top 3 this week" in html
    assert "more this week" in html
    # Market context numbered editorial blocks (numeral hex 32px serif)
    assert "Surf City 1" in html and "Surf City 2" in html
    # Weekly News Spotlight + Pulpo Pro self-attribution
    assert "Weekly News Spotlight" in html
    assert "Pulpo Pro" in html
    # Your Pulpo as 3 stacked cream cards (not the v3 dark panel)
    assert 'class="yp-table"' not in html
    assert "Pick up where you left off" in html
    # Footer pill buttons (border:1px on each action)
    assert "Change filters" in html and "Change cadence" in html and "Unsubscribe" in html
    # Footer copyright says Pulpo Pro (v4.1)
    assert "Pulpo Pro" in html


def test_pro_general_no_v3_leftovers(rendered_pro_general_html):
    html = rendered_pro_general_html
    # v3 chrome that v4 dropped — these should never resurface
    assert 'class="glance"' not in html
    assert "Skip this one" not in html
    assert 'class="yp-panel"' not in html  # dark navy Your Pulpo
    assert 'class="meta-row"' not in html  # v3 rich-pick meta strip
    assert "Each one suits a different kind of buyer" not in html  # v3 shortlist copy


def test_pro_general_every_pick_card_has_a_real_photo(rendered_pro_general_html):
    """v4.3 operator policy: a listing can only appear if its photo is
    available. The pool is filtered upstream in
    `build_issue._listing_has_eligible_photo`, the renderer's photo
    placeholder branch is dead-removed, so the rendered output must
    contain ONE `<img>` inside every pick-card and zero placeholder
    bands ("Photo not available from source" / "Imagen no disponible
    desde la fuente").
    """
    import re
    html = rendered_pro_general_html
    # No placeholder text in either locale
    assert "Photo not available from source" not in html
    assert "Imagen no disponible desde la fuente" not in html
    # Count pick-cards and the photo <img> inside them. The photo is
    # the first <img> in each card (`<div class="pick-card"...><img ...>`).
    cards = re.findall(
        r'class="pick-card"[\s\S]*?(?=class="pick-card"|</table>)',
        html,
    )
    assert cards, "Rendered HTML had zero pick-cards — unexpected fixture"
    for i, card in enumerate(cards, start=1):
        first_img = re.search(r'<img\s+src="([^"]+)"', card)
        assert first_img, f"Pick card {i:02d} has no <img> tag (photo missing)"
        assert first_img.group(1).startswith("http"), (
            f"Pick card {i:02d} <img> src is not an http(s) URL: "
            f"{first_img.group(1)!r}"
        )


def test_listing_without_photo_is_filtered_before_render():
    """Belt-and-suspenders for the upstream filter — drop in a synthetic
    listing where every photo-eligibility check fails and assert it
    never makes it to the rendered output.
    """
    from datetime import datetime, timezone
    from automation.newsletter import build_issue
    from automation.newsletter.types import Preference, Recipient
    from automation.newsletter.store import email_hash
    from tests.newsletter.conftest import _listing

    pool = [_listing(rank=i + 1) for i in range(15)]
    # The first listing fails the card-eligible gate.
    pool[0]["card_eligible"] = False
    pool[0]["title"] = "BROKER-LOGO-ONLY · SHOULD NEVER RENDER"

    recipient = Recipient(
        email_hash=email_hash("test@example.com"),
        display_name="Test",
        locale="en",
        tier="pro",
        has_account=True,
        preference=Preference(),
    )
    issue = build_issue(
        recipient=recipient,
        ranked_listings=pool,
        issue_number=1,
        issue_date=datetime(2026, 5, 31, 14, 0, tzinfo=timezone.utc),
        history_rows=[],
    )
    # The synthetic ineligible listing's title must not show up anywhere
    # in the picks tuple (top, shortlist, skip).
    all_titles = (
        [p.title for p in issue.picks_top]
        + [p.title for p in issue.picks_shortlist]
        + ([issue.skip_pick.title] if issue.skip_pick else [])
    )
    assert "BROKER-LOGO-ONLY · SHOULD NEVER RENDER" not in all_titles
