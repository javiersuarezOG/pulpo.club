"""Pulpo Pro General — the canonical Pro template.

Powers the weekly Pro digest (`pro-weekly`) and is the base every
future Pro template builds on. The composition is:

    header  →  hero  →  favorites  →  market context
            →  Top-3 intro  →  picks 01-03
            →  paywall banner (Free cohort only)
            →  7-more intro  →  picks 04-10
            →  Weekly News Spotlight
            →  Your Pulpo  →  footer

Visual reference: web/newsletter-mockup-v4-en.html (the locked
mockup the v4 redesign was built against).

For the v4.2 architecture pass, the rendering itself is delegated to
`automation.newsletter.render_html.render_html` — the function body
hasn't moved yet. This keeps the component-and-template scaffolding
in place without the risk of a big-bang code shuffle. A follow-up
PR will lift the composition out of render_html.py and into this
module.
"""

from __future__ import annotations

from ..types import Issue


def render(issue: Issue) -> str:
    """Compose the Pulpo Pro General newsletter for a single
    recipient's Issue and return the rendered HTML string."""
    # Import lazily so the registry import (templates/__init__.py)
    # doesn't trigger the renderer module unnecessarily.
    from ..render_html import render_html
    return render_html(issue)
