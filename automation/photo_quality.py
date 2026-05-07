"""
PR-7.6 — heuristic photo-quality scoring.

Per-photo composite score in [0, 100] based on cheap, reliable signals:

- Resolution (raw width × height before any pipeline downscale)
- File size (proxy for compression aggression)
- Aspect ratio (between 4:3 and 21:9 reads well in cards/hero)
- Sharpness via OpenCV Laplacian variance (blur detector)
- Format / load gate — image must decode cleanly

Phase 1 of the two-phase strategy laid out in the WS plan: heuristics
ship first, free, and filter most low-quality photos. A future Phase 2
would bolt on a vision-model review for the top-N candidates.

Pure functions over `bytes` (raw image content) + size hint. No I/O,
no listing knowledge — the caller owns when/how to score.

Caller pattern (see automation/run.py:_download_hero_photos):

    raw = httpx.get(url, ...).content
    score = compute_score(raw, byte_size=len(raw))
    li.hero_photo_quality_score = score

OpenCV is optional. When `cv2` isn't importable (lean CI runners,
local dev without the headless OpenCV), the sharpness leg is skipped
and the score falls back to resolution + size + aspect ratio + format.
The fallback path is the only behavior tests run.
"""
from __future__ import annotations

import io
from typing import Optional


# Buckets per the plan (gstack design review). The boundaries are
# multiplicative steps so a 4× resolution jump (HD→4K) reads as a
# meaningful score bump, not a tiny noisy delta.
_RESOLUTION_TIERS = (
    (1920 * 1080, 100),     # full HD or better
    (1280 * 720,   70),     # HD
    (800  * 600,   40),     # passable
    (0,             0),     # below 800×600 — score 0 (gate)
)

# File size in bytes. Tiny files = aggressive compression / thumbnail.
_SIZE_BONUS_BYTES = (
    (200_000,  20),         # ≥ 200 KB
    (100_000,  10),         # ≥ 100 KB
    (0,         0),         # neutral
)
_SIZE_PENALTY_THRESHOLD = 50_000   # < 50 KB → −20

# Sharpness — Laplacian variance of grayscale pixels. Higher = sharper
# edges. Numbers calibrated against ~50 hand-classified Pulpo photos.
_SHARPNESS_BONUS = (
    (100, 30),
    (50,  10),
)
_SHARPNESS_BLUR_THRESHOLD = 20    # < 20 → −30 (likely blurry)


def _resolution_score(width: int, height: int) -> int:
    pixels = width * height
    for threshold, score in _RESOLUTION_TIERS:
        if pixels >= threshold:
            return score
    return 0


def _size_delta(byte_size: int) -> int:
    """+0..+20 bonus for adequate file size, −20 if too small."""
    if byte_size < _SIZE_PENALTY_THRESHOLD:
        return -20
    for threshold, bonus in _SIZE_BONUS_BYTES:
        if byte_size >= threshold:
            return bonus
    return 0


def _aspect_ratio_delta(width: int, height: int) -> int:
    """+10 if aspect is within [4:3, 21:9]; 0 otherwise.

    Penalizes 1:2 or worse (ultra-narrow / tall phone shots that crop
    poorly into card thumbnails).
    """
    if width <= 0 or height <= 0:
        return 0
    ratio = width / height if width >= height else height / width
    # Card and hero crops live between 1.33 (4:3) and 2.33 (21:9).
    if 1.33 <= ratio <= 2.33:
        return 10
    return 0


def _sharpness_delta_from_bytes(raw: bytes) -> int:
    """OpenCV Laplacian variance. Returns 0 when cv2/numpy isn't available."""
    try:
        import cv2          # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return 0

    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0

    var = cv2.Laplacian(img, cv2.CV_64F).var()
    if var < _SHARPNESS_BLUR_THRESHOLD:
        return -30
    for threshold, bonus in _SHARPNESS_BONUS:
        if var >= threshold:
            return bonus
    return 0


def compute_score(raw_bytes: bytes, byte_size: Optional[int] = None) -> int:
    """Return a heuristic quality score in [0, 100] for the given image bytes.

    Args:
        raw_bytes: image file bytes (jpeg / png / webp).
        byte_size: optional override for the file size used in scoring.
                   Defaults to len(raw_bytes). Pass the original wire
                   size when the bytes have been re-compressed in-flight.

    Returns:
        Integer score in [0, 100]. 0 means "do not show": image
        couldn't decode, was below 800×600, OR the composite score
        landed at zero. Caller treats `score == 0` as a hard gate.
    """
    if not raw_bytes:
        return 0

    # PIL gate: the file must decode. Same Pillow already in
    # requirements.txt — no extra dep here.
    try:
        from PIL import Image
    except ImportError:
        # Without Pillow we can't read dimensions; refuse to score.
        return 0

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
        width, height = img.size
    except Exception:
        return 0

    if width < 800 or height < 600:
        # Hard floor — Card hero crops at 600px wide so anything under
        # 800×600 source ends up upscaled and ugly.
        return 0

    if byte_size is None:
        byte_size = len(raw_bytes)

    score = _resolution_score(width, height)
    score += _size_delta(byte_size)
    score += _aspect_ratio_delta(width, height)
    score += _sharpness_delta_from_bytes(raw_bytes)

    # Clamp to [0, 100]. Scores can otherwise drift to ±200 with all
    # bonuses or all penalties firing.
    return max(0, min(100, score))


def score_band(score: Optional[int]) -> str:
    """Human-readable band — used in run.py log output + featured pick."""
    if score is None:
        return "unscored"
    if score >= 80:
        return "excellent"
    if score >= 60:
        return "good"
    if score >= 40:
        return "ok"
    if score >= 20:
        return "poor"
    return "reject"
