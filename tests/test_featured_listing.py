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


# ─────────────────────────────────────────────────────────────────────
# Proof-row picker tests (hero rewrite Phase 3)
# ─────────────────────────────────────────────────────────────────────

from pulpo.featured_listing import (   # noqa: E402
    PROOF_ROW_PICK_COUNT,
    pick_proof_row,
)


def _pr(**overrides) -> dict:
    """Listing dict that satisfies every proof-row STRICT gate by default
    (rank ≥ 75, days ≤ 60, hero_eligible, not sold, no overlay). Each
    helper invocation gets a unique source_id so the dedupe-by-key
    inside _pick_diverse doesn't collapse rows."""
    base = dict(_li())  # inherit not-sold + photos baseline
    base.update({
        "rank_score":      80.0,
        "days_listed":     30,
        "hero_eligible":   True,
        "card_eligible":   True,
        "master_category": "beach",
        "subcategory":     "homes",
    })
    base.update(overrides)
    return base


def test_proof_row_strict_returns_three_with_diversity():
    """Three rank-eligible listings spanning three buckets → all chosen."""
    listings = [
        _pr(source_id="A", rank_score=92, master_category="beach", subcategory="homes"),
        _pr(source_id="B", rank_score=88, master_category="lake",  subcategory="land"),
        _pr(source_id="C", rank_score=85, master_category="beach", subcategory="condos"),
    ]
    picks, tier = pick_proof_row(listings, override_path=Path("/dev/null"))
    assert tier == "strict"
    assert len(picks) == 3
    assert {p["source_id"] for p in picks} == {"A", "B", "C"}


def test_proof_row_prefers_unseen_buckets_over_rank():
    """A higher-rank duplicate-bucket loses to a lower-rank fresh bucket
    until count-or-buckets-exhausted, then rank-desc fill."""
    listings = [
        _pr(source_id="A", rank_score=99, master_category="beach", subcategory="homes"),
        _pr(source_id="B", rank_score=95, master_category="beach", subcategory="homes"),  # dup
        _pr(source_id="C", rank_score=80, master_category="lake",  subcategory="land"),
        _pr(source_id="D", rank_score=78, master_category="beach", subcategory="condos"),
    ]
    picks, _tier = pick_proof_row(listings, override_path=Path("/dev/null"))
    ids = [p["source_id"] for p in picks]
    # A wins on rank (first beach-homes), then C (fresh lake bucket), then
    # D (fresh beach-condos bucket). B (duplicate beach-homes) skipped.
    assert ids == ["A", "C", "D"]


def test_proof_row_enforces_beach_lake_invariant():
    """Even when 3 highest-rank eligible listings are all beach, one slot
    is swapped for the highest-rank lake candidate to satisfy the
    'must include ≥1 beach AND ≥1 lake' contract.

    All listings in the test set must clear the strict gate (rank ≥ 75)
    — the invariant only swaps within the eligible pool, not from
    outside. A below-threshold lake listing wouldn't be considered."""
    listings = [
        _pr(source_id="A", rank_score=99, master_category="beach", subcategory="homes"),
        _pr(source_id="B", rank_score=95, master_category="beach", subcategory="condos"),
        _pr(source_id="C", rank_score=90, master_category="beach", subcategory="land"),
        _pr(source_id="D", rank_score=78, master_category="lake",  subcategory="homes"),
        _pr(source_id="E", rank_score=82, master_category="beach", subcategory="homes"),  # dup
    ]
    picks, tier = pick_proof_row(listings, override_path=Path("/dev/null"))
    assert tier == "strict"
    masters = {p["master_category"] for p in picks}
    assert "beach" in masters and "lake" in masters
    # Should have kept the two highest-rank beach picks + injected D for lake
    ids = {p["source_id"] for p in picks}
    assert "D" in ids


def test_proof_row_invariant_unsatisfiable_returns_unchanged():
    """When the eligible pool has zero lake listings, the invariant
    can't be satisfied — picks come back beach-only and the tier is
    reported as-is. Caller sees the constraint slip via observability."""
    listings = [
        _pr(source_id="A", rank_score=99, master_category="beach", subcategory="homes"),
        _pr(source_id="B", rank_score=95, master_category="beach", subcategory="condos"),
        _pr(source_id="C", rank_score=90, master_category="beach", subcategory="land"),
    ]
    picks, tier = pick_proof_row(listings, override_path=Path("/dev/null"))
    assert tier == "strict"
    assert {p["master_category"] for p in picks} == {"beach"}


def test_proof_row_falls_back_to_relaxed_rank():
    """Strict pool < 3 (rank >= 75) but relaxed pool (rank >= 50) hits 3."""
    listings = [
        _pr(source_id="A", rank_score=80, master_category="beach", subcategory="homes"),
        _pr(source_id="B", rank_score=60, master_category="lake",  subcategory="land"),
        _pr(source_id="C", rank_score=55, master_category="beach", subcategory="condos"),
    ]
    picks, tier = pick_proof_row(listings, override_path=Path("/dev/null"))
    assert tier == "relaxed_rank"
    assert len(picks) == 3


def test_proof_row_falls_back_to_relaxed_eligibility():
    """All listings are card_eligible only (hero_eligible=False) — the
    relaxed_eligibility tier accepts them."""
    listings = [
        _pr(source_id="A", rank_score=80, hero_eligible=False, card_eligible=True,
            master_category="beach", subcategory="homes"),
        _pr(source_id="B", rank_score=60, hero_eligible=False, card_eligible=True,
            master_category="lake",  subcategory="land"),
        _pr(source_id="C", rank_score=55, hero_eligible=False, card_eligible=True,
            master_category="beach", subcategory="condos"),
    ]
    picks, tier = pick_proof_row(listings, override_path=Path("/dev/null"))
    assert tier == "relaxed_eligibility"
    assert len(picks) == 3


def test_proof_row_shortfall_returns_partial():
    """Even the loosest gate can't yield 3 — return whatever passed
    with the shortfall tier so operators see the constraint slip."""
    listings = [
        _pr(source_id="A", rank_score=80, master_category="beach", subcategory="homes"),
    ]
    picks, tier = pick_proof_row(listings, override_path=Path("/dev/null"))
    assert tier == "shortfall"
    assert len(picks) == 1


def test_proof_row_excludes_sold_and_overlay():
    """Sold + has_text_overlay listings never reach the picker."""
    listings = [
        _pr(source_id="A", is_sold=True, master_category="beach", subcategory="homes"),
        _pr(source_id="B", has_text_overlay=True, master_category="lake", subcategory="land"),
        _pr(source_id="C", rank_score=80, master_category="beach", subcategory="condos"),
    ]
    picks, tier = pick_proof_row(listings, override_path=Path("/dev/null"))
    assert tier == "shortfall"
    assert {p["source_id"] for p in picks} == {"C"}


def test_proof_row_override_wins_when_valid(tmp_path: Path):
    """A complete + resolvable override file beats the auto-pick. The
    picks land in override order, not rank order."""
    override = tmp_path / "override.json"
    override.write_text(json.dumps({
        "week_starting": "2026-05-12",
        "picks": ["goodlife|X", "goodlife|Y", "goodlife|Z"],
    }))
    listings = [
        _pr(source_id="X", rank_score=10, master_category="beach", subcategory="land"),
        _pr(source_id="Y", rank_score=20, master_category="lake",  subcategory="condos"),
        _pr(source_id="Z", rank_score=30, master_category="beach", subcategory="homes"),
        _pr(source_id="ignored", rank_score=99, master_category="beach", subcategory="homes"),
    ]
    picks, tier = pick_proof_row(listings, override_path=override)
    assert tier == "override"
    assert [p["source_id"] for p in picks] == ["X", "Y", "Z"]


def test_proof_row_override_falls_through_when_stale(tmp_path: Path):
    """Override IDs that don't resolve (deleted listings) cause a fall-
    through to the auto-pick when fewer than 3 ids resolve."""
    override = tmp_path / "override.json"
    override.write_text(json.dumps({
        "week_starting": "2026-05-12",
        "picks": ["gone|1", "gone|2", "goodlife|REAL"],
    }))
    listings = [
        _pr(source_id="REAL", rank_score=80, master_category="beach", subcategory="homes"),
        _pr(source_id="B",    rank_score=70, master_category="lake",  subcategory="land"),
        _pr(source_id="C",    rank_score=65, master_category="beach", subcategory="condos"),
    ]
    picks, tier = pick_proof_row(listings, override_path=override)
    # 1-of-3 resolved → not enough, auto-pick kicks in. Auto-pick
    # against this set lands in either strict or relaxed_rank.
    assert tier in ("strict", "relaxed_rank")
    assert len(picks) == 3


def test_proof_row_override_malformed_silently_ignored(tmp_path: Path):
    """A malformed override file (non-JSON, missing keys, wrong shape)
    falls through to the auto-pick without raising."""
    override = tmp_path / "override.json"
    override.write_text("{ not json")
    listings = [
        _pr(source_id="A", master_category="beach", subcategory="homes"),
        _pr(source_id="B", master_category="lake",  subcategory="land"),
        _pr(source_id="C", master_category="beach", subcategory="condos"),
    ]
    picks, tier = pick_proof_row(listings, override_path=override)
    assert tier == "strict"
    assert len(picks) == 3


def test_write_featured_json_includes_picks_for_proof_row(tmp_path: Path):
    """End-to-end: featured.json now carries both the legacy `pool` and
    the new `picks_for_proof_row` + `proof_row_tier` fields."""
    listings = [
        _pr(source_id="A", rank_score=90, master_category="beach", subcategory="homes"),
        _pr(source_id="B", rank_score=85, master_category="lake",  subcategory="land"),
        _pr(source_id="C", rank_score=80, master_category="beach", subcategory="condos"),
    ]
    out = tmp_path / "featured.json"
    write_featured_json(out, listings, now=_NOW, override_path=tmp_path / "missing.json")
    payload = json.loads(out.read_text())
    assert "pool" in payload  # legacy rotation
    assert "picks_for_proof_row" in payload
    assert "proof_row_tier" in payload
    assert payload["proof_row_tier"] == "strict"
    assert len(payload["picks_for_proof_row"]) == PROOF_ROW_PICK_COUNT
    # Each proof-row entry carries the bucket fields the FE needs
    for entry in payload["picks_for_proof_row"]:
        assert "listing_id" in entry
        assert "master_category" in entry
        assert "subcategory" in entry
        assert "star_rating" in entry
        assert "hero_eligible" in entry
