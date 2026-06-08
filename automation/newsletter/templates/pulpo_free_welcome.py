"""Pulpo Free Welcome — the free-tier onboarding email.

The free-general master (`render_html`) with `variant="free_welcome"`:
the free body (plain `pulpo` masthead, top-3 "See on Pulpo", ranks 04-10
"Sign up to Pro", Pro-locked Weekly News Spotlight) under a warm welcome
hero. Identity is plain Pulpo — NOT "Pulpo Pro" — a free reader isn't a
Pro member.

Carries its own version line (FREE_WELCOME_TEMPLATE_VERSION). Everything
below the hero is the free-general body, so it can't drift from the free
weekly. Fired once when a free reader subscribes (homepage form); the
dispatch trigger is wired separately.
"""

from __future__ import annotations

from ..types import Issue


def render(issue: Issue) -> str:
    from ..render_html import render_free_welcome_html
    return render_free_welcome_html(issue)
