"""
Tests for automation/zone_medians.py — pins the FR-7.5 contract:

- Bucketing per (zone, property_type)
- MIN_LISTINGS_PER_ZONE threshold
- Active-filter exclusions (no price, sold, > 365 days_listed)
- Signed-percent computation for price_vs_zone_pct
- Idempotency (recompute each run = same values)
- Mixed-property-type segmentation (house $/m² doesn't pollute land $/m²)
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.zone_medians import (   # noqa: E402
    compute_zone_medians,
    apply_zone_metrics,
    compute_and_apply,
    _is_active,
    _bucket_key,
    MIN_LISTINGS_PER_ZONE,
    MAX_DAYS_LISTED_FOR_COMPS,
)


def _li(zone: str = "el-tunco", property_type: str = "land",
        price_per_m2: float | None = 200.0,
        days_listed: int | None = 30,
        is_sold: bool = False) -> dict:
    return {
        "zone":            zone,
        "property_type":   property_type,
        "price_per_m2":    price_per_m2,
        "days_listed":     days_listed,
        "is_sold":         is_sold,
        "price_vs_zone_median": None,
        "price_vs_zone_pct":    None,
    }


# ── _is_active filter ──────────────────────────────────────────────────

def test_active_basic():
    assert _is_active(_li())


def test_inactive_when_sold():
    assert not _is_active(_li(is_sold=True))


def test_inactive_when_no_price():
    assert not _is_active(_li(price_per_m2=None))


def test_inactive_when_zero_price():
    assert not _is_active(_li(price_per_m2=0))


def test_inactive_when_negative_price():
    assert not _is_active(_li(price_per_m2=-1))


def test_inactive_when_too_old():
    """PRD §FR-7.5 — exclude listings older than MAX_DAYS_LISTED_FOR_COMPS."""
    assert not _is_active(_li(days_listed=MAX_DAYS_LISTED_FOR_COMPS + 1))


def test_active_at_threshold():
    """At-the-threshold listings count (boundary: ≤365)."""
    assert _is_active(_li(days_listed=MAX_DAYS_LISTED_FOR_COMPS))


def test_active_when_days_listed_none():
    """Missing days_listed shouldn't disqualify (some scrapers don't expose it)."""
    assert _is_active(_li(days_listed=None))


# ── _bucket_key ────────────────────────────────────────────────────────

def test_bucket_key_basic():
    assert _bucket_key(_li(zone="el-cuco", property_type="land")) == ("el-cuco", "land")


def test_bucket_key_none_when_zone_missing():
    assert _bucket_key(_li(zone="")) is None
    assert _bucket_key({"zone": None, "property_type": "land"}) is None


def test_bucket_key_none_when_zone_unresolved():
    assert _bucket_key(_li(zone="unresolved")) is None


def test_bucket_key_defaults_property_type_to_land():
    assert _bucket_key({"zone": "el-tunco", "property_type": None}) == ("el-tunco", "land")


# ── compute_zone_medians ───────────────────────────────────────────────

def test_compute_below_min_returns_empty():
    """Bucket with fewer than MIN_LISTINGS_PER_ZONE peers is excluded."""
    listings = [_li(price_per_m2=p) for p in [100, 200, 300]]   # n=3 < 10
    medians = compute_zone_medians(listings)
    assert medians == {}


def test_compute_at_min_returns_median():
    listings = [_li(price_per_m2=p) for p in range(100, 100 + MIN_LISTINGS_PER_ZONE * 10, 10)]
    assert len(listings) == MIN_LISTINGS_PER_ZONE
    medians = compute_zone_medians(listings)
    assert ("el-tunco", "land") in medians
    # Even spread 100, 110, 120, ..., 190 → median is between 140 and 150
    assert 140 <= medians[("el-tunco", "land")] <= 150


def test_compute_segments_by_property_type():
    """House $/m² shouldn't pollute land $/m² in the same zone."""
    land_listings  = [_li(price_per_m2=200) for _ in range(MIN_LISTINGS_PER_ZONE)]
    house_listings = [_li(price_per_m2=1000, property_type="house")
                      for _ in range(MIN_LISTINGS_PER_ZONE)]
    medians = compute_zone_medians(land_listings + house_listings)
    assert medians[("el-tunco", "land")]  == 200.0
    assert medians[("el-tunco", "house")] == 1000.0


def test_compute_excludes_sold_listings():
    listings  = [_li(price_per_m2=100) for _ in range(MIN_LISTINGS_PER_ZONE)]
    listings += [_li(price_per_m2=999, is_sold=True) for _ in range(20)]
    medians = compute_zone_medians(listings)
    # Sold listings excluded → median should be ~100
    assert medians[("el-tunco", "land")] == 100.0


def test_compute_excludes_stale_listings():
    listings  = [_li(price_per_m2=100) for _ in range(MIN_LISTINGS_PER_ZONE)]
    listings += [_li(price_per_m2=999, days_listed=400) for _ in range(20)]
    medians = compute_zone_medians(listings)
    assert medians[("el-tunco", "land")] == 100.0


# ── apply_zone_metrics ─────────────────────────────────────────────────

def test_apply_signs_pct_correctly():
    """Positive pct = above median; negative = below."""
    bucket_medians = {("el-tunco", "land"): 200.0}
    listings = [
        _li(price_per_m2=200),   # at median → 0%
        _li(price_per_m2=240),   # +20% above
        _li(price_per_m2=160),   # -20% below
    ]
    apply_zone_metrics(listings, bucket_medians)
    assert listings[0]["price_vs_zone_pct"] == 0.0
    assert listings[1]["price_vs_zone_pct"] == 20.0
    assert listings[2]["price_vs_zone_pct"] == -20.0


def test_apply_sets_median_field_too():
    bucket_medians = {("el-tunco", "land"): 175.5}
    li = _li(price_per_m2=200)
    apply_zone_metrics([li], bucket_medians)
    assert li["price_vs_zone_median"] == 175.5


def test_apply_skips_listings_with_no_bucket_median():
    """Bucket not in medians dict → both fields stay None."""
    listings = [_li(zone="rare-zone", price_per_m2=100)]
    metrics = apply_zone_metrics(listings, {})
    assert listings[0]["price_vs_zone_median"] is None
    assert listings[0]["price_vs_zone_pct"] is None
    assert metrics["listings_skipped_no_bucket_median"] == 1


def test_apply_skips_inactive_listings():
    listings = [_li(price_per_m2=None), _li(is_sold=True),
                _li(price_per_m2=100)]
    metrics = apply_zone_metrics(listings, {("el-tunco", "land"): 100.0})
    assert metrics["listings_skipped_inactive"] == 2
    assert metrics["listings_scored"] == 1


# ── compute_and_apply (end-to-end) ─────────────────────────────────────

def test_compute_and_apply_full_path():
    """End-to-end on a realistic mini-catalog."""
    # 12 land listings in el-tunco — eligible for median
    listings = [_li(price_per_m2=p) for p in [100, 110, 120, 130, 140, 150,
                                                 160, 170, 180, 190, 200, 210]]
    # Plus 5 listings in el-cuco — NOT eligible (below threshold)
    listings += [_li(zone="el-cuco", price_per_m2=p) for p in [50, 60, 70, 80, 90]]
    # Plus a sold listing that should be excluded
    listings.append(_li(price_per_m2=9999, is_sold=True))

    metrics = compute_and_apply(listings)
    assert metrics["buckets_computed"] == 1   # only el-tunco land qualifies
    assert metrics["listings_scored"] == 12   # all 12 active el-tunco land

    # el-tunco median: midpoint of 12 sorted values is between 150 and 160
    tunco_median = listings[0]["price_vs_zone_median"]
    assert tunco_median == 155.0

    # el-cuco listings get NOTHING — bucket below threshold
    el_cuco = [li for li in listings if li["zone"] == "el-cuco"]
    assert all(li["price_vs_zone_median"] is None for li in el_cuco)
    assert all(li["price_vs_zone_pct"] is None for li in el_cuco)


def test_idempotent_repeat_application():
    """Running twice with the same inputs produces identical outputs."""
    listings = [_li(price_per_m2=100 + i * 10) for i in range(MIN_LISTINGS_PER_ZONE)]
    compute_and_apply(listings)
    snapshot = [(li["price_vs_zone_median"], li["price_vs_zone_pct"]) for li in listings]
    compute_and_apply(listings)
    again = [(li["price_vs_zone_median"], li["price_vs_zone_pct"]) for li in listings]
    assert snapshot == again


def test_metrics_shape():
    metrics = compute_and_apply([])
    for k in ("buckets_computed", "buckets_below_min", "listings_scored",
              "listings_skipped_no_zone", "listings_skipped_inactive",
              "listings_skipped_no_bucket_median"):
        assert k in metrics
