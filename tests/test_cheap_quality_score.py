"""
Tests for automation/photo_quality.py::cheap_quality_score — the
composite gate used to decide which candidate photos earn an
expensive aesthetic LLM call.

The helper is a pure transform over already-computed cheap signals;
no image I/O happens here when the signals are passed explicitly.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.photo_quality import cheap_quality_score  # noqa: E402


def test_clean_high_tech_returns_technical_unchanged():
    """A clean photo (no text overlay, hero-eligible) returns its
    technical score unchanged — that's the upper-bound contract."""
    assert (
        cheap_quality_score(
            b"unused",
            technical=80,
            has_text_overlay=False,
            hero_eligible=True,
        )
        == 80
    )


def test_text_overlay_penalty_is_50():
    """Brochure-style photos get penalized 50 — pushes them well below
    a peer that scored 30 on technical alone."""
    assert (
        cheap_quality_score(
            b"unused",
            technical=80,
            has_text_overlay=True,
            hero_eligible=True,
        )
        == 30
    )


def test_not_hero_eligible_penalty_is_10():
    """A small but otherwise-clean photo loses 10. Smaller hit than the
    text-overlay penalty — low-res clean photos are still preferable to
    high-res brochures."""
    assert (
        cheap_quality_score(
            b"unused",
            technical=80,
            has_text_overlay=False,
            hero_eligible=False,
        )
        == 70
    )


def test_both_penalties_stack():
    """A small brochure photo: technical 80 − 50 − 10 = 20."""
    assert (
        cheap_quality_score(
            b"unused",
            technical=80,
            has_text_overlay=True,
            hero_eligible=False,
        )
        == 20
    )


def test_clamps_at_zero():
    """Total negatives don't go below 0 — the helper produces a sort key,
    not a signed delta."""
    assert (
        cheap_quality_score(
            b"unused",
            technical=10,
            has_text_overlay=True,
            hero_eligible=False,
        )
        == 0
    )


def test_clamps_at_hundred():
    """Defense in depth — even if a caller passes technical=120, the
    output stays in [0, 100]."""
    assert (
        cheap_quality_score(
            b"unused",
            technical=120,
            has_text_overlay=False,
            hero_eligible=True,
        )
        == 100
    )


def test_missing_flags_treated_neutral():
    """None on either flag = no penalty applied. Mirrors the existing
    null-tolerance pattern in detect_text_overlay (None means 'no
    signal, don't exclude')."""
    assert (
        cheap_quality_score(
            b"unused",
            technical=70,
            has_text_overlay=None,
            hero_eligible=None,
        )
        == 70
    )


def test_zero_technical_is_respected_not_recomputed():
    """A caller who explicitly passes technical=0 must get 0 back, not
    have compute_score() re-run on the bytes. Guards against the
    ``technical or compute_score()`` falsy-fallback bug."""
    assert (
        cheap_quality_score(
            b"unused",
            technical=0,
            has_text_overlay=False,
            hero_eligible=True,
        )
        == 0
    )


def test_missing_technical_falls_back_to_compute_score():
    """When the caller omits ``technical``, the helper decodes the bytes
    via compute_score. Empty bytes → compute_score returns 0 → cheap
    score is 0."""
    assert cheap_quality_score(b"") == 0
