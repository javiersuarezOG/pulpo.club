"""Free general (free-tier weekly) render contract.

The free weekly is the Pro General master with `variant="free_general"`:
three free-cohort changes, all gated on the variant so the Pro path is
untouched. These tests pin each change against real build output and
guard the "no other brand / no smoke" rules.

Cross-checked by:
  • test_templates.py — registry alignment + version-string shape.
  • test_render.py — the Pro path still wears the PRO badge + "See on
    Pulpo" on all 10.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from automation.newsletter import build_issue, render_html
from automation.newsletter.templates import TEMPLATES
from automation.newsletter.types import NewsSpotlight

ISSUE_DATE = datetime(2026, 6, 7, 14, 0, tzinfo=timezone.utc)


def _free_issue(recipient, pool):
    return build_issue(
        recipient=recipient,
        ranked_listings=pool,
        issue_number=2,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )


def test_free_general_masthead_drops_pro_badge(free_with_prefs, ranked_pool):
    """Rule 1: a free email never wears Pro chrome — the gold PRO badge
    is gone from BOTH the header and footer masthead."""
    issue = _free_issue(free_with_prefs, ranked_pool)
    html = render_html(issue, variant="free_general")
    assert ">PRO</span>" not in html
    # The plain wordmark is still there.
    assert ">pulpo</span>" in html


def test_free_general_ctas_top3_vs_rest(free_with_prefs, ranked_pool):
    """Top 3 keep the listing link ("See on Pulpo"); ranks 04-10 swap to
    the sign-up ask ("Sign up to Pro"). Every card stays a FULL listing
    card (why-block present) — the value gate is the CTA, not hidden
    content. The old "Pulpo Pro reveals…" paywall teaser must NOT appear.
    """
    issue = _free_issue(free_with_prefs, ranked_pool)
    html = render_html(issue, variant="free_general")

    assert html.count("See on Pulpo →") == len(issue.picks_top)
    assert html.count("Sign up to Pro →") == len(issue.picks_shortlist)
    # All 10 cards render the full listing component (why-block each).
    expected_cards = len(issue.picks_top) + len(issue.picks_shortlist)
    assert html.count('class="why-block"') == expected_cards
    # The free shortlist is built paywalled=True, but free render shows it
    # full — so the locked teaser blurb must be absent.
    assert "Pulpo Pro reveals the address" not in html
    # Save (ghost) button appears on the top 3 ONLY — the ranks 04-10
    # sign-up cards drop it (no "save before sign-up" dead end, and it
    # keeps the longer sign-up CTA from overflowing 320px in ES).
    assert html.count("&hearts;&#xfe0e; Save") == len(issue.picks_top)


def test_free_general_has_no_paywall_banner(free_with_prefs, ranked_pool):
    """The mid-email 'Free edition / Pro goes deeper' banner is suppressed
    in the free weekly — the per-card 'Sign up to Pro' CTAs + the locked
    spotlight carry the upgrade ask. (The build still sets
    paywall_banner=True for the cohort; the free_general variant just
    doesn't render the block.)"""
    issue = _free_issue(free_with_prefs, ranked_pool)
    assert issue.paywall_banner is True              # build flag unchanged
    html = render_html(issue, variant="free_general")
    assert '<div class="paywall-banner">' not in html
    assert "Pro goes deeper on every pick" not in html


def test_free_general_version_stamp(free_with_prefs, ranked_pool):
    issue = _free_issue(free_with_prefs, ranked_pool)
    html = render_html(issue, variant="free_general")
    assert 'name="x-pulpo-template" content="free-general-v1.0' in html


def test_free_general_spotlight_is_pro_locked_real_data(free_with_prefs, ranked_pool):
    """The Weekly News Spotlight is Pro-locked: the REAL headline + source
    (from the committed artifact, here the conftest fixture) show, and the
    sign-up panel wraps it. No fabricated article-specific analysis."""
    issue = _free_issue(free_with_prefs, ranked_pool)
    html = render_html(issue, variant="free_general")

    # Real artifact data is shown — no smoke.
    assert "New coastal road reaches El Zonte" in html   # fixture headline
    assert "La Prensa Gráfica" in html                   # fixture source
    # The lock wrapper + sign-up CTA.
    assert "Pro analysis" in html
    assert "Get the analysis with Pro" in html


def test_free_general_spotlight_withholds_the_tail(free_with_prefs, ranked_pool):
    """With a multi-sentence article, only the opening sentence shows; the
    rest of the read is withheld behind the lock."""
    issue = _free_issue(free_with_prefs, ranked_pool)
    issue.news_spotlight = NewsSpotlight(
        title="A flag hotel lands on the coast",
        paragraph="First sentence is the visible tease. Second sentence is the withheld read.",
        source_name="El Diario de Hoy",
        source_url="https://eldiariodehoy.test/article",
        source_date="5 Jun 2026",
    )
    html = render_html(issue, variant="free_general")
    assert "First sentence is the visible tease." in html
    assert "Second sentence is the withheld read" not in html


def test_free_general_renders_through_registry(free_with_prefs, ranked_pool):
    """The tool routes templates via the TEMPLATES registry — the free
    weekly must produce the same output through that path."""
    issue = _free_issue(free_with_prefs, ranked_pool)
    via_registry = TEMPLATES["pulpo-free-general"](issue)
    via_variant = render_html(issue, variant="free_general")
    assert via_registry == via_variant


def test_free_general_es_no_english_cta_leak(free_with_prefs, ranked_pool):
    """Spanish render: the free CTAs localize and no English canary leaks."""
    es_recipient = replace(free_with_prefs, locale="es")
    issue = _free_issue(es_recipient, ranked_pool)
    html = render_html(issue, variant="free_general")
    assert "Regístrate en Pro →" in html
    assert "Sign up to Pro" not in html
    assert "Pro analysis" not in html         # locked label localizes
    assert "Análisis Pro" in html
