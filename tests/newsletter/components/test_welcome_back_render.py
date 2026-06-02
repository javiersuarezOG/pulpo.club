"""Snapshot guards for the Pulpo Pro Welcome-back (resubscribe) render.

Locks the shape of the resubscribe re-acquisition email so a future
renderer edit can't silently drift it. Mirrors the assertion style of
`test_welcome_render.py`: not byte-for-byte HTML diffing (too brittle),
but per-named-block copy presence, the right cadence variant, locale
coverage, and the blocks welcome-back explicitly drops vs. the
first-time welcome.

Companion to `tests/newsletter/components/test_welcome_render.py`
(first-time welcome) and `tests/newsletter/test_templates.py`
(registry-alignment CI guard).
"""

from __future__ import annotations

from datetime import datetime, timezone

from automation.newsletter import build_issue
from automation.newsletter.render_html import render_welcome_back_html
from automation.newsletter.templates import TEMPLATES, pulpo_pro_welcome_back


def _issue(*, ranked, recipient):
    """Build an Issue for the welcome-back path. issue_number=1 by the
    same convention as the first-time welcome (own telemetry namespace)."""
    return build_issue(
        recipient=recipient,
        ranked_listings=ranked,
        issue_number=1,
        issue_date=datetime(2026, 6, 2, 16, 0, 0, tzinfo=timezone.utc),
        history_rows=None,
    )


def test_template_registry_exposes_welcome_back():
    """The pro-welcome-back template id MUST round-trip through the
    registry, not just exist as a module."""
    assert "pulpo-pro-welcome-back" in TEMPLATES
    assert TEMPLATES["pulpo-pro-welcome-back"] is pulpo_pro_welcome_back.render


def test_welcome_back_render_en_includes_named_blocks(ranked_pool, pro_with_prefs):
    """The welcome-back's editorial top: re-entry hero, cadence note,
    "Your fresh 10" intro, and the "Pick up where you left off"
    re-engagement cards. Each must surface in the EN render."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_back_html(issue)
    # Re-entry hero
    assert "Welcome back to Pulpo Pro" in html
    assert "Good to have you back, Javier." in html      # first-name personalization
    assert "Your Pulpo Pro access is live again" in html
    # Salvadoran grounding (surf strip + lakes by name); never "volcanic"
    assert "El Tunco to El Cuco, Coatepeque, Ilopango" in html
    assert "volcanic" not in html.lower()
    # Picks section intro (resubscribe framing)
    assert "Your next 10." in html
    # Re-engagement cards (saved first)
    assert "Pick up where you left off" in html
    assert "Your saved listings" in html
    assert "Open saved" in html
    assert "Browse all listings" in html
    assert "Open your account" in html
    # Saved card links to /saved (the strongest re-engagement hook)
    assert "/saved?ref=newsletter_pro_welcome_back" in html


def test_welcome_back_render_es_uses_spanish_copy(ranked_pool, pro_with_prefs):
    """ES locale must localize the entire welcome-back surface. Canary
    English strings must NOT appear when locale='es'."""
    es_recipient = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "locale": "es"}
    )
    issue = _issue(ranked=ranked_pool, recipient=es_recipient)
    html = render_welcome_back_html(issue)
    assert "Bienvenido de nuevo a Pulpo Pro" in html
    assert "Qué bueno tenerte de vuelta, Javier." in html
    assert "Tu acceso a Pulpo Pro está activo otra vez" in html
    assert "Tus próximas 10." in html
    assert "Acá tenés las diez mejores" in html        # Salvadoran voseo
    assert "volcánico" not in html.lower()
    assert "Retomá donde lo dejaste" in html
    assert "Abrir guardadas" in html
    # Canary check — bare English block titles must NOT leak through.
    assert "Welcome back to Pulpo Pro" not in html
    assert "Your next 10." not in html
    assert "Pick up where you left off" not in html


def test_welcome_back_drops_first_time_onboarding_blocks(ranked_pool, pro_with_prefs):
    """Welcome-back explicitly drops the first-time welcome's tutorial +
    onboarding steps — the returning reader already knows the ropes. A
    regression where those leak back in surfaces here."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_back_html(issue)
    # "How Pulpo works" tutorial — dropped
    assert "How Pulpo works" not in html
    assert "We scan every supplier" not in html
    # First-time "Start here" 3-step onboarding — dropped
    assert "Start here" not in html
    assert "Step 1 · Tune what you see" not in html
    # First-time hero/intro copy — must NOT appear
    assert "Welcome to Pulpo Pro" not in html             # first-time eyebrow
    assert "Your first 10 picks." not in html


def test_welcome_back_cadence_same_day_variant(ranked_pool, pro_with_prefs):
    """Welcome-back reuses the shared cadence note. Sunday before 10:00
    SV → same-day variant (2026-05-31 14:00 UTC == 08:00 SV)."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    sunday_before_send = datetime(2026, 5, 31, 14, 0, 0, tzinfo=timezone.utc)
    html = render_welcome_back_html(issue, now=sunday_before_send)
    assert "lands today at 10 AM SV" in html
    assert "Sunday, June 7" not in html


def test_welcome_back_cadence_future_variant(ranked_pool, pro_with_prefs):
    """Mid-week `now` → cadence note names the upcoming Sunday. 2026-06-01
    (Mon) → next Sunday 2026-06-07."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    monday = datetime(2026, 6, 1, 18, 0, 0, tzinfo=timezone.utc)
    html = render_welcome_back_html(issue, now=monday)
    assert "Sunday, June 7" in html
    assert "lands today at 10 AM SV" not in html


def test_welcome_back_falls_back_when_display_name_missing(ranked_pool, pro_with_prefs):
    """No first name on Clerk → 'Good to have you back.' fallback. Never
    render 'Good to have you back, .' or '…, None.'."""
    anon = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "display_name": None}
    )
    issue = _issue(ranked=ranked_pool, recipient=anon)
    html = render_welcome_back_html(issue)
    assert "Good to have you back." in html
    assert "Good to have you back, ." not in html
    assert "Good to have you back, None" not in html


def test_welcome_back_subject_localized():
    """Subject must localize. The dispatcher reads this i18n key before
    handing off to send_issue for the welcome-back variant."""
    from automation.newsletter import i18n
    assert i18n.t("welcome_back.email.subject", "en") == "Welcome back to Pulpo Pro — your next 10"
    assert i18n.t("welcome_back.email.subject", "es") == "Bienvenido de nuevo a Pulpo Pro — tus próximas 10"


def test_welcome_back_meta_tag_uses_welcome_back_version_constant(ranked_pool, pro_with_prefs):
    """The welcome-back's `<meta name="x-pulpo-template">` must carry the
    welcome-back-specific version, NOT the General's or the first-time
    welcome's. This is the discriminator PostHog uses to slice
    re-acquisition renders from first-time welcomes and weeklies."""
    from automation.newsletter.components._common import (
        TEMPLATE_VERSION as GENERAL_VERSION,
        WELCOME_TEMPLATE_VERSION,
        WELCOME_BACK_TEMPLATE_VERSION,
    )
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_back_html(issue)
    assert f'<meta name="x-pulpo-template" content="{WELCOME_BACK_TEMPLATE_VERSION}"' in html, (
        f"welcome-back render should stamp WELCOME_BACK_TEMPLATE_VERSION "
        f"({WELCOME_BACK_TEMPLATE_VERSION!r}) into the x-pulpo-template meta tag"
    )
    # Neither the General nor the first-time welcome version may leak in.
    assert f'content="{GENERAL_VERSION}"' not in html
    assert f'content="{WELCOME_TEMPLATE_VERSION}"' not in html
