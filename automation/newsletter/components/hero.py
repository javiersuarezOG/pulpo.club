"""Hero block component — the eyebrow + H1 + lede + filter chip that
sits directly under the header strip.

Visual reference: web/newsletter-mockup-v4-en.html (top of the email
frame, immediately under the header).

Locked contract for v4:
  • Eyebrow: small-caps cohort label ("HAND-PICKED FOR <NAME>")
  • H1: editorial headline ("The 10 best, this week.")
  • Lede: 2 sentences naming the scan size + standout count
    (3rd sentence describing the rich/short split was DROPPED in v4
    since all 10 picks now render through the same locked card)
  • Filter chip: one pill per non-empty Preference slot

Today the hero is composed inline inside `render_html()`; the
filter-chip helper is the only piece this module re-exports for now.
When the full hero block is extracted into this module (follow-up
PR), this becomes the direct definition site.
"""

from __future__ import annotations

from ..render_html import _filter_chips_html as filter_chips_html

__all__ = ["filter_chips_html"]
