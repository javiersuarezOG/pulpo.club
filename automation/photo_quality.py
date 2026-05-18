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


# ── Image-enrichment metadata (hero rewrite Phase 2) ───────────────────
#
# Image-enrichment is a separate concern from the per-photo quality
# score above. The eligibility flags below gate which photos can serve
# as the homepage hero / proof-row image vs. the card thumbnail. The
# numeric score still feeds the featured-pool ranker tie-break; the
# flags answer the structural question "is this file the right size +
# aspect for this surface."
#
# Gates (per the rewrite plan):
#   hero_eligible: width >= 1600 AND height >= 1200
#                  AND 1.4 <= aspect_ratio <= 1.85
#                  AND file_size_kb <= 5120 (5 MB)
#   card_eligible: width >= 800 AND height >= 600
#
# Both are evaluated against the on-disk derivative file, not the raw
# source bytes. Source bytes are discarded after pipeline processing
# (we keep only the thumbnail at <file>.jpg and the hero derivative
# at <file>.hero.jpg). Sidecar JSONs at <file>.jpg.meta.json and
# <file>.hero.jpg.meta.json record the per-file dimensions so re-
# computation is fast on subsequent runs.

HERO_MIN_WIDTH_PX   = 1600
HERO_MIN_HEIGHT_PX  = 1200
HERO_MIN_ASPECT     = 1.4
HERO_MAX_ASPECT     = 1.85
HERO_MAX_SIZE_KB    = 5120

CARD_MIN_WIDTH_PX   = 800
CARD_MIN_HEIGHT_PX  = 600

# Hi-res derivative gate — the new <file>.hires.jpg pipeline (plan v2)
# preserves the broker's native resolution. We require the source to be
# at least the social canonical (1080×1080) on both axes since anything
# smaller forces /api/social/image to upscale, which pulpo-social's
# resdet gate rejects. No aspect-ratio bound here — hires serves the
# pre-crop bytes; the social endpoint does its own cover-crop.
HIRES_MIN_WIDTH_PX  = 1080
HIRES_MIN_HEIGHT_PX = 1080
HIRES_MAX_SIZE_KB   = 10240  # 10 MB ceiling; brokers rarely exceed this


def compute_image_metadata(raw_bytes: bytes, *, file_size_bytes: Optional[int] = None) -> Optional[dict]:
    """Return the sidecar metadata dict for an image, or None when undecodable.

    Args:
        raw_bytes: image file bytes (jpeg/png/webp).
        file_size_bytes: optional override for on-disk size. Defaults to
                         ``len(raw_bytes)``. Pass the wire size when the
                         bytes have been recompressed since the on-disk
                         write so the sidecar reflects file truth.

    Returns:
        ``{width, height, aspect_ratio, file_size_kb, hero_eligible,
        card_eligible, computed_at}`` or ``None`` when Pillow isn't
        installed or the bytes don't decode.

    The ``hero_eligible`` / ``card_eligible`` flags reflect the gates
    against THIS file's properties. A 600×400 thumbnail file will
    always be card_eligible=False (under 800×600) — that's correct;
    the on-disk file IS the surface a card consumes. The card flag is
    only useful when the original source was at least 800×600 and we
    chose not to downsample.
    """
    if not raw_bytes:
        return None

    try:
        from PIL import Image
    except ImportError:
        return None

    import io
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
        width, height = img.size
    except Exception:
        return None

    if width <= 0 or height <= 0:
        return None

    size_bytes = file_size_bytes if file_size_bytes is not None else len(raw_bytes)
    file_size_kb = round(size_bytes / 1024, 1)

    # Aspect ratio is the long/short side so portrait photos read the
    # same value as their landscape rotation. The hero gate also bounds
    # via this normalized value — a portrait 600×1600 image would have
    # aspect 2.67 which fails the hero gate (correctly: we don't want
    # vertical phone photos full-bleed).
    long_side  = max(width, height)
    short_side = min(width, height)
    aspect = round(long_side / short_side, 3) if short_side > 0 else 0.0

    hero_eligible = (
        width >= HERO_MIN_WIDTH_PX
        and height >= HERO_MIN_HEIGHT_PX
        and HERO_MIN_ASPECT <= aspect <= HERO_MAX_ASPECT
        and file_size_kb <= HERO_MAX_SIZE_KB
    )
    card_eligible = (
        width >= CARD_MIN_WIDTH_PX
        and height >= CARD_MIN_HEIGHT_PX
    )
    hires_eligible = (
        width >= HIRES_MIN_WIDTH_PX
        and height >= HIRES_MIN_HEIGHT_PX
        and file_size_kb <= HIRES_MAX_SIZE_KB
    )

    from datetime import datetime, timezone
    return {
        "width":          width,
        "height":         height,
        "aspect_ratio":   aspect,
        "file_size_kb":   file_size_kb,
        "hero_eligible":  bool(hero_eligible),
        "card_eligible":  bool(card_eligible),
        "hires_eligible": bool(hires_eligible),
        "computed_at":    datetime.now(timezone.utc).isoformat(),
    }


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


# ── Composite of cheap signals (Phase 4 U3 cost-gating helper) ─────────
#
# Used by automation/run.py to decide which candidate photos deserve an
# expensive aesthetic LLM call. Combines the technical score with the
# binary signals (text-overlay flag + hero-eligibility) into a single
# 0-100 number suitable for sorting. The penalties are intentionally
# coarse — the goal is to push obviously-bad candidates below the top-X%
# threshold, not to rank fine differences between good photos.

_TEXT_OVERLAY_PENALTY = 50
_NOT_HERO_ELIGIBLE_PENALTY = 10


def cheap_quality_score(
    raw_bytes: bytes,
    *,
    technical: Optional[int] = None,
    has_text_overlay: Optional[bool] = None,
    hero_eligible: Optional[bool] = None,
) -> int:
    """Composite 0-100 of the non-LLM signals.

    Caller pattern in automation/run.py — pass the already-computed
    cheap-signal results so we don't re-decode the image:

        score = cheap_quality_score(
            raw,
            technical=compute_score(raw),
            has_text_overlay=detect_text_overlay(raw),
            hero_eligible=compute_image_metadata(raw)["hero_eligible"],
        )

    Any of ``technical``, ``has_text_overlay``, ``hero_eligible`` may be
    ``None`` — the helper falls back to ``compute_score(raw)`` for a
    missing technical score and treats missing flags as neutral (no
    penalty applied).
    """
    base = technical if technical is not None else compute_score(raw_bytes)
    if has_text_overlay is True:
        base -= _TEXT_OVERLAY_PENALTY
    if hero_eligible is False:
        base -= _NOT_HERO_ELIGIBLE_PENALTY
    return max(0, min(100, base))


# ── Text-overlay detection (brochure-style hero exclusion) ─────────────
#
# Brokers often submit listings with the first photo being a brochure:
# property image + price stamp + agency logo + "FOR SALE" banner. These
# read as advertising rather than property and look bad as a full-bleed
# hero. detect_text_overlay() flags such images so they can be excluded
# from the featured-listing pool (pulpo/featured_listing.py:_is_elite).
#
# Implementation: pytesseract over the raw image bytes. Words with
# confidence >= TEXT_MIN_CONF count toward two thresholds — flagged
# True if either holds. The two thresholds catch different failure
# modes:
#   - high word count → blocks of paragraph text (descriptions baked in)
#   - high area % → big "FOR SALE / VENDIDO" banners (few words but huge)
#
# Returns None when pytesseract isn't importable OR the tesseract binary
# isn't on PATH OR the image fails to decode. None means "no signal" —
# the caller treats it as "do not exclude" (same null-tolerance pattern
# as hero_photo_quality_score). A single warning is logged on the first
# missing-binary error per process; we don't spam logs across hundreds
# of photos in a nightly run.

TEXT_MIN_CONF = 60          # Tesseract confidence threshold per word
TEXT_MIN_WORDS = 8          # >= this many qualifying words → flag
TEXT_MIN_AREA_PCT = 5.0     # >= this % of image covered by text → flag

_TESSERACT_WARNED = False   # one-shot warning gate per process


def _detector_unavailable(reason: str) -> None:
    global _TESSERACT_WARNED
    if not _TESSERACT_WARNED:
        print(f"[photo_quality] text-overlay detection disabled: {reason}")
        _TESSERACT_WARNED = True


def detect_text_overlay(
    raw_bytes: bytes,
    *,
    min_word_count: int = TEXT_MIN_WORDS,
    min_area_pct: float = TEXT_MIN_AREA_PCT,
    min_word_confidence: int = TEXT_MIN_CONF,
) -> Optional[bool]:
    """Return True if the image carries a significant text overlay.

    Args:
        raw_bytes: image file bytes (jpeg / png / webp).
        min_word_count: word-count threshold for "lots of text".
        min_area_pct: bounding-box area threshold for "huge banner".
        min_word_confidence: ignore Tesseract words below this confidence.

    Returns:
        - True  → flagged: brochure-style or text-heavy
        - False → no/minimal text detected
        - None  → cannot decide (Tesseract missing, image undecodable, OCR error)

    None is the "no-signal" sentinel — featured_listing._is_elite
    treats a None as not-flagged, same convention as the score field.
    """
    if not raw_bytes:
        return None

    try:
        import pytesseract                       # type: ignore
    except ImportError:
        _detector_unavailable("pytesseract not installed")
        return None

    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
        width, height = img.size
    except Exception:
        return None

    if width <= 0 or height <= 0:
        return None

    try:
        data = pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
        )
    except pytesseract.TesseractNotFoundError:
        _detector_unavailable("tesseract binary not on PATH")
        return None
    except Exception as e:
        _detector_unavailable(f"tesseract error: {e!r}")
        return None

    confs = data.get("conf", [])
    texts = data.get("text", [])
    widths = data.get("width", [])
    heights = data.get("height", [])

    img_area = float(width * height)
    if img_area <= 0:
        return None

    qualifying_words = 0
    text_area = 0
    for conf, txt, w, h in zip(confs, texts, widths, heights):
        try:
            c = int(float(conf))
        except (TypeError, ValueError):
            continue
        if c < min_word_confidence:
            continue
        if not txt or not txt.strip():
            continue
        qualifying_words += 1
        try:
            text_area += int(w) * int(h)
        except (TypeError, ValueError):
            continue

    area_pct = 100.0 * text_area / img_area
    return qualifying_words >= min_word_count or area_pct >= min_area_pct
