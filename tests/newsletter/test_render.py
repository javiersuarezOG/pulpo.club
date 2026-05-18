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
    "Open the file",
    "Top pick · ",
    "Hand-picked",
    "Skip this one",
    "Adjust your filters",
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
    assert "Unlock with Pulpo Pro" not in html  # no locked CTAs for Pro
    assert "Open the file →" in html
    assert "Hand-picked for Javier" in html


def test_render_free_prefs_shows_paywall(free_with_prefs, ranked_pool):
    html = _render(free_with_prefs, ranked_pool)
    assert '<div class="paywall-banner">' in html
    assert "Unlock with Pulpo Pro" in html
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
    # And the Spanish hero copy is there
    assert "Pulpo revisó" in html


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


def test_render_glance_includes_skip_row(pro_with_prefs, ranked_pool):
    html = _render(pro_with_prefs, ranked_pool)
    # At-a-glance section exists
    assert "At a glance" in html
    # Skip block uses the muted '×' marker
    assert ">×<" in html or ">×</td>" in html


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
