"""Tests for pulpo.ranker_legs.quality_score — the soft quality-score
ranker leg added in PR A6.

The leg reads pre-computed `listing.quality_score` (stamped by
automation/run.py via pulpo.quality_score.compute) and scales
0..MAX_SCORE → 0..100 for the composite. Weight defaults to 0.05;
after renormalization
the three pre-existing legs (value 0.40, location 0.35, momentum 0.25)
keep ~95% of their original weight.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pulpo.agents import RANKER_LEGS
from pulpo.quality_score import MAX_SCORE
from pulpo.ranker_legs.quality_score import QualityScoreLeg


@dataclass
class _FakeListing:
    quality_score: Optional[int] = None


def test_leg_registered_under_quality_score_slug():
    """Side-effect-on-import registration must put the leg under the
    `quality_score` slug so the ranker's iteration includes it."""
    assert "quality_score" in RANKER_LEGS
    assert isinstance(RANKER_LEGS["quality_score"], QualityScoreLeg)


def test_default_weight_is_a_rank_nudge_not_reshuffle():
    """0.05 default — small enough that quality_score can't reshuffle
    the top of the ranking, big enough to break ties. PRD A6 explicit."""
    assert QualityScoreLeg.weight == 0.05


def test_env_weight_key_follows_convention():
    assert QualityScoreLeg.env_weight_key == "PULPO_W_QUALITY"


def test_missing_quality_score_returns_neutral_zero():
    """A listing without `quality_score` returns 0 (no rank bonus).
    Never raises; never gates visibility."""
    leg = QualityScoreLeg()
    score, reason = leg.score(_FakeListing(quality_score=None), [])
    assert score == 0.0
    assert "not computed" in reason


def test_max_quality_score_maps_to_one_hundred():
    leg = QualityScoreLeg()
    score, _ = leg.score(_FakeListing(quality_score=MAX_SCORE), [])
    assert score == 100.0


def test_zero_quality_score_maps_to_zero():
    leg = QualityScoreLeg()
    score, _ = leg.score(_FakeListing(quality_score=0), [])
    assert score == 0.0


def test_intermediate_quality_score_scales_linearly():
    leg = QualityScoreLeg()
    raw = 3
    score, _ = leg.score(_FakeListing(quality_score=raw), [])
    # MAX_SCORE-relative so the assertion survives a bump (3/11*100 ≈ 27.3
    # after the image-fitness inputs landed; was 3/9 ≈ 33.3).
    expected = 100.0 * (raw / MAX_SCORE)
    assert abs(score - expected) < 0.5


def test_out_of_range_quality_score_is_clamped():
    """Defense against a stamp loop writing an out-of-range value
    (e.g. a future change to MAX_SCORE not propagating)."""
    leg = QualityScoreLeg()
    high, _ = leg.score(_FakeListing(quality_score=20), [])
    low, _ = leg.score(_FakeListing(quality_score=-5), [])
    assert high == 100.0
    assert low == 0.0


def test_quality_score_reason_includes_raw_score():
    leg = QualityScoreLeg()
    _, reason = leg.score(_FakeListing(quality_score=6), [])
    # MAX_SCORE-relative so the assertion survives a bump (now 11 after the
    # image-fitness inputs landed in pulpo.quality_score).
    assert f"6/{MAX_SCORE}" in reason


def test_ranker_includes_quality_leg_in_composite():
    """Smoke test: an end-to-end rank() call must include quality_score
    in the composite weights without exploding on missing fields."""
    # Lazy import — pulpo.ranker triggers side-effect leg registration.
    from pulpo.ranker import rank
    from pulpo.models import Listing

    listings = [
        Listing(
            source="encuentra24",
            source_id=f"x{i}",
            url=f"https://example.test/{i}",
            title=f"Listing {i}",
            country="SV",
            zone="el-zonte",
            price_usd=100_000 + i * 1000,
            area_m2=500,
            property_type="land",
            photos_count=3,
            scraped_at="2026-06-04T00:00:00+00:00",
            quality_score=q,
        )
        for i, q in enumerate([0, 3, 6, 9])
    ]
    ranked = rank(listings)
    assert len(ranked) == 4
    # Higher quality_score should NOT reshuffle when other signals are
    # near-identical — quality is a NUDGE at 0.05 weight. We confirm
    # every listing got a rank assigned and the leg ran.
    for li in ranked:
        assert li.rank_score is not None
        # The reason chain must include the quality_score breadcrumb.
        assert any("quality_score" in r for r in (li.rank_reasons or []))
