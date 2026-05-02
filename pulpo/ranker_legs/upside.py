from __future__ import annotations
from typing import TYPE_CHECKING
from pulpo.agents import RANKER_LEGS, register

if TYPE_CHECKING:
    from pulpo.models import Listing

# Path-of-progress mapping. Higher = more headroom for $/m² to expand over a
# 5–10 year hold. Calibrated against:
#   * Surf City Phase 2 narrative (eastern coast)
#   * La Unión deep-water port + Bitcoin City discussion (gulf-fonseca)
#   * Already-priced-in core (Tunco/Sunzal/Zonte appreciation slowing)
#   * El Espino still slow vs adjacent corridors
ZONE_UPSIDE = {
    "el-tunco": 60, "el-sunzal": 60, "el-zonte": 65,    # priced-in core
    "san-diego": 75, "la-libertad": 70, "puerto-la-libertad": 70,
    "mizata": 80,                                          # next wave west
    "el-cuco": 85, "las-flores": 88, "punta-mango": 85,   # Surf City Phase 2
    "el-espino": 65,
    "conchagua": 90, "la-union": 92,                       # gulf-fonseca thesis
}


class UpsideLeg:
    slug = "upside"
    weight = 0.20
    env_weight_key = "PULPO_W_UPSIDE"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        """Path-of-progress / growth-corridor headroom."""
        base = ZONE_UPSIDE.get(listing.zone or "", 50)
        parts = [f"zone-upside {base}"]
        # Beachfront in any tier gets a small upside bump (development premium scales).
        bonus = 0
        if listing.is_beachfront:
            bonus += 5
            parts.append("beachfront +5")
        # Large parcels in growth zones offer subdivision optionality.
        if listing.area_m2 and listing.area_m2 >= 50_000 and base >= 75:
            bonus += 5
            parts.append("scale +5 (subdividable in growth zone)")
        score = max(0.0, min(100.0, base + bonus))
        return score, "upside " + str(int(score)) + " (" + ", ".join(parts) + ")"


register(RANKER_LEGS, "upside", UpsideLeg())
