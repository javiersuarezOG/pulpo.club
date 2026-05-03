"""
Area Momentum leg — measures whether a zone is heating up, cooling down,
or holding steady, using delta-shaped signals only.

Replaces the previous Upside leg, which scored an editor-curated zone-upside
table (correlated 0.66 with the Quality/Location leg, indicating substantial
shared variance with the static zone-tier signal). This leg constructs
momentum exclusively from rate-of-change observations so it stays orthogonal
to Location.

V1 input: per-zone repriced rate. For each zone, compute the fraction of
listings flagged `is_repriced = True`. Zones above the cross-zone median get
high momentum scores (lots of motivated sellers, opportunity to negotiate);
zones below the median score lower (stable market, fewer concessions).

Sparse zones (< MIN_ZONE_LISTINGS listings) score the neutral default 50.0 —
the rate is too noisy to be informative.

Phase 6.5 (~2026-06-01) will add listing-velocity-per-zone as a second input
once we have 4+ weeks of nightly scrape history. Until then, momentum runs
on repriced-rate alone.

Default weight 0.25 (consolidation rebalance from Upside's 0.20).
"""
from __future__ import annotations
from bisect import bisect_left
from typing import TYPE_CHECKING
from pulpo.agents import RANKER_LEGS, register

if TYPE_CHECKING:
    from pulpo.models import Listing


# Minimum listings per zone before we trust the repriced-rate signal.
# Below this, the per-zone fraction is too noisy to be meaningful (a single
# repriced listing in a 2-listing zone reads as "50% repriced" — meaningless).
MIN_ZONE_LISTINGS = 5

NEUTRAL_SCORE = 50.0

# Listing-level bonus when the listing itself has been repriced. A motivated
# seller deserves an extra nudge regardless of the zone's overall behavior.
SELF_REPRICED_BONUS = 5


def _zone_repriced_rates(comp_pool: list["Listing"]) -> tuple[dict[str, float], list[float]]:
    """Compute per-zone repriced rate. Returns (rates_by_zone, sorted_rates).

    Only zones with at least MIN_ZONE_LISTINGS listings appear in the result.
    Sparser zones are excluded because their rate isn't reliable.
    """
    counts: dict[str, list[int]] = {}  # zone -> [repriced_count, total_count]
    for li in comp_pool:
        z = li.zone
        if not z:
            continue
        if z not in counts:
            counts[z] = [0, 0]
        if li.is_repriced:
            counts[z][0] += 1
        counts[z][1] += 1
    rates = {
        z: r / t
        for z, (r, t) in counts.items()
        if t >= MIN_ZONE_LISTINGS
    }
    return rates, sorted(rates.values())


class MomentumLeg:
    slug = "momentum"
    weight = 0.25
    env_weight_key = "PULPO_W_MOMENTUM"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        rates, sorted_rates = _zone_repriced_rates(comp_pool)
        zone = listing.zone

        # No zone, or zone is sparse → neutral. Nothing else to say.
        if not zone or zone not in rates:
            return NEUTRAL_SCORE, f"momentum {NEUTRAL_SCORE:.0f} (sparse zone, no signal)"

        # No variance across all dense zones → everyone neutral. Avoids
        # a degenerate percentile that would award 0 (or 100) to every
        # listing when all zones happen to have the same repriced rate.
        if len(set(sorted_rates)) <= 1:
            return NEUTRAL_SCORE, (
                f"momentum {NEUTRAL_SCORE:.0f} "
                f"(no zone variance — all zones at {sorted_rates[0]*100:.0f}% repriced)"
            )

        # Percentile rank within the dense-zone repriced-rate distribution.
        # Higher rate → higher percentile → higher momentum score.
        rate = rates[zone]
        pct = bisect_left(sorted_rates, rate) / len(sorted_rates)
        score = 100.0 * pct

        # Listing-level self-repriced bonus.
        if listing.is_repriced:
            score = min(100.0, score + SELF_REPRICED_BONUS)
            return score, (
                f"momentum {score:.0f} "
                f"(zone {rate*100:.0f}% repriced, +{SELF_REPRICED_BONUS} self-repriced)"
            )
        return score, f"momentum {score:.0f} (zone {rate*100:.0f}% repriced)"


register(RANKER_LEGS, "momentum", MomentumLeg())
