"""
Multi-factor investment ranker for raw beach + recreational land in El Salvador.

Why a multi-factor model?  A pure "cheap-for-zone" scorer tells you which
listings are mispriced low against their comp pool — but it punishes prime-
location plays at fair price and rewards cheap parcels in zones nobody is
buying. The classic real-estate trap: you get a nominal "discount" on
something with no liquidity and no exit.

Three legs, each on a 0..100 scale, combined with editor-tunable weights:

    1. VALUE    — entry price vs comparable sales (cheaper-for-pool = higher)
    2. QUALITY  — zone tier + physical attributes + freshness signals
    3. UPSIDE   — path-of-progress: where is capital flowing next?

    composite = 0.40*value + 0.35*quality + 0.25*upside

…then converted to a 1-based position rank (1 = best opportunity).

A previous LIQUIDITY leg was dropped after a correlation audit on 803 live
listings showed it was 0.99 correlated with QUALITY (i.e. the same signal in
two skins). Its DOM penalty + repriced bonus moved into the QUALITY leg's
score function. Top-10 leaderboard overlap before/after the consolidation
was 9/10 — the change is empirically free.

Re-weight via env vars:
    PULPO_W_VALUE / PULPO_W_QUALITY / PULPO_W_UPSIDE

(weights renormalize so they don't have to sum to 1.0).
"""
from __future__ import annotations
import os
from typing import Iterable
from .models import Listing
import pulpo.ranker_legs.value    # noqa: F401 — triggers registration
import pulpo.ranker_legs.quality  # noqa: F401
import pulpo.ranker_legs.upside   # noqa: F401
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
            # Store component scores on the Listing for UI. liquidity_score
            # remains a None-able field on the dataclass for backward compat
            # with cached payloads, but we no longer populate it.
            if slug == "value":
                li.value_score = round(s, 1)
            elif slug == "quality":
                li.quality_score = round(s, 1)
            elif slug == "upside":
                li.upside_score = round(s, 1)

        composite = round(composite, 2)
        li.rank_score = composite
        wv = weights.get("value", 0.40)
        wq = weights.get("quality", 0.35)
        wu = weights.get("upside", 0.25)
        reasons.append(f"weights V{wv:.2f} Q{wq:.2f} U{wu:.2f} → {composite:.1f}")
        li.rank_reasons = reasons

    items.sort(key=lambda x: (x.rank_score or 0), reverse=True)
    for i, li in enumerate(items, start=1):
        li.rank = i

    return items
