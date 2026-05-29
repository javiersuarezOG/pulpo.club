"""HTML render contract.

Per the post-mortem rule in CLAUDE.md: every nullable field must be safe to
render. These tests force the renderer through every cohort and a couple of
data-sparse edge cases.

Spanish-canary check mirrors the spirit of preview-smoke.spec.ts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from automation.newsletter import build_issue, render_html
from automation.newsletter.types import Preference, Recipient
from automation.newsletter.store import email_hash


ISSUE_DATE = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)

ENGLISH_CANARIES = (
    # PR-NL-5 (v2.4): the hero-pick CTAs are "See on Pulpo →" + "Save to
    # favorites". Paywalled picks still use the v2.2 "Unlock this pick"
    # text. None of these should leak into an ES render.
    "See on Pulpo",
    "Save to favorites",
    "Unlock this pick",
    "Top pick · ",
    "Hand-picked",
    "Skip this one",
    "Tune what you see",
    "Unsubscribe",
    "The shortlist",
    "Market context",
)


def _render(recipient: Recipient, pool: list[dict], **kwargs) -> str:
    issue = build_issue(
        recipient=recipient,
        ranked_listings=pool,
        issue_number=kwargs.pop("issue_number", 1),
        issue_date=kwargs.pop("issue_date", ISSUE_DATE),
        history_rows=kwargs.pop("history_rows", []),
    )
    return render_html(issue)


def test_render_pro_prefs_has_no_paywall_banner(pro_with_prefs, ranked_pool):
    html = _render(pro_with_prefs, ranked_pool)
    # The banner element is rendered only when paywall_banner=True. The CSS
    # class is always present in the <style> block; we check the rendered
    # element instead.
    assert '<div class="paywall-banner">' not in html
    assert "Unlock this pick" not in html       # no locked CTAs for Pro
    assert "See on Pulpo →" in html             # PR-NL-5: hero-pick solid CTA
    assert "Save to favorites" in html          # PR-NL-5: hero-pick ghost CTA
    assert "Hand-picked for Javier" in html


def test_render_free_prefs_shows_paywall(free_with_prefs, ranked_pool):
    html = _render(free_with_prefs, ranked_pool)
    assert '<div class="paywall-banner">' in html
    # v2.2: paywalled rich-pick CTA carries the price anchor
    assert "Unlock this pick — $9.99/mo →" in html
    assert "stripe/start-checkout" in html


def test_render_anonymous_has_welcome_cta(anonymous, ranked_pool):
    html = _render(anonymous, ranked_pool)
    assert "/welcome?r=" in html
    assert anonymous.email_hash in html
    # No named greeting
    assert "Hand-picked for " not in html
    assert "Hand-picked this fortnight" in html or "The 10 best, this fortnight" in html


def test_render_es_locale_has_no_english_canary(pro_with_prefs, ranked_pool):
    pro_with_prefs.locale = "es"
    html = _render(pro_with_prefs, ranked_pool)
    leaked = [c for c in ENGLISH_CANARIES if c in html]
    assert not leaked, f"English canaries leaked into ES render: {leaked}"
    # And the Spanish hero copy is there. PR-NL-7a moved the lede to
    # the welcome teaser ("Empieza por #01 — …"); anchor on that phrase.
    assert "Empieza por" in html


def test_render_no_unfilled_placeholders(pro_with_prefs, ranked_pool):
    html = _render(pro_with_prefs, ranked_pool)
    # An unfilled str.format placeholder would show up as '{name}' or similar.
    unfilled = re.findall(r"\{(?:name|n_scanned|filter_summary|kept|rank|n|pct|km|min|beds|baths)\}", html)
    assert not unfilled, f"unfilled placeholders: {unfilled}"


def test_render_handles_listing_with_null_fields(make_listing, pro_with_prefs):
    """Renderer survives a pool where every nullable field is null."""
    sparse = make_listing(rank=1)
    sparse.update({
        "price_usd": None,
        "price_per_m2": None,
        "price_vs_zone_pct": None,
        "dist_beach_km": None,
        "dist_airport_km": None,
        "days_listed": None,
        "short_description_canonical": {},
        "title_canonical": {},
        "reasons_to_buy": [],
        "rank_reasons": [],
        "photo_urls": [],
        "hero_photo_path": "",
        "is_beachfront": False,
        "is_walk_to_beach": False,
        "has_power": False,
        "has_water": False,
        "has_paved_access": False,
    })
    pool = [sparse] + [make_listing(rank=i + 2) for i in range(9)]
    html = _render(pro_with_prefs, pool)
    assert "<title>" in html
    assert "—" in html or "$" in html  # price fallback rendered


def test_render_html_is_well_formed_basic(pro_with_prefs, ranked_pool):
    html = _render(pro_with_prefs, ranked_pool)
    # Balanced top-level structure
    assert html.count("<html") == 1 and html.count("</html>") == 1
    assert html.count("<body") == 1 and html.count("</body>") == 1
    # The CSS shouldn't have stray closing braces leaking from a templating bug
    assert "}}" not in html
    # No empty href / src
    assert 'href=""' not in html
    assert 'src=""' not in html


def test_render_issue_header_carries_issue_number(pro_with_prefs, ranked_pool):
    html = _render(pro_with_prefs, ranked_pool, issue_number=7)
    assert "ISSUE 07" in html


def test_render_v3_drops_at_a_glance_table(pro_with_prefs, ranked_pool):
    """v3 dropped the `<table class="glance">` numbered list.

    The welcome teaser already names #01-#03 inline; the per-pick + the
    shortlist sections cover the rest. The table was the most visible
    `<table>` left in the document and the user called out "no tables"
    in the 2026-05-29 review of the v2.8 send. The "Skip this one"
    block survives as its own editorial section."""
    html = _render(pro_with_prefs, ranked_pool)
    assert "At a glance" not in html
    assert 'class="glance"' not in html
    # Skip block lives outside the (gone) glance table — survives as its
    # own editorial section.
    assert "Skip this one" in html


def test_render_keytable_does_not_double_up_keys(pro_with_prefs, ranked_pool):
    html = _render(pro_with_prefs, ranked_pool)
    # The keytable wraps every two rows into one <tr>. The "Beach" key shouldn't
    # appear more than once per pick (we only render up to 6 rows total).
    assert html.count(">Beach<") <= 3  # 2 rich picks + a skip with location_line, generous bound


def test_render_smoke_all_cohorts(pro_with_prefs, free_with_prefs, logged_no_prefs, anonymous, ranked_pool):
    for r in (pro_with_prefs, free_with_prefs, logged_no_prefs, anonymous):
        html = _render(r, ranked_pool)
        assert "</html>" in html
        # Always carries a working unsubscribe link
        assert "/unsubscribe?r=" in html


def test_render_carries_template_version_meta(pro_with_prefs, ranked_pool):
    """Every rendered issue carries the TEMPLATE_VERSION in a <meta> tag so
    PostHog telemetry can be cross-referenced against the source HTML when
    debugging a regression. Bump TEMPLATE_VERSION in lockstep with
    docs/newsletter-audit.md when CSS or layout changes meaningfully."""
    from automation.newsletter.render_html import TEMPLATE_VERSION
    html = _render(pro_with_prefs, ranked_pool)
    assert TEMPLATE_VERSION  # non-empty
    assert TEMPLATE_VERSION.startswith("newsletter-v"), (
        f"TEMPLATE_VERSION drifted: {TEMPLATE_VERSION!r}"
    )
    assert f'<meta name="x-pulpo-template" content="{TEMPLATE_VERSION}"' in html


def test_render_v3_redesign_contract(pro_with_prefs, ranked_pool):
    """v3 renderer contract — the 5 fixes from Sebas's 2026-05-29 review:

      1. Layout flows top-to-bottom, nothing collapses or expands
         (smoke: every section's heading is present on a single render).
      2. No `<table>` elements past the outer email frame and the
         opt-in dark "Your Pulpo" rows. The v2.x `<table class="glance">`
         and the inner shortlist tables are gone.
      3. Each hero pick renders a "Why we picked it" `<ul>` driven by
         the why_bullets generator instead of the v2 "Why Pulpo ranked
         it: value 100 · momentum 50" callout.
      4. Shortlist copy is the simpler "Each one suits a different
         kind of buyer" — the v2 "Read the frame first; skip if it
         isn't yours" copy is banned.
      5. Market context renders BEFORE the first hero pick (the warm
         "buyer's fortnight" framing the v2 send buried at the bottom).
    """
    html = _render(pro_with_prefs, ranked_pool)
    # Fix #2 — only the outer frame `<table>` and the `yp-table`
    # survive. Both have specific class hooks so we can count exactly.
    assert html.count('class="glance"') == 0
    assert html.count('<table class="frame"') == 1
    assert html.count('<table class="yp-table"') == 1
    # Fix #3 — at least one hero pick rendered a why-block (data is
    # rich enough to surface bullets).
    assert 'class="why-block"' in html
    assert "Why we picked it" in html
    assert "Why Pulpo ranked it" not in html  # v2 callout label is gone
    # Fix #4 — new copy in, old copy out.
    assert "Each one suits a different kind of buyer" in html
    assert "Read the frame first" not in html
    # Fix #5 — market-context HTML appears before the first hero pick.
    market_idx = html.find("Market context")
    pick_idx = html.find('class="pill pill-forest"')  # "TOP PICK · 01" pill
    if market_idx != -1 and pick_idx != -1:
        assert market_idx < pick_idx, "market context must render before the first pick"


def test_render_v24_redesign_contract(pro_with_prefs, ranked_pool):
    """v2.4 renderer contract — the four visible changes that PR-NL-5
    locked in, plus the two that survived from v2.2:

    From v2.2 (still true):
      • Keytable grid replaced by the meta-row strip
      • Callout left-bar stripe is gone

    From v2.4 / PR-NL-5:
      • Per-pick CTAs route to pulpo.club/listing/<id>, NOT the external
        source brokerage URL
      • Hero picks render both a solid "See on Pulpo →" + a ghost
        "Save to favorites" CTA (the dual-CTA pair)
    """
    import re
    html = _render(pro_with_prefs, ranked_pool)
    # From v2.2: keytable HTML element gone, meta-row present
    assert '<table class="keytable"' not in html
    assert 'class="meta-row"' in html
    # From v2.2: callout left-bar stripe + colored panel are gone
    assert "border-left: 3px solid var(--clay)" not in html
    # PR-NL-5: CTAs go to pulpo.club, never to the source brokerage
    assert "pulpo.club/listing/" in html
    assert not re.search(r"View on [a-z0-9.-]+\.[a-z]{2,}", html), (
        "v2.4 dropped the source-domain CTA; pulpo.club is the canonical CTA target now."
    )
    # PR-NL-5: both hero CTAs present
    assert "See on Pulpo →" in html
    assert "Save to favorites" in html
