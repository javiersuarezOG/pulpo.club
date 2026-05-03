from __future__ import annotations
from typing import TYPE_CHECKING
from pulpo.agents import RANKER_LEGS, register

if TYPE_CHECKING:
    from pulpo.models import Listing

# Zone tiers reflect today's market reality, not aspirations.
# A: established, deep buyer pool, premium $/m², resilient through cycles.
# B: secondary but proven; thicker discounts to A but real exit demand.
# C: frontier; cheap but liquidity risk dominates for non-strategic buyers.
ZONE_TIER = {
    # A — Surf City core
    "el-tunco":  "A",
    "el-sunzal": "A",
    "el-zonte":  "A",
    # B — established secondary
    "san-diego":          "B",
    "la-libertad":        "B",
    "puerto-la-libertad": "B",
    "el-cuco":            "B",
    "las-flores":         "B",
    "mizata":             "B",
    # C — frontier / interior / Gulf
    "punta-mango": "C",
    "el-espino":   "C",
    "conchagua":   "C",
    "la-union":    "C",
}
TIER_BASE = {"A": 85, "B": 65, "C": 45}


class QualityLeg:
    """Zone tier + physical attributes + freshness signals.

    Default weight bumped from 0.25 → 0.35 in the V/Q/U consolidation. Q now
    absorbs what was previously the LIQUIDITY leg's responsibility (DOM
    penalty + repriced bonus) — the legs were 0.99 correlated on live data,
    so the merge is empirically free. See pulpo/ranker.py docstring.
    """
    slug = "quality"
    weight = 0.35
    env_weight_key = "PULPO_W_QUALITY"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        tier = ZONE_TIER.get(listing.zone or "", None)
        base = TIER_BASE.get(tier, 30)
        bonuses = 0
        parts = [f"tier-{tier or '?'} {base}"]
        # Physical attributes (currently 0% live coverage; bonuses no-op until
        # scraper task #28 lifts coverage on these flags).
        if listing.is_beachfront:
            bonuses += 10
            parts.append("beachfront +10")
        if listing.has_paved_access:
            bonuses += 4
            parts.append("paved +4")
        if listing.has_water:
            bonuses += 3
            parts.append("water +3")
        if listing.has_power:
            bonuses += 3
            parts.append("power +3")
        # Freshness signals — folded in from the dropped LIQUIDITY leg.
        # Long DOM means the listing has been seen and passed on.
        if listing.days_listed is not None:
            if listing.days_listed > 180:
                bonuses -= 20
                parts.append(f"DOM {listing.days_listed}d -20")
            elif listing.days_listed > 90:
                bonuses -= 10
                parts.append(f"DOM {listing.days_listed}d -10")
            elif listing.days_listed <= 14:
                bonuses += 5
                parts.append(f"DOM {listing.days_listed}d +5 fresh")
        # Repriced means seller is motivated → shorter time to clearing price.
        if listing.is_repriced:
            bonuses += 5
            parts.append("repriced +5")
        s = max(0.0, min(100.0, base + bonuses))
        return s, "quality " + str(int(s)) + " (" + ", ".join(parts) + ")"


register(RANKER_LEGS, "quality", QualityLeg())
