"""
Area Momentum leg — measures whether a zone is gaining or losing inventory
faster than other zones, using the persistent `first_seen_at` sidecar
populated by automation/run.py.

Why this signal: listing velocity (rate of new inventory per zone) is a
genuine momentum measurement — zones that are heating up see more new
listings appear; zones that are cooling see existing inventory persist
without churn. Unlike level signals (zone tier, search volume), velocity
is structurally orthogonal to Location: a tier-B zone with rising velocity
and a tier-A zone with flat velocity tell different stories.

Implementation: for each zone, compute the mean age (in days) of its
listings' first_seen_at. Zones with a low mean age — listings are mostly
new arrivals — score high. Zones with a high mean age — same listings
have been sitting in our index — score low.

History-depth guard: when first_seen_at across all dense zones spans less
than 1 day (i.e. the sidecar is too new), the leg returns the neutral
default 50.0 with an "insufficient history" reason. This gates the leg
behind real signal — when nightly cron has run for a week+ and zones have
differing mean ages, the gate opens automatically and the leg starts
contributing. No code change needed when the data matures.

Why we replaced the prior `is_repriced` algorithm: the audit on 811 live
listings showed 0% of broker titles or descriptions contain "REBAJADO",
"REDUCED", or any equivalent repricing marker. The fixture data that
informed the prior design was curated and didn't reflect actual SV broker
conventions. is_repriced as a "Momentum" signal was also a stretch
semantically — it captures seller distress / capitulation, not actual
market acceleration. Listing-velocity is closer to the real thing.

Default weight 0.25 (unchanged).
"""
from __future__ import annotations
from bisect import bisect_left
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from pulpo.agents import RANKER_LEGS, register

if TYPE_CHECKING:
    from pulpo.models import Listing


# Minimum listings per zone before we trust the velocity signal. Below this,
# the per-zone mean age is too noisy to be meaningful.
MIN_ZONE_LISTINGS = 5

# Minimum time-span (in days) across all dense-zone mean ages before the
# leg actually contributes. Below this, the sidecar is too young to give
# a meaningful relative ranking — every zone has the same near-zero mean
# age. Default 1 day; once the cron has run for ~3-7 days and zones diverge
# in their first_seen_at distributions, this gate opens automatically.
MIN_HISTORY_SPAN_DAYS = 1.0

NEUTRAL_SCORE = 50.0


def _parse_iso(s: str | None) -> datetime | None:
    """Tolerant ISO8601 parser. Returns None on parse failure."""
    if not s:
        return None
    try:
        # Handle trailing Z (Python's fromisoformat doesn't accept it pre-3.11).
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _zone_mean_ages_days(comp_pool: list["Listing"], now: datetime | None = None) -> dict[str, float]:
    """Mean age (in days) of listings' first_seen_at, per zone.

    Only zones with at least MIN_ZONE_LISTINGS appear in the result. Listings
    without a first_seen_at or with an unparseable timestamp are skipped.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    by_zone_ages: dict[str, list[float]] = {}
    for li in comp_pool:
        z = li.zone
        if not z:
            continue
        ts = _parse_iso(getattr(li, "first_seen_at", None))
        if ts is None:
            continue
        age_days = (now - ts).total_seconds() / 86400.0
        by_zone_ages.setdefault(z, []).append(age_days)

    return {
        z: sum(ages) / len(ages)
        for z, ages in by_zone_ages.items()
        if len(ages) >= MIN_ZONE_LISTINGS
    }


class MomentumLeg:
    slug = "momentum"
    weight = 0.25
    env_weight_key = "PULPO_W_MOMENTUM"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        mean_ages = _zone_mean_ages_days(comp_pool)
        zone = listing.zone

        # No zone, or zone is sparse → neutral.
        if not zone or zone not in mean_ages:
            return NEUTRAL_SCORE, f"momentum {NEUTRAL_SCORE:.0f} (sparse zone, no signal)"

        sorted_ages = sorted(mean_ages.values())
        history_span = sorted_ages[-1] - sorted_ages[0]

        # Sidecar is too new to differentiate zones. When the cron has
        # accumulated several days of runs and zones diverge in mean age,
        # this gate opens automatically.
        if history_span < MIN_HISTORY_SPAN_DAYS:
            return NEUTRAL_SCORE, (
                f"momentum {NEUTRAL_SCORE:.0f} "
                f"(insufficient history: {history_span:.1f}d range, "
                f"need ≥{MIN_HISTORY_SPAN_DAYS:.0f}d)"
            )

        zone_age = mean_ages[zone]
        # Lower mean age (newer listings) → higher percentile → higher score.
        # bisect_left gives the count of zones with strictly lower mean age,
        # i.e. zones that are newer / hotter than this one. Invert via (1-r).
        rank = bisect_left(sorted_ages, zone_age) / len(sorted_ages)
        score = 100.0 * (1 - rank)
        return score, (
            f"momentum {score:.0f} "
            f"(zone mean age {zone_age:.1f}d in {sorted_ages[0]:.1f}-"
            f"{sorted_ages[-1]:.1f}d range)"
        )


register(RANKER_LEGS, "momentum", MomentumLeg())
