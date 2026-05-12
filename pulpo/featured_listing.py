"""
Cron-stable featured-listing selection for the Discover hero.

Two-stage design:

1. **Backend (this module)** picks a *pool* of up to N elite listings
   per UTC day and writes them to `web/data/featured.json`. Selection
   is deterministic — same listings → same pool order across runs, so
   debugging "why was this listing in the hero?" has a single answer.

2. **Frontend** rotates within that pool: per-session sticky random
   start + slow auto-crossfade. So a visitor sees one listing per
   session (no jarring mid-session swaps), but different visitors —
   and the same visitor across sessions — see different premium
   properties.

Three tiers, layered. The first tier that yields >=1 listing wins.

| Tier      | not sold | photos >= | rank >= | days <= | photo quality >= |
|-----------|----------|-----------|---------|---------|-------------------|
| elite     | yes      |    8      |   75    |   30    |   80 (or null)    |
| soft      | yes      |    5      |   65    |   30    |    -              |
| fallback  | yes      |    1      |    -    |    -    |    -              |

The elite tier accepts `hero_photo_quality_score == None` provided
rank >= 75 and photos >= 8 - those are strong proxies for a curated
listing while the photo-scoring backfill catches up on the catalog.
Once scoring is populated, null scores become rare and the literal
">=80" bar takes over.

Pool size is capped at MAX_POOL so we don't ship 50 hero candidates
to the FE; 12 is enough rotation that a returning visitor sees
variety, small enough that every listing in the pool is genuinely
top-shelf.

Output: web/data/featured.json carrying:

    {
        "tier":         "elite",
        "criteria":     { "elite": {...}, "soft": {...} },
        "picked_at":    "2026-05-07T12:00:00+00:00",
        "expires_at":   "2026-05-08T00:00:00+00:00",
        "listing_id":   "goodlife|GL-001",
        "rank_score":   87.5,
        "hero_photo_quality_score": null,
        "fallback":     false,
        "pool": [
            { "listing_id": "goodlife|GL-001",
              "rank_score": 87.5,
              "hero_photo_quality_score": null,
              "photos_count": 28 },
            ...
        ]
    }

Frontend reads this once on app boot and renders the Hero with a
random pool entry per session. Vercel CDN serves edge-cached for 24h
aligned to UTC midnight.

Pure: no I/O outside the single write. Listings are passed in;
pick_featured_pool() returns the chosen pool. write_featured_json()
serialises and writes.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


# Elite tier - the visible, exclusive bar.
MIN_PHOTOS_COUNT     = 8        # rich gallery; signals seller invested
MIN_RANK_SCORE       = 75.0     # roughly top ~5% of catalog
MIN_PHOTO_QUALITY    = 80       # excellent band per automation/photo_quality.py
MAX_DAYS_LISTED      = 30       # fresh

# Soft tier - invoked when elite pool is empty (early-catalog states,
# post-tightening). Still selective, just less stringent.
SOFT_MIN_PHOTOS      = 5
SOFT_MIN_RANK        = 65.0

# Maximum pool size shipped to the FE. Capped so the JSON stays tiny
# and the rotation is meaningful (every entry is genuinely elite).
MAX_POOL             = 12


@dataclass(frozen=True)
class FeaturedEntry:
    """One listing in the featured pool."""
    listing_id:                 str
    rank_score:                 float
    hero_photo_quality_score:   Optional[int]
    photos_count:               int


@dataclass(frozen=True)
class FeaturedPool:
    """Result of pick_featured_pool().

    `tier` answers "why was this pool chosen": "elite" (strict gates
    passed), "soft" (relaxed gates), "fallback" (last-resort single pick).
    """
    tier:        str        # "elite" | "soft" | "fallback"
    entries:     tuple      # tuple[FeaturedEntry, ...] - ordered, top first


def _key(li: Any) -> str:
    """Identifier shared with sidecars and price_history. Format
    `{source}|{source_id}` - matches the FE adapter's `id` shape via
    a hyphen-replacement on the FE side."""
    src = getattr(li, "source", None) or (li.get("source") if isinstance(li, dict) else None)
    sid = getattr(li, "source_id", None) or (li.get("source_id") if isinstance(li, dict) else None)
    return f"{src}|{sid}"


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _is_elite(li: Any) -> bool:
    """Strict eligibility for the elite pool - every gate must hold.

    The photo-quality gate is permissive on null: the rank+photos
    proxies stand in until the scoring backfill catches up.

    Brochure-style hero photos (text overlays, price stamps, agency
    banners) are excluded — they read as advertising rather than
    property and look bad full-bleed. `has_text_overlay is True` is
    the only hard exclusion; None means no OCR signal (Tesseract
    not available or image undecodable) and we keep the listing.
    """
    if _g(li, "is_sold") is True:
        return False
    if _g(li, "has_text_overlay") is True:
        return False
    if (_g(li, "photos_count") or 0) < MIN_PHOTOS_COUNT:
        return False
    days = _g(li, "days_listed")
    if days is None or days > MAX_DAYS_LISTED:
        return False
    rank = _g(li, "rank_score")
    if not isinstance(rank, (int, float)) or rank < MIN_RANK_SCORE:
        return False
    score = _g(li, "hero_photo_quality_score")
    if score is None:
        # Unscored - accept on rank+photos proxies (already gated above).
        return True
    return score >= MIN_PHOTO_QUALITY


def _is_soft(li: Any) -> bool:
    """Softer gates - still selective. Used only if elite pool is empty."""
    if _g(li, "is_sold") is True:
        return False
    if (_g(li, "photos_count") or 0) < SOFT_MIN_PHOTOS:
        return False
    days = _g(li, "days_listed")
    if days is None or days > MAX_DAYS_LISTED:
        return False
    rank = _g(li, "rank_score")
    if not isinstance(rank, (int, float)) or rank < SOFT_MIN_RANK:
        return False
    return True


def _is_minimum(li: Any) -> bool:
    """Last-resort relaxed pass - only sold + has-a-photo gates."""
    if _g(li, "is_sold") is True:
        return False
    return (_g(li, "photos_count") or 0) >= 1


def _to_entry(li: Any) -> FeaturedEntry:
    return FeaturedEntry(
        listing_id               = _key(li),
        rank_score               = float(_g(li, "rank_score") or 0),
        hero_photo_quality_score = _g(li, "hero_photo_quality_score"),
        photos_count             = int(_g(li, "photos_count") or 0),
    )


def _ranked_pool(listings: list, predicate) -> list:
    """Filter + sort: rank_score desc, then deterministic source/source_id
    for stable tie-break."""
    eligible = [li for li in listings if predicate(li)]
    eligible.sort(
        key=lambda li: (
            -float(_g(li, "rank_score") or 0),
            _g(li, "source") or "",
            _g(li, "source_id") or "",
        )
    )
    return eligible


def _utc_midnight_after(now: datetime) -> datetime:
    """Next UTC-midnight after `now`. The cache TTL is aligned to
    midnight so the pool changes at most once per UTC day, regardless
    of when the nightly cron actually runs."""
    next_day = (now + timedelta(days=1)).date()
    return datetime(
        next_day.year, next_day.month, next_day.day,
        tzinfo=timezone.utc,
    )


def pick_featured_pool(listings: list,
                       now: Optional[datetime] = None) -> Optional[FeaturedPool]:
    """Return the highest-tier non-empty pool, or None when nothing
    qualifies (e.g. an empty listings list, or every listing is sold
    with zero photos).

    `now` is reserved for future "freshness windows" but currently unused.
    """
    del now

    elite = _ranked_pool(listings, _is_elite)
    if elite:
        return FeaturedPool(
            tier    = "elite",
            entries = tuple(_to_entry(li) for li in elite[:MAX_POOL]),
        )

    soft = _ranked_pool(listings, _is_soft)
    if soft:
        return FeaturedPool(
            tier    = "soft",
            entries = tuple(_to_entry(li) for li in soft[:MAX_POOL]),
        )

    minimal = _ranked_pool(listings, _is_minimum)
    if minimal:
        # Last-resort: single listing, just so the hero renders.
        return FeaturedPool(
            tier    = "fallback",
            entries = (_to_entry(minimal[0]),),
        )

    return None


# ─────────────────────────────────────────────────────────────────────
# Proof-row picker (hero rewrite Phase 3)
#
# The rewritten homepage's "This week's top 3 deals" surface (per the
# rewrite plan §4) needs THREE listings, not the 12-entry rotation pool
# above. Selection differs from the rotation pool on two axes:
#
# 1. Eligibility uses the NEW hero_eligible flag (Phase 2) instead of
#    the photos_count + has_text_overlay proxies. hero_eligible already
#    encodes the resolution + aspect + size + text-overlay gates we
#    want — see automation/photo_quality.compute_image_metadata.
# 2. Selection is bucket-diverse: greedy walk in rank-desc order,
#    preferring listings whose (master_category, subcategory) bucket
#    isn't yet represented in the pick set. AND a hard invariant:
#    the final 3 must include ≥ 1 beach AND ≥ 1 lake property.
#
# Fallback ladder when the strict pool is < 3:
#   strict           rank ≥ 75 + days ≤ 60 + hero_eligible
#   relaxed_rank     rank ≥ 50 + days ≤ 60 + hero_eligible
#   relaxed_eligib   rank ≥ 50 + days ≤ 60 + card_eligible
#   shortfall        whatever passed, < 3 — log so operators see it
#
# Manual override: pulpo/featured_pick_override.json, when present and
# valid, wins outright. Schema:
#   {
#     "week_starting": "2026-05-12",
#     "picks": ["goodlife|GL-001", "oceanside|OS-042", "kazu|KZ-007"],
#     "notes": "manual curation for May 12 launch week"
#   }
# Stale listing_ids that don't resolve against the current catalog are
# silently dropped; if fewer than PROOF_ROW_PICK_COUNT resolve, we fall
# through to the auto-pick rather than ship a partial manual set.
# ─────────────────────────────────────────────────────────────────────

PROOF_ROW_PICK_COUNT       = 3
PROOF_ROW_MIN_RANK_STRICT  = 75.0
PROOF_ROW_MIN_RANK_RELAXED = 50.0
PROOF_ROW_MAX_DAYS         = 60

# Module-relative default override path. Tests pass an explicit path;
# automation/run.py uses the default.
OVERRIDE_PATH_DEFAULT = Path(__file__).resolve().parent / "featured_pick_override.json"


def _is_proof_row_strict(li: Any) -> bool:
    """rank ≥ 75 + days ≤ 60 + hero_eligible (+ not sold, no overlay).

    hero_eligible already enforces dimensions + aspect + file size +
    (text-overlay implicitly via Phase 2's metadata pass). The
    has_text_overlay check stays for defense — listings predating
    Phase 2 may have hero_eligible=False from the missing-sidecar
    path, but if they get re-fetched and pass, we still want the
    text-overlay guard.
    """
    if _g(li, "is_sold") is True:
        return False
    if _g(li, "has_text_overlay") is True:
        return False
    if not bool(_g(li, "hero_eligible")):
        return False
    days = _g(li, "days_listed")
    if days is None or days > PROOF_ROW_MAX_DAYS:
        return False
    rank = _g(li, "rank_score")
    if not isinstance(rank, (int, float)) or rank < PROOF_ROW_MIN_RANK_STRICT:
        return False
    return True


def _is_proof_row_relaxed_rank(li: Any) -> bool:
    """Strict gates with rank lowered to 50. Hero_eligible still required."""
    if _g(li, "is_sold") is True:
        return False
    if _g(li, "has_text_overlay") is True:
        return False
    if not bool(_g(li, "hero_eligible")):
        return False
    days = _g(li, "days_listed")
    if days is None or days > PROOF_ROW_MAX_DAYS:
        return False
    rank = _g(li, "rank_score")
    if not isinstance(rank, (int, float)) or rank < PROOF_ROW_MIN_RANK_RELAXED:
        return False
    return True


def _is_proof_row_relaxed_eligibility(li: Any) -> bool:
    """Rank ≥ 50 but accept card_eligible (the lower image bar) when
    no hero_eligible alternative is available."""
    if _g(li, "is_sold") is True:
        return False
    if _g(li, "has_text_overlay") is True:
        return False
    if not (bool(_g(li, "hero_eligible")) or bool(_g(li, "card_eligible"))):
        return False
    days = _g(li, "days_listed")
    if days is None or days > PROOF_ROW_MAX_DAYS:
        return False
    rank = _g(li, "rank_score")
    if not isinstance(rank, (int, float)) or rank < PROOF_ROW_MIN_RANK_RELAXED:
        return False
    return True


def _bucket_of(li: Any) -> tuple[str, str]:
    """(master_category, subcategory) with 'none' fallbacks. Used for
    diversity-picking and reporting only — doesn't affect eligibility."""
    return (
        _g(li, "master_category") or "none",
        _g(li, "subcategory")     or "none",
    )


def _pick_diverse(eligible: list, count: int) -> list:
    """Greedy bucket-diverse pick.

    Walks the eligible list (already sorted rank-desc by caller),
    appending each listing whose (master, sub) bucket isn't yet
    represented. Once all buckets are covered OR we've walked the
    list once, fall through to rank-desc fill from the leftovers.
    """
    chosen: list = []
    seen_buckets: set = set()
    leftovers: list = []
    for li in eligible:
        if len(chosen) >= count:
            break
        b = _bucket_of(li)
        if b not in seen_buckets:
            chosen.append(li)
            seen_buckets.add(b)
        else:
            leftovers.append(li)
    if len(chosen) < count:
        for li in leftovers:
            if len(chosen) >= count:
                break
            chosen.append(li)
    return chosen


def _enforce_beach_lake_invariant(picks: list, eligible: list, count: int) -> list:
    """Try to ensure picks includes ≥ 1 beach AND ≥ 1 lake.

    For each missing master_category, find the highest-rank eligible
    candidate of that master that isn't already in picks. Swap it in
    for the lowest-rank pick whose removal won't break the invariant
    on the OTHER side. When the invariant can't be satisfied (e.g. no
    lake listings in the eligible pool), return picks unchanged —
    the caller logs the constraint slip via the tier label.
    """
    if count <= 0:
        return picks
    missing = [m for m in ("beach", "lake")
               if not any(_g(p, "master_category") == m for p in picks)]
    if not missing:
        return picks

    # Operate on a mutable copy
    out = list(picks)
    for required in missing:
        candidate = next(
            (li for li in eligible
             if _g(li, "master_category") == required and li not in out),
            None,
        )
        if candidate is None:
            continue  # can't satisfy
        # Find a pick to swap out. Prefer one whose master_category has
        # other reps in `out` so the swap doesn't break the invariant
        # from the other direction.
        for replaceable in reversed(out):
            r_master = _g(replaceable, "master_category")
            others = [p for p in out if _g(p, "master_category") == r_master and p is not replaceable]
            if others:
                idx = out.index(replaceable)
                out[idx] = candidate
                break
        else:
            # No safe swap exists (each pick is the last of its master).
            # Swap the lowest-rank one anyway so we land ≥ 1 of the
            # required master — the other-side invariant slips but
            # we surface that via the tier label.
            if out:
                out[-1] = candidate
    return out


def _read_override(path: Path) -> Optional[list[str]]:
    """Return the listing_ids from the override file, or None when the
    file is absent, malformed, or contains no usable picks."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    picks = data.get("picks")
    if not isinstance(picks, list) or len(picks) == 0:
        return None
    cleaned = [str(p) for p in picks if isinstance(p, str) and p]
    return cleaned or None


def pick_proof_row(
    listings: list,
    override_path: Optional[Path] = None,
) -> tuple[list, str]:
    """Return (picks, tier) for the homepage proof row.

    `picks` is a list of up to PROOF_ROW_PICK_COUNT Listing-like objects,
    ordered as they should render (beach-or-lake invariant respected
    where possible).

    `tier` ∈ {"override", "strict", "relaxed_rank", "relaxed_eligibility",
              "shortfall"} answers "why this set" for telemetry +
    operator debug.

    `override_path` defaults to OVERRIDE_PATH_DEFAULT; tests pass an
    explicit path so they don't depend on the repo-relative file.
    """
    if override_path is None:
        override_path = OVERRIDE_PATH_DEFAULT

    override_ids = _read_override(override_path)
    if override_ids:
        id_to_listing = {_key(li): li for li in listings}
        resolved = [id_to_listing[i] for i in override_ids if i in id_to_listing]
        if len(resolved) >= PROOF_ROW_PICK_COUNT:
            return (resolved[:PROOF_ROW_PICK_COUNT], "override")
        # Partial / stale override — fall through to auto-pick.

    # Fallback ladder: strict → relaxed_rank → relaxed_eligibility.
    for tier, predicate in (
        ("strict",                _is_proof_row_strict),
        ("relaxed_rank",          _is_proof_row_relaxed_rank),
        ("relaxed_eligibility",   _is_proof_row_relaxed_eligibility),
    ):
        eligible = _ranked_pool(listings, predicate)
        if len(eligible) >= PROOF_ROW_PICK_COUNT:
            picks = _pick_diverse(eligible, PROOF_ROW_PICK_COUNT)
            picks = _enforce_beach_lake_invariant(
                picks, eligible, PROOF_ROW_PICK_COUNT,
            )
            return (picks, tier)

    # Shortfall — return whatever the loosest gate yielded, even if
    # under PROOF_ROW_PICK_COUNT. Caller surfaces a clear telemetry
    # signal so operators can investigate. The featured.json schema
    # still writes the array (possibly empty); the FE renders fewer
    # cards or hides the proof row entirely.
    eligible = _ranked_pool(listings, _is_proof_row_relaxed_eligibility)
    picks = _pick_diverse(eligible, PROOF_ROW_PICK_COUNT)
    picks = _enforce_beach_lake_invariant(
        picks, eligible, PROOF_ROW_PICK_COUNT,
    )
    return (picks, "shortfall")


def _proof_row_entry_dict(li: Any) -> dict:
    """Lightweight dict representation for the featured.json output —
    one line per pick with the fields the FE needs to render the card
    without re-resolving via ranked.json."""
    return {
        "listing_id":     _key(li),
        "rank_score":     round(float(_g(li, "rank_score") or 0), 2),
        "master_category": _g(li, "master_category"),
        "subcategory":     _g(li, "subcategory"),
        "star_rating":     _g(li, "star_rating") or 0.0,
        "hero_eligible":   bool(_g(li, "hero_eligible")),
        "card_eligible":   bool(_g(li, "card_eligible")),
    }


def write_featured_json(out_path: Path, listings: list,
                        now: Optional[datetime] = None,
                        override_path: Optional[Path] = None) -> Optional[FeaturedPool]:
    """Pick + serialize. Idempotent - safe to call from a cron and
    locally without side effects beyond the single file write.

    Writes the legacy 12-entry rotation pool (`pool`) for the current
    hero AND the new 3-entry proof row (`picks_for_proof_row`) for the
    rewritten homepage. Both surfaces are populated each run; the FE
    picks which to consume.

    Returns the chosen FeaturedPool or None when no listing was
    eligible for the legacy rotation pool. The proof row may still be
    written even when the rotation pool is None (e.g. all listings
    are stale but hero_eligible) — but in practice the gates overlap
    enough that an empty rotation pool also implies an empty proof row.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    pool = pick_featured_pool(listings, now=now)
    proof_picks, proof_tier = pick_proof_row(listings, override_path=override_path)

    if pool is None and not proof_picks:
        # Nothing eligible — refuse to write rather than emit a sentinel.
        # Callers check existence of featured.json to decide whether to
        # fall back to client-side selection.
        return None

    payload: dict = {
        "criteria": {
            "elite": {
                "min_rank":      MIN_RANK_SCORE,
                "min_photos":    MIN_PHOTOS_COUNT,
                "min_quality":   MIN_PHOTO_QUALITY,
                "max_days":      MAX_DAYS_LISTED,
            },
            "soft": {
                "min_rank":      SOFT_MIN_RANK,
                "min_photos":    SOFT_MIN_PHOTOS,
                "max_days":      MAX_DAYS_LISTED,
            },
            "proof_row": {
                "min_rank_strict":   PROOF_ROW_MIN_RANK_STRICT,
                "min_rank_relaxed":  PROOF_ROW_MIN_RANK_RELAXED,
                "max_days":          PROOF_ROW_MAX_DAYS,
                "pick_count":        PROOF_ROW_PICK_COUNT,
            },
        },
        "picked_at":  now.isoformat(),
        "expires_at": _utc_midnight_after(now).isoformat(),
    }

    if pool is not None:
        top = pool.entries[0]
        payload.update({
            "tier":                     pool.tier,
            # Legacy single-pick fields kept for any reader that hasn't
            # migrated to `pool`/`picks_for_proof_row`.
            "listing_id":               top.listing_id,
            "rank_score":               round(top.rank_score, 2),
            "hero_photo_quality_score": top.hero_photo_quality_score,
            "fallback":                 pool.tier != "elite",
            "pool": [
                {
                    "listing_id":               e.listing_id,
                    "rank_score":               round(e.rank_score, 2),
                    "hero_photo_quality_score": e.hero_photo_quality_score,
                    "photos_count":             e.photos_count,
                }
                for e in pool.entries
            ],
        })
    else:
        # No legacy rotation pool but the proof row has picks — still
        # emit a valid-shape envelope so older readers don't 500 on
        # missing keys.
        payload.update({
            "tier":     "none",
            "fallback": True,
            "pool":     [],
        })

    payload["picks_for_proof_row"] = [_proof_row_entry_dict(li) for li in proof_picks]
    payload["proof_row_tier"]      = proof_tier

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return pool
