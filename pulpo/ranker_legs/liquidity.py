from __future__ import annotations
from typing import TYPE_CHECKING
from pulpo.agents import RANKER_LEGS, register

if TYPE_CHECKING:
    from pulpo.models import Listing

# Zones with deeper buyer pools -> faster exit -> higher liquidity score.
# These weights are SV-market judgment calls; tune with real DOM data when
# we have it (Phase 2: track listing -> sold transitions).
ZONE_LIQUIDITY = {
    "el-tunco": 90, "el-sunzal": 88, "el-zonte": 85,
    "san-diego": 75, "la-libertad": 72, "puerto-la-libertad": 72,
    "mizata": 65,
    "el-cuco": 70, "las-flores": 68, "punta-mango": 55,
    "el-espino": 50,
    "conchagua": 45, "la-union": 50,
}


class LiquidityLeg:
    slug = "liquidity"
    weight = 0.20
    env_weight_key = "PULPO_W_LIQUIDITY"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        """Zone exit-risk proxy + freshness penalty."""
        base = ZONE_LIQUIDITY.get(listing.zone or "", 35)   # unknown zone is illiquid
        parts = [f"zone-base {base}"]
        # Long DOM is a yellow flag — listing has been seen and passed on.
        if listing.days_listed is not None:
            if listing.days_listed > 180:
                base -= 20
                parts.append(f"DOM {listing.days_listed}d -20")
            elif listing.days_listed > 90:
                base -= 10
                parts.append(f"DOM {listing.days_listed}d -10")
            elif listing.days_listed <= 14:
                base += 5
                parts.append(f"DOM {listing.days_listed}d +5 fresh")
        # Repriced means seller is motivated -> shorter time to clearing price.
        if listing.is_repriced:
            base += 5
            parts.append("repriced +5")
        score = max(0.0, min(100.0, base))
        return score, "liquidity " + str(int(score)) + " (" + ", ".join(parts) + ")"


register(RANKER_LEGS, "liquidity", LiquidityLeg())
