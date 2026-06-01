"""Snapshot guards for the Pulpo Pro Welcome render.

Locks the shape of the welcome editorial top so a future renderer
edit can't silently drift the onboarding email. These tests do NOT
do byte-for-byte HTML diffing (too brittle against innocuous CSS
tweaks) — they assert that each named block renders WITH key copy
present, the welcome-specific cadence note picks the right variant,
and the layout omits the blocks the welcome explicitly drops vs.
General.

Companion to `tests/newsletter/test_templates.py` (registry-alignment
CI guard) and `tests/newsletter/test_components.py` (per-component
shape tests for the General weekly).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from automation.newsletter import build_issue
from automation.newsletter.render_html import render_welcome_html
from automation.newsletter.templates import TEMPLATES, pulpo_pro_welcome


def _issue(*, locale="en", ranked, recipient):
    """Build an Issue for the welcome path. issue_number=1 by convention
    (the welcome lives in its own telemetry namespace; the weekly's
    auto-increment doesn't apply)."""
    return build_issue(
        recipient=recipient,
        ranked_listings=ranked,
        issue_number=1,
        issue_date=datetime(2026, 6, 1, 16, 0, 0, tzinfo=timezone.utc),
        history_rows=None,
    )


def test_template_registry_exposes_welcome():
    """The pro-welcome template id MUST round-trip through the registry,
    not just exist as a module. Catches a half-merged add where the
    file lands but the dict entry is forgotten."""
    assert "pulpo-pro-welcome" in TEMPLATES
    assert TEMPLATES["pulpo-pro-welcome"] is pulpo_pro_welcome.render


def test_welcome_render_en_includes_named_blocks(ranked_pool, pro_with_prefs):
    """The welcome's editorial top has 4 named blocks (welcome hero,
    how-pulpo-works, cadence note, your-first-10 intro) PLUS the
    onboarding cards at the bottom. Each must surface in the EN render."""
    issue = _issue(locale="en", ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_html(issue)
    # Welcome hero
    assert "Welcome to Pulpo Pro" in html
    assert "Welcome, Javier." in html              # first-name personalization
    assert "Pulpo covers the coast and the volcanic lakes" in html
    # "How Pulpo works" — 3 numbered editorial beats
    assert "How Pulpo works" in html
    assert "We scan every supplier" in html        # step 01
    assert "We rank them on value" in html         # step 02
    assert "You filter and save" in html           # step 03
    # Picks section intro (welcome-specific framing)
    assert "Your first 10 picks." in html
    # Start-here onboarding cards
    assert "Start here" in html
    assert "Set your filter" in html
    assert "Browse all listings" in html
    assert "Open your account" in html


def test_welcome_render_es_uses_spanish_copy(ranked_pool, pro_with_prefs):
    """ES locale must localize the entire welcome surface. Canary
    English strings ('Welcome', 'Browse all listings') must NOT
    appear when locale='es'."""
    es_recipient = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "locale": "es"}
    )
    issue = _issue(locale="es", ranked=ranked_pool, recipient=es_recipient)
    html = render_welcome_html(issue)
    assert "Bienvenido a Pulpo Pro" in html
    assert "Bienvenido, Javier." in html
    assert "Pulpo cubre la costa y los lagos volcánicos" in html
    assert "Cómo funciona Pulpo" in html
    assert "Revisamos a cada proveedor" in html
    assert "Tus primeras 10 selecciones." in html
    assert "Empezá acá" in html
    assert "Configurá tu filtro" in html
    # Canary check — bare English block titles must NOT leak through.
    assert "Welcome to Pulpo Pro" not in html
    assert "How Pulpo works" not in html
    assert "Your first 10 picks." not in html


def test_welcome_drops_general_only_blocks(ranked_pool, pro_with_prefs):
    """The welcome explicitly drops these blocks vs. the General weekly.
    A regression where the General's structure leaks into the welcome
    (because someone reused too many helpers) would surface here."""
    issue = _issue(locale="en", ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_html(issue)
    # Market context (replaced by how-it-works)
    assert "Market context" not in html
    assert "Surf City 1 = the La Libertad coast" not in html
    # Weekly News Spotlight
    assert "Weekly News Spotlight" not in html
    assert "What we're watching on the coast" not in html
    # General "Your Pulpo / Pick up where you left off"
    assert "Pick up where you left off" not in html


def test_welcome_cadence_same_day_variant(ranked_pool, pro_with_prefs):
    """When `now` is a Sunday before 10:00 SV (UTC-6), the cadence
    note uses the same-day variant. UTC reference: 2026-05-31 (Sun)
    at 14:00 UTC == 08:00 SV — should be same-day."""
    issue = _issue(locale="en", ranked=ranked_pool, recipient=pro_with_prefs)
    sunday_before_send = datetime(2026, 5, 31, 14, 0, 0, tzinfo=timezone.utc)
    html = render_welcome_html(issue, now=sunday_before_send)
    assert "lands today at 10 AM SV" in html
    assert "Sunday, June 7" not in html            # future variant must NOT appear


def test_welcome_cadence_future_variant(ranked_pool, pro_with_prefs):
    """When `now` is mid-week (or Sunday after 10:00 SV), the cadence
    note names the upcoming Sunday concretely. 2026-06-01 (Mon) is
    mid-week; next Sunday is 2026-06-07."""
    issue = _issue(locale="en", ranked=ranked_pool, recipient=pro_with_prefs)
    monday = datetime(2026, 6, 1, 18, 0, 0, tzinfo=timezone.utc)
    html = render_welcome_html(issue, now=monday)
    assert "Sunday, June 7" in html
    assert "lands today at 10 AM SV" not in html


def test_welcome_cadence_es_locale(ranked_pool, pro_with_prefs):
    """Cadence date must localize. EN: 'Sunday, June 7'; ES: 'el domingo 7 de junio'."""
    es_recipient = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "locale": "es"}
    )
    issue = _issue(locale="es", ranked=ranked_pool, recipient=es_recipient)
    monday = datetime(2026, 6, 1, 18, 0, 0, tzinfo=timezone.utc)
    html = render_welcome_html(issue, now=monday)
    assert "el domingo 7 de junio" in html
    assert "Sunday, June 7" not in html


def test_welcome_falls_back_when_display_name_missing(ranked_pool, pro_with_prefs):
    """No first name on Clerk → 'Welcome aboard.' fallback. Don't
    render 'Welcome, .' or 'Welcome, None.' under any path."""
    anon = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "display_name": None}
    )
    issue = _issue(locale="en", ranked=ranked_pool, recipient=anon)
    html = render_welcome_html(issue)
    assert "Welcome aboard." in html
    assert "Welcome, ." not in html
    assert "Welcome, None" not in html


def test_welcome_subject_localized():
    """Subject must localize. The dispatcher reads this i18n key
    before handing off to send_issue."""
    from automation.newsletter import i18n
    assert i18n.t("welcome.email.subject", "en") == "Welcome to Pulpo Pro — your first 10"
    assert i18n.t("welcome.email.subject", "es") == "Bienvenido a Pulpo Pro — tus primeras 10"
