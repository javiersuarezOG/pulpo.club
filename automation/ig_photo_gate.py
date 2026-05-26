"""ig_photo_gate.py — pick listings worthy of Instagram from ranked.json.

The IG batch 1 plan only publishes listings whose photos won't embarrass
the brand.  Rather than recomputing photo quality (the nightly already
ran photo_quality.py and wrote sidecars), this gate filters on the flags
ranked.json already carries:

  - photos_count           ≥ IG_GATE_MIN_PHOTOS    (default 4)
  - hero_photo_quality_score ≥ IG_GATE_MIN_HERO_SCORE  (default 60)
  - card_eligible OR hero_eligible        truthy
  - has_text_overlay                      not True
  - has_marketing_overlay                 not True
  - data_quality_score    ≥ IG_GATE_MIN_DATA_QUALITY  (default 0.55)
  - is_incomplete                         not True
  - is_agricultural                       not True   (per the founder brief)
  - validation_status                     not "rejected"
  - property_type=='land'  if IG_GATE_TERRENOS_ONLY=1 (default for batch 1)

Output: web/data/ig_candidates.json
{
  "version": 1,
  "computed_at": "...",
  "config": {...},          # what thresholds produced this output
  "stats": {
    "scanned": 879,
    "passed": 30,
    "rejection_reasons": {"low_photos": 421, "agricultural": 88, ...}
  },
  "candidates": [
    {
      "listing_id": "remax__001461165132",  # source__source_id
      "source": "remax",
      "source_id": "001461165132",
      "rank": 2,
      "rank_score": 87.5,
      "property_type": "land",
      "subcategory": "land",
      "zone": "el-tunco",
      "photos_count": 5,
      "hero_photo_quality_score": 60,
      "hero_index": 0,
      "photo_indices_ordered": [0, 1, 2, 3, 4],
      "palette_suggested": "ink",
      "passes_at": "2026-05-26T..."
    },
    ...
  ]
}

CLI:
  python3 -m automation.ig_photo_gate \\
    [--ranked web/data/ranked.json] \\
    [--output web/data/ig_candidates.json] \\
    [--limit N]

Hooked into the nightly via automation/run.py after phase_write_outputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

from automation._atomic import atomic_write_json
from automation._config import env_bool, env_float, env_int


# ── tunables (env-overridable) ─────────────────────────────────────────

def _config_snapshot() -> dict[str, Any]:
    """Read tunables once per run.  Returned snapshot is embedded in the
    output JSON so a future operator can diff today's batch against
    last week's and see which knob moved if the candidate count shifted."""
    return {
        # min_photos=6 matches the IG playbook spec ("≥ 6 fotos válidas").
        # min_hero_score=80 keeps only top-tier hero shots (60+ also lets
        # in mediocre).  Tuned 2026-05-26 against ranked.json to land at
        # ~30 candidates (3.4%), matching the founder's pre-validation.
        "min_photos":         env_int("IG_GATE_MIN_PHOTOS",  6),
        "min_hero_score":     env_int("IG_GATE_MIN_HERO_SCORE", 80),
        "min_data_quality":   env_float("IG_GATE_MIN_DATA_QUALITY", 0.55),
        "terrenos_only":      env_bool("IG_GATE_TERRENOS_ONLY", True),
        "exclude_agricultural": env_bool("IG_GATE_EXCLUDE_AGRICULTURAL", True),
        "max_candidates":     env_int("IG_GATE_MAX_CANDIDATES", 0),  # 0 = no cap
    }


# ── per-listing predicates ─────────────────────────────────────────────

# Each predicate returns (passes, reject_reason_or_None).  Reason string
# is keyed for the stats counter — keep stable across versions so trend
# tracking on the nightly bot commits stays comparable.

_LandPredicate = Tuple[bool, Optional[str]]


def _check_photos_count(li: dict, cfg: dict) -> _LandPredicate:
    n = li.get("photos_count") or 0
    if n < cfg["min_photos"]:
        return False, "low_photos"
    return True, None


def _check_hero_score(li: dict, cfg: dict) -> _LandPredicate:
    score = li.get("hero_photo_quality_score")
    if score is None or score < cfg["min_hero_score"]:
        return False, "low_hero_score"
    return True, None


def _check_eligibility_flags(li: dict, _cfg: dict) -> _LandPredicate:
    if not (li.get("card_eligible") or li.get("hero_eligible")):
        return False, "not_eligible"
    return True, None


def _check_overlays(li: dict, _cfg: dict) -> _LandPredicate:
    if li.get("has_text_overlay") is True:
        return False, "text_overlay"
    if li.get("has_marketing_overlay") is True:
        return False, "marketing_overlay"
    return True, None


def _check_data_quality(li: dict, cfg: dict) -> _LandPredicate:
    if li.get("is_incomplete") is True:
        return False, "incomplete"
    dq = li.get("data_quality_score")
    if dq is None or dq < cfg["min_data_quality"]:
        return False, "low_data_quality"
    return True, None


def _check_agricultural(li: dict, cfg: dict) -> _LandPredicate:
    if cfg["exclude_agricultural"] and li.get("is_agricultural") is True:
        return False, "agricultural"
    return True, None


def _check_terreno_only(li: dict, cfg: dict) -> _LandPredicate:
    if cfg["terrenos_only"] and li.get("property_type") != "land":
        return False, "not_terreno"
    return True, None


def _check_validation(li: dict, _cfg: dict) -> _LandPredicate:
    if li.get("validation_status") == "rejected":
        return False, "validation_rejected"
    return True, None


def _check_essentials(li: dict, _cfg: dict) -> _LandPredicate:
    """price_usd + area_m2 + source_id are the bare minimum for ANY post.
    Without them the formatters render '—' and the post is broken."""
    if not li.get("price_usd"):
        return False, "missing_price"
    if not li.get("area_m2"):
        return False, "missing_area"
    if not li.get("source_id"):
        return False, "missing_source_id"
    return True, None


# Order matters — cheapest / most-likely-to-fail predicates first so a
# rejection on `low_photos` short-circuits before we look at scores.
_PREDICATES = (
    _check_essentials,
    _check_terreno_only,
    _check_agricultural,
    _check_photos_count,
    _check_eligibility_flags,
    _check_overlays,
    _check_data_quality,
    _check_hero_score,
    _check_validation,
)


def evaluate_listing(li: dict, cfg: dict | None = None) -> _LandPredicate:
    """Run all predicates; return (passes, first_failing_reason)."""
    cfg = cfg or _config_snapshot()
    for pred in _PREDICATES:
        ok, reason = pred(li, cfg)
        if not ok:
            return False, reason
    return True, None


def passes_gate(li: dict, cfg: dict | None = None) -> bool:
    """Thin wrapper.  Useful for callers that don't care about reason."""
    return evaluate_listing(li, cfg)[0]


# ── hero + photo ordering ──────────────────────────────────────────────

def select_hero_index(li: dict) -> int:
    """Which photo_url index is the hero shot.

    Today: 0.  The nightly's repick_heroes.py has already shuffled
    photo_urls so the best image is first (that's the whole point of
    that module).  Future: if per-photo quality scores get computed,
    pick the max here."""
    return 0


def order_photo_indices(li: dict) -> list[int]:
    """Carousel order.  Hero first, then the rest in source order.

    Hard-capped at 10 — Instagram carousels max out at 10 slides and a
    poster slide will be prepended by the assembler in PR-2."""
    n = li.get("photos_count") or 0
    if n <= 0:
        return []
    hero = select_hero_index(li)
    rest = [i for i in range(n) if i != hero]
    ordered = [hero, *rest]
    return ordered[:10]


# ── palette suggestion (Direction A — editorial) ──────────────────────

# Direction A locked: 3 modes for the IG poster — ink (dark), paper
# (light), cream (sand).  The queue builder in PR-3 will pick the final
# palette per post for variety; the gate just suggests a starting point
# based on listing characteristics so the queue has something sensible
# pre-filled.

def suggest_palette(li: dict) -> str:
    """'ink' / 'paper' / 'cream' — default ink for hero terrenos, paper
    for alerts, cream for intros (the queue builder owns final pick)."""
    pvp = li.get("price_vs_zone_pct")
    # Bargain-ish listings lean to paper/red for the eventual post-it.
    if pvp is not None and pvp <= -20:
        return "paper"
    return "ink"


# ── candidate building ─────────────────────────────────────────────────

def _listing_id(li: dict) -> str:
    """Stable composite ID:  '{source}__{source_id}'.  Used everywhere
    downstream (queue, publisher, posted_media tracking)."""
    return f"{li.get('source', 'unknown')}__{li.get('source_id', 'unknown')}"


def _candidate_from_listing(li: dict, cfg: dict, computed_at: str) -> dict:
    return {
        "listing_id":               _listing_id(li),
        "source":                   li.get("source"),
        "source_id":                li.get("source_id"),
        "rank":                     li.get("rank"),
        "rank_score":               li.get("rank_score"),
        "property_type":            li.get("property_type"),
        "subcategory":              li.get("subcategory"),
        "zone":                     li.get("zone"),
        "department":               li.get("department"),
        "photos_count":             li.get("photos_count"),
        "hero_photo_quality_score": li.get("hero_photo_quality_score"),
        "hero_index":               select_hero_index(li),
        "photo_indices_ordered":    order_photo_indices(li),
        "palette_suggested":        suggest_palette(li),
        "price_usd":                li.get("price_usd"),
        "area_m2":                  li.get("area_m2"),
        "price_per_m2":             li.get("price_per_m2"),
        "price_vs_zone_pct":        li.get("price_vs_zone_pct"),
        "dist_beach_km":            li.get("dist_beach_km"),
        "passes_at":                computed_at,
    }


def build_candidates(
    listings: Iterable[dict],
    *,
    cfg: dict | None = None,
    computed_at: str | None = None,
) -> dict:
    """Run gate over `listings`; return the full output payload (ready
    to atomic-write as JSON).  Pure function — no I/O."""
    cfg = cfg or _config_snapshot()
    computed_at = computed_at or datetime.now(timezone.utc).isoformat()

    candidates: list[dict] = []
    rejections: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    scanned = 0

    for li in listings:
        scanned += 1
        ok, reason = evaluate_listing(li, cfg)
        if not ok:
            rejections[reason or "unknown"] += 1
            continue
        candidates.append(_candidate_from_listing(li, cfg, computed_at))
        by_type[li.get("property_type") or "unknown"] += 1

    # Order candidates by rank_score desc so consumers see the strongest
    # first; ties broken by rank asc (smaller rank == better).
    candidates.sort(
        key=lambda c: (-(c.get("rank_score") or 0), c.get("rank") or 1_000_000)
    )

    # Optional hard cap (IG_GATE_MAX_CANDIDATES=N).  Useful for keeping
    # the output JSON small in dev or smoke tests.
    cap = cfg["max_candidates"]
    if cap > 0:
        candidates = candidates[:cap]

    return {
        "version":      1,
        "computed_at":  computed_at,
        "config":       cfg,
        "stats": {
            "scanned":            scanned,
            "passed":             len(candidates),
            "by_property_type":   dict(by_type),
            "rejection_reasons":  dict(rejections),
        },
        "candidates":   candidates,
    }


# ── I/O wrappers ───────────────────────────────────────────────────────

def load_ranked(path: Path) -> list[dict]:
    """Read ranked.json and return its list payload.  Errors loudly if
    the file shape doesn't match (a silently empty list would produce a
    silently empty candidates output and we'd miss the regression)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"{path}: expected top-level list, got {type(raw).__name__}"
        )
    return raw


def write_candidates(path: Path, payload: dict) -> None:
    atomic_write_json(path, payload, indent=2)


# ── CLI entry ──────────────────────────────────────────────────────────

DEFAULT_RANKED = Path("web/data/ranked.json")
DEFAULT_OUTPUT = Path("web/data/ig_candidates.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Filter ranked.json into IG-worthy candidates."
    )
    parser.add_argument(
        "--ranked", type=Path, default=DEFAULT_RANKED,
        help=f"Input ranked.json (default {DEFAULT_RANKED}).",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output ig_candidates.json (default {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="If >0, only scan the first N listings (for smoke testing).",
    )
    args = parser.parse_args(argv)

    if not args.ranked.exists():
        print(f"[ig_photo_gate] ranked input missing: {args.ranked}", file=sys.stderr)
        return 2

    listings = load_ranked(args.ranked)
    if args.limit > 0:
        listings = listings[:args.limit]

    payload = build_candidates(listings)
    write_candidates(args.output, payload)

    s = payload["stats"]
    print(
        f"[ig_photo_gate] scanned={s['scanned']} passed={s['passed']} "
        f"by_type={s['by_property_type']} "
        f"rejections={s['rejection_reasons']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
