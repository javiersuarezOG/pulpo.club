"""
Multi-factor investment ranker for raw beach + recreational land in El Salvador.

Why a multi-factor model?  A pure "cheap-for-zone" scorer tells you which
listings are mispriced low against their comp pool — but it punishes prime-
location plays at fair price and rewards cheap parcels in zones nobody is
buying. The classic real-estate trap: you get a nominal "discount" on
something with no liquidity and no exit.

Three legs, each on a 0..100 scale, combined with editor-tunable weights:

    1. VALUE    — entry price vs comparable sales (cheaper-for-pool = higher)
    2. LOCATION — zone tier + airport accessibility + amenities + freshness
    3. MOMENTUM — repriced-rate-per-zone, a delta signal that captures
                  whether an area is heating up or cooling down

    composite = 0.40*value + 0.35*location + 0.25*momentum

…then converted to a 1-based position rank (1 = best opportunity).

User-facing labels for the three dimensions:
    Price vs Comparable Lots / Location & Accessibility / Area Momentum

Two legs were retired in the consolidation after a correlation audit on 803
live listings:
- LIQUIDITY (Q-L corr 0.99 — same signal in two skins). DOM penalty +
  repriced bonus moved into LOCATION.
- UPSIDE-as-zone-table (Q-U corr 0.66 — heavily zone-tier-derived). The
  algorithm replaced with a delta-shaped repriced-rate signal so MOMENTUM
  stays orthogonal to LOCATION.

Re-weight via env vars:
    PULPO_W_VALUE / PULPO_W_LOCATION / PULPO_W_MOMENTUM

(weights renormalize so they don't have to sum to 1.0).
"""
from __future__ import annotations
import os
from typing import Iterable
from .models import Listing
import pulpo.ranker_legs.value     # noqa: F401 — triggers registration
import pulpo.ranker_legs.location  # noqa: F401
import pulpo.ranker_legs.momentum  # noqa: F401
from pulpo.agents import RANKER_LEGS


def _weights() -> dict[str, float]:
    """Return normalized weights from env vars or defaults."""
    legs = list(RANKER_LEGS.values())
    raw = {}
    for leg in legs:
        try:
            raw[leg.slug] = float(os.environ.get(leg.env_weight_key, leg.weight))
        except ValueError:
            raw[leg.slug] = leg.weight
    total = sum(raw.values())
    if total <= 0:
        return {leg.slug: leg.weight for leg in legs}
    return {slug: w / total for slug, w in raw.items()}


def rank(listings: Iterable[Listing]) -> list[Listing]:
    """Compute composite investment score + 1-based rank, sort, return."""
    items = list(listings)
    weights = _weights()

    for li in items:
        composite = 0.0
        reasons = []
        for slug, leg in RANKER_LEGS.items():
            s, reason = leg.score(li, items)
            w = weights.get(slug, leg.weight)
            composite += w * s
            reasons.append(reason)
            # Store component scores on the Listing for UI.
            if slug == "value":
                li.value_score = round(s, 1)
            elif slug == "location":
                li.location_score = round(s, 1)
            elif slug == "momentum":
                li.momentum_score = round(s, 1)

        composite = round(composite, 2)
        li.rank_score = composite
        wv = weights.get("value", 0.40)
        wl = weights.get("location", 0.35)
        wm = weights.get("momentum", 0.25)
        reasons.append(f"weights V{wv:.2f} L{wl:.2f} M{wm:.2f} → {composite:.1f}")
        li.rank_reasons = reasons

    items.sort(key=lambda x: (x.rank_score or 0), reverse=True)
    for i, li in enumerate(items, start=1):
        li.rank = i

    return items
