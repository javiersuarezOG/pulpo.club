"""Tests for automation/image_hash.py — within-listing photo dedup
(image-pipeline audit 2026-07-29, PR-F).

Pins: content_sha1 identity + key length; dhash decode-fail → None;
near-duplicate detection under re-encode/resize; that two genuinely
different images do NOT collapse; and the dedupe_within_listing grouping
contract (representative = highest cheap_score, order preserved, dupes
tagged with reason).

Uses PNG fixtures (avoids the libjpeg-version mismatch on dev machines).
"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.image_hash import (  # noqa: E402
    content_sha1,
    dhash,
    hamming,
    dedupe_within_listing,
    DHASH_HAMMING_THRESHOLD,
)


def _textured_png(width: int, height: int, *, phase: float = 0.0, fmt: str = "PNG") -> bytes:
    """A smooth 2D wave pattern normalized to the image size — carries
    real tonal structure in BOTH axes (so the dhash has a rich set-bit
    population, not the degenerate all-0 of a flat/gradient image) yet is
    low-frequency, so it survives resize + JPEG re-encode as a near-dup
    (mirrors a real photo). `phase` shifts the pattern to make a clearly
    different image; `fmt` re-encodes the same picture as JPEG."""
    from PIL import Image

    img = Image.new("RGB", (width, height))
    px = []
    for y in range(height):
        fy = y / max(1, height - 1)
        for x in range(width):
            fx = x / max(1, width - 1)
            wave = math.sin(6.0 * fx + phase) * math.cos(6.0 * fy + phase)
            v = int(255 * (0.5 + 0.5 * wave))
            px.append((v, (v + 40) % 256, (v + 80) % 256))
    img.putdata(px)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _distinct_png(width: int, height: int) -> bytes:
    """A visually different image: vertical bands."""
    from PIL import Image

    img = Image.new("RGB", (width, height))
    px = []
    for y in range(height):
        for x in range(width):
            v = 0 if (x // 8) % 2 == 0 else 255
            px.append((v, v, v))
    img.putdata(px)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _solid_png(width: int, height: int, color=(200, 200, 200)) -> bytes:
    """A flat solid-color image — degenerate dhash (no structure)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


# Back-compat alias for the tests below (the fixture gained structure but
# the call sites read naturally as "a textured gradient-like image").
_gradient_png = _textured_png


# ── content_sha1 ──────────────────────────────────────────────────────

def test_content_sha1_is_stable_and_16_hex():
    raw = _gradient_png(64, 64)
    h = content_sha1(raw)
    assert h == content_sha1(raw)
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_content_sha1_differs_on_different_bytes():
    assert content_sha1(_gradient_png(64, 64)) != content_sha1(_distinct_png(64, 64))


def test_content_sha1_matches_picker_excluded_convention():
    """PR-F reuses the picker_excluded key convention so a photo has one
    identity across stores."""
    from automation.picker_excluded import _cache_key

    raw = _gradient_png(48, 48)
    assert content_sha1(raw) == _cache_key(raw)


# ── dhash ─────────────────────────────────────────────────────────────

def test_dhash_none_on_garbage():
    assert dhash(b"") is None
    assert dhash(b"\x00\x01 not an image \xff") is None


def test_dhash_identical_bytes_zero_distance():
    raw = _gradient_png(200, 150)
    assert hamming(dhash(raw), dhash(raw)) == 0


def test_dhash_near_duplicate_under_threshold():
    """Same picture, re-encoded as JPEG + resized — near-duplicate must
    stay within the Hamming threshold."""
    original = _gradient_png(256, 192, fmt="PNG")
    reencoded = _gradient_png(240, 180, fmt="JPEG")  # different bytes, ~same image
    d1, d2 = dhash(original), dhash(reencoded)
    assert d1 is not None and d2 is not None
    assert hamming(d1, d2) <= DHASH_HAMMING_THRESHOLD


def test_dhash_distinct_images_over_threshold():
    d1 = dhash(_gradient_png(200, 150))
    d2 = dhash(_distinct_png(200, 150))
    assert hamming(d1, d2) > DHASH_HAMMING_THRESHOLD


# ── dedupe_within_listing ─────────────────────────────────────────────

def _cand(url: str, raw: bytes, cheap: int) -> dict:
    return {"url": url, "content": raw, "cheap_score": cheap}


def test_exact_duplicate_marked_lower_score_dropped():
    raw = _gradient_png(128, 96)
    cands = [
        _cand("a", raw, cheap=70),
        _cand("b", raw, cheap=40),  # exact dup, lower score → dropped
        _cand("c", _distinct_png(128, 96), cheap=55),
    ]
    dedupe_within_listing(cands)
    by_url = {c["url"]: c for c in cands}
    assert by_url["a"]["is_duplicate"] is False
    assert by_url["b"]["is_duplicate"] is True
    assert by_url["b"]["dup_of"] == "a"
    assert by_url["b"]["dup_reason"] == "exact"
    assert by_url["c"]["is_duplicate"] is False


def test_representative_is_highest_cheap_score():
    """When the later copy scores higher, it becomes the representative
    and the earlier one is demoted."""
    raw = _gradient_png(128, 96)
    cands = [
        _cand("low", raw, cheap=30),
        _cand("high", raw, cheap=90),  # same image, better score
    ]
    dedupe_within_listing(cands)
    by_url = {c["url"]: c for c in cands}
    assert by_url["high"]["is_duplicate"] is False
    assert by_url["low"]["is_duplicate"] is True
    assert by_url["low"]["dup_of"] == "high"


def test_near_duplicate_tagged_reason_near():
    original = _gradient_png(256, 192, fmt="PNG")
    reencoded = _gradient_png(240, 180, fmt="JPEG")
    cands = [_cand("orig", original, cheap=80), _cand("reenc", reencoded, cheap=50)]
    dedupe_within_listing(cands)
    by_url = {c["url"]: c for c in cands}
    assert by_url["reenc"]["is_duplicate"] is True
    assert by_url["reenc"]["dup_reason"] == "near"


def test_distinct_images_all_kept():
    cands = [
        _cand("a", _gradient_png(120, 90), cheap=60),
        _cand("b", _distinct_png(120, 90), cheap=60),
    ]
    dedupe_within_listing(cands)
    assert all(c["is_duplicate"] is False for c in cands)


def test_flat_images_do_not_perceptually_collapse():
    """Two DIFFERENT flat/solid images have degenerate (all-0) dhashes.
    The structure guard must stop them near-matching — only an exact byte
    match may dedupe a low-detail image. Regression for the false-positive
    that would have collapsed distinct placeholder tiles."""
    a = _solid_png(1920, 1080, color=(200, 200, 200))
    b = _solid_png(800, 600, color=(180, 180, 180))
    cands = [_cand("a", a, cheap=70), _cand("b", b, cheap=40)]
    dedupe_within_listing(cands)
    assert all(c["is_duplicate"] is False for c in cands)


def test_identical_flat_images_still_exact_dedupe():
    """A structure guard must not disable EXACT dedup — byte-identical
    flat tiles are still duplicates."""
    raw = _solid_png(400, 300)
    cands = [_cand("a", raw, cheap=50), _cand("b", raw, cheap=20)]
    dedupe_within_listing(cands)
    by_url = {c["url"]: c for c in cands}
    assert by_url["b"]["is_duplicate"] is True
    assert by_url["b"]["dup_reason"] == "exact"


def test_hashes_stamped_on_every_candidate():
    cands = [_cand("a", _gradient_png(64, 64), cheap=50)]
    dedupe_within_listing(cands)
    assert cands[0]["content_sha1"] is not None
    assert cands[0]["dhash"] is not None


def test_empty_and_missing_content_are_safe():
    cands = [{"url": "x", "content": None, "cheap_score": 0}]
    dedupe_within_listing(cands)
    assert cands[0]["is_duplicate"] is False
    assert dedupe_within_listing([]) == []
