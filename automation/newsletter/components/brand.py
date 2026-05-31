"""Brand chrome components — header strip + footer.

Both blocks carry the Pulpo Pro identity: octopus mark + wordmark + a
small gold `PRO` pill that signals this is the personalised Pro
product (audience scoped to Pro subscribers per PR-NL-9).

Today these components live as inline blocks inside the top-level
`render_html()` composition; this module re-exports the shared
helpers used to build them so future templates can compose them
without duplicating CSS or SVG markup.

Visual reference: web/newsletter-mockup-v4-en.html (header + footer
blocks at the very top and very bottom of the email frame).

Locked contract for v4:
  • Header: octopus SVG + lowercase "pulpo" wordmark + gold "PRO"
    pill, right-aligned issue line ("ISSUE NN · DD MON YYYY")
  • Footer: same Pulpo + PRO mark + brand tagline + trust line +
    horizontal rule + personalisation note + 3 pill buttons
    (Change filters / Change cadence / Unsubscribe) + copyright
    line ("© YYYY Pulpo Pro · pulpo.club")
"""

from __future__ import annotations

from ..render_html import _footer_html as footer_html

# Header strip is currently rendered inline inside `render_html()` —
# expose it through a lazy accessor so future templates can compose
# it without forking the markup. When the function body is extracted
# into this module (follow-up PR), this re-export will become the
# direct definition.

__all__ = ["footer_html"]
