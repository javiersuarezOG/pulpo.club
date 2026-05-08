"""
Tests for automation/photo_quality.py — pin the heuristic-scoring
contract for hero photos.

OpenCV (cv2) is optional in CI; the sharpness leg is exercised via
in-memory PIL images and falls back gracefully when cv2 isn't present.
Tests don't depend on cv2 — they pin the resolution + size + aspect
+ format gate, and the calibration that sharpness is purely additive.
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.photo_quality import (   # noqa: E402
    compute_score,
    score_band,
    detect_text_overlay,
)


def _make_image(width: int, height: int) -> bytes:
    """Synthesize a PNG of given size. PNG instead of JPEG to avoid the
    libjpeg-version mismatch on dev machines (Pillow shipped against
    libjpeg-90, system libjpeg-80 → encoder errors).

    Random pixel data so the sharpness leg's Laplacian variance lands
    above the blur threshold rather than penalizing the flat fill.
    """
    from PIL import Image
    import random
    random.seed(width * height)  # reproducible
    img = Image.new("RGB", (width, height))
    pixels = [
        (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        for _ in range(width * height)
    ]
    img.putdata(pixels)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── format / load gate ─────────────────────────────────────────────────

def test_empty_bytes_score_zero():
    assert compute_score(b"") == 0


def test_garbage_bytes_score_zero():
    """Random bytes that don't decode → 0 (image gate)."""
    assert compute_score(b"\x00\x01\x02 NOT A JPEG \xff\xff") == 0


def test_under_minimum_resolution_score_zero():
    """Below 800×600 is the hard floor — gets 0 regardless of other signals."""
    raw = _make_image(640, 480)
    assert compute_score(raw) == 0


# ── resolution leg ────────────────────────────────────────────────────

def test_full_hd_starts_at_100():
    """1920×1080 at high quality → resolution leg gives 100; size + aspect
    can add bonuses; sharpness on a flat image gives 0 or +10/+30 depending
    on cv2 availability. Score lands at 100 (clamped) most of the time."""
    raw = _make_image(1920, 1080)
    assert compute_score(raw) >= 100 - 30   # at least 70 even if all penalties hit
    assert compute_score(raw) <= 100        # always clamped to 100


def test_hd_resolution_lands_in_good_band():
    raw = _make_image(1280, 720)
    score = compute_score(raw)
    # Resolution leg alone is 70; aspect bonus is +10; size bonus is variable.
    assert score >= 60


def test_passable_resolution_lands_below_full_hd_score():
    """Resolution is the strongest signal. A 1024×768 image must
    score below the same image grown to 1920×1080 (full HD jumps
    from the 40 bucket to the 100 bucket)."""
    small = compute_score(_make_image(1024, 768))
    full_hd = compute_score(_make_image(1920, 1080))
    # Both have noise (sharpness OK), so the only difference is the
    # resolution leg (+60) and the file size at the bigger image (+0..+20).
    assert small <= full_hd
    assert small >= 30   # passable image gets at least 30


# ── size leg ───────────────────────────────────────────────────────────

def test_tiny_file_gets_size_penalty():
    """Force the byte_size signal independently. A 1280×720 PNG with
    a synthetically tiny byte_size argument should score below the
    same image with the real (larger) byte_size."""
    raw = _make_image(1280, 720)
    score_with_real_size = compute_score(raw)
    score_with_tiny_size = compute_score(raw, byte_size=10_000)   # < 50KB → −20
    assert score_with_tiny_size < score_with_real_size


# ── aspect ratio leg ───────────────────────────────────────────────────

def test_phone_portrait_gets_no_aspect_bonus():
    """1080×2400 (modern phone portrait) is outside [4:3, 21:9].
    Resolution leg still applies (≥1920×1080 by total pixels)."""
    raw = _make_image(1080, 2400)
    # No aspect bonus, but resolution leg + maybe sharpness.
    # Compare to the same total resolution at landscape ratio.
    landscape = _make_image(1920, 1350)   # ≈4:2.8 → in the 4:3..21:9 band
    assert compute_score(raw) <= compute_score(landscape)


def test_widescreen_in_band():
    """16:9 (1920×1080) sits well inside [4:3, 21:9] → +10 aspect bonus."""
    raw = _make_image(1920, 1080)
    # All bonuses fire; compute_score clamps to 100.
    assert compute_score(raw) == 100


# ── score_band ────────────────────────────────────────────────────────

def test_score_band_brackets():
    assert score_band(None) == "unscored"
    assert score_band(85) == "excellent"
    assert score_band(80) == "excellent"
    assert score_band(70) == "good"
    assert score_band(60) == "good"
    assert score_band(50) == "ok"
    assert score_band(40) == "ok"
    assert score_band(30) == "poor"
    assert score_band(10) == "reject"
    assert score_band(0) == "reject"


def test_score_clamped_to_zero_to_hundred():
    """Even with all penalties OR all bonuses, the result stays in [0, 100]."""
    raw = _make_image(1920, 1080)
    score = compute_score(raw, byte_size=1)   # force size penalty
    assert 0 <= score <= 100


# ── detect_text_overlay ───────────────────────────────────────────────
#
# Tesseract is system-binary-dependent. The graceful-degradation tests
# run unconditionally and pin the contract that the pipeline never
# crashes when the binary is absent. Tesseract-dependent tests skip
# cleanly via @pytest.mark.skipif when the binary isn't installed —
# they document the *behavior* without forcing a binary install on
# every contributor's machine. CI installs tesseract-ocr so the
# positive-case tests run on every PR.

def _tesseract_available() -> bool:
    try:
        import pytesseract  # type: ignore
    except ImportError:
        return False
    try:
        from PIL import Image
        pytesseract.image_to_string(Image.new("RGB", (32, 32), "white"))
        return True
    except Exception:
        return False


def _make_text_overlay_image(text: str = "FOR SALE\n$250,000\nCONTACT NOW", size=(900, 700)) -> bytes:
    """Synthesize a brochure-style image: dark background + large text.
    Used by the text-detection tests when Tesseract is available."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", size, color=(40, 60, 90))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    for i, line in enumerate(text.split("\n")):
        for repeat_x in range(3):
            for repeat_y in range(3):
                draw.text(
                    (40 + repeat_x * 280, 40 + i * 120 + repeat_y * 40),
                    line,
                    fill=(255, 255, 255),
                    font=font,
                )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# Graceful-degradation contract — runs everywhere.

def test_detect_text_overlay_empty_bytes_returns_none():
    """Empty input → no signal. None means 'do not exclude' downstream."""
    assert detect_text_overlay(b"") is None


def test_detect_text_overlay_garbage_bytes_returns_none():
    """Bytes that don't decode as an image → no signal."""
    assert detect_text_overlay(b"\x00\x01 not an image \xff\xff") is None


def test_detect_text_overlay_no_pytesseract_returns_none(monkeypatch):
    """When pytesseract isn't importable, detector returns None instead
    of crashing — pipeline must still run on a leaner image."""
    import sys
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    raw = _make_image(900, 700)
    assert detect_text_overlay(raw) is None


# Tesseract-dependent tests — skip when the binary isn't available.

import pytest  # noqa: E402


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract binary not installed")
def test_detect_text_overlay_clean_image_returns_false():
    """Random-pixel image (no readable text) → not flagged."""
    raw = _make_image(900, 700)
    assert detect_text_overlay(raw) is False


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract binary not installed")
def test_detect_text_overlay_text_heavy_image_returns_true():
    """Image with prominent multi-line text → flagged. The fixture
    synthesises a dark backdrop with large white text repeated many
    times; this should comfortably exceed both the word-count and
    text-area thresholds. If Tesseract calibration drifts, lower
    min_word_count / min_area_pct via the kwargs to keep the test
    behavior-pinned rather than threshold-fragile."""
    raw = _make_text_overlay_image()
    assert detect_text_overlay(raw) is True
