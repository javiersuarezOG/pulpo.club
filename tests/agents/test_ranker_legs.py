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
    """Locks in the Value / Location / Momentum consolidation. A regression
    that re-adds Liquidity, or restores the old "quality" / "upside" slugs,
    needs to update this assertion explicitly — silent re-introduction is
    exactly the kind of drift this is here to catch.
    """
    assert set(RANKER_LEGS.keys()) == {"value", "location", "momentum"}


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


# ── Property-type segmentation contract ────────────────────────────────
# These tests pin the invariant that the value leg's comp pools are keyed on
# (property_type, zone) tuples, not bare zone strings. The scrapers pull every
# real-estate listing — houses, condos, mansions, raw land — and without this
# segmentation a 6-bed mansion's $/m² would skew the percentile for vacant
# lots in the same zone. A future "simplification" that collapses the keys
# back to dict[str, list] would pass every other test silently. These don't.
# Architecture rationale lives in the docstring of pulpo/ranker_legs/value.py.

def test_value_segments_houses_from_land_in_same_zone():
    """A target lot's score must reflect ONLY land comps, never houses.

    Setup: 3 lots in el-tunco priced cheaply ($200–400/m²), 3 houses in
    el-tunco priced very cheaply ($10–30/m²). If the pools were mixed, the
    target lot at $200/m² would land at the median (50th pct) and score ~50.
    With segmentation, it falls into the land-only pool, scores at the bottom
    of that pool (0th pct → score 100).
    """
    leg = RANKER_LEGS["value"]
    pool = [
        _make_listing(source_id="land-a", property_type="land", price_per_m2=200.0),
        _make_listing(source_id="land-b", property_type="land", price_per_m2=300.0),
        _make_listing(source_id="land-c", property_type="land", price_per_m2=400.0),
        # If these houses leak into the land pool, the target's percentile drops.
        _make_listing(source_id="house-a", property_type="house", price_per_m2=10.0),
        _make_listing(source_id="house-b", property_type="house", price_per_m2=20.0),
        _make_listing(source_id="house-c", property_type="house", price_per_m2=30.0),
    ]
    target_lot = _make_listing(property_type="land", price_per_m2=200.0)
    score, reason = leg.score(target_lot, pool)
    # Segmented: target is at 0th pct of land-only pool → score 100
    # If broken: target would be at ~50th pct of mixed pool → score ~50
    assert score == pytest.approx(100.0), (
        f"expected segmented score 100, got {score}. Pool may have leaked across "
        f"property types. Reason: {reason}"
    )
    assert "land" in reason, f"reason should mention land pool: {reason}"


def test_value_macro_cascade_respects_property_type():
    """When a (property_type, zone) pool is too sparse, cascade falls through to
    that property_type's macro pool — never into a mixed pool that includes a
    different property_type.

    Setup: 1 land in el-tunco (sparse for zone-level), 3 houses in el-tunco
    (would-be tempting to merge), 3 land in el-zonte (same central-pacific
    macro). Target land in el-tunco should fall through to ('land',
    'central-pacific') macro — a 4-listing pool of LAND ONLY.
    """
    leg = RANKER_LEGS["value"]
    pool = [
        # 1 land in el-tunco — too sparse for zone-level (MIN_COMPS=3)
        _make_listing(source_id="land-tunco-a", zone="el-tunco",
                      property_type="land", price_per_m2=200.0),
        # 3 houses in el-tunco — must NOT be picked up by the land target
        _make_listing(source_id="house-tunco-a", zone="el-tunco",
                      property_type="house", price_per_m2=900.0),
        _make_listing(source_id="house-tunco-b", zone="el-tunco",
                      property_type="house", price_per_m2=1000.0),
        _make_listing(source_id="house-tunco-c", zone="el-tunco",
                      property_type="house", price_per_m2=1100.0),
        # 3 land in el-zonte — same central-pacific macro, valid cascade target
        _make_listing(source_id="land-zonte-a", zone="el-zonte",
                      property_type="land", price_per_m2=100.0),
        _make_listing(source_id="land-zonte-b", zone="el-zonte",
                      property_type="land", price_per_m2=200.0),
        _make_listing(source_id="land-zonte-c", zone="el-zonte",
                      property_type="land", price_per_m2=300.0),
    ]
    target_lot = _make_listing(zone="el-tunco", property_type="land", price_per_m2=250.0)
    score, reason = leg.score(target_lot, pool)
    # Macro pool for ("land", "central-pacific") = [200, 100, 200, 300] → sorted [100, 200, 200, 300]
    # Target 250 → bisect_left = 3 → percentile = 75 → score = 25
    # If houses leaked in, mixed pool would be 7 entries and percentile would shift to ~43, score ~57
    assert score == pytest.approx(25.0, abs=1.0), (
        f"expected segmented macro score ~25, got {score}. House comps may have "
        f"leaked into the land macro pool. Reason: {reason}"
    )
    assert "macro" in reason, f"expected macro cascade, got: {reason}"
    assert "land" in reason, f"reason should specify land pool: {reason}"


def test_value_reason_string_includes_property_type_label():
    """The reason string is the source of truth for which pool was picked.
    Pinning the format prevents an accidental drop of the type token from the
    label that would make pool selection silently invisible.
    """
    leg = RANKER_LEGS["value"]
    pool = [
        _make_listing(source_id="a", property_type="land", price_per_m2=100.0),
        _make_listing(source_id="b", property_type="land", price_per_m2=200.0),
        _make_listing(source_id="c", property_type="land", price_per_m2=300.0),
    ]
    _, reason = leg.score(
        _make_listing(property_type="land", price_per_m2=150.0),
        pool,
    )
    # Format: "value <s> ($X.XX/m² = Yth pct of <zone> land, N comps)"
    assert "el-tunco land" in reason, (
        f"expected zone-and-type label 'el-tunco land' in reason: {reason}"
    )


# ── Momentum leg (replaces Upside, repriced-rate-based) ───────────────────

def test_momentum_repriced_rate_orthogonal_to_zone_tier():
    """The point of Momentum: it ranks zones by price-drop activity, NOT by
    zone tier. A tier-A zone with low repriced rate must score lower than a
    tier-C zone with high repriced rate. Without this property, Momentum is
    just Location with extra steps (the failure mode of the old Upside leg).
    """
    leg = RANKER_LEGS["momentum"]
    # Pool: el-tunco (tier-A) with ~0% repriced rate; conchagua (tier-C) with
    # ~80% repriced rate. Zone has 5+ listings each so neither is sparse.
    pool = []
    for i in range(8):  # 8 tunco listings, 0 repriced
        pool.append(_make_listing(source_id=f"tunco-{i}", zone="el-tunco", is_repriced=False))
    for i in range(5):  # 5 conchagua, 4 repriced
        pool.append(_make_listing(source_id=f"con-{i}", zone="conchagua",
                                   is_repriced=(i < 4)))
    tunco_target = _make_listing(zone="el-tunco", is_repriced=False)
    con_target   = _make_listing(zone="conchagua", is_repriced=False)
    s_tunco, _ = leg.score(tunco_target, pool)
    s_con,   _ = leg.score(con_target, pool)
    assert s_con > s_tunco, (
        f"high-repriced-rate zone (conchagua, 80%) must score higher than "
        f"low-repriced-rate zone (el-tunco, 0%); got conchagua={s_con} vs "
        f"el-tunco={s_tunco}. If they're equal, the leg is collapsing the "
        f"signal it was designed to surface."
    )


def test_momentum_sparse_zone_neutral():
    """Zones with <5 listings score the neutral default 50.0. The repriced
    rate signal is too noisy on small samples to be informative.
    """
    leg = RANKER_LEGS["momentum"]
    # Only 3 listings in the zone — sparse. Even with 100% repriced rate the
    # zone gets neutral score because we don't trust the signal.
    pool = [
        _make_listing(source_id=f"sparse-{i}", zone="el-cuco", is_repriced=True)
        for i in range(3)
    ]
    target = _make_listing(zone="el-cuco", is_repriced=False)
    score, reason = leg.score(target, pool)
    assert score == pytest.approx(50.0)
    assert "sparse" in reason


def test_momentum_self_repriced_bonus():
    """A repriced listing gets a small bonus on top of its zone score. Two
    listings in the same dense zone — one repriced, one not — must differ
    by at least 5 points (or be capped at 100).
    """
    leg = RANKER_LEGS["momentum"]
    # Build a dense pool with non-zero repriced rate so the zone is in the
    # rates dict. Use el-tunco with 6 listings, 2 repriced.
    pool = [
        _make_listing(source_id=f"tunco-{i}", zone="el-tunco",
                      is_repriced=(i < 2))
        for i in range(6)
    ]
    # We also need a second zone with a different rate so the leg has variance.
    pool += [
        _make_listing(source_id=f"con-{i}", zone="conchagua",
                      is_repriced=(i < 3))
        for i in range(5)
    ]
    base     = _make_listing(zone="el-tunco", is_repriced=False)
    repriced = _make_listing(zone="el-tunco", is_repriced=True)
    s_base, _     = leg.score(base, pool)
    s_repriced, _ = leg.score(repriced, pool)
    assert s_repriced > s_base, (
        f"self-repriced listing must score above non-repriced peer in same "
        f"zone; got {s_repriced} vs {s_base}"
    )
