"""Surgical ranked.json patch — propagate hires_* dims into top-level
source-eligibility fields.

Context: the photo step writes hero_eligible / card_eligible / source_width /
source_height from the DOWNSAMPLED hero derivative (clamped to 1920×1080).
That makes hero_eligible permanently False on every listing because
HERO_MIN_HEIGHT_PX=1200 is unreachable after the 1080 clamp.

PR #321 (merged 2026-05-19) fixes the code path so future runs compute
those fields from source bytes. But the existing ranked.json on prod is
still wrong-flagged across all 917 listings. Pulpo-social rejects all
of them with `upstream_hero_ineligible`.

This script avoids waiting for a full ~85-min workflow rerun: for
listings where the hires backfill already captured the SOURCE
dimensions (`hires_width` / `hires_height`), it propagates those into
the top-level `source_width` / `source_height` and recomputes
`hero_eligible` / `card_eligible` / `hires_eligible` from them.

Listings without hires data stay un-patched; their hero_eligible
remains false until Option B/C (a full Stage A rerun) replaces them.

Usage:
    python3 scripts/patch_hero_eligible_from_hires.py        # dry-run
    python3 scripts/patch_hero_eligible_from_hires.py --execute
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Eligibility constants — mirror automation/photo_quality.py to avoid
# importing pulpo's Python module tree from a standalone script.
HERO_MIN_WIDTH_PX   = 1600
HERO_MIN_HEIGHT_PX  = 1200
HERO_MIN_ASPECT     = 1.4
HERO_MAX_ASPECT     = 1.85
HERO_MAX_SIZE_KB    = 5120

CARD_MIN_WIDTH_PX   = 800
CARD_MIN_HEIGHT_PX  = 600

HIRES_MIN_WIDTH_PX  = 1080
HIRES_MIN_HEIGHT_PX = 1080


def compute_eligibility(width: int, height: int) -> dict:
    """Mirror of automation/photo_quality.py::compute_image_metadata's
    eligibility logic, given just dimensions. File-size gate is
    inapplicable here (we don't have source bytes); treat as pass.
    """
    long_side  = max(width, height)
    short_side = min(width, height) if width != 0 and height != 0 else 1
    aspect = round(long_side / short_side, 3) if short_side > 0 else 0.0
    hero_eligible = (
        width  >= HERO_MIN_WIDTH_PX
        and height >= HERO_MIN_HEIGHT_PX
        and HERO_MIN_ASPECT <= aspect <= HERO_MAX_ASPECT
    )
    card_eligible = width >= CARD_MIN_WIDTH_PX and height >= CARD_MIN_HEIGHT_PX
    hires_eligible = width >= HIRES_MIN_WIDTH_PX and height >= HIRES_MIN_HEIGHT_PX
    return {
        "aspect_ratio": aspect,
        "hero_eligible": hero_eligible,
        "card_eligible": card_eligible,
        "hires_eligible": hires_eligible,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true",
                   help="actually rewrite ranked.json. Without this, run as dry-run.")
    p.add_argument("--input", type=Path,
                   default=Path("web/data/ranked.json"),
                   help="path to ranked.json (default: web/data/ranked.json)")
    args = p.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found", file=sys.stderr)
        return 1

    data = json.loads(args.input.read_text(encoding="utf-8"))
    n = len(data)
    print(f"loaded {n} listings from {args.input}")

    n_with_hires_dims = 0
    n_hero_flipped = 0
    n_card_flipped = 0
    n_source_dims_set = 0

    for li in data:
        hw = li.get("hires_width")
        hh = li.get("hires_height")
        if not (isinstance(hw, int) and isinstance(hh, int) and hw > 0 and hh > 0):
            continue
        n_with_hires_dims += 1

        elig = compute_eligibility(hw, hh)

        # hero_eligible: flip when going false → true.
        if elig["hero_eligible"] and not li.get("hero_eligible"):
            li["hero_eligible"] = True
            n_hero_flipped += 1
        elif not elig["hero_eligible"]:
            # Keep accurate: if the source genuinely fails the gate,
            # don't lie about it (current false stays false; current
            # true → would never happen given the bug, but defensive).
            li["hero_eligible"] = bool(elig["hero_eligible"])

        # card_eligible: same pattern.
        if elig["card_eligible"] and not li.get("card_eligible"):
            li["card_eligible"] = True
            n_card_flipped += 1
        elif not elig["card_eligible"]:
            li["card_eligible"] = bool(elig["card_eligible"])

        # source_width / source_height: propagate from hires dims if
        # the existing values are missing or smaller (the existing
        # values are derivative dims, capped at 1920×1080, so hires
        # dims are always ≥ them when both are real).
        if li.get("source_width") != hw:
            li["source_width"] = hw
            n_source_dims_set += 1
        if li.get("source_height") != hh:
            li["source_height"] = hh

    print("\n── patch results ──")
    print(f"listings with hires dims:    {n_with_hires_dims}/{n}")
    print(f"hero_eligible: false→true:   {n_hero_flipped}")
    print(f"card_eligible: false→true:   {n_card_flipped}")
    print(f"source_width/_height set:    {n_source_dims_set}")

    if not args.execute:
        print("\nDRY-RUN — no write. Re-run with --execute to persist.")
        return 0

    # Atomic write so a crash mid-write can't corrupt ranked.json.
    tmp = args.input.with_suffix(args.input.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(args.input)
    print(f"\nWROTE {args.input}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
