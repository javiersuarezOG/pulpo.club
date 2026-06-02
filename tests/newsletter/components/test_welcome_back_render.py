"""Guards for the Pulpo Pro Welcome-back (resubscribe) render.

Two layered guarantees:
  • Welcome-back is the SAME render as the first-time welcome save the
    hero greeting (render_html variant="welcome_back"). The hero copy
    DERIVES from the welcome.* strings via i18n.welcome_text, so the two
    can't drift. test_welcome_back_is_welcome_with_only_hero_swapped
    proves byte-identity after swapping the hero strings + version back.
  • Both are the General master with only the hero swapped — covered by
    test_welcome_render.py's General-parity test.

All three Pulpo emails are Pro emails (no paywall renders).
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape as _e

from automation.newsletter import i18n
from automation.newsletter.components._common import (
    TEMPLATE_VERSION,
    WELCOME_TEMPLATE_VERSION,
    WELCOME_BACK_TEMPLATE_VERSION,
)
from automation.newsletter import build_issue
from automation.newsletter.render_html import (
    render_welcome_html,
    render_welcome_back_html,
)
from automation.newsletter.templates import TEMPLATES, pulpo_pro_welcome_back


def _issue(*, ranked, recipient):
    return build_issue(
        recipient=recipient,
        ranked_listings=ranked,
        issue_number=1,
        issue_date=datetime(2026, 6, 2, 16, 0, 0, tzinfo=timezone.utc),
        history_rows=None,
    )


def test_template_registry_exposes_welcome_back():
    assert "pulpo-pro-welcome-back" in TEMPLATES
    assert TEMPLATES["pulpo-pro-welcome-back"] is pulpo_pro_welcome_back.render


def test_welcome_back_is_welcome_with_only_hero_swapped(ranked_pool, pro_with_prefs):
    """The welcome-back render, with its hero copy + version stamp swapped
    back to the first-time welcome's, must be BYTE-IDENTICAL to the
    welcome. The two share one template + derive copy from one source, so
    the only legal difference is the welcome→welcome-back wording."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    lc = "en"  # pro_with_prefs is en, display_name "Javier"
    welcome = render_welcome_html(issue)
    welcome_back = render_welcome_back_html(issue)

    swaps = [
        (i18n.welcome_text("hero.eyebrow", lc, variant="welcome_back"),
         i18n.t("welcome.hero.eyebrow", lc)),
        (i18n.welcome_text("hero.headline.named", lc, variant="welcome_back", name="Javier"),
         i18n.t("welcome.hero.headline.named", lc, name="Javier")),
        (i18n.welcome_text("hero.lede", lc, variant="welcome_back"),
         i18n.t("welcome.hero.lede", lc)),
        (WELCOME_BACK_TEMPLATE_VERSION, WELCOME_TEMPLATE_VERSION),
    ]
    normalized = welcome_back
    for back, first in swaps:
        normalized = normalized.replace(_e(back), _e(first))
    assert normalized == welcome, (
        "welcome-back diverges from the welcome beyond the hero copy + "
        "version stamp. They share one template (variant) + one copy source "
        "(welcome_text) — a structural edit to only one path broke parity."
    )


def test_welcome_back_hero_says_welcome_back(ranked_pool, pro_with_prefs):
    """The one block that changes: the hero greeting (derived from welcome)."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_back_html(issue)
    assert "Welcome back to Pulpo Pro" in html        # eyebrow + <title>
    assert "Welcome back, Javier." in html            # first-name personalization
    assert "Your next 10 are below" in html           # lede reworded (first → next)
    # The first-time greeting must NOT survive.
    assert "Welcome to Pulpo Pro" not in html
    assert "Welcome, Javier." not in html
    # Brand voice: never "volcanic".
    assert "volcanic" not in html.lower()
    # Shared weekly body present (same as General + welcome).
    assert "Market context" in html
    assert "Weekly News Spotlight" in html


def test_welcome_text_derives_back_copy_from_welcome():
    """The invariant: welcome-back hero/subject copy is a pure function of
    the welcome copy (welcome_text), so editing a welcome.* string flows to
    the welcome-back automatically. Locks the two rewrites (greeting →
    'back' form, 'first 10' → 'next 10') in EN + ES."""
    wt = i18n.welcome_text
    # variant defaults to welcome → untouched
    assert wt("hero.eyebrow", "en") == i18n.t("welcome.hero.eyebrow", "en")
    # EN derivations
    assert wt("hero.eyebrow", "en", variant="welcome_back") == "Welcome back to Pulpo Pro"
    assert wt("hero.headline.named", "en", variant="welcome_back", name="Ana") == "Welcome back, Ana."
    assert wt("hero.headline.unnamed", "en", variant="welcome_back") == "Welcome back aboard."
    assert wt("email.subject", "en", variant="welcome_back") == "Welcome back to Pulpo Pro — your next 10"
    assert "Your next 10 are below" in wt("hero.lede", "en", variant="welcome_back")
    assert "first 10" not in wt("hero.lede", "en", variant="welcome_back")
    # ES derivations (Salvadoran voseo intact)
    assert wt("hero.eyebrow", "es", variant="welcome_back") == "Bienvenido de nuevo a Pulpo Pro"
    assert wt("hero.headline.named", "es", variant="welcome_back", name="Ana") == "Bienvenido de nuevo, Ana."
    assert wt("email.subject", "es", variant="welcome_back") == "Bienvenido de nuevo a Pulpo Pro — tus próximas 10"


def test_welcome_back_es_uses_spanish_copy(ranked_pool, pro_with_prefs):
    es_recipient = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "locale": "es"}
    )
    issue = _issue(ranked=ranked_pool, recipient=es_recipient)
    html = render_welcome_back_html(issue)
    assert "Bienvenido de nuevo a Pulpo Pro" in html
    assert "Bienvenido de nuevo, Javier." in html
    assert "Tus próximas 10 están abajo" in html
    assert "volcánico" not in html.lower()
    assert "Welcome back to Pulpo Pro" not in html


def test_welcome_back_falls_back_when_display_name_missing(ranked_pool, pro_with_prefs):
    """No first name → the welcome's 'Welcome aboard.' fallback, derived to
    'Welcome back aboard.' (pure derivation, no special-case)."""
    anon = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "display_name": None}
    )
    issue = _issue(ranked=ranked_pool, recipient=anon)
    html = render_welcome_back_html(issue)
    assert "Welcome back aboard." in html
    assert "Welcome aboard." not in html
    assert "Welcome back, ." not in html


def test_welcome_back_subject_localized():
    assert i18n.welcome_text("email.subject", "en", variant="welcome_back") == "Welcome back to Pulpo Pro — your next 10"
    assert i18n.welcome_text("email.subject", "es", variant="welcome_back") == "Bienvenido de nuevo a Pulpo Pro — tus próximas 10"


def test_welcome_back_meta_tag_uses_welcome_back_version_constant(ranked_pool, pro_with_prefs):
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_back_html(issue)
    assert f'<meta name="x-pulpo-template" content="{WELCOME_BACK_TEMPLATE_VERSION}"' in html
    assert f'content="{WELCOME_TEMPLATE_VERSION}"' not in html
    assert f'content="{TEMPLATE_VERSION}"' not in html
