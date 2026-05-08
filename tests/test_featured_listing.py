"""
Tests for pulpo/featured_listing.py — pin the cron-stable hero pool
contract.

Three tiers, layered. The first non-empty tier wins:

  elite     not sold | photos>=8 | rank>=75 | days<=30 | quality>=80 (or null)
  soft      not sold | photos>=5 | rank>=65 | days<=30
  fallback  not sold | photos>=1                                (single entry)

Pool order: rank_score desc, ties broken by source then source_id.
Pool capped at MAX_POOL = 12.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pulpo.featured_listing import (   # noqa: E402
    MAX_POOL,
    FeaturedEntry,
    FeaturedPool,
    pick_featured_pool,
    write_featured_json,
)


def _li(**overrides) -> dict:
    """Listing dict that satisfies every elite-tier gate by default."""
    base = {
        "source":                   "goodlife",
        "source_id":                "GL-001",
        "is_sold":                  False,
        "hero_photo_quality_score": 85,
        "photos_count":             10,
        "days_listed":              7,
        "rank_score":               80.0,
    }
    base.update(overrides)
    return base


_NOW = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


# elite-tier eligibility

def test_pick_returns_elite_pool():
    pool = pick_featured_pool([_li()], now=_NOW)
    assert isinstance(pool, FeaturedPool)
    assert pool.tier == "elite"
    assert len(pool.entries) == 1
    assert pool.entries[0].listing_id == "goodlife|GL-001"


def test_elite_accepts_null_photo_quality_when_rank_and_photos_strong():
    """Photo-scoring backfill catches up over time - until then, rank+photos proxy must work."""
    pool = pick_featured_pool([_li(hero_photo_quality_score=None)], now=_NOW)
    assert pool is not None
    assert pool.tier == "elite"


def test_elite_rejects_low_photo_quality_when_scored():
    """Once a listing IS scored, the literal >=80 bar bites."""
    pool = pick_featured_pool([_li(hero_photo_quality_score=70)], now=_NOW)
    # Falls to soft tier (still passes rank>=65, photos>=5).
    assert pool is not None
    assert pool.tier == "soft"


def test_elite_rejects_too_few_photos():
    pool = pick_featured_pool([_li(photos_count=6)], now=_NOW)
    # 6 < elite floor of 8, but >= soft floor of 5.
    assert pool is not None
    assert pool.tier == "soft"


def test_elite_rejects_low_rank():
    pool = pick_featured_pool([_li(rank_score=70)], now=_NOW)
    # 70 < elite floor of 75, but >= soft floor of 65.
    assert pool is not None
    assert pool.tier == "soft"


def test_elite_rejects_stale_listings():
    pool = pick_featured_pool([_li(days_listed=60)], now=_NOW)
    # Days gate applies to elite AND soft - falls all the way to fallback.
    assert pool is not None
    assert pool.tier == "fallback"


def test_filters_sold_listings_at_every_tier():
    assert pick_featured_pool([_li(is_sold=True)], now=_NOW) is None


def test_elite_excludes_text_overlay_hero():
    """OCR-flagged brochure-style hero photos are excluded from the
    elite pool. Soft tier doesn't gate on this — text-overlay listings
    are still acceptable as soft fallbacks since the bar is lower."""
    pool = pick_featured_pool([_li(has_text_overlay=True)], now=_NOW)
    assert pool is not None
    assert pool.tier == "soft"


def test_elite_accepts_null_text_overlay():
    """None means 'no OCR signal' (Tesseract absent / undecodable image).
    Same null-tolerance pattern as hero_photo_quality_score — keep the
    listing rather than dropping it on a missing-signal."""
    pool = pick_featured_pool([_li(has_text_overlay=None)], now=_NOW)
    assert pool is not None
    assert pool.tier == "elite"


def test_elite_accepts_explicit_false_text_overlay():
    """Explicit False = OCR ran and found no text. Same as null path."""
    pool = pick_featured_pool([_li(has_text_overlay=False)], now=_NOW)
    assert pool is not None
    assert pool.tier == "elite"


# pool ordering + capping

def test_pool_sorted_by_rank_score_desc():
    listings = [
        _li(source_id="LOW",  rank_score=76),
        _li(source_id="HIGH", rank_score=87),
        _li(source_id="MID",  rank_score=80),
    ]
    pool = pick_featured_pool(listings, now=_NOW)
    assert pool is not None
    assert [e.listing_id for e in pool.entries] == [
        "goodlife|HIGH", "goodlife|MID", "goodlife|LOW",
    ]


def test_pool_tie_break_deterministic_by_source_then_id():
    listings = [
        _li(source="oceanside", source_id="X", rank_score=80),
        _li(source="goodlife",  source_id="Z", rank_score=80),
        _li(source="goodlife",  source_id="A", rank_score=80),
    ]
    pool = pick_featured_pool(listings, now=_NOW)
    assert pool is not None
    # Same rank: goodlife before oceanside; A before Z.
    assert [e.listing_id for e in pool.entries] == [
        "goodlife|A", "goodlife|Z", "oceanside|X",
    ]


def test_pool_capped_at_max():
    listings = [
        _li(source_id=f"GL-{i:03d}", rank_score=75 + (i * 0.01))
        for i in range(MAX_POOL + 5)
    ]
    pool = pick_featured_pool(listings, now=_NOW)
    assert pool is not None
    assert len(pool.entries) == MAX_POOL


# tier promotion

def test_falls_to_soft_when_no_elite():
    listings = [_li(photos_count=5, rank_score=66, hero_photo_quality_score=None)]
    pool = pick_featured_pool(listings, now=_NOW)
    assert pool is not None
    assert pool.tier == "soft"


def test_falls_to_fallback_when_no_soft():
    """Single old listing with one photo - only the minimum tier accepts it."""
    listings = [_li(photos_count=1, rank_score=40, days_listed=120)]
    pool = pick_featured_pool(listings, now=_NOW)
    assert pool is not None
    assert pool.tier == "fallback"
    assert len(pool.entries) == 1


def test_returns_none_when_pool_empty():
    assert pick_featured_pool([], now=_NOW) is None


def test_returns_none_when_only_zero_photo_listings():
    """Zero-photo listings fail every tier."""
    assert pick_featured_pool([_li(photos_count=0)], now=_NOW) is None


# write_featured_json

def test_write_creates_json_with_pool_shape(tmp_path: Path):
    out = tmp_path / "featured.json"
    pool = write_featured_json(out, [_li()], now=_NOW)
    assert pool is not None
    assert out.exists()
    payload = json.loads(out.read_text())

    # Top-level shape
    assert payload["tier"] == "elite"
    assert payload["picked_at"] == _NOW.isoformat()
    assert payload["expires_at"] == "2026-05-08T00:00:00+00:00"
    assert payload["fallback"] is False

    # Legacy single-pick fields still present
    assert payload["listing_id"] == "goodlife|GL-001"
    assert payload["rank_score"] == 80.0
    assert payload["hero_photo_quality_score"] == 85

    # Pool array
    assert isinstance(payload["pool"], list)
    assert len(payload["pool"]) == 1
    assert payload["pool"][0]["listing_id"] == "goodlife|GL-001"
    assert payload["pool"][0]["photos_count"] == 10

    # Criteria block - observability + debugging
    assert payload["criteria"]["elite"]["min_rank"] == 75
    assert payload["criteria"]["elite"]["min_photos"] == 8


def test_write_marks_fallback_true_when_tier_not_elite(tmp_path: Path):
    out = tmp_path / "featured.json"
    pool = write_featured_json(
        out, [_li(photos_count=5, rank_score=66)], now=_NOW
    )
    assert pool is not None
    assert pool.tier == "soft"
    payload = json.loads(out.read_text())
    assert payload["tier"] == "soft"
    assert payload["fallback"] is True


def test_write_does_not_create_file_when_no_pick(tmp_path: Path):
    out = tmp_path / "featured.json"
    result = write_featured_json(out, [], now=_NOW)
    assert result is None
    assert not out.exists()


def test_write_works_with_dataclass_like_objects(tmp_path: Path):
    """The pick logic must work over both dicts (test stubs) and the
    real Listing dataclass - _g handles both."""
    class L:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
    listings = [L(**_li())]
    out = tmp_path / "featured.json"
    pool = write_featured_json(out, listings, now=_NOW)
    assert pool is not None
    assert pool.entries[0].listing_id == "goodlife|GL-001"


def test_entry_carries_photos_count():
    """photos_count is in each pool entry so the FE can show it
    without needing the full listing data."""
    pool = pick_featured_pool([_li(photos_count=15)], now=_NOW)
    assert pool is not None
    assert isinstance(pool.entries[0], FeaturedEntry)
    assert pool.entries[0].photos_count == 15
