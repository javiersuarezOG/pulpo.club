"""Python port of pulpo-social's deterministic aesthetic scorer.

Mirrors ``pulpo-social/packages/photo-quality/src/core/aesthetic-deterministic.ts``.
No LLM, no network. Used by the hires pipeline as the per-listing aesthetic
signal that lands in the sidecar.

Signals (all deterministic, ~50ms per image on a 1080×1080 jpeg):

1. Edge-concentration Gini — divide image into 4×4 grid, compute
   per-cell Laplacian magnitude, then Gini coefficient over the 16
   cells. Peak around 0.40 = clear focal subject. Below 0.15 = uniform
   (boring or cluttered). Above 0.85 = single-hotspot, often a watermark.

2. Color entropy — Shannon entropy over an 8-bin-per-channel RGB
   histogram on a downsampled image. High entropy = many colors,
   visually interesting. Low entropy = drab.

3. Pre-computed PhotoMetrics signals (when caller passes them):
   - cornerEdgeDensities → if any corner exceeds 0.11, flag as
     logo_or_watermark.
   - ocrWordCount >= 2 → flag as logo_or_watermark.

Score blend (0-10):
   40% edge-Gini (bell curve around 0.40)
   30% color entropy
   20% cleanliness (binary: not flagged for watermark/text)
   10% bytes-per-pixel detail proxy (when provided)

Output shape matches the TS AestheticResult type:
   {"visual_appeal": float, "issues": [str], "provider": "deterministic",
    "prompt_version": str, "rationale": str}

Issues vocabulary (must match the TS port):
   "uninteresting" | "awkward_angle" | "cluttered" | "no_focal_point"
   | "poor_lighting" | "low_quality" | "logo_or_watermark"
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

DETERMINISTIC_VERSION = "2026-05-15.det-v1.py"

# Tuning knobs (mirror the TS values).
_GRID_SIZE = 4
_RESIZE_FOR_ANALYSIS = 400
_COLOR_HISTOGRAM_RESIZE = 64
_COLOR_HISTOGRAM_BINS_PER_CHANNEL = 8

_EDGE_GINI_PEAK = 0.40
_EDGE_GINI_PEAK_WIDTH = 0.30

_ISSUE_EDGE_GINI_UNINTERESTING_LT = 0.15
_ISSUE_EDGE_GINI_NO_FOCAL_POINT_GT = 0.85
_ISSUE_COLOR_ENTROPY_LOW_QUALITY_LT = 0.40

_CORNER_WATERMARK_THRESHOLD = 0.11


def assess_deterministic_aesthetic(
    raw_bytes: bytes,
    *,
    precomputed_corner_edge_densities: Optional[dict] = None,
    precomputed_ocr_word_count: Optional[int] = None,
    precomputed_bytes_per_pixel: Optional[float] = None,
) -> Optional[dict]:
    """Score an image. Returns None when Pillow / decode fails.

    Args:
        raw_bytes: image bytes (jpeg/png/webp).
        precomputed_*: optional pre-computed metrics from another pass
            (e.g. corner Laplacian densities, OCR word count, bytes/pixel)
            that the caller already has. Saves redundant work.
    """
    if not raw_bytes:
        return None

    try:
        from PIL import Image, ImageFilter, ImageStat  # noqa: F401
    except ImportError:
        return None

    import io
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
    except Exception:
        return None

    if img.mode not in ("RGB", "L"):
        try:
            img = img.convert("RGB")
        except Exception:
            return None

    edge_gini = _compute_edge_gini(img)
    color_entropy = _compute_color_entropy(img)

    issues: list[str] = []
    if edge_gini < _ISSUE_EDGE_GINI_UNINTERESTING_LT:
        issues.append("uninteresting")
    elif edge_gini > _ISSUE_EDGE_GINI_NO_FOCAL_POINT_GT:
        issues.append("no_focal_point")
    if color_entropy < _ISSUE_COLOR_ENTROPY_LOW_QUALITY_LT:
        issues.append("low_quality")

    has_corner_watermark = False
    if precomputed_corner_edge_densities:
        for v in precomputed_corner_edge_densities.values():
            if v is not None and v > _CORNER_WATERMARK_THRESHOLD:
                has_corner_watermark = True
                break
    has_text_overlay = (
        precomputed_ocr_word_count is not None and precomputed_ocr_word_count >= 2
    )
    if (has_corner_watermark or has_text_overlay) and "logo_or_watermark" not in issues:
        issues.append("logo_or_watermark")

    gini_01 = _bell_curve(edge_gini, _EDGE_GINI_PEAK, _EDGE_GINI_PEAK_WIDTH)
    entropy_01 = _clamp01(color_entropy)
    cleanliness_01 = 0.0 if "logo_or_watermark" in issues else 1.0
    bpp_01 = (
        _smooth_norm(precomputed_bytes_per_pixel, 0.15)
        if precomputed_bytes_per_pixel is not None
        else 0.5
    )

    score_01 = _clamp01(
        0.40 * gini_01 + 0.30 * entropy_01 + 0.20 * cleanliness_01 + 0.10 * bpp_01
    )
    visual_appeal = round(score_01 * 10, 1)

    return {
        "visual_appeal": visual_appeal,
        "issues": issues,
        "provider": "deterministic",
        "prompt_version": DETERMINISTIC_VERSION,
        "rationale": (
            f"edge_gini={edge_gini:.3f} color_entropy={color_entropy:.3f}"
            + (f" bpp={precomputed_bytes_per_pixel}" if precomputed_bytes_per_pixel is not None else "")
        ),
    }


def _compute_edge_gini(img) -> float:
    from PIL import Image, ImageFilter
    target = _RESIZE_FOR_ANALYSIS
    cell_size = target // _GRID_SIZE
    grey = img.resize((target, target), Image.LANCZOS).convert("L")
    edges = grey.filter(ImageFilter.Kernel((3, 3), [-1, -1, -1, -1, 8, -1, -1, -1, -1], 1, 0))
    pixels = list(edges.getdata())  # length target*target

    cells = [0] * (_GRID_SIZE * _GRID_SIZE)
    for y in range(target):
        cy = min(_GRID_SIZE - 1, y // cell_size)
        row_base = y * target
        for x in range(target):
            cx = min(_GRID_SIZE - 1, x // cell_size)
            cells[cy * _GRID_SIZE + cx] += pixels[row_base + x]
    return _gini(cells)


def _compute_color_entropy(img) -> float:
    from PIL import Image
    size = _COLOR_HISTOGRAM_RESIZE
    small = img.resize((size, size), Image.LANCZOS).convert("RGB")
    bins = _COLOR_HISTOGRAM_BINS_PER_CHANNEL
    bin_shift = max(0, 8 - int(math.log2(bins))) if bins > 0 else 0
    total_bins = bins * bins * bins
    hist = [0] * total_bins
    px = list(small.getdata())  # list of (r,g,b)
    for r, g, b in px:
        r_b = r >> bin_shift
        g_b = g >> bin_shift
        b_b = b >> bin_shift
        hist[r_b * bins * bins + g_b * bins + b_b] += 1
    n = len(px)
    if n == 0:
        return 0.0
    entropy = 0.0
    for c in hist:
        if c > 0:
            p = c / n
            entropy -= p * math.log2(p)
    return entropy / math.log2(total_bins) if total_bins > 1 else 0.0


def _gini(values: Sequence[float]) -> float:
    """Standard Gini coefficient on a non-negative distribution.

    0 = uniform, 1 = fully concentrated in a single bucket.
    """
    n = len(values)
    if n == 0:
        return 0.0
    s = sorted(values)
    total = sum(s)
    if total == 0:
        return 0.0
    weighted = sum((i + 1) * v for i, v in enumerate(s))
    return (2 * weighted) / (n * total) - (n + 1) / n


def _bell_curve(value: float, peak: float, width: float) -> float:
    d = (value - peak) / width
    return math.exp(-(d * d))


def _smooth_norm(value: float, threshold: float) -> float:
    if value <= 0:
        return 0.0
    x = value / threshold
    return _clamp01(x / (x + 2))


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))
