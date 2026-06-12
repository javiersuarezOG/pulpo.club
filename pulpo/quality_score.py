"""Listing soft quality score — PRD A6.

RANK-ONLY. **Never read by `isShelfEligible` or any visibility predicate.**
The PRD's "soft quality score" is explicitly a ranking nudge: listings
that pass the hard gates are visible. These factors raise their position
within the shelf. They do NOT change which listings render.

Scoring table (PRD §"Soft Quality Score — Used for Ranking, Not Filtering"):

  +3  photos >= 3
  +2  area_m2 present
  +1  description >= 30 words
  +1  contact info present (any of: broker_email / broker_phone / agent_url)
  +1  source institutional (encuentra24, remax, century21, citymax, csbr,
      santizo — agency portals)
  +1  price_per_m2 calculable (price_usd AND area_m2 both present)
  +1  card_eligible (photo phase verdict: hero clears the resolution
      floor, not a logo/placeholder)
  +1  hero_eligible (≥1080² source) — only when card_eligible is also True

Maximum 11. Pure function; no I/O. Tested by `tests/test_quality_score.py`.

Consumer: `pulpo/ranker_legs/quality_score.py` (registered as a 4th leg
with weight 0.05 — a rank nudge, not a reshuffle). After PR-renormalization
the three pre-existing legs keep ~95% of their original weight.
"""
from __future__ import annotations

import re
from typing import Any


# Institutional source slugs — agency portals carry more complete
# listing metadata on average and earn the +1 institutional bonus.
# Adding a new agency-portal scraper in Phase C? Append here so it
# inherits the bonus from day 1.
INSTITUTIONAL_SOURCES: frozenset[str] = frozenset({
    "encuentra24",  # broad SV-native portal
    "remax",        # franchise
    "century21",    # franchise
    "citymax",      # franchise SV branch
    "citymax_sc",   # franchise Surf City branch (Phase C)
    "csbr",         # Cámara Salvadoreña de Bienes Raíces (Phase C)
    "santizo",      # Santizo Real Estate (Phase C)
})


MAX_SCORE = 11


def _g(li: Any, name: str) -> Any:
    """Read a field from a dict or dataclass-like Listing."""
    if isinstance(li, dict):
        return li.get(name)
    return getattr(li, name, None)


def _has_contact(li: Any) -> bool:
    for field in ("broker_email", "broker_phone", "agent_url"):
        v = _g(li, field)
        if isinstance(v, str) and v.strip():
            return True
    return False


def _word_count(text: Any) -> int:
    if not isinstance(text, str):
        return 0
    return len(re.findall(r"\b\w+\b", text))


def compute(li: Any) -> int:
    """Return the soft quality score in [0, MAX_SCORE]. Pure function."""
    score = 0

    photos = _g(li, "photos_count")
    if isinstance(photos, int) and photos >= 3:
        score += 3

    area = _g(li, "area_m2")
    if isinstance(area, (int, float)) and area > 0:
        score += 2

    description = _g(li, "description")
    if _word_count(description) >= 30:
        score += 1

    if _has_contact(li):
        score += 1

    source = _g(li, "source")
    if isinstance(source, str) and source in INSTITUTIONAL_SOURCES:
        score += 1

    price = _g(li, "price_usd")
    if (
        isinstance(price, (int, float)) and price > 0
        and isinstance(area, (int, float)) and area > 0
    ):
        score += 1

    # Image fitness — the photo phase's verdicts. +1 for a card-suitable
    # hero (resolution floor, not a logo/placeholder), +1 more when the
    # hero is hero_eligible (>=1080^2 source). None counts as 0: unverified
    # photos confer no rank benefit.
    if _g(li, "card_eligible") is True:
        score += 1
        if _g(li, "hero_eligible") is True:
            score += 1

    return score
