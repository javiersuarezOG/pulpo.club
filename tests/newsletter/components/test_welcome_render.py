"""Guards for the Pulpo Pro Welcome render.

The welcome is the General weekly master with ONLY the hero swapped
(`render_html(variant="welcome")`). So the headline guarantee is parity:
the welcome must be byte-identical to the General save the hero block,
the <title>, and the <meta> version stamp —
`test_welcome_is_general_with_only_hero_swapped` proves exactly that.

All three Pulpo emails (General weekly, Welcome, Welcome-back) are Pro
emails, so the paywall block never renders for them (paywall_banner is
False for Pro).

Companion to `test_welcome_back_render.py` and
`tests/newsletter/test_templates.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from automation.newsletter import build_issue, i18n
from automation.newsletter.components._common import (
    TEMPLATE_VERSION,
    WELCOME_TEMPLATE_VERSION,
)
from automation.newsletter.render_html import (
    render_html,
    render_welcome_html,
    _general_hero_html,
    _welcome_hero_html,
)


def _issue(*, ranked, recipient):
    return build_issue(
        recipient=recipient,
        ranked_listings=ranked,
        issue_number=1,
        issue_date=datetime(2026, 6, 1, 16, 0, 0, tzinfo=timezone.utc),
        history_rows=None,
    )


def test_welcome_is_general_with_only_hero_swapped(ranked_pool, pro_with_prefs):
    """THE parity guarantee for the new master. The welcome render, with
    its hero block + <title> + version stamp swapped back to the General's,
    must be BYTE-IDENTICAL to the General weekly. If anyone adds a
    welcome-only block below the hero — or the two render paths drift —
    this fails. One master template, one variant point (the hero)."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    general = render_html(issue)                       # variant="general"
    welcome = render_welcome_html(issue)               # variant="welcome"

    welcome_title = i18n.welcome_text("hero.eyebrow", "en", variant="welcome")
    general_title = f"Pulpo — Issue {issue.issue_number:02d} · {issue.issue_date_human}"

    normalized = welcome
    normalized = normalized.replace(_welcome_hero_html(issue, variant="welcome"),
                                    _general_hero_html(issue))
    normalized = normalized.replace(WELCOME_TEMPLATE_VERSION, TEMPLATE_VERSION)
    # <title> swap (escaped exactly as render emits it)
    from html import escape as _e
    normalized = normalized.replace(f"<title>{_e(welcome_title)}</title>",
                                    f"<title>{_e(general_title)}</title>")
    assert normalized == general, (
        "welcome diverges from the General master beyond the hero + title + "
        "version. The welcome is meant to be render_html(variant='welcome') — "
        "a welcome-only block below the hero, or a one-sided structural edit, "
        "broke parity."
    )


def test_welcome_hero_and_shared_body(ranked_pool, pro_with_prefs):
    """Readable spelling-out: welcome shows the welcome hero, then the SAME
    weekly body (market context, news spotlight, Your Pulpo, footer). The
    old onboarding blocks (how-it-works, start-here) are gone."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_html(issue)
    # Welcome hero
    assert "Welcome to Pulpo Pro" in html
    assert "Welcome, Javier." in html
    assert "Pulpo covers the coast and the lakes" in html
    # Shared weekly body (from the General master)
    assert "Market context" in html
    assert "Weekly News Spotlight" in html
    assert "Pick up where you left off" in html      # Your Pulpo
    # Removed onboarding blocks
    assert "How Pulpo works" not in html
    assert "Start here" not in html
    assert "Your first 10 picks." not in html        # welcome's old picks intro
    # Pro reader → no paywall element (CSS class in <style> is fine)
    assert '<div class="paywall-banner">' not in html


def test_welcome_es_uses_spanish_hero(ranked_pool, pro_with_prefs):
    """ES localizes the welcome hero; the shared body localizes via the
    General's keys. No English greeting canary leaks."""
    es_recipient = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "locale": "es"}
    )
    issue = _issue(ranked=ranked_pool, recipient=es_recipient)
    html = render_welcome_html(issue)
    assert "Bienvenido a Pulpo Pro" in html
    assert "Bienvenido, Javier." in html
    assert "Pulpo cubre la costa y los lagos" in html
    assert "Welcome to Pulpo Pro" not in html


def test_welcome_falls_back_when_display_name_missing(ranked_pool, pro_with_prefs):
    """No first name on Clerk → 'Welcome aboard.' fallback. Never
    'Welcome, .' or 'Welcome, None.'."""
    anon = pro_with_prefs.__class__(
        **{**pro_with_prefs.__dict__, "display_name": None}
    )
    issue = _issue(ranked=ranked_pool, recipient=anon)
    html = render_welcome_html(issue)
    assert "Welcome aboard." in html
    assert "Welcome, ." not in html
    assert "Welcome, None" not in html


def test_welcome_subject_localized():
    """Subject must localize. The dispatcher reads this before send."""
    assert i18n.t("welcome.email.subject", "en") == "Welcome to Pulpo Pro — your first 10"
    assert i18n.t("welcome.email.subject", "es") == "Bienvenido a Pulpo Pro — tus primeras 10"


def test_welcome_meta_tag_uses_welcome_version(ranked_pool, pro_with_prefs):
    """The welcome stamps WELCOME_TEMPLATE_VERSION (not the General's), so
    PostHog can slice rendered welcomes from weeklies."""
    issue = _issue(ranked=ranked_pool, recipient=pro_with_prefs)
    html = render_welcome_html(issue)
    assert f'<meta name="x-pulpo-template" content="{WELCOME_TEMPLATE_VERSION}"' in html
    assert f'content="{TEMPLATE_VERSION}"' not in html
