"""
PR-7.6 — daily-cron-stable featured-listing pick for the Discover hero.

Replaces the prototype's client-side hero pick (which sorted by
`photos_count desc, first_seen_at asc` per pageview) with a single,
deterministic pick written to disk so an Instagram ad clicked at
9:00:00 hits the same listing as one clicked at 9:00:01.

Eligibility (a featured listing satisfies ALL):
  - hero_photo_quality_score ≥ 80      (PR-7.6 — Phase 1 quality gate)
  - photos_count ≥ 3                    (avoid one-photo skeleton listings)
  - is_sold == false
  - days_listed ≤ 30                    (recent — keeps the hero fresh)
  - rank_score ≥ 70                      (defensible to surface investors)

Tie-break: highest rank_score wins. Same score → first by source/source_id
to keep the result deterministic across runs.

Output: web/data/featured.json carrying:

    {
        "listing_id":  "goodlife|GL-CUCO-001",
        "picked_at":   "2026-05-07T12:00:00+00:00",
        "expires_at":  "2026-05-08T00:00:00+00:00",
        "rank_score":  78.4,
        "hero_photo_quality_score": 90,
        "fallback":    false   // true when no eligible listing exists
                                // and we relax the gates
    }

Frontend reads this once on app boot and renders the Hero. Vercel CDN
serves the file edge-cached for 24h aligned to UTC midnight.

Pure: no I/O outside the single write. Listings are passed in;
pick_featured() returns the chosen Listing or None. write_featured_json()
serialises and writes.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


# Eligibility thresholds — kept here as constants so the cron-stable
# "why was THIS listing picked" question has a single clear answer.
MIN_PHOTO_QUALITY    = 80
MIN_PHOTOS_COUNT     = 3
MAX_DAYS_LISTED      = 30
MIN_RANK_SCORE       = 70.0


@dataclass(frozen=True)
class FeaturedPick:
    """Result of pick_featured(). Carries the chosen listing's
    identifiers + the score components that made it eligible. Used by
    the JSON writer + by tests."""
    listing_id:                 str
    rank_score:                 float
    hero_photo_quality_score:   Optional[int]
    fallback:                   bool      # True when gates were relaxed


def _key(li: Any) -> str:
    """Identifier shared with sidecars and price_history. Format:
    `{source}|{source_id}` — matches the FE adapter's `id` shape via
    a hyphen-replacement on the FE side."""
    src = getattr(li, "source", None) or (li.get("source") if isinstance(li, dict) else None)
    sid = getattr(li, "source_id", None) or (li.get("source_id") if isinstance(li, dict) else None)
    return f"{src}|{sid}"


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _eligible(li: Any) -> bool:
    """Strict eligibility — used in the primary pass."""
    if _g(li, "is_sold") is True:
        return False
    score = _g(li, "hero_photo_quality_score")
    if not isinstance(score, int) or score < MIN_PHOTO_QUALITY:
        return False
    photos_count = _g(li, "photos_count") or 0
    if photos_count < MIN_PHOTOS_COUNT:
        return False
    days_listed = _g(li, "days_listed")
    if days_listed is None or days_listed > MAX_DAYS_LISTED:
        return False
    rank = _g(li, "rank_score")
    if not isinstance(rank, (int, float)) or rank < MIN_RANK_SCORE:
        return False
    return True


def _eligible_relaxed(li: Any) -> bool:
    """Fallback when the strict pass returns nothing.

    Drops the rank_score gate (some early-catalog states have <10
    listings above 70) and the photo_quality gate (zero listings have
    quality scores in offline / no-OpenCV runs). Keeps the hard
    is_sold filter and a softened photos_count ≥ 1.
    """
    if _g(li, "is_sold") is True:
        return False
    photos_count = _g(li, "photos_count") or 0
    if photos_count < 1:
        return False
    return True


def _utc_midnight_after(now: datetime) -> datetime:
    """Next UTC-midnight after `now`. The cache TTL is aligned to
    midnight so the hero changes at most once per UTC day, regardless
    of when the nightly cron actually runs."""
    next_day = (now + timedelta(days=1)).date()
    return datetime(
        next_day.year, next_day.month, next_day.day,
        tzinfo=timezone.utc,
    )


def pick_featured(listings: list, now: Optional[datetime] = None) -> Optional[FeaturedPick]:
    """Pick the highest-ranking eligible listing.

    Returns None when neither the strict nor relaxed pass yields a
    candidate (e.g. an empty listings list). The caller decides what
    to do with None — typically: don't write featured.json, let the FE
    fall back to client-side hero pick (legacy behavior).

    `now` is injectable for tests.
    """
    del now  # unused in pick logic; reserved for future "freshness" gates

    # Stable tie-break: source/source_id, then strict ordering by score.
    pool = sorted(
        listings,
        key=lambda li: (_g(li, "source") or "", _g(li, "source_id") or ""),
    )

    strict = [li for li in pool if _eligible(li)]
    if strict:
        winner = max(strict, key=lambda li: _g(li, "rank_score") or 0)
        return FeaturedPick(
            listing_id               = _key(winner),
            rank_score               = float(_g(winner, "rank_score") or 0),
            hero_photo_quality_score = _g(winner, "hero_photo_quality_score"),
            fallback                 = False,
        )

    relaxed = [li for li in pool if _eligible_relaxed(li)]
    if relaxed:
        winner = max(relaxed, key=lambda li: _g(li, "rank_score") or 0)
        return FeaturedPick(
            listing_id               = _key(winner),
            rank_score               = float(_g(winner, "rank_score") or 0),
            hero_photo_quality_score = _g(winner, "hero_photo_quality_score"),
            fallback                 = True,
        )

    return None


def write_featured_json(out_path: Path, listings: list,
                        now: Optional[datetime] = None) -> Optional[FeaturedPick]:
    """Pick + serialize. Idempotent — safe to call from a cron and
    locally without side effects beyond the single file write.

    Returns the chosen FeaturedPick or None when no listing was eligible.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    pick = pick_featured(listings, now=now)
    if pick is None:
        # Nothing eligible — refuse to write the file rather than
        # writing a sentinel that the FE then has to interpret. Callers
        # check the existence of featured.json to decide whether to use
        # the cron-stable pick or fall back to client-side selection.
        return None

    payload = {
        "listing_id":               pick.listing_id,
        "picked_at":                now.isoformat(),
        "expires_at":               _utc_midnight_after(now).isoformat(),
        "rank_score":               round(pick.rank_score, 2),
        "hero_photo_quality_score": pick.hero_photo_quality_score,
        "fallback":                 pick.fallback,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return pick
