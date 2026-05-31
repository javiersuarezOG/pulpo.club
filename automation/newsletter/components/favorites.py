"""Favorites block — "Your favorites · this week" with per-save cards.

Visual reference: web/newsletter-mockup-v4-en.html (cream block
directly below the hero).

Locked contract for v4:
  • Cream `#F8F4EC` background, clay-colored eyebrow
  • Numeric headline ("3 you're following.", not spelled-out)
  • Italic editorial summary line ("Two of three moved on price
    this week — busier than a typical week on your watchlist")
  • Per-save card: thumb + change chip + title + meta + price +
    See-on-Pulpo + ♥ Following badge
  • Bottom underlined "Open all favorites →" link

Today the block is composed inline inside `render_html.py`; this
module re-exports the public helpers so future templates can choose
to include or omit the section (e.g. a Pro Welcome template wouldn't
render favorites — new subscribers have none).
"""

from __future__ import annotations

from ..render_html import _favorite_card_html as favorite_card_html
from ..render_html import _favorites_editorial_summary as favorites_editorial_summary
from ..render_html import _favorites_html as favorites_html

__all__ = [
    "favorites_html",
    "favorite_card_html",
    "favorites_editorial_summary",
]
