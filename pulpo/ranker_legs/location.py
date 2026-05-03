from __future__ import annotations
from typing import TYPE_CHECKING
from pulpo.agents import RANKER_LEGS, register
from pulpo.airports import airport_bonus

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
UNKNOWN_TIER_BASE = 30


class LocationLeg:
    """Zone tier + physical attributes + airport accessibility + freshness.

    Renamed from QualityLeg in the V/Q/U → V/L/U consolidation: the leg now
    explicitly covers location-and-accessibility (zone tier + airport
    distance + amenity flags) rather than the more abstract "quality"
    framing. User-facing label is "Location & Accessibility".

    Inherits the DOM penalty + repriced bonus that the dropped Liquidity
    leg used to own. Adds airport-distance bonus per the static
    pulpo.airports.ZONE_TO_AIRPORT_KM lookup.

    Default weight 0.35 (unchanged from QualityLeg's post-Phase-5A weight).
    """
    slug = "location"
    weight = 0.35
    env_weight_key = "PULPO_W_LOCATION"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        tier = ZONE_TIER.get(listing.zone or "")
        # Type-narrow: TIER_BASE.get rejects None, so feed it a literal default.
        base = TIER_BASE.get(tier, UNKNOWN_TIER_BASE) if tier else UNKNOWN_TIER_BASE
        bonuses = 0
        parts = [f"tier-{tier or '?'} {base}"]

        # Airport accessibility — only El Salvador's SAL is operational today.
        ap_bonus, ap_reason = airport_bonus(listing.zone)
        if ap_reason:
            bonuses += ap_bonus
            parts.append(ap_reason)

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
        return s, "location " + str(int(s)) + " (" + ", ".join(parts) + ")"


register(RANKER_LEGS, "location", LocationLeg())
