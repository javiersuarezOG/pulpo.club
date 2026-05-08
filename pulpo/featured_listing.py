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


def write_featured_json(out_path: Path, listings: list,
                        now: Optional[datetime] = None) -> Optional[FeaturedPool]:
    """Pick + serialize. Idempotent - safe to call from a cron and
    locally without side effects beyond the single file write.

    Returns the chosen FeaturedPool or None when no listing was eligible.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    pool = pick_featured_pool(listings, now=now)
    if pool is None:
        # Nothing eligible - refuse to write the file rather than
        # writing a sentinel. Callers check the existence of
        # featured.json to decide whether to use the cron-stable pick
        # or fall back to client-side selection.
        return None

    top = pool.entries[0]
    payload = {
        "tier":       pool.tier,
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
        },
        "picked_at":               now.isoformat(),
        "expires_at":              _utc_midnight_after(now).isoformat(),
        # Legacy single-pick fields - older readers and the schema keep
        # working. The FE prefers `pool`.
        "listing_id":              top.listing_id,
        "rank_score":              round(top.rank_score, 2),
        "hero_photo_quality_score": top.hero_photo_quality_score,
        "fallback":                pool.tier != "elite",
        "pool": [
            {
                "listing_id":               e.listing_id,
                "rank_score":               round(e.rank_score, 2),
                "hero_photo_quality_score": e.hero_photo_quality_score,
                "photos_count":             e.photos_count,
            }
            for e in pool.entries
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return pool
