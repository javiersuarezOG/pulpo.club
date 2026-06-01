"""Pulpo Pro Welcome — one-shot onboarding email.

Fires once per recipient when a Free user upgrades to Pro (Stripe
`customer.subscription.created` webhook will be the eventual trigger;
template ships first, trigger plumbing follows in a separate PR).

Composition is identical to General for the chrome (header, picks
card component, footer) and swaps the editorial top:

    header  →  welcome_hero  →  how_pulpo_works  →  cadence_note
            →  welcome_picks_intro  →  picks 01-10
            →  welcome_start_here  →  footer

Dropped vs General: favorites (nothing saved yet), market_context
(replaced by how_pulpo_works), paywall_banner (Pro reader),
news_spotlight (welcome is heavy enough), your_pulpo (replaced by
welcome_start_here onboarding cards).

The actual render logic lives in `automation.newsletter.render_html.
render_welcome_html` — this module is the registry entry point per the
`pulpo_pro_general.py` convention. Keeps blast radius low while the
component scaffolding beds in.
"""

from __future__ import annotations

from ..types import Issue


def render(issue: Issue) -> str:
    """Compose the Pulpo Pro Welcome email for a single recipient and
    return the rendered HTML string."""
    from ..render_html import render_welcome_html
    return render_welcome_html(issue)
