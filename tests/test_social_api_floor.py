"""Regression guard for pulpo-social's /admin/trigger.

The trigger picks one listing per IG post from a random sample of N
candidates returned by ``/api/social/listings``. When the fleet's
pulpo-social-passable pool drops too low, the random sample finds zero
qualifying candidates and the trigger fails with
``no qualifying listing found``.

This has shipped to prod twice (2026-05-19 and 2026-05-20). Both
breakages were silent — CI green, prod red. This test makes that
failure mode loud at PR-review time by reading the committed
``web/data/ranked.json`` and asserting the qualifying pool stays above
a panic floor.

The qualifying-pool definition mirrors ``api/social/listings.js::passesQualityGate``
plus pulpo-social's downstream ``source≥1080²`` check:

  - hero_photo_path exists (no null-hero rows)
  - price_usd populated
  - data_quality_score >= 0.5
  - has_text_overlay !== true
  - has_marketing_overlay !== true
  - hero_photo_quality_score >= 50 (or null)
  - hero_eligible === true   (pulpo.club's photo_quality.py gate)
  - source_width >= 1080 AND source_height >= 1080
                            (pulpo-social's IG 1:1 crop floor)

Floor: 50 listings. With a 10-candidate trigger sample, that gives
~88% per-attempt success; below 50, the trigger is gambling. Today's
baseline (post HERO_MIN_*=1080 alignment) is ~217; floor is set well
below current for headroom but well above the broken state (26).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RANKED = REPO / "web" / "data" / "ranked.json"

PULPO_SOCIAL_PANIC_FLOOR = 50
"""Minimum qualifying-pool size below which pulpo-social's /admin/trigger
is statistically broken. Tuned for the default 10-candidate sample:
  - 217 (today's baseline) → 99.99% per-trigger success
  - 50  (panic floor)      → 88% per-trigger success
  - 26  (2026-05-20 break) → 24% per-trigger success
"""


def _qualifies_for_social(li: dict) -> bool:
    """Mirror api/social/listings.js::passesQualityGate + pulpo-social's
    downstream source-size gate. Keep this in sync with any change to
    either rule."""
    if not li.get("hero_photo_path"):
        return False
    if li.get("price_usd") is None:
        return False
    if (li.get("data_quality_score") or 0) < 0.5:
        return False
    if li.get("has_text_overlay") is True:
        return False
    if li.get("has_marketing_overlay") is True:
        return False
    qs = li.get("hero_photo_quality_score")
    if qs is not None and qs < 50:
        return False
    if li.get("hero_eligible") is not True:
        return False
    if (li.get("source_width") or 0) < 1080:
        return False
    if (li.get("source_height") or 0) < 1080:
        return False
    return True


def test_social_api_pool_above_panic_floor():
    data = json.loads(RANKED.read_text(encoding="utf-8"))
    qualifying = [li for li in data if _qualifies_for_social(li)]
    n = len(qualifying)
    assert n >= PULPO_SOCIAL_PANIC_FLOOR, (
        f"\n\nPulpo-social qualifying pool is {n}/{len(data)} — below the "
        f"{PULPO_SOCIAL_PANIC_FLOOR}-floor that guarantees ~88% per-trigger "
        f"success.\n"
        f"\n"
        f"Likely cause of regression (most→least common):\n"
        f"  1. photo_quality.py constants tightened\n"
        f"     (HERO_MIN_WIDTH_PX, HERO_MIN_HEIGHT_PX, HERO_MIN_ASPECT,\n"
        f"      HERO_MAX_ASPECT)\n"
        f"  2. _download_hero_photos source-bytes eligibility logic broke\n"
        f"     (li.hero_eligible computed from wrong derivative)\n"
        f"  3. Tesseract OR LLM Vision false-flagging legit photos\n"
        f"     (has_text_overlay / has_marketing_overlay)\n"
        f"  4. data_quality_score collapsed (enrichment regression)\n"
        f"\n"
        f"Investigate with `python3 tests/test_social_api_floor.py` (the\n"
        f"file is also runnable to print a per-rejection-reason breakdown)."
    )


def test_social_api_pool_qualifying_by_source():
    """Sanity check — at least 2 sources contribute to the pool. Catches
    the case where a single broker dominates and one scraper breakage
    starves the trigger fleet-wide."""
    data = json.loads(RANKED.read_text(encoding="utf-8"))
    qualifying = [li for li in data if _qualifies_for_social(li)]
    sources = {li.get("source") for li in qualifying if li.get("source")}
    assert len(sources) >= 2, (
        f"Only {len(sources)} source(s) contribute qualifying listings: "
        f"{sorted(sources)}. Single-source dominance means one scraper "
        f"regression starves the trigger fleet-wide."
    )


# Allow running as a script for a richer rejection breakdown.
if __name__ == "__main__":  # pragma: no cover — manual diagnostic
    data = json.loads(RANKED.read_text(encoding="utf-8"))
    reasons = {
        "no_hero_photo_path":    0,
        "no_price":              0,
        "low_data_quality":      0,
        "has_text_overlay":      0,
        "has_marketing_overlay": 0,
        "low_hero_quality":      0,
        "hero_ineligible":       0,
        "source_below_1080":     0,
    }
    qualifying = 0
    for li in data:
        if not li.get("hero_photo_path"):
            reasons["no_hero_photo_path"] += 1; continue
        if li.get("price_usd") is None:
            reasons["no_price"] += 1; continue
        if (li.get("data_quality_score") or 0) < 0.5:
            reasons["low_data_quality"] += 1; continue
        if li.get("has_text_overlay") is True:
            reasons["has_text_overlay"] += 1; continue
        if li.get("has_marketing_overlay") is True:
            reasons["has_marketing_overlay"] += 1; continue
        qs = li.get("hero_photo_quality_score")
        if qs is not None and qs < 50:
            reasons["low_hero_quality"] += 1; continue
        if li.get("hero_eligible") is not True:
            reasons["hero_ineligible"] += 1; continue
        if (li.get("source_width") or 0) < 1080 or (li.get("source_height") or 0) < 1080:
            reasons["source_below_1080"] += 1; continue
        qualifying += 1
    print(f"total: {len(data)}")
    print(f"qualifying: {qualifying} (floor={PULPO_SOCIAL_PANIC_FLOOR})")
    print(f"rejected by:")
    for r, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {r:30s} {n:>4}")
