"""
Tests for pulpo/featured_listing.py — pin the cron-stable hero pick
contract.

Eligibility (strict pass): hero_photo_quality_score ≥ 80 AND
photos_count ≥ 3 AND days_listed ≤ 30 AND not is_sold AND
rank_score ≥ 70.

Tie-break: highest rank_score wins; same score → first by source/source_id.

Fallback (relaxed pass) drops the rank/quality/days gates and keeps
just is_sold + photos_count ≥ 1.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pulpo.featured_listing import (   # noqa: E402
    FeaturedPick,
    pick_featured,
    write_featured_json,
)


def _li(**overrides) -> dict:
    """Listing dict that satisfies every strict-pass gate by default."""
    base = {
        "source":                   "goodlife",
        "source_id":                "GL-001",
        "is_sold":                  False,
        "hero_photo_quality_score": 85,
        "photos_count":             5,
        "days_listed":              7,
        "rank_score":               80.0,
    }
    base.update(overrides)
    return base


_NOW = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


# ── strict-pass eligibility ────────────────────────────────────────────

def test_pick_returns_strict_winner():
    pick = pick_featured([_li()], now=_NOW)
    assert isinstance(pick, FeaturedPick)
    assert pick.listing_id == "goodlife|GL-001"
    assert pick.fallback is False


def test_filters_sold_listings():
    pick = pick_featured([_li(is_sold=True)], now=_NOW)
    # No strict eligible — falls back, but relaxed pass also rejects sold
    assert pick is None


def test_filters_low_photo_quality():
    pick = pick_featured([_li(hero_photo_quality_score=70)], now=_NOW)
    # Below 80 — strict fails. Relaxed permits it (only is_sold + photos_count gate).
    assert pick is not None
    assert pick.fallback is True


def test_filters_too_few_photos():
    pick = pick_featured([_li(photos_count=2)], now=_NOW)
    # Strict requires ≥3; relaxed only requires ≥1.
    assert pick is not None
    assert pick.fallback is True


def test_filters_old_listings():
    pick = pick_featured([_li(days_listed=60)], now=_NOW)
    # Strict requires ≤30; relaxed has no days_listed gate.
    assert pick is not None
    assert pick.fallback is True


def test_filters_low_rank_score():
    pick = pick_featured([_li(rank_score=40.0)], now=_NOW)
    # Strict requires ≥70; relaxed has no rank gate.
    assert pick is not None
    assert pick.fallback is True


# ── tie-breaking ───────────────────────────────────────────────────────

def test_highest_rank_score_wins():
    pool = [
        _li(source="goodlife",   source_id="A", rank_score=72),
        _li(source="oceanside",  source_id="B", rank_score=85),
        _li(source="century21",  source_id="C", rank_score=78),
    ]
    pick = pick_featured(pool, now=_NOW)
    assert pick.listing_id == "oceanside|B"


def test_tie_breaks_deterministically_by_source_then_id():
    """Two listings with same rank_score → stable order by source then source_id."""
    pool = [
        _li(source="oceanside",  source_id="X", rank_score=80),
        _li(source="goodlife",   source_id="A", rank_score=80),
        _li(source="goodlife",   source_id="Z", rank_score=80),
    ]
    pick = pick_featured(pool, now=_NOW)
    # `goodlife` < `oceanside` lexicographically → goodlife wins;
    # then `A` < `Z` within goodlife.
    assert pick.listing_id == "goodlife|A"


# ── fallback pass ──────────────────────────────────────────────────────

def test_no_strict_winner_falls_back():
    """All listings fail strict but pass relaxed → fallback=True."""
    pool = [_li(rank_score=10), _li(source_id="GL-002", rank_score=20)]
    pick = pick_featured(pool, now=_NOW)
    assert pick is not None
    assert pick.fallback is True


def test_returns_none_when_pool_empty():
    assert pick_featured([], now=_NOW) is None


def test_returns_none_when_only_sold_listings():
    """Sold listings fail both strict AND relaxed pass."""
    pool = [_li(is_sold=True), _li(source_id="GL-002", is_sold=True)]
    assert pick_featured(pool, now=_NOW) is None


def test_returns_none_when_only_zero_photo_listings():
    """Zero-photo listings fail relaxed (photos_count ≥ 1)."""
    pool = [_li(photos_count=0)]
    assert pick_featured(pool, now=_NOW) is None


# ── write_featured_json ───────────────────────────────────────────────

def test_write_creates_json_with_expected_shape(tmp_path: Path):
    out = tmp_path / "featured.json"
    pick = write_featured_json(out, [_li()], now=_NOW)
    assert pick is not None
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["listing_id"] == "goodlife|GL-001"
    assert payload["picked_at"] == _NOW.isoformat()
    # Expires at next UTC midnight
    assert payload["expires_at"] == "2026-05-08T00:00:00+00:00"
    assert payload["rank_score"] == 80.0
    assert payload["hero_photo_quality_score"] == 85
    assert payload["fallback"] is False


def test_write_does_not_create_file_when_no_pick(tmp_path: Path):
    """Empty pool → no file written → FE falls back to client-side pick."""
    out = tmp_path / "featured.json"
    result = write_featured_json(out, [], now=_NOW)
    assert result is None
    assert not out.exists()


def test_write_carries_fallback_flag(tmp_path: Path):
    out = tmp_path / "featured.json"
    pick = write_featured_json(out, [_li(rank_score=10)], now=_NOW)
    assert pick is not None
    assert pick.fallback is True
    payload = json.loads(out.read_text())
    assert payload["fallback"] is True


def test_write_works_with_dataclass_like_objects(tmp_path: Path):
    """The pick logic must work over both dicts (test stubs) and the
    real Listing dataclass — _g handles both."""
    class L:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
    pool = [L(**_li())]
    out = tmp_path / "featured.json"
    pick = write_featured_json(out, pool, now=_NOW)
    assert pick is not None
    assert pick.listing_id == "goodlife|GL-001"
