"""Tests for automation/ig_photo_beauty.py — the heuristic beauty scorer.

Synthetic solid-colour images make the score components deterministic:
open sky/ocean scores high, flat grey/dark interiors score low.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from PIL import Image   # noqa: E402

from automation.ig_photo_beauty import (   # noqa: E402
    GORGEOUS_MIN, score_photo, is_gorgeous, score_breakdown,
)


def _solid(rgb):
    return Image.new("RGB", (400, 500), rgb)


def test_sky_blue_scores_high():
    assert score_photo(_solid((90, 160, 230))) >= GORGEOUS_MIN


def test_flat_grey_concrete_scores_low():
    # low saturation, mid brightness → the 'dull' penalty dominates
    assert score_photo(_solid((150, 150, 150))) < GORGEOUS_MIN


def test_dark_interior_scores_low():
    assert score_photo(_solid((30, 28, 26))) < GORGEOUS_MIN


def test_is_gorgeous_matches_threshold():
    assert is_gorgeous(_solid((80, 150, 235))) is True
    assert is_gorgeous(_solid((140, 138, 135))) is False


def test_score_is_bounded():
    for rgb in [(0, 0, 0), (255, 255, 255), (10, 120, 240), (128, 90, 60)]:
        s = score_photo(_solid(rgb))
        assert 0.0 <= s <= 100.0


def test_breakdown_detects_blue_and_dull():
    b_blue = score_breakdown(_solid((90, 160, 230)))
    assert b_blue["blue_frac"] > 0.9
    b_grey = score_breakdown(_solid((150, 150, 150)))
    assert b_grey["dull_frac"] > 0.9
