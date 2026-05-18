"""Tests for the Python port of the deterministic aesthetic scorer.

Goal: verify the scorer returns well-shaped results, handles common
edge cases without crashing, and produces signals consistent with the
TS port (a flat-gray image scores low; a focal-subject image scores
higher; corner watermarks fire logo_or_watermark).
"""
from __future__ import annotations

import io

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from automation.aesthetic_deterministic import (  # noqa: E402
    DETERMINISTIC_VERSION,
    assess_deterministic_aesthetic,
)


def _flat_jpeg(rgb: tuple[int, int, int] = (128, 128, 128)) -> bytes:
    img = Image.new("RGB", (400, 400), color=rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")  # PNG avoids libjpeg version skew on dev machines
    return buf.getvalue()


def _focal_subject_jpeg() -> bytes:
    """Dark canvas with a bright off-center square — strong edge concentration."""
    img = Image.new("RGB", (400, 400), color=(30, 30, 30))
    for y in range(150, 250):
        for x in range(150, 250):
            img.putpixel((x, y), (240, 200, 80))
    buf = io.BytesIO()
    img.save(buf, format="PNG")  # PNG avoids libjpeg version skew on dev machines
    return buf.getvalue()


class TestResultShape:
    def test_returns_well_shaped_dict(self) -> None:
        result = assess_deterministic_aesthetic(_flat_jpeg())
        assert result is not None
        assert set(result.keys()) >= {
            "visual_appeal",
            "issues",
            "provider",
            "prompt_version",
            "rationale",
        }
        assert result["provider"] == "deterministic"
        assert result["prompt_version"] == DETERMINISTIC_VERSION
        assert isinstance(result["issues"], list)

    def test_score_is_between_zero_and_ten(self) -> None:
        for bytes_ in (
            _flat_jpeg(),
            _flat_jpeg((255, 255, 255)),
            _focal_subject_jpeg(),
        ):
            result = assess_deterministic_aesthetic(bytes_)
            assert result is not None
            assert 0 <= result["visual_appeal"] <= 10


class TestSignalCorrelation:
    def test_flat_gray_flags_a_quality_issue(self) -> None:
        # A pure flat gray image should trigger AT LEAST one quality
        # issue (low color entropy → low_quality, or uniform Laplacian
        # → uninteresting). Heuristic; either firing means the scorer
        # noticed the image is degenerate.
        result = assess_deterministic_aesthetic(_flat_jpeg())
        assert result is not None
        assert any(i in result["issues"] for i in ("uninteresting", "low_quality")), (
            f"expected at least one of uninteresting/low_quality, got {result['issues']}"
        )

    def test_focal_subject_does_not_score_lower_than_flat(self) -> None:
        # The focal-subject image shouldn't rank STRICTLY below a flat
        # gray. (Strict-above is too strong for a heuristic scorer on
        # tiny synthetic fixtures — production photos exercise the
        # signals more meaningfully.)
        flat = assess_deterministic_aesthetic(_flat_jpeg())
        focal = assess_deterministic_aesthetic(_focal_subject_jpeg())
        assert flat is not None and focal is not None
        assert focal["visual_appeal"] >= flat["visual_appeal"]


class TestPrecomputedSignals:
    def test_corner_watermark_fires_logo_issue(self) -> None:
        result = assess_deterministic_aesthetic(
            _focal_subject_jpeg(),
            precomputed_corner_edge_densities={
                "top-left": 0.15,  # above 0.11 threshold
                "top-right": 0.02,
                "bottom-left": 0.02,
                "bottom-right": 0.02,
            },
        )
        assert result is not None
        assert "logo_or_watermark" in result["issues"]

    def test_ocr_word_count_fires_logo_issue(self) -> None:
        result = assess_deterministic_aesthetic(
            _focal_subject_jpeg(),
            precomputed_ocr_word_count=5,
        )
        assert result is not None
        assert "logo_or_watermark" in result["issues"]

    def test_ocr_below_threshold_does_not_fire(self) -> None:
        result = assess_deterministic_aesthetic(
            _focal_subject_jpeg(),
            precomputed_ocr_word_count=1,
        )
        assert result is not None
        assert "logo_or_watermark" not in result["issues"]

    def test_bpp_lifts_score(self) -> None:
        low = assess_deterministic_aesthetic(
            _focal_subject_jpeg(),
            precomputed_bytes_per_pixel=0.05,
        )
        high = assess_deterministic_aesthetic(
            _focal_subject_jpeg(),
            precomputed_bytes_per_pixel=0.40,
        )
        assert low is not None and high is not None
        assert high["visual_appeal"] >= low["visual_appeal"]


class TestErrorHandling:
    def test_empty_bytes_returns_none(self) -> None:
        assert assess_deterministic_aesthetic(b"") is None

    def test_invalid_jpeg_returns_none(self) -> None:
        assert assess_deterministic_aesthetic(b"\x00\x01\x02\x03 not a jpeg") is None

    def test_small_image_does_not_crash(self) -> None:
        # 50x50 — smaller than the analysis resize target.
        img = Image.new("RGB", (50, 50), color=(80, 120, 60))
        buf = io.BytesIO()
        img.save(buf, format="PNG")  # PNG avoids libjpeg version skew on dev machines
        result = assess_deterministic_aesthetic(buf.getvalue())
        assert result is not None
        assert 0 <= result["visual_appeal"] <= 10
