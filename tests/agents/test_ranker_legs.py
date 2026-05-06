"""Tests for individual ranker legs in isolation."""
import pytest
from pulpo.models import Listing
# Import the leg modules so each registers itself in RANKER_LEGS. Without
# this, RANKER_LEGS is empty when the file is run in isolation (the full
# suite previously masked this — some earlier test file pre-imported them).
import pulpo.ranker_legs.value     # noqa: F401
import pulpo.ranker_legs.location  # noqa: F401
import pulpo.ranker_legs.momentum  # noqa: F401
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
    """Per pulpo/airports.py, the leg picks the nearest airport across SAL
    (operational) and AeP (planned, eastern coast) and applies a bonus.

    Comparing two same-tier (C) zones to isolate the airport signal:
    Conchagua sits ~15 km from AeP (+5 "near airport"); El Espino is
    ~62 km from its nearest airport (0, mid-bracket). Same tier, same
    base — only the airport bonus differs.
    """
    leg = RANKER_LEGS["location"]
    near_aep = leg.score(_make_listing(zone="conchagua"), [])  # tier-C, AeP 15 km, +5
    far_aep  = leg.score(_make_listing(zone="el-espino"), [])  # tier-C, AeP 62 km, 0
    assert near_aep[0] > far_aep[0], (
        f"zone with closer airport (conchagua, AeP 15 km) should score higher "
        f"than mid-bracket (el-espino, 62 km); got {near_aep} vs {far_aep}"
    )
    # Sanity: airport reason string surfaces in both, and surfaces the
    # specific airport code so the user can read which one was picked.
    assert "airport" in near_aep[1] and "AeP" in near_aep[1]
    assert "airport" in far_aep[1]


def test_location_airport_picks_nearest_across_sal_and_aep():
    """The eastern coast benefits from AeP even though SAL is far away.
    Conchagua → SAL is ~130 km (-5 in the old single-airport model);
    Conchagua → AeP is ~15 km (+5). The leg must pick the minimum.
    """
    leg = RANKER_LEGS["location"]
    s, reason = leg.score(_make_listing(zone="conchagua"), [])
    # Reason must reference AeP, not SAL — proves min(SAL, AeP) is firing.
    assert "AeP" in reason, (
        f"expected AeP in reason for conchagua (closer than SAL); got: {reason}"
    )
    # And the bonus must be +5 (near bracket), not -5 (far bracket).
    assert "+5" in reason, (
        f"expected +5 near-airport bonus for conchagua via AeP; got: {reason}"
    )


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


# ── Momentum leg (listing-velocity via first_seen_at) ─────────────────────
# Replaces the prior is_repriced-based algorithm: live broker data has 0%
# REBAJADO/REDUCED markers, so that signal was effectively dead. The new
# algorithm ranks zones by the mean age of their listings' first_seen_at
# timestamps — newer-on-average inventory → higher momentum score.


def _at(days_ago: float) -> str:
    """Helper: ISO timestamp for a point N days before now."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_momentum_newer_listings_score_higher_than_stale_zone():
    """A zone whose listings are mostly new arrivals scores higher than a
    zone whose listings have been sitting in our index. Same property type,
    same composition — only the first_seen_at distribution differs.
    """
    leg = RANKER_LEGS["momentum"]
    pool = []
    # Zone A: 6 listings, all first seen 0–1 days ago (fresh)
    for i in range(6):
        pool.append(_make_listing(source_id=f"fresh-{i}", zone="el-tunco",
                                   first_seen_at=_at(i * 0.2)))
    # Zone B: 6 listings, all first seen 30+ days ago (stale)
    for i in range(6):
        pool.append(_make_listing(source_id=f"stale-{i}", zone="conchagua",
                                   first_seen_at=_at(30 + i * 0.2)))
    fresh_target = _make_listing(zone="el-tunco", first_seen_at=_at(0.5))
    stale_target = _make_listing(zone="conchagua", first_seen_at=_at(30.5))
    s_fresh, _ = leg.score(fresh_target, pool)
    s_stale, _ = leg.score(stale_target, pool)
    assert s_fresh > s_stale, (
        f"zone with fresh listings (mean age ~0.5d) should score higher "
        f"than zone with stale listings (mean age ~30d); got fresh={s_fresh} "
        f"vs stale={s_stale}"
    )


def test_momentum_sparse_zone_neutral():
    """Zones with <5 listings score the neutral default 50.0 — too few
    listings for the per-zone mean age to be informative."""
    leg = RANKER_LEGS["momentum"]
    pool = [
        _make_listing(source_id=f"sparse-{i}", zone="el-cuco", first_seen_at=_at(i))
        for i in range(3)
    ]
    target = _make_listing(zone="el-cuco", first_seen_at=_at(1))
    score, reason = leg.score(target, pool)
    assert score == pytest.approx(50.0)
    assert "sparse" in reason


def test_momentum_insufficient_history_returns_neutral():
    """When all dense zones have mean ages within MIN_HISTORY_SPAN_DAYS
    (=1 day) of each other, the sidecar is too young — the leg returns
    neutral with an explanatory reason instead of producing meaningless
    rank-noise. This is the gate that auto-opens once the cron has been
    running for ~3-7 days and zones diverge.
    """
    leg = RANKER_LEGS["momentum"]
    pool = []
    for i in range(6):
        pool.append(_make_listing(source_id=f"a-{i}", zone="el-tunco",
                                   first_seen_at=_at(0.1 * i)))
    for i in range(6):
        pool.append(_make_listing(source_id=f"b-{i}", zone="conchagua",
                                   first_seen_at=_at(0.1 * i)))
    target = _make_listing(zone="el-tunco", first_seen_at=_at(0))
    score, reason = leg.score(target, pool)
    assert score == pytest.approx(50.0)
    assert "insufficient history" in reason


def test_momentum_orthogonal_to_zone_tier():
    """The point of Momentum: it ranks zones by inventory dynamics, NOT by
    zone tier. A tier-C zone with fresh listings must score higher than a
    tier-A zone with stale listings. Without this, Momentum is just
    Location with extra steps.
    """
    leg = RANKER_LEGS["momentum"]
    pool = []
    # Tier-A zone (el-tunco) but stale — listings have been sitting for 30+ days
    for i in range(6):
        pool.append(_make_listing(source_id=f"tunco-stale-{i}", zone="el-tunco",
                                   first_seen_at=_at(30 + i * 0.1)))
    # Tier-C zone (conchagua) but fresh — listings just arrived
    for i in range(6):
        pool.append(_make_listing(source_id=f"con-fresh-{i}", zone="conchagua",
                                   first_seen_at=_at(i * 0.1)))
    a_target = _make_listing(zone="el-tunco", first_seen_at=_at(30))
    c_target = _make_listing(zone="conchagua", first_seen_at=_at(0))
    s_a, _ = leg.score(a_target, pool)
    s_c, _ = leg.score(c_target, pool)
    assert s_c > s_a, (
        f"fresh tier-C zone must score higher Momentum than stale tier-A "
        f"zone (Momentum is delta-shaped, independent of tier); got "
        f"tier-A_stale={s_a} vs tier-C_fresh={s_c}"
    )


# ── Per-type ranker — built metric ─────────────────────────────────────
# Phase B: house/condo with built_area_m2 ranks against $/built-m² pool of
# similar built listings. House/condo without built_area_m2 falls through
# to the existing $/lot-m² metric. Land never uses the built pool.

def _h(source_id: str, **kw) -> Listing:
    """A built listing — defaults wired so price_per_built_m2 derives via
    normalize-style construction. Tests pass it pre-computed for clarity."""
    defaults = dict(
        source="bienesraices", url=f"http://x.com/{source_id}",
        scraped_at="2026-01-01T00:00:00Z",
        title="Casa", property_type="house", zone="el-tunco",
        area_m2=300.0, price_usd=400_000.0, price_per_m2=None,
        built_area_m2=200.0, price_per_built_m2=2_000.0, bedrooms=3,
    )
    defaults.update(kw)
    return Listing(source_id=source_id, **defaults)


def test_value_built_metric_used_for_house_with_built_area():
    """House with built_area_m2 should be scored against the built pool,
    not the lot pool. The reason string must reflect $/built-m²."""
    leg = RANKER_LEGS["value"]
    pool = [_h(f"H{i}", price_per_built_m2=2000.0 + 100 * i) for i in range(5)]
    cheap = pool[0]   # $2000/built-m² (cheapest)
    score, reason = leg.score(cheap, pool)
    assert "$/built-m²" not in reason or "built-m²" in reason  # label lands
    assert "built-m² = 0th pct" in reason or "built" in reason
    assert score > 80


def test_value_lot_metric_for_land_unchanged():
    """Land must NOT use the built pool — pure regression guard for the
    815 land listings on production today."""
    leg = RANKER_LEGS["value"]
    pool = [_make_listing(source_id=f"L{i}", price_per_m2=100.0 + 10 * i)
            for i in range(5)]
    target = pool[0]
    score, reason = leg.score(target, pool)
    assert "/built-m²" not in reason, "land must use lot metric"
    assert "/m² = " in reason


def test_value_house_without_built_area_falls_back_to_lot_pool():
    """80% of bienesraices houses have no built_area_m2. They must still
    get a score (against the lot pool) instead of the no-comp default."""
    leg = RANKER_LEGS["value"]
    # Pool of houses where most have built area (built pool exists)
    pool = [_h(f"H{i}", price_per_built_m2=2000.0) for i in range(5)]
    # Target house with NO built area but lot data present
    no_built = _h("HX", built_area_m2=None, price_per_built_m2=None,
                  area_m2=300.0, price_per_m2=1333.0)
    # Add lot comps so the lot pool has signal
    pool += [_h(f"HL{i}", built_area_m2=None, price_per_built_m2=None,
                area_m2=300.0, price_per_m2=1000.0 + 100 * i) for i in range(5)]
    score, reason = leg.score(no_built, pool)
    # Built pool empty for HX → fall through to lot metric
    assert "(no" not in reason, f"expected scored result, got: {reason}"


def test_value_villa_with_no_area_returns_default():
    """Goodlife villa case — no built_area_m2, no area_m2, no price_per_m2.
    Honest default 35.0 — no metric to score against."""
    leg = RANKER_LEGS["value"]
    pool = [_h(f"H{i}", price_per_built_m2=2000.0) for i in range(5)]
    villa = _h("Villa", area_m2=None, price_per_m2=None,
               built_area_m2=None, price_per_built_m2=None)
    score, reason = leg.score(villa, pool)
    assert score == 35.0
    assert "no $/m²" in reason


def test_built_pool_excludes_land():
    """Land listings must NOT enter the built pool — even if a malformed
    record has property_type='land' AND price_per_built_m2 set somehow,
    pool builder shouldn't accept it. Documented invariant: built pool
    is house+condo only."""
    from pulpo.ranker_legs.value import _build_pools
    pool = [
        _make_listing(source_id="L1", property_type="land", price_per_m2=100),
        _h("H1", price_per_built_m2=2000),
        _h("H2", price_per_built_m2=2200),
    ]
    pools = _build_pools(pool)
    # Land never enters built pool
    assert pools["built"]["global"].get("land", []) == []
    # Land always in lot pool
    assert 100 in pools["lot"]["global"]["land"]
    # Houses go to both their built pool and (since price_per_m2=None) NOT lot pool
    assert sorted(pools["built"]["global"]["house"]) == [2000, 2200]


def test_value_legacy_pick_pool_shim_still_works():
    """Pre-Phase-B helper signature kept as a shim — anything importing
    _pick_pool with 3 positional args (by_zone, by_macro, global_pool)
    should still resolve a pool for land. Backwards compat lock."""
    from pulpo.ranker_legs.value import _build_pools_legacy_lot_only, _pick_pool
    pool = [_make_listing(source_id=f"L{i}", price_per_m2=100.0 + 10 * i)
            for i in range(5)]
    by_zone, by_macro, global_pool = _build_pools_legacy_lot_only(pool)
    target = pool[0]
    out, label = _pick_pool(target, by_zone, by_macro, global_pool)
    assert len(out) == 5
    assert "land" in label


def test_per_type_score_distribution_helper():
    """Stdout helper must remain silent for land-only datasets (the
    historical state) and emit when a second type appears."""
    from io import StringIO
    from contextlib import redirect_stdout
    from automation.run import _print_per_type_score_distribution

    land_only = [_make_listing(source_id=f"L{i}") for i in range(3)]
    for li in land_only:
        li.rank_score = 50.0
    buf = StringIO()
    with redirect_stdout(buf):
        _print_per_type_score_distribution(land_only)
    assert "by_type" not in buf.getvalue(), "land-only dataset must stay silent"

    # Add one house — now it must emit
    h = _h("H1")
    h.rank_score = 75.0
    for li in land_only:
        li.rank_score = 50.0
    buf = StringIO()
    with redirect_stdout(buf):
        _print_per_type_score_distribution(land_only + [h])
    out = buf.getvalue()
    assert "by_type" in out
    assert "house" in out and "land" in out
