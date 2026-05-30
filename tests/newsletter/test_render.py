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
    # v4: per-pick locked CTA was dropped — the paywall banner one row up
    # carries the price-anchored upsell instead. The banner's CTA text
    # comes from `paywall.cta` ("Go Pro — $9.99/month →") and links to
    # the same Stripe checkout endpoint.
    assert "Go Pro — $9.99/month →" in html
    assert "stripe/start-checkout" in html


def test_render_anonymous_has_welcome_cta(anonymous, ranked_pool):
    html = _render(anonymous, ranked_pool)
    assert "/welcome?r=" in html
    assert anonymous.email_hash in html
    # No named greeting
    assert "Hand-picked for " not in html
    # v3.1 (2026-05-29): cadence flipped to weekly across all hero copy.
    assert "Hand-picked this week" in html or "The 10 best, this week" in html


def test_render_es_locale_has_no_english_canary(pro_with_prefs, ranked_pool):
    pro_with_prefs.locale = "es"
    html = _render(pro_with_prefs, ranked_pool)
    leaked = [c for c in ENGLISH_CANARIES if c in html]
    assert not leaked, f"English canaries leaked into ES render: {leaked}"
    # v3.2 (2026-05-29): the Spanish lede now opens with the beach+lake
    # scope ("propiedades activas de playa y lago en El Salvador") and
    # spells out the issue shape ("perfil completo: foto, nuestra
    # lectura"). Anchor on either as a positive signal the ES render
    # emitted the v3.2 lede and not a fallback.
    assert (
        "playa y lago" in html
        or "perfil completo" in html
        or "lecturas rápidas" in html
    ), "Spanish v3.2 lede phrases all missing from ES render"

    # v3.3.2 (2026-05-30) — Salvadoran voseo. The audience is Salvadoran;
    # every imperative or 2nd-person-singular present in editorial copy
    # uses VOS, not TÚ. Castilian/Mexican tú-forms ("Ajusta", "Continúa",
    # "Recibes", "Sigues", "Lee los", "Hazte", "Trae", "Úsalo") are
    # banned. Possessives ("tu filtro") stay — "tu" works for vos and tú.
    # Each entry below is a tú-form the renderer was caught emitting
    # before this rule landed; add new entries when more leak.
    TU_FORMS_FORBIDDEN = (
        "Ajusta filtros",
        "Ajusta lo que ves",
        "Configura tu filtro",
        "Continúa donde",
        "Hazte Pro",
        "Recibes esto",
        "Sigues ",          # "Sigues 3 propiedades"
        "Abre tus favoritos",
        "Lee los resúmenes",
        "Trae presupuesto",
        "Úsalo como ancla",
        "tú añades",
        "la traes de",
    )
    tu_leaked = [t for t in TU_FORMS_FORBIDDEN if t in html]
    assert not tu_leaked, (
        f"Castilian/Mexican tú-forms leaked into Salvadoran ES render: {tu_leaked}. "
        "Use voseo: Ajustá / Configurá / Seguí / Hacete / Recibís / Seguís / "
        "Abrí / Leé / Traé / Usalo / vos le ponés / la traés."
    )


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
    section-intro blocks cover the rest. v4 (2026-05-30) ALSO dropped
    the "Skip this one" editorial block — it was deemed noise in the
    redesign review. The remaining content is in the locked card grid
    plus the editorial Weekly News Spotlight."""
    html = _render(pro_with_prefs, ranked_pool)
    assert "At a glance" not in html
    assert 'class="glance"' not in html
    # v4 — the skip-block is gone for good.
    assert "Skip this one" not in html
    assert 'class="eyebrow clay"' not in html  # skip-block's clay eyebrow


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


def test_render_v4_redesign_contract(pro_with_prefs, ranked_pool):
    """v4 renderer contract — what the 2026-05-30 redesign locks in:

      1. ONE locked card component (`_pick_card_html`) renders every
         pick (top 3 and 4-10 alike). Only background color + rank
         pill copy differ. No more rich/short split.
      2. Section intros sit above each pick block: "Top 3 this week"
         and "{N} more this week".
      3. Market context renders BEFORE the first pick and carries the
         Surf City 1/2 decoder line.
      4. The "Weekly News Spotlight" block (deterministic fallback
         in v4, LLM-curated in PR-news) replaces the v3 skip + next-
         issue blocks.
      5. Why-bullets card still present on every non-paywalled pick.
    """
    html = _render(pro_with_prefs, ranked_pool)
    # Fix #1 — every pick renders via `.pick-card` (the locked component).
    assert 'class="pick-card"' in html
    # Fix #2 — section intros land.
    assert "Top 3 this week" in html
    # When the shortlist is non-empty (it is for a Pro-with-prefs
    # fixture) the "{n} more this week" intro renders too.
    assert "more this week" in html
    # Fix #3 — market context with decoder line.
    assert "Market context" in html
    assert "Surf City 1" in html and "Surf City 2" in html
    # Fix #4 — Weekly News Spotlight is rendered, skip+next-issue gone.
    assert "Weekly News Spotlight" in html
    assert "Skip this one" not in html
    assert "Next issue" not in html
    # Fix #5 — why-block still present.
    assert 'class="why-block"' in html
    assert "Why we picked it" in html
    # Composition guard: market context must precede the first pick card.
    market_idx = html.find("Market context")
    card_idx = html.find('class="pick-card"')
    assert market_idx != -1 and card_idx != -1
    assert market_idx < card_idx, "market context must render before the first pick card"
    # Frame table count guard — v4 redesign drops v3's `.yp-table`
    # (dark panel rewritten as 3 stacked cream action cards). Only the
    # outer frame survives as a `class`-selectable visible table; every
    # other table is `role="presentation"` for email-safe layout.
    assert html.count('<table class="frame"') == 1
    assert 'class="yp-table"' not in html  # v3 dark panel gone


def test_render_card_component_contract(pro_with_prefs, ranked_pool):
    """v4 locked card component contract — same CTA pair on every pick,
    pulpo.club routing, no source-brokerage CTAs, paired filled+ghost
    buttons.
    """
    import re
    html = _render(pro_with_prefs, ranked_pool)
    # v3 keytable grid gone — v4 dropped the meta-row strip too. The
    # locked card now carries: photo + pill row + title + spec strip +
    # price + why card + filled/ghost CTAs.
    assert '<table class="keytable"' not in html
    # v4 callout/blurb/meta-row stripes are gone — the card body is
    # photo → title → spec → price → why → CTAs only.
    assert "border-left: 3px solid var(--clay)" not in html
    # CTAs route to pulpo.club, never to source brokerage.
    assert "pulpo.club/listing/" in html
    assert not re.search(r"View on [a-z0-9.-]+\.[a-z]{2,}", html), (
        "v4 keeps pulpo.club as the canonical CTA target — no source-domain CTAs."
    )
    # Every non-paywalled pick renders the dual CTA pair.
    assert "See on Pulpo →" in html
    assert "Save to favorites" in html
