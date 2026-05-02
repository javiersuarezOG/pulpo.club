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
    slug = "quality"
    weight = 0.25
    env_weight_key = "PULPO_W_QUALITY"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        tier = ZONE_TIER.get(listing.zone or "", None)
        base = TIER_BASE.get(tier, 30)
        bonuses = 0
        parts = [f"tier-{tier or '?'} {base}"]
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
        s = max(0.0, min(100.0, base + bonuses))
        return s, "quality " + str(int(s)) + " (" + ", ".join(parts) + ")"


register(RANKER_LEGS, "quality", QualityLeg())
