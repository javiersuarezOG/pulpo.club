"""Guards for the Pulpo Pro Welcome-back (resubscribe) render.

The welcome-back is NOT a separate template — it's `render_welcome_html`
with `variant="welcome_back"`. So the headline guarantee here is
*parity*: the welcome-back must be byte-identical to the first-time
welcome EXCEPT the hero copy, the picks-intro title, and the version
stamp. `test_welcome_back_is_welcome_with_only_hero_and_title_swapped`
proves exactly that — swap the welcome-back-specific strings back to
their `welcome.*` counterparts and the two renders must be equal.

Companion to `test_welcome_render.py` (the first-time welcome) and
`tests/newsletter/test_templates.py` (registry-alignment CI guard).
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape as _e

from automation.newsletter import i18n
from automation.newsletter.components._common import (
    WELCOME_TEMPLATE_VERSION,
    WELCOME_BACK_TEMPLATE_VERSION,
)
from automation.newsletter import build_issue
from automation.newsletter.render_html import (
    render_welcome_html,
    render_welcome_back_html,
)
from automation.newsletter.templates import TEMPLATES, pulpo_pro_welcome_back

_NOW = datetime(2026, 6, 1, 18, 0, 0, tzinfo=timezone.utc)  # Mon → future cadence


def _issue(*, ranked, recipient):
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


def test_welcome_back_is_welcome_with_only_hero_and_title_swapped(ranked_pool, pro_with_prefs):
    """THE parity guarantee. The welcome-back render, with its hero copy +
    picks-intro title + version stamp swapped back to the first-time
    welcome's, must be EXACTLY equal to the first-time welcome render. If
    anyone adds a welcome-back-only block (or the two render paths drift),
    this fails. One template, one sub-version — they can't diverge."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    lc = "en"  # pro_with_prefs is en, display_name "Javier"
    welcome = render_welcome_html(issue, now=_NOW)
    welcome_back = render_welcome_back_html(issue, now=_NOW)

    # The complete set of strings that may differ between the two — each is
    # the welcome string vs its welcome_text()-derived welcome-back form.
    swaps = [
        (i18n.welcome_text("hero.eyebrow", lc, variant="welcome_back"),
         i18n.t("welcome.hero.eyebrow", lc)),
        (i18n.welcome_text("hero.headline.named", lc, variant="welcome_back", name="Javier"),
         i18n.t("welcome.hero.headline.named", lc, name="Javier")),
        (i18n.welcome_text("hero.lede", lc, variant="welcome_back"),
         i18n.t("welcome.hero.lede", lc)),
        (i18n.welcome_text("section.picks.title", lc, variant="welcome_back"),
         i18n.t("welcome.section.picks.title", lc)),
        (WELCOME_BACK_TEMPLATE_VERSION, WELCOME_TEMPLATE_VERSION),
    ]
    normalized = welcome_back
    for back, first in swaps:
        # The strings land in the HTML html.escape()'d (the lede carries an
        # apostrophe + em-dash), so swap the escaped forms.
        normalized = normalized.replace(_e(back), _e(first))
    assert normalized == welcome, (
        "welcome-back diverges from the first-time welcome beyond the hero "
        "copy + picks title + version stamp. The welcome-back is meant to be "
        "the SAME template (variant='welcome_back') — a new welcome-back-only "
        "block, or a structural edit to only one path, broke parity."
    )


def test_welcome_back_hero_says_welcome_back(ranked_pool, pro_with_prefs):
    """The one block that changes: the hero greeting."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_back_html(issue, now=_NOW)
    assert "Welcome back to Pulpo Pro" in html        # eyebrow + <title>
    assert "Welcome back, Javier." in html            # first-name personalization
    assert "Your next 10 are below" in html           # lede reworded (first → next)
    assert "Your next 10 picks." in html              # picks-intro title
    # The first-time greeting must NOT survive into the welcome-back.
    assert "Welcome to Pulpo Pro" not in html
    assert "Welcome, Javier." not in html
    assert "Your first 10 picks." not in html
    # Brand voice: never "volcanic".
    assert "volcanic" not in html.lower()


def test_welcome_back_keeps_the_shared_welcome_blocks(ranked_pool, pro_with_prefs):
    """Everything below the hero is the SAME as the first-time welcome —
    how-it-works, cadence, start-here onboarding cards, footer. This is the
    'identical end-to-end' requirement spelled out as presence checks."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_back_html(issue, now=_NOW)
    # How Pulpo works (3 beats) — shared
    assert "How Pulpo works" in html
    assert "We scan every supplier" in html
    # Cadence note — shared (future variant for a Monday `now`)
    assert "Sunday, June 7" in html
    # Start-here onboarding cards — shared
    assert "Start here" in html
    assert "Set your filter" in html
    assert "Browse all listings" in html
    assert "Open your account" in html


def test_welcome_back_es_uses_spanish_copy(ranked_pool, pro_with_prefs):
    """ES locale localizes the welcome-back hero too, with Salvadoran
    voseo inherited from the shared blocks. No English canary leaks."""
    es_recipient = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "locale": "es"}
    )
    issue = _issue(ranked=ranked_pool, recipient=es_recipient)
    html = render_welcome_back_html(issue, now=_NOW)
    assert "Bienvenido de nuevo a Pulpo Pro" in html
    assert "Bienvenido de nuevo, Javier." in html
    assert "Tus próximas 10 están abajo" in html
    assert "Tus próximas 10 selecciones." in html
    assert "volcánico" not in html.lower()
    # Canary — English greeting must NOT leak through.
    assert "Welcome back to Pulpo Pro" not in html
    assert "Your next 10 picks." not in html


def test_welcome_back_falls_back_when_display_name_missing(ranked_pool, pro_with_prefs):
    """No first name → the welcome's 'Welcome aboard.' fallback, derived to
    'Welcome back aboard.'. Pure derivation (no special-case), so never the
    first-time 'Welcome aboard.' and never 'Welcome back, .'."""
    anon = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "display_name": None}
    )
    issue = _issue(ranked=ranked_pool, recipient=anon)
    html = render_welcome_back_html(issue, now=_NOW)
    assert "Welcome back aboard." in html
    assert "Welcome aboard." not in html
    assert "Welcome back, ." not in html


def test_welcome_text_derives_back_copy_from_welcome():
    """The invariant: welcome-back copy is a pure function of the welcome
    copy (welcome_text), so editing a welcome.* string flows to the
    welcome-back automatically — they can't drift. Locks the two rewrites
    (greeting → 'back' form, 'first 10' → 'next 10') in EN + ES."""
    wt = i18n.welcome_text
    # variant defaults to welcome → untouched
    assert wt("hero.eyebrow", "en") == i18n.t("welcome.hero.eyebrow", "en")
    # EN derivations
    assert wt("hero.eyebrow", "en", variant="welcome_back") == "Welcome back to Pulpo Pro"
    assert wt("hero.headline.named", "en", variant="welcome_back", name="Ana") == "Welcome back, Ana."
    assert wt("hero.headline.unnamed", "en", variant="welcome_back") == "Welcome back aboard."
    assert wt("section.picks.title", "en", variant="welcome_back") == "Your next 10 picks."
    assert wt("email.subject", "en", variant="welcome_back") == "Welcome back to Pulpo Pro — your next 10"
    assert "Your next 10 are below" in wt("hero.lede", "en", variant="welcome_back")
    assert "first 10" not in wt("hero.lede", "en", variant="welcome_back")
    # ES derivations (Salvadoran voseo intact)
    assert wt("hero.eyebrow", "es", variant="welcome_back") == "Bienvenido de nuevo a Pulpo Pro"
    assert wt("hero.headline.named", "es", variant="welcome_back", name="Ana") == "Bienvenido de nuevo, Ana."
    assert wt("section.picks.title", "es", variant="welcome_back") == "Tus próximas 10 selecciones."
    assert wt("email.subject", "es", variant="welcome_back") == "Bienvenido de nuevo a Pulpo Pro — tus próximas 10"


def test_welcome_back_subject_localized():
    """Subject derives from welcome.email.subject via welcome_text. The
    dispatcher reads it for the welcome-back variant."""
    assert i18n.welcome_text("email.subject", "en", variant="welcome_back") == "Welcome back to Pulpo Pro — your next 10"
    assert i18n.welcome_text("email.subject", "es", variant="welcome_back") == "Bienvenido de nuevo a Pulpo Pro — tus próximas 10"


def test_welcome_back_meta_tag_uses_welcome_back_version_constant(ranked_pool, pro_with_prefs):
    """The welcome-back stamps its own version so PostHog can slice
    re-acquisition renders from first-time welcomes."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_back_html(issue, now=_NOW)
    assert f'<meta name="x-pulpo-template" content="{WELCOME_BACK_TEMPLATE_VERSION}"' in html
    assert f'content="{WELCOME_TEMPLATE_VERSION}"' not in html
