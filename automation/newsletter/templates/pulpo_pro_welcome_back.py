"""Pulpo Pro Welcome-back — resubscribe re-acquisition email.

Fires once per resubscription when a previously-welcomed user reactivates
Pro after a lapse. The Stripe `customer.subscription` → checkout path
auto-routes here (instead of the first-time welcome) when the recipient
already carries a `welcome_newsletter_sent_at` stamp — see
`automation.newsletter.welcome_dispatch.dispatch_welcome` and the
`project_resubscribe_welcome_funnel` memory for the funnel rationale.

Composition reuses the first-time welcome chrome (header, pick cards,
cadence note, footer) and swaps the onboarding-flavored blocks for
re-entry ones:

    header  →  welcome_back_hero  →  cadence_note
            →  welcome_back_picks_intro  →  picks 01-10
            →  welcome_back_resume  →  footer

Dropped vs the first-time welcome: how_pulpo_works (the returning reader
knows the ropes) and the 3-step start_here onboarding cards (replaced by
the "Pick up where you left off" re-engagement block).

The actual render logic lives in `automation.newsletter.render_html.
render_welcome_back_html` — this module is the registry entry point per
the `pulpo_pro_welcome.py` convention.
"""

from __future__ import annotations

from ..types import Issue


def render(issue: Issue) -> str:
    """Compose the Pulpo Pro Welcome-back email for a single recipient
    and return the rendered HTML string."""
    from ..render_html import render_welcome_back_html
    return render_welcome_back_html(issue)
