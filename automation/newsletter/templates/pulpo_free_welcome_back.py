"""Pulpo Free Welcome-back — free-tier re-acquisition email.

The free-general master (`render_html`) with `variant="free_welcome_back"`:
identical to the Free Welcome save the hero greeting, which derives from
the free welcome copy via i18n.welcome_text ("Welcome → Welcome back",
"first 10 → next 10") — the same rewrite the Pro pair uses, so the two
free onboarding emails can't drift.

One template serves both re-acquisition triggers (a churned Pro who drops
to free, and a free subscriber who resubscribes) — the trigger differs,
the rendered email is the same. Carries its own version line
(FREE_WELCOME_BACK_TEMPLATE_VERSION).
"""

from __future__ import annotations

from ..types import Issue


def render(issue: Issue) -> str:
    from ..render_html import render_free_welcome_back_html
    return render_free_welcome_back_html(issue)
