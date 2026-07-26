"""ig_photo_beauty.py — heuristic aesthetic score for a listing photo.

The story feed must show a *gorgeous* photo OF the listing (Javier,
2026-07-26: "high quality and not generic", "same location as the
listing"). The pipeline's "hero" is chosen for representativeness, not
beauty, and most broker land shots are dull (concrete, dry brush,
interiors). This scorer lets the autopilot pick each listing's most
beautiful frame and *skip the listing entirely* when its best shot isn't
good enough — quality over cadence.

No ML model / no new heavy deps: a fast, explainable heuristic over the
pixels (numpy + Pillow, both already in the pipeline). It rewards the
things that make a coastal/nature shot sing — open blue sky, ocean/water,
green vegetation, overall vibrancy and good light — and penalises the
grey/brown flatness of concrete lots, dirt, and dim interiors. Imperfect
by design; paired with a threshold + the human Skip in /admin.

score_photo(img) -> float in [0, 100].  GORGEOUS_MIN is the gate.
"""
from __future__ import annotations

from PIL import Image

# Gate: a listing's best frame must clear this to be featured. Tuned so
# sky/ocean/pool/greenery shots pass and concrete/dirt/interior fail
# (validated against the campaign photo set).
GORGEOUS_MIN = 55.0

_SAMPLE_W = 128     # small: pure-Python pixel loop stays fast (~20k px)


def score_breakdown(img: Image.Image) -> dict:
    """Component scores over a downscaled HSV copy (pure Pillow, no numpy)."""
    img = img.convert("RGB")
    w, h = img.size
    if w > _SAMPLE_W:
        img = img.resize((_SAMPLE_W, max(1, round(h * _SAMPLE_W / w))), Image.BILINEAR)
    px = list(img.convert("HSV").getdata())     # [(H,S,V), …] each 0–255
    n = len(px) or 1

    blue = green = dull = dark = blown = 0
    s_sum = v_sum = 0.0
    for H, S, V in px:
        hf, sf, vf = H / 255.0, S / 255.0, V / 255.0
        s_sum += sf
        v_sum += vf
        if 0.52 <= hf <= 0.72 and vf >= 0.35 and sf >= 0.12:   # sky / ocean
            blue += 1
        if 0.20 <= hf <= 0.45 and sf >= 0.20 and vf >= 0.20:   # vegetation
            green += 1
        if sf < 0.15 and vf < 0.75:                            # grey/brown flat
            dull += 1
        if vf < 0.18:
            dark += 1
        if vf > 0.97:
            blown += 1
    return {
        "blue_frac": blue / n, "green_frac": green / n,
        "sat_mean": s_sum / n, "bright": v_sum / n, "dull_frac": dull / n,
        "dark_frac": dark / n, "blown_frac": blown / n, "n": n,
    }


def score_photo(img: Image.Image) -> float:
    """Aesthetic score in [0, 100]. Higher = more beautiful/scenic."""
    b = score_breakdown(img)
    score = 30.0
    score += 45.0 * min(b["blue_frac"] / 0.32, 1.0)      # open sky/ocean
    score += 18.0 * min(b["green_frac"] / 0.35, 1.0)     # vegetation
    score += 22.0 * min(max(b["sat_mean"] - 0.12, 0) / 0.33, 1.0)  # vibrancy
    # light: sweet spot ~0.45–0.8
    if b["bright"] < 0.28:
        score -= 22.0 * (0.28 - b["bright"]) / 0.28
    elif b["bright"] > 0.85:
        score -= 14.0 * (b["bright"] - 0.85) / 0.15
    score -= 42.0 * min(b["dull_frac"] / 0.6, 1.0)       # concrete/dirt/interior
    score -= 20.0 * min(b["dark_frac"] / 0.4, 1.0)
    score -= 14.0 * min(b["blown_frac"] / 0.3, 1.0)
    return float(max(0.0, min(100.0, score)))


def is_gorgeous(img: Image.Image, threshold: float = GORGEOUS_MIN) -> bool:
    return score_photo(img) >= threshold
