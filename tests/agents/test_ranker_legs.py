"""Tests for individual ranker legs in isolation."""
import pytest
from pulpo.models import Listing
from pulpo.agents import RANKER_LEGS


def _make_listing(**kwargs) -> Listing:
    defaults = dict(
        source="test", source_id="t1", url="http://x.com/1", scraped_at="2026-01-01T00:00:00Z",
        title="Test Lot", zone="el-tunco", area_m2=1000.0, price_usd=200_000.0, price_per_m2=200.0,
    )
    defaults.update(kwargs)
    return Listing(**defaults)


def test_only_three_legs_registered():
    """Locks in the V/Location/Upside consolidation. A regression that
    re-adds Liquidity or restores the old "quality" slug needs to update
    this assertion explicitly — silent re-introduction is exactly the
    kind of drift this is here to catch.
    """
    assert set(RANKER_LEGS.keys()) == {"value", "location", "upside"}


def test_location_beachfront_bonus():
    leg = RANKER_LEGS["location"]
    base = leg.score(_make_listing(is_beachfront=False), [])
    beach = leg.score(_make_listing(is_beachfront=True), [])
    assert beach[0] > base[0]


def test_location_tier_a_beats_tier_c():
    leg = RANKER_LEGS["location"]
    tier_a = leg.score(_make_listing(zone="el-tunco"), [])
    tier_c = leg.score(_make_listing(zone="conchagua"), [])
    assert tier_a[0] > tier_c[0]


def test_location_stale_listing_penalized():
    """DOM penalty was folded in from the dropped LIQUIDITY leg. A 200-day
    stale listing must score lower than a 5-day fresh one, all else equal.
    """
    leg = RANKER_LEGS["location"]
    fresh = leg.score(_make_listing(days_listed=5), [])
    stale = leg.score(_make_listing(days_listed=200), [])
    assert fresh[0] > stale[0]


def test_location_repriced_bonus():
    """Repriced bonus was folded in from the dropped LIQUIDITY leg. A
    repriced listing must score higher than an otherwise-identical
    unrepriced one (motivated-seller signal)."""
    leg = RANKER_LEGS["location"]
    base = leg.score(_make_listing(is_repriced=False), [])
    repriced = leg.score(_make_listing(is_repriced=True), [])
    assert repriced[0] > base[0]


def test_location_airport_distance_bonus():
    """Per pulpo/airports.py, zones near SAL get +5, far zones get -5.
    Comparing two same-tier (C) zones to isolate the airport signal:
    punta-mango is ~105 km from SAL (0 bonus) and la-union is ~132 km
    (-5 penalty). The closer zone scores higher.
    """
    leg = RANKER_LEGS["location"]
    far    = leg.score(_make_listing(zone="la-union"), [])      # tier-C, ~132 km, -5
    nearer = leg.score(_make_listing(zone="punta-mango"), [])   # tier-C, ~105 km,  0
    assert nearer[0] > far[0], (
        f"closer zone (punta-mango, 105 km) should score higher than far "
        f"zone (la-union, 132 km); got {nearer} vs {far}"
    )
    # Sanity: airport reason string surfaces in both
    assert "airport" in far[1]
    assert "airport" in nearer[1]


def test_value_cheaper_scores_higher():
    leg = RANKER_LEGS["value"]
    pool = [
        _make_listing(source_id="a", price_per_m2=100.0),
        _make_listing(source_id="b", price_per_m2=500.0),
        _make_listing(source_id="c", price_per_m2=1000.0),
    ]
    cheap = leg.score(_make_listing(price_per_m2=50.0), pool)
    expensive = leg.score(_make_listing(price_per_m2=2000.0), pool)
    assert cheap[0] > expensive[0]


def test_value_no_price_returns_default():
    leg = RANKER_LEGS["value"]
    s, reason = leg.score(_make_listing(price_per_m2=None), [])
    assert s == pytest.approx(35.0)
    assert "no $/m²" in reason


def test_upside_beachfront_bonus():
    leg = RANKER_LEGS["upside"]
    base = leg.score(_make_listing(is_beachfront=False), [])
    beach = leg.score(_make_listing(is_beachfront=True), [])
    assert beach[0] >= base[0]
