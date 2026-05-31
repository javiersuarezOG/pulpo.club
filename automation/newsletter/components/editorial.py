"""Editorial blocks — market context + Weekly News Spotlight.

Visual reference: web/newsletter-mockup-v4-en.html (market context
sits between favorites and the Top 3 section; news spotlight sits
between picks 04-10 and Your Pulpo).

Locked contract for v4:

  • `market_html(issue)` — three numbered editorial mini-blocks
    (`01` / `02` / `03`) keyed off `issue.commentary.market_context`.
    Each block: big serif numeral (left, forest green) + bold lead
    + body sentence (right). Surf City 1/2 decoder line sits above
    the blocks as small caption.

  • `weekly_news_spotlight_html(issue)` — Pulpo octopus icon +
    "WEEKLY NEWS SPOTLIGHT" eyebrow + "Reported by …" source line
    + H2 title + body paragraph. Two paths:
      1. LLM-curated story from `issue.news_spotlight` (preferred)
      2. Deterministic fallback ("What we're watching on the coast")
         with Pulpo Pro self-attribution (no fake citation)

  • `hydrate_pick_urls(paragraph, issue)` — resolves
    `<a href="PICK_URL_N">…</a>` placeholders against the actual
    pick URLs. Used by market_html before render.

Today these helpers are implemented inline inside `render_html.py`;
this module re-exports them so future templates can compose editorial
blocks or skip them (a Pro Welcome template wouldn't need market
context — there's no fortnight to summarize).
"""

from __future__ import annotations

from ..render_html import _hydrate_pick_urls as hydrate_pick_urls
from ..render_html import _market_html as market_html
from ..render_html import _weekly_news_spotlight_html as weekly_news_spotlight_html

__all__ = [
    "market_html",
    "weekly_news_spotlight_html",
    "hydrate_pick_urls",
]
