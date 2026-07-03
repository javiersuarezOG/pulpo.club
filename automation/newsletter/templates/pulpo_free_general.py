"""Pulpo Free General — the free-tier weekly digest.

It IS the Pro General master (`render_html`) with `variant="free_general"`,
which applies three free-cohort changes, all gated on the variant so the
Pro path is untouched:

    1. masthead drops the gold "PRO" badge → plain `pulpo`
    2. ranks 04-10 ("7 more") swap the "See on Pulpo" CTA for
       "Sign up to Pro"; top 3 keep "See on Pulpo". Every card still
       renders the full listing component (photo, title, location, price,
       "Why we picked it") — the value gate is the CTA, not hidden content.
    3. the Weekly News Spotlight is Pro-LOCKED: the real headline, source
       citation and opening sentence show (straight from the committed
       news_spotlight.json artifact — no fabricated copy); the rest of the
       read sits behind a single "Sign up to Pro" panel.

Carries its own version line (FREE_GENERAL_TEMPLATE_VERSION) so PostHog
can slice free weeklies from Pro weeklies. Composition below the hero is
otherwise byte-identical to the Pro General, so a change to any shared
block lands here automatically and the two cannot drift.
"""

from __future__ import annotations

from ..types import Issue


def render(issue: Issue) -> str:
    """Compose the Pulpo Free General weekly for a single recipient's
    Issue and return the rendered HTML string."""
    from ..render_html import render_free_general_html
    return render_free_general_html(issue)
