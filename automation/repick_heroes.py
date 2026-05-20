"""One-off retroactive hero picker.

Re-runs the picker across every listing in ``web/data/ranked.json``
without firing the full nightly (no scrape, no DeepSeek enrichment, no
ranker, no commit-PR step). Reuses the same helpers
``automation/run.py`` uses during the photo phase:

    _score_candidates_cheap → _apply_aesthetic_to_eligible
    → _pick_winner_from_scored → Pillow thumb/hero writes → sidecars

Two design goals:

1. **Score every eligible photo on the first pass.** Today's
   ``LLM_VISION_TOP_PCT=5`` is a deferral mechanism (5%/night until
   every photo gets scored over ~20 nights). The quality floor
   introduced in the companion PR is the real filter; whatever
   survives the floor should be scored in one pass.

2. **Idempotent + cheap on re-run.** First pass downloads + scores
   everything. Second pass hits the aesthetic cache
   (``web/data/llm_vision_cache.json``) for ~100% of photos →
   $0 spend, ~10 min runtime.

The script does NOT commit / push / open a PR — that's a separate
concern owned by the CI workflow (PR 3) which wraps this CLI in the
same data-PR flow ``pulpo-nightly.yml`` uses.

Usage:

    python automation/repick_heroes.py                           # dry-run
    python automation/repick_heroes.py --execute                 # write
    python automation/repick_heroes.py --execute --limit 20      # first 20
    python automation/repick_heroes.py --execute --source remax  # filter
    python automation/repick_heroes.py --execute --floor 50      # tighter
    python automation/repick_heroes.py --booster-only-cached     # $0 spend

Environment:
- ``HERO_PICKER_MIN_CHEAP_SCORE`` — floor override (also via ``--floor``).
- ``LLM_VISION_ENABLED`` — booster on/off (default true post-PR #286).
- ``SEGMIND_API_KEY`` / ``QWEN_API_KEY`` — provider keys.
- ``LLM_VISION_DAILY_BUDGET_USD`` — hard cap on spend.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Import the production picker helpers — single source of truth.
from automation.run import (  # noqa: E402  -- sys.path manipulation above
    _apply_aesthetic_to_eligible,
    _hero_file_path,
    _meta_sidecar_path,
    _pick_winner_from_scored,
    _score_candidates_cheap,
    _write_sidecar,
)

DEFAULT_INPUT = REPO / "web" / "data" / "ranked.json"
DEFAULT_SUMMARY = REPO / "web" / "data" / "repick_summary.jsonl"


def _filter_listings(
    data: list[dict],
    *,
    limit: Optional[int],
    sources: Optional[set[str]],
) -> list[dict]:
    out = data
    if sources:
        out = [li for li in out if li.get("source") in sources]
    if limit is not None and limit > 0:
        out = out[:limit]
    return out


def _repick_one_listing(
    listing: dict,
    *,
    photos_dir: Path,
    booster_only_cached: bool,
) -> dict:
    """Per-listing pick. Returns a summary dict with per-listing outcome:
        {listing_id, source, source_id, candidate_count, picker_excluded,
         winner_url, technical_score, has_text_overlay, action}
    where ``action`` is one of:
        - "no_photo_urls"  (listing has no photos)
        - "winner_picked"  (new hero written to disk)
        - "no_winner"      (every candidate failed download)
    """
    source = listing.get("source") or "unknown"
    source_id = listing.get("source_id") or "unknown"
    listing_id = f"{source}__{source_id}"
    photo_urls = listing.get("photo_urls") or []

    if not photo_urls:
        return {
            "listing_id": listing_id,
            "source": source,
            "source_id": source_id,
            "candidate_count": 0,
            "picker_excluded": 0,
            "winner_url": None,
            "technical_score": None,
            "has_text_overlay": None,
            "has_marketing_overlay": None,
            "action": "no_photo_urls",
        }

    candidates = _score_candidates_cheap(photo_urls)
    n_excluded = sum(1 for c in candidates if c.get("picker_excluded"))

    if booster_only_cached:
        eligible_urls: Optional[set[str]] = set()
    else:
        # After the floor filter has done its job, score everything that
        # survives in one pass. Cache hits cost $0 regardless.
        eligible_urls = {
            c["url"] for c in candidates if not c.get("picker_excluded")
        }
    _apply_aesthetic_to_eligible(candidates, eligible_urls=eligible_urls)

    (winning_url, winning_content, winning_score,
     winning_has_text, winning_has_marketing) = _pick_winner_from_scored(candidates)

    if winning_url is None or winning_content is None:
        return {
            "listing_id": listing_id,
            "source": source,
            "source_id": source_id,
            "candidate_count": len(candidates),
            "picker_excluded": n_excluded,
            "winner_url": None,
            "technical_score": None,
            "has_text_overlay": None,
            "has_marketing_overlay": None,
            "action": "no_winner",
        }

    fname = f"{source}_{source_id}.jpg"
    fpath = photos_dir / fname
    hero_fpath = _hero_file_path(fpath)
    hero_meta_path = _meta_sidecar_path(hero_fpath)

    try:
        from PIL import Image

        # Match _download_hero_photos exactly (run.py:636-664).
        try:
            _LANCZOS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
        except AttributeError:
            _LANCZOS = Image.LANCZOS  # type: ignore[attr-defined]

        thumb_img = Image.open(io.BytesIO(winning_content))
        thumb_img.thumbnail((600, 400), _LANCZOS)
        if thumb_img.mode in ("RGBA", "P"):
            thumb_img = thumb_img.convert("RGB")
        thumb_buf = io.BytesIO()
        thumb_img.save(thumb_buf, format="JPEG", quality=75, optimize=True)
        thumb_bytes = thumb_buf.getvalue()
        fpath.write_bytes(thumb_bytes)
        _write_sidecar(fpath, thumb_bytes)

        hero_img = Image.open(io.BytesIO(winning_content))
        hero_img.thumbnail((1920, 1080), _LANCZOS)
        if hero_img.mode in ("RGBA", "P"):
            hero_img = hero_img.convert("RGB")
        hero_buf = io.BytesIO()
        hero_img.save(hero_buf, format="JPEG", quality=85, optimize=True)
        hero_bytes = hero_buf.getvalue()
        hero_fpath.write_bytes(hero_bytes)
        hero_meta = _write_sidecar(hero_fpath, hero_bytes)

        # Compute SOURCE-bytes metadata so hero_eligible reflects the
        # source's intrinsic resolution, not the 1920×1080-clamped
        # derivative's. Mirrors automation/run.py::_download_hero_photos
        # — same code path, same fix. See PR #319 commit message.
        from automation.photo_quality import compute_image_metadata as _cim
        source_meta = _cim(winning_content, file_size_bytes=len(winning_content))

        if hero_meta is not None:
            # Stash derivative dims separately; never read these for
            # eligibility decisions.
            hero_meta["derivative_width"]  = hero_meta.get("width")
            hero_meta["derivative_height"] = hero_meta.get("height")
            if source_meta is not None:
                hero_meta["width"]          = source_meta["width"]
                hero_meta["height"]         = source_meta["height"]
                hero_meta["aspect_ratio"]   = source_meta.get("aspect_ratio")
                hero_meta["file_size_kb"]   = source_meta.get("file_size_kb")
                hero_meta["hero_eligible"]  = source_meta.get("hero_eligible")
                hero_meta["card_eligible"]  = source_meta.get("card_eligible")
                hero_meta["hires_eligible"] = source_meta.get("hires_eligible")
            hero_meta["hero_photo_quality_score"] = winning_score
            hero_meta["has_text_overlay"] = winning_has_text
            hero_meta["has_marketing_overlay"] = winning_has_marketing
            hero_meta["winning_url"] = winning_url
            hero_meta["candidate_count"] = len(candidates)
            hero_meta["picker_excluded_count"] = n_excluded
            hero_meta["repicked_at"] = datetime.now(timezone.utc).isoformat()
            hero_meta_path.write_text(
                json.dumps(hero_meta, indent=2) + "\n", encoding="utf-8"
            )
    except ImportError:
        # Pillow missing — script can't write derivatives. Surface as
        # no_winner so the summary is honest.
        return {
            "listing_id": listing_id,
            "source": source,
            "source_id": source_id,
            "candidate_count": len(candidates),
            "picker_excluded": n_excluded,
            "winner_url": winning_url,
            "technical_score": winning_score,
            "has_text_overlay": winning_has_text,
            "has_marketing_overlay": winning_has_marketing,
            "action": "no_winner",
        }

    # Update the listing dict in place so the caller can rewrite
    # ranked.json with fresh hero metadata. Source-bytes eligibility
    # values (hero_eligible / card_eligible / source_width /
    # source_height) come from the sidecar's overwritten top-level
    # fields, which now reflect the SOURCE bytes per the fix above.
    listing["hero_photo_path"] = f"/photos/{fname}"
    listing["hero_photo_quality_score"] = winning_score
    listing["has_text_overlay"] = winning_has_text
    listing["has_marketing_overlay"] = winning_has_marketing
    if hero_meta is not None:
        if "hero_eligible" in hero_meta:
            listing["hero_eligible"] = bool(hero_meta["hero_eligible"])
        if "card_eligible" in hero_meta:
            listing["card_eligible"] = bool(hero_meta["card_eligible"])
        if hero_meta.get("width") is not None:
            listing["source_width"] = int(hero_meta["width"])
        if hero_meta.get("height") is not None:
            listing["source_height"] = int(hero_meta["height"])

    return {
        "listing_id": listing_id,
        "source": source,
        "source_id": source_id,
        "candidate_count": len(candidates),
        "picker_excluded": n_excluded,
        "winner_url": winning_url,
        "technical_score": winning_score,
        "has_text_overlay": winning_has_text,
        "has_marketing_overlay": winning_has_marketing,
        "action": "winner_picked",
    }


def _atomic_write_json(path: Path, data) -> None:
    """Temp-file + rename so a partial write can't corrupt the file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    p = argparse.ArgumentParser(description="One-off retroactive hero picker")
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                   help=f"ranked.json path (default {DEFAULT_INPUT})")
    p.add_argument("--execute", action="store_true",
                   help="actually download bytes, score, write heroes + ranked.json. "
                        "Without this flag the run is a dry-run that only logs intent.")
    p.add_argument("--limit", type=int, default=None,
                   help="operate on first N listings (after --source filter)")
    p.add_argument("--source", type=str, default=None,
                   help="comma-separated source codes (e.g. remax,bienesraices) — filter listings")
    p.add_argument("--floor", type=int, default=None,
                   help="override HERO_PICKER_MIN_CHEAP_SCORE for this run (0-100)")
    p.add_argument("--booster-only-cached", action="store_true",
                   help="pass empty eligible_urls — only cache-hit aesthetic scores apply, $0 spend")
    p.add_argument("--summary-out", type=Path, default=DEFAULT_SUMMARY,
                   help=f"per-listing JSONL outcome log (default {DEFAULT_SUMMARY})")
    args = p.parse_args()

    if args.floor is not None:
        if not (0 <= args.floor <= 100):
            print(f"ERROR: --floor must be 0..100, got {args.floor}", file=sys.stderr)
            return 1
        os.environ["HERO_PICKER_MIN_CHEAP_SCORE"] = str(args.floor)

    if not args.input.exists():
        print(f"ERROR: {args.input} not found", file=sys.stderr)
        return 1

    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        print("ERROR: ranked.json is empty or not a list", file=sys.stderr)
        return 1

    # Backfill missing Listing fields on every dict so the schema-required
    # set is satisfied even for listings the picker skips (no_photo_urls).
    # The repick only mutates dicts when it picks a winner — skipped ones
    # pass through unchanged. If the prior ranked.json predates a field
    # added to pulpo.models.Listing, those skipped dicts ship with a stale
    # shape and tests/test_ranked_schema.py fails the data PR. This loop
    # normalizes load-time so adding a new Listing field never requires a
    # one-off data-patch PR again.
    from dataclasses import MISSING, fields as _dataclass_fields
    from pulpo.models import Listing as _Listing
    _listing_field_defaults: dict = {}
    for _f in _dataclass_fields(_Listing):
        if _f.default is not MISSING:
            _listing_field_defaults[_f.name] = _f.default
        elif _f.default_factory is not MISSING:  # type: ignore[misc]
            _listing_field_defaults[_f.name] = _f.default_factory()
        # fields without any default stay absent — they must be explicitly
        # set by the caller, so we don't invent values for them.
    _backfilled = 0
    for _li in data:
        for _name, _default in _listing_field_defaults.items():
            if _name not in _li:
                _li[_name] = _default
                _backfilled += 1
    if _backfilled:
        print(f"[repick] backfilled {_backfilled} missing Listing-field "
              f"defaults across {len(data)} listings")

    sources = None
    if args.source:
        sources = {s.strip() for s in args.source.split(",") if s.strip()}

    targets = _filter_listings(data, limit=args.limit, sources=sources)
    n_targets = len(targets)
    if n_targets == 0:
        print("[repick] no listings matched filter — nothing to do")
        return 0

    floor_in_use = os.environ.get("HERO_PICKER_MIN_CHEAP_SCORE", "<default 40>")
    print(f"[repick] mode={'execute' if args.execute else 'dry-run'} "
          f"listings={n_targets} floor={floor_in_use} "
          f"booster_only_cached={args.booster_only_cached}")

    if not args.execute:
        print("[repick] dry-run — no network, no writes. Re-invoke with --execute to act.")
        return 0

    photos_dir = REPO / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    summary_fh = args.summary_out.open("w", encoding="utf-8")

    t0 = time.monotonic()
    counts = {"winner_picked": 0, "no_winner": 0, "no_photo_urls": 0}
    try:
        for i, listing in enumerate(targets, 1):
            try:
                result = _repick_one_listing(
                    listing,
                    photos_dir=photos_dir,
                    booster_only_cached=args.booster_only_cached,
                )
            except Exception as e:
                result = {
                    "listing_id": f"{listing.get('source','?')}__{listing.get('source_id','?')}",
                    "error": repr(e),
                    "action": "error",
                }
                counts.setdefault("error", 0)
                counts["error"] += 1
            else:
                counts[result["action"]] = counts.get(result["action"], 0) + 1

            summary_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            summary_fh.flush()

            if i % 25 == 0:
                elapsed = time.monotonic() - t0
                print(f"[repick] {i}/{n_targets} ({counts}) elapsed={elapsed:.0f}s")
    finally:
        summary_fh.close()

    # Rewrite ranked.json atomically with mutated hero fields.
    _atomic_write_json(args.input, data)

    elapsed = time.monotonic() - t0
    print(f"[repick] done: {counts} elapsed={elapsed:.0f}s "
          f"summary={args.summary_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
