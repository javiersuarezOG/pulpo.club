"""Your Pulpo block — "Pick up where you left off" 3-card stack.

Visual reference: web/newsletter-mockup-v4-en.html (block above
the footer).

Locked contract for v4:
  • Forest-green eyebrow "YOUR PULPO" + serif H2 "Pick up where
    you left off."
  • Up to 4 stacked cream `#F8F4EC` action cards:
      1. Saved listings (skip when `saved_count == 0`)
      2. Filter (skip when `filter_summary_human` is empty)
      3. Browse (always present)
      4. Welcome (anonymous cohort only — carries `/welcome?r=…`)
  • Each card: small-caps eyebrow + bold action title + right-aligned
    → arrow. Full-width anchor, no separate button styling.

Today the block is composed inline inside `render_html.py`; this
module re-exports it. Future templates can choose to omit Your Pulpo
(e.g. Pro Welcome doesn't need it — there's no "where you left off"
for a brand-new subscriber).
"""

from __future__ import annotations

from ..render_html import _your_pulpo_html as your_pulpo_html

__all__ = ["your_pulpo_html"]
