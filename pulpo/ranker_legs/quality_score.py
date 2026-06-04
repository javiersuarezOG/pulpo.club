"""Quality-score ranker leg — PRD A6.

Adds the listing's soft quality_score (0..9, computed by
`pulpo.quality_score.compute`) as a small ranking nudge on top of
the three primary legs (value / location / momentum).

Default weight: 0.05 — small enough that two listings within a few
points of value+location+momentum tied can still flip on
quality_score, but not enough to reshuffle the top of the ranking
based on metadata completeness alone. The PRD is explicit: this is
"used for Ranking, Not Filtering" — visibility is decided by
`pulpo.filter_config` (A2) and `pulpo.derived_rules`, not this leg.

Re-weight via `PULPO_W_QUALITY` env var.

After renormalization the three pre-existing legs keep ~95% of
their original weight (0.40 + 0.35 + 0.25 + 0.05 = 1.05 → each
divides by 1.05).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pulpo.agents import RANKER_LEGS, register
from pulpo.quality_score import MAX_SCORE

if TYPE_CHECKING:
    from pulpo.models import Listing


class QualityScoreLeg:
    slug = "quality_score"
    weight = 0.05
    env_weight_key = "PULPO_W_QUALITY"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        """Read pre-computed `quality_score` from the listing.

        The score is stamped on the listing by `automation/run.py` after
        `derive_is_incomplete` but before `ranker.rank()`. We read it
        here rather than re-computing per-leg-call to avoid duplicating
        the predicate logic across the codebase.
        """
        raw = getattr(listing, "quality_score", None)
        if not isinstance(raw, int):
            return 0.0, "quality_score 0 (not computed)"
        if raw < 0:
            raw = 0
        if raw > MAX_SCORE:
            raw = MAX_SCORE
        normalized = 100.0 * (raw / MAX_SCORE)
        return normalized, f"quality_score {normalized:.0f} ({raw}/{MAX_SCORE})"


register(RANKER_LEGS, "quality_score", QualityScoreLeg())
