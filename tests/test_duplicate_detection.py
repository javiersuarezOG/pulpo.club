"""
Tests for automation/duplicate_detection.py — pins the cross-source
duplicate-detection contract.

Coverage:
- phone normalisation (formatting + country-code stripping + edge cases)
- haversine accuracy + symmetry
- cross-source phone match — fires
- within-source phone match — does NOT fire (broker's own CMS dup, not a
  cross-post; muddying that signal would defeat the whole point)
- coord match below threshold — fires
- coord match above threshold — drops
- price-band gate — too-wide price gap drops the pair
- missing price — pair still counts (liberal default; documented)
- empty input — clean zero metrics, no crash
- sidecar appends one JSONL row per call
- sidecar write failure is non-fatal — pipeline continues
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.duplicate_detection import (   # noqa: E402
    CENTROID_MIN_LISTINGS,
    COORD_RADIUS_M,
    MAX_AREA_RATIO,
    PRICE_TOLERANCE_PCT,
    _compute_centroids,
    detect_duplicates,
    haversine_m,
    normalize_phone,
)


# ── listing factory ────────────────────────────────────────────────────


def _li(**overrides) -> dict:
    """A baseline listing the matchers will accept (lat/lng + price set).

    Tests mutate per-case overrides to exercise edge conditions; the
    defaults are deliberately innocuous so a single override surfaces
    what the test is exercising.
    """
    base = {
        "source":       "bienesraices",
        "source_id":    "TEST-001",
        "title":        "Lote en El Tunco",
        "broker_phone": None,
        "lat":          13.4912,
        "lng":          -89.3818,
        "price_usd":    100_000.0,
        "area_m2":      1_000.0,
    }
    base.update(overrides)
    return base


# ── normalize_phone ────────────────────────────────────────────────────


def test_normalize_phone_strips_punctuation_and_whitespace():
    assert normalize_phone("+503 7851-3928") == "78513928"
    assert normalize_phone("(503) 7851 3928") == "78513928"
    assert normalize_phone("503-7851-3928")   == "78513928"
    assert normalize_phone("78513928")        == "78513928"


def test_normalize_phone_strips_sv_country_code():
    """`+503 7851-3928` and bare `78513928` should canonicalise to the
    same key so phones from a scraper that emits the international
    form match phones from one that emits the local form."""
    assert normalize_phone("+50378513928") == normalize_phone("78513928")


def test_normalize_phone_returns_none_for_empty_or_short():
    assert normalize_phone(None) is None
    assert normalize_phone("") is None
    assert normalize_phone("123456") is None    # < 7 digits → not a phone
    assert normalize_phone("not a phone") is None


def test_normalize_phone_handles_non_string_input():
    """Defensive — broker_phone occasionally arrives as int from JSON
    sources where the schema is loose."""
    assert normalize_phone(78513928) == "78513928"


# ── haversine_m ────────────────────────────────────────────────────────


def test_haversine_zero_at_same_point():
    assert haversine_m(13.5, -89.0, 13.5, -89.0) == 0.0


def test_haversine_symmetric():
    a = haversine_m(13.5, -89.0, 13.6, -89.1)
    b = haversine_m(13.6, -89.1, 13.5, -89.0)
    assert abs(a - b) < 0.001


def test_haversine_known_distance():
    """Roughly 100 km between two points 1 deg lat apart at SV latitude.
    1 deg lat ≈ 111 km — boundary-checking the constant."""
    d = haversine_m(13.5, -89.0, 14.5, -89.0)
    assert 110_000 < d < 112_000


# ── cross-source phone match ──────────────────────────────────────────


def test_phone_match_across_sources_counts():
    a = _li(source="bienesraices", source_id="A", broker_phone="+503 7851-3928",
            lat=13.0, lng=-89.0)
    b = _li(source="century21", source_id="B", broker_phone="78513928",
            lat=13.5, lng=-89.5)  # different coords — pure phone match
    metrics = detect_duplicates([a, b])
    assert metrics["phone_pairs"] == 1
    assert metrics["duplicate_listings_either"] == 2
    assert metrics["by_source_pair"] == {"bienesraices+century21": 1}


def test_phone_match_within_same_source_does_not_count():
    """Two listings on the SAME source sharing a phone is the broker's
    own CMS duplicate (not a cross-post). Must NOT count — would
    contaminate the cross-source signal."""
    a = _li(source="bienesraices", source_id="A", broker_phone="+503 7851-3928",
            lat=13.0, lng=-89.0)
    b = _li(source="bienesraices", source_id="B", broker_phone="78513928",
            lat=13.5, lng=-89.5)
    metrics = detect_duplicates([a, b])
    assert metrics["phone_pairs"] == 0
    assert metrics["duplicate_listings_either"] == 0


def test_phone_match_three_sources_yields_three_pairs():
    """If A, B, C all share a phone across 3 sources, that's 3 pairwise
    matches but only 3 unique flagged listings (each appears in some
    pair)."""
    a = _li(source="bienesraices", source_id="A", broker_phone="78513928",
            lat=10.0, lng=-89.0)
    b = _li(source="century21", source_id="B", broker_phone="78513928",
            lat=11.0, lng=-89.0)
    c = _li(source="remax", source_id="C", broker_phone="78513928",
            lat=12.0, lng=-89.0)
    metrics = detect_duplicates([a, b, c])
    assert metrics["phone_pairs"] == 3
    assert metrics["duplicate_listings_either"] == 3


# ── cross-source coord match ──────────────────────────────────────────


def test_coord_match_within_radius_counts():
    a = _li(source="bienesraices", source_id="A",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    b = _li(source="remax", source_id="B",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 1
    assert metrics["by_source_pair"] == {"bienesraices+remax": 1}


def test_coord_match_beyond_radius_drops():
    """100m radius — two points 0.01 degrees apart (~1.1 km) must not
    match."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    b = _li(source="remax", source_id="B",
            lat=13.5012, lng=-89.3818, price_usd=100_000)  # ~1.1 km away
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 0


def test_coord_match_within_same_source_does_not_count():
    """Two listings on the same source at the same coords is a building
    with multiple units, not a cross-post. Must not count."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    b = _li(source="bienesraices", source_id="B",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 0


def test_price_band_drops_pair_when_prices_diverge():
    """Same coords + wildly different prices is more likely a multi-unit
    building (different unit prices) than a duplicate."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    b = _li(source="remax", source_id="B",
            lat=13.4912, lng=-89.3818, price_usd=500_000)  # 5× difference
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 0


def test_price_band_keeps_pair_when_prices_within_tolerance():
    a = _li(source="bienesraices", source_id="A",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    # Within ±25% — keep
    b = _li(source="remax", source_id="B",
            lat=13.4912, lng=-89.3818, price_usd=120_000)
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 1


def test_price_tolerance_constant_documented():
    """If you change PRICE_TOLERANCE_PCT, this test fails — forcing a
    deliberate decision rather than silent drift in the duplicate rate
    we report. Tighten if false-positive analysis says we should."""
    assert PRICE_TOLERANCE_PCT == 0.25


def test_coord_radius_constant_documented():
    """Same rationale — drift here directly moves the headline number."""
    assert COORD_RADIUS_M == 100.0


def test_coord_match_with_missing_price_still_counts():
    """When EITHER listing has no price, we can't run the price-band
    gate — default to keeping the coord match (liberal). Documents
    this choice; tighten later if FP analysis shows it's wrong."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.4912, lng=-89.3818, price_usd=None)
    b = _li(source="remax", source_id="B",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 1


# ── union + headline metric ───────────────────────────────────────────


def test_listing_in_phone_AND_coord_match_counted_once():
    """A pair caught by both phone and coord matchers is one logical
    duplicate. duplicate_listings_either dedupes the listing keys so
    the headline doesn't double-count."""
    a = _li(source="bienesraices", source_id="A", broker_phone="78513928",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    b = _li(source="century21", source_id="B", broker_phone="78513928",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    metrics = detect_duplicates([a, b])
    # Both passes catch the pair, so phone_pairs=1 AND coord_pairs=1.
    # But it's still 2 listings flagged total.
    assert metrics["phone_pairs"] == 1
    assert metrics["coord_pairs"] == 1
    assert metrics["duplicate_listings_either"] == 2
    assert metrics["unique_listings_estimate"] == 0


def test_empty_input_returns_clean_zero_metrics():
    metrics = detect_duplicates([])
    assert metrics["total_listings"] == 0
    assert metrics["phone_pairs"] == 0
    assert metrics["coord_pairs"] == 0
    assert metrics["duplicate_listings_either"] == 0
    assert metrics["unique_listings_estimate"] == 0
    assert metrics["duplicate_pct"] == 0.0
    assert metrics["by_source_pair"] == {}


def test_no_duplicates_returns_full_unique_count():
    """3 listings from 3 different sources, distinct phones AND distinct
    coords — every listing unique."""
    listings = [
        _li(source="bienesraices", source_id="A", broker_phone="11111111",
            lat=13.0, lng=-89.0),
        _li(source="century21", source_id="B", broker_phone="22222222",
            lat=14.0, lng=-89.5),
        _li(source="remax", source_id="C", broker_phone="33333333",
            lat=13.5, lng=-90.0),
    ]
    metrics = detect_duplicates(listings)
    assert metrics["duplicate_listings_either"] == 0
    assert metrics["unique_listings_estimate"] == 3
    assert metrics["duplicate_pct"] == 0.0


# ── sidecar telemetry ─────────────────────────────────────────────────


def test_sidecar_writes_one_row_per_call(tmp_path):
    history = tmp_path / "duplicate_detection_history.jsonl"
    a = _li(source="bienesraices", source_id="A", broker_phone="78513928")
    b = _li(source="century21", source_id="B", broker_phone="78513928")
    detect_duplicates([a, b], history_path=history)
    assert history.exists()
    rows = [json.loads(ln) for ln in history.read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    assert rows[0]["phone_pairs"] == 1
    assert rows[0]["total_listings"] == 2
    assert "ts" in rows[0]
    assert "by_source_pair" in rows[0]


def test_sidecar_appends_across_runs(tmp_path):
    history = tmp_path / "h.jsonl"
    detect_duplicates([_li()], history_path=history)
    detect_duplicates([_li(), _li(source="remax", source_id="B")],
                      history_path=history)
    rows = [json.loads(ln) for ln in history.read_text().splitlines() if ln.strip()]
    assert len(rows) == 2


def test_sidecar_write_failure_is_non_fatal(tmp_path):
    """If history can't be written, detect_duplicates still returns
    metrics. Pipeline must never die because telemetry I/O failed."""
    bad_path = tmp_path / "is_a_file"
    bad_path.write_text("blocking")
    history = bad_path / "h.jsonl"   # parent isn't a dir
    metrics = detect_duplicates([_li()], history_path=history)
    assert metrics["total_listings"] == 1


# ── coverage telemetry ───────────────────────────────────────────────


def test_coverage_metrics_match_input():
    listings = [
        _li(source="bienesraices", source_id="A", broker_phone="78513928",
            lat=13.0, lng=-89.0),
        _li(source="century21", source_id="B", broker_phone=None,
            lat=14.0, lng=-89.5),
        _li(source="remax", source_id="C", broker_phone="22222222",
            lat=None, lng=None),
    ]
    metrics = detect_duplicates(listings)
    assert metrics["total_listings"] == 3
    assert metrics["listings_with_phone"] == 2
    assert metrics["listings_with_coords"] == 2


# ── centroid suppression (Phase 1.1) ─────────────────────────────────


def test_centroid_threshold_constant_documented():
    """If you change CENTROID_MIN_LISTINGS, this test fails — same
    rationale as PRICE_TOLERANCE_PCT and COORD_RADIUS_M. The choice
    directly moves the headline number; tweak deliberately."""
    assert CENTROID_MIN_LISTINGS == 5


def test_compute_centroids_returns_coords_at_or_above_threshold():
    """A coord shared by exactly CENTROID_MIN_LISTINGS listings counts
    as a centroid; below threshold doesn't."""
    # 5 listings at one coord → centroid
    centroid_coord_listings = [
        _li(source=f"s{i}", source_id=f"id{i}", lat=13.4833, lng=-89.3167)
        for i in range(CENTROID_MIN_LISTINGS)
    ]
    # 4 listings at another coord → NOT a centroid
    non_centroid_listings = [
        _li(source=f"s{i}", source_id=f"id{i}", lat=14.0, lng=-89.0)
        for i in range(CENTROID_MIN_LISTINGS - 1)
    ]
    centroids = _compute_centroids(centroid_coord_listings + non_centroid_listings)
    assert (13.4833, -89.3167) in centroids
    assert (14.0, -89.0) not in centroids


def test_compute_centroids_ignores_listings_without_coords():
    """Listings with lat=None or lng=None can't contribute to a
    fallback-centroid count — they have no coord to share."""
    listings = [
        _li(source="s", source_id=f"id{i}", lat=None, lng=None)
        for i in range(CENTROID_MIN_LISTINGS)
    ]
    centroids = _compute_centroids(listings)
    assert centroids == set()


def test_compute_centroids_uses_5_decimal_precision():
    """Centroid bucketing rounds to 5 decimals (~1m). Two coords that
    round to the same bucket should be treated as the same coord."""
    listings = [
        _li(source=f"s{i}", source_id=f"id{i}",
            lat=13.483300001 + i * 1e-7,   # all round to 13.48330
            lng=-89.316700001 + i * 1e-7)  # all round to -89.31670
        for i in range(CENTROID_MIN_LISTINGS)
    ]
    centroids = _compute_centroids(listings)
    assert (13.48330, -89.31670) in centroids


def test_coord_pair_at_centroid_is_suppressed():
    """The whole point of Phase 1.1: cross-source listings at a fallback
    centroid coord must NOT flag as duplicates."""
    # Build a centroid: CENTROID_MIN_LISTINGS listings sharing (13.4833, -89.3167)
    centroid_listings = [
        _li(source="bienesraices", source_id=f"BR-{i}",
            lat=13.4833, lng=-89.3167, price_usd=100_000 + i * 10_000)
        for i in range(CENTROID_MIN_LISTINGS)
    ]
    # Add a remax listing at the same centroid coord — would have
    # paired with all the bienesraices listings under the old rule.
    centroid_listings.append(
        _li(source="remax", source_id="RX-X",
            lat=13.4833, lng=-89.3167, price_usd=110_000)
    )
    metrics = detect_duplicates(centroid_listings)
    assert metrics["coord_pairs"] == 0
    assert metrics["coord_pairs_suppressed_centroid"] >= 1
    assert (13.4833, -89.3167) in _compute_centroids(centroid_listings)


def test_coord_pair_at_non_centroid_still_counts():
    """Two cross-source listings at a UNIQUE coord (no other listings
    sharing it) match cleanly — Phase 1.1 only suppresses centroids,
    not all coord matches."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    b = _li(source="remax", source_id="B",
            lat=13.4912, lng=-89.3818, price_usd=100_000)
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 1
    assert metrics["coord_pairs_suppressed_centroid"] == 0


def test_coord_pair_with_one_endpoint_at_centroid_is_suppressed():
    """Aggressive rule per the design: if EITHER endpoint sits at a
    centroid, suppress. Listing A might be at a real coord that
    happens to coincide with a centroid bucket; listing B's "centroid"
    coord isn't a real geocode at all. Pair them and we're trusting
    a fallback to confirm a duplicate — not safe."""
    # Build a centroid at (13.4833, -89.3167)
    centroid_population = [
        _li(source="bienesraices", source_id=f"BR-{i}",
            lat=13.4833, lng=-89.3167, price_usd=100_000 + i * 1_000)
        for i in range(CENTROID_MIN_LISTINGS)
    ]
    # A: at the centroid coord
    a = _li(source="goodlife", source_id="A",
            lat=13.4833, lng=-89.3167, price_usd=100_000)
    # B: at a slightly different coord (within 100m of the centroid).
    # Without Phase 1.1, A↔B would match by coord. Phase 1.1
    # suppresses because A is at a centroid coord.
    b = _li(source="remax", source_id="B",
            lat=13.4838, lng=-89.3167, price_usd=100_000)   # ~55m away
    metrics = detect_duplicates(centroid_population + [a, b])
    # The A↔B match should be suppressed.
    assert metrics["coord_pairs_suppressed_centroid"] >= 1


def test_centroid_metrics_appear_in_summary():
    """centroid_count + listings_at_centroids show up in the metrics
    dict so nightly logs and the sidecar can track the suppression."""
    listings = [
        _li(source=f"s{i}", source_id=f"id{i}", lat=13.4833, lng=-89.3167)
        for i in range(CENTROID_MIN_LISTINGS)
    ]
    metrics = detect_duplicates(listings)
    assert metrics["centroid_count"] == 1
    assert metrics["listings_at_centroids"] == CENTROID_MIN_LISTINGS


def test_phone_match_still_fires_at_centroid_coord():
    """Phone matching is independent of coord matching — a cross-source
    phone match at a centroid coord still fires (the phone is the
    high-precision signal; coord centroids only suppress the
    coord-based pass)."""
    # Build a centroid population that includes A and B.
    centroid_filler = [
        _li(source=f"s{i}", source_id=f"id{i}", lat=13.4833, lng=-89.3167)
        for i in range(CENTROID_MIN_LISTINGS - 1)
    ]
    a = _li(source="bienesraices", source_id="A", broker_phone="78513928",
            lat=13.4833, lng=-89.3167, price_usd=100_000)
    b = _li(source="century21", source_id="B", broker_phone="78513928",
            lat=13.4833, lng=-89.3167, price_usd=100_000)
    metrics = detect_duplicates(centroid_filler + [a, b])
    assert metrics["phone_pairs"] == 1   # phone match still fires
    # Coord match for A↔B is suppressed by centroid rule, but phone
    # match catches them anyway → still flagged in the headline.
    assert "bienesraices+century21" in metrics["by_source_pair"]


# ── area-band gate (Phase 1.2) ────────────────────────────────────────


def test_max_area_ratio_constant_documented():
    """If you change MAX_AREA_RATIO, this test fails — same rationale as
    the price-band, coord-radius, and centroid-threshold pinning. The
    1.5× threshold was calibrated against the Phase 1.1.5 audit
    (samples/dedup_audit_2026-05-08_v2.md): caught 20 of 20 FPs while
    preserving the only UNCLEAR pair (1.07× ratio)."""
    assert MAX_AREA_RATIO == 1.5


def test_coord_pair_with_huge_area_mismatch_is_suppressed():
    """The headline Phase 1.2 case: same coord, areas 22× apart
    ('11 manzanas Santa Ana commercial 76,880 m²' vs 'Residencial Sinai
    lot 431 m²') must NOT flag as a duplicate. They are obviously
    distinct parcels at the same fallback geocode."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.99, lng=-89.55, price_usd=308_000, area_m2=76_880)
    b = _li(source="remax", source_id="B",
            lat=13.99, lng=-89.55, price_usd=260_000, area_m2=3_500)
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 0
    assert metrics["coord_pairs_suppressed_area"] == 1


def test_coord_pair_with_close_area_match_keeps():
    """Areas inside MAX_AREA_RATIO must NOT be suppressed — those are
    the candidates we actually want. The Phase 1.1.5 audit's only
    UNCLEAR pair (Tenerife vs El Encanto, ratio 1.07×) is exactly
    this case."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.674, lng=-89.279, price_usd=334_520, area_m2=875)
    b = _li(source="remax", source_id="B",
            lat=13.674, lng=-89.279, price_usd=365_000, area_m2=934)
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 1
    assert metrics["coord_pairs_suppressed_area"] == 0


def test_area_band_just_below_threshold_keeps():
    """Area ratio = MAX_AREA_RATIO - epsilon → keep. Pinning the
    boundary so a future tweak surfaces in the diff."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.5, lng=-89.0, price_usd=100_000, area_m2=1_000)
    b = _li(source="remax", source_id="B",
            lat=13.5, lng=-89.0, price_usd=100_000,
            area_m2=1_490)   # ratio 1.49×, just below 1.5
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 1


def test_area_band_just_above_threshold_drops():
    """Area ratio just over MAX_AREA_RATIO → drop. Other side of the
    same boundary."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.5, lng=-89.0, price_usd=100_000, area_m2=1_000)
    b = _li(source="remax", source_id="B",
            lat=13.5, lng=-89.0, price_usd=100_000,
            area_m2=1_510)   # ratio 1.51×, just over 1.5
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 0
    assert metrics["coord_pairs_suppressed_area"] == 1


def test_area_band_both_areas_missing_keeps_pair():
    """When EITHER area is missing, the gate doesn't fire — liberal
    default mirroring the price-band's "missing-price-keeps-pair"
    behaviour. Documents the choice; tighten later if FP analysis
    shows it's wrong."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.5, lng=-89.0, price_usd=100_000, area_m2=None)
    b = _li(source="remax", source_id="B",
            lat=13.5, lng=-89.0, price_usd=100_000, area_m2=1_000)
    metrics = detect_duplicates([a, b])
    assert metrics["coord_pairs"] == 1
    assert metrics["coord_pairs_suppressed_area"] == 0


def test_area_band_zero_area_is_treated_as_missing():
    """area_m2 == 0 is invalid (no real lot has zero area) — mirror
    the price-band's `>0` precondition and treat zero as missing."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.5, lng=-89.0, price_usd=100_000, area_m2=0)
    b = _li(source="remax", source_id="B",
            lat=13.5, lng=-89.0, price_usd=100_000, area_m2=10_000)
    metrics = detect_duplicates([a, b])
    # Pair survives because zero is treated as missing (gate doesn't fire)
    assert metrics["coord_pairs"] == 1


def test_area_band_does_not_affect_phone_match():
    """Phone matching is independent of coord matching, including the
    area-band. Two listings with very different areas but a shared
    phone still flag as duplicates via the phone pass."""
    a = _li(source="bienesraices", source_id="A",
            broker_phone="78513928",
            lat=13.5, lng=-89.0, price_usd=100_000, area_m2=1_000)
    b = _li(source="century21", source_id="B",
            broker_phone="78513928",
            lat=14.0, lng=-89.5,   # different coord — no coord match anyway
            price_usd=100_000, area_m2=20_000)
    metrics = detect_duplicates([a, b])
    assert metrics["phone_pairs"] == 1
    assert metrics["coord_pairs_suppressed_area"] == 0   # gate didn't run


def test_area_band_metric_appears_in_summary():
    """coord_pairs_suppressed_area surfaces in the metrics dict so
    nightly logs and the sidecar can prove the gate is doing useful
    work each run."""
    a = _li(source="bienesraices", source_id="A",
            lat=13.5, lng=-89.0, price_usd=100_000, area_m2=10_000)
    b = _li(source="remax", source_id="B",
            lat=13.5, lng=-89.0, price_usd=100_000, area_m2=1_000)
    metrics = detect_duplicates([a, b])
    assert "coord_pairs_suppressed_area" in metrics
    assert metrics["coord_pairs_suppressed_area"] == 1
