"""Pick-card component family — the locked listing card + section
intros that bracket the top-3 and next-7 blocks.

Visual reference: web/newsletter-mockup-v4-en.html (the 10 stacked
listing cards in the middle of the email, plus the two big serif
section headers above each block).

Locked contract for v4:
  • `pick_card_html(pick, locale, is_top_deal, paywall_url)` — THE
    single listing component. Renders every pick. Two things differ
    between top-3 and next-7 variants: card background (sage `#DDE9DC`
    vs white) and rank pill chrome (forest-on-cream pill for top-3,
    sand-on-grey for picks 4–10). v4.4 (2026-06-01) — the rank pill
    LABEL is unified: "Top deal · NN" (EN) / "Mejor oferta · NN" (ES)
    across all 10 picks. The numbering does the ranking work; having
    two labels (Top deal vs Pick) was confusing readers who asked
    what the product difference was when there isn't one. Photo,
    title, spec strip, price, "Why we picked it" card, and the
    paired See-on-Pulpo + ♥ Save CTA pair are IDENTICAL across both
    variants.
  • `section_intro_top3_html(locale)` — big serif H2 ("Top 3 this
    week.") + subtitle. Sits above pick 01.
  • `section_intro_rest_html(locale, n_rest)` — same shape, "{n}
    more this week." Sits between pick 03 and pick 04.

Helpers re-exported here:
  • `why_block_html` — the cream "Why we picked it" card with green
    check bullets. Inline-style version that survives Gmail / Outlook
    pseudo-element stripping (see PR #572).
  • `state_pill_html` — generic small-caps pill for the per-card
    state label ("New this week", "−78% under area avg", etc.).
  • `pick_state_pill_html` — picks the right state pill given a
    `IssuePick`'s real fields (price drop > zone-discount >
    new-this-week > none).
  • `pick_ppm_from_keytable` — pulls the "$XX/m²" string from the
    legacy keytable; used by the card body's price line.

Today these helpers are implemented inline inside `render_html.py`;
this module re-exports them so future templates can compose pick
cards without forking the markup.
"""

from __future__ import annotations

from ..render_html import _pick_card_html as pick_card_html
from ..render_html import _pick_ppm_from_keytable as pick_ppm_from_keytable
from ..render_html import _pick_state_pill_html as pick_state_pill_html
from ..render_html import _section_intro_rest_html as section_intro_rest_html
from ..render_html import _section_intro_top3_html as section_intro_top3_html
from ..render_html import _state_pill_html as state_pill_html
from ..render_html import _why_block_html as why_block_html

__all__ = [
    "pick_card_html",
    "section_intro_top3_html",
    "section_intro_rest_html",
    "why_block_html",
    "state_pill_html",
    "pick_state_pill_html",
    "pick_ppm_from_keytable",
]
