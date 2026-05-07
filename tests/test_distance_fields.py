"""
Tests for automation/distance_fields.py — pins the FR-5.5 contract:
- haversine math correctness
- preferred path (haversine from lat/lng) when coords present
- fallback path (zone table) when coords absent
- graceful None when neither is available
- correct nearest-airport selection across SAL + AeP
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.distance_fields import (   # noqa: E402
    haversine_km,
    compute_dist_airport_km,
    apply_distances,
    AIRPORTS_LAT_LNG,
    EARTH_RADIUS_KM,
)


def _li(zone: str | None = "el-tunco",
        lat: float | None = None,
        lng: float | None = None,
        dist_airport_km: float | None = None) -> dict:
    return {
        "zone": zone,
        "lat":  lat,
        "lng":  lng,
        "dist_airport_km": dist_airport_km,
    }


# ── haversine math ─────────────────────────────────────────────────────

def test_haversine_zero_distance():
    """Same point → 0 km."""
    assert haversine_km(13.5, -89.0, 13.5, -89.0) == 0.0


def test_haversine_known_distance_san_salvador_to_sal_airport():
    """San Salvador (~13.7, -89.2) → SAL airport (13.4408, -89.0556)
    is roughly 30-35 km."""
    sal_lat, sal_lng = AIRPORTS_LAT_LNG["SAL"]
    d = haversine_km(13.7, -89.2, sal_lat, sal_lng)
    assert 25 <= d <= 40, f"got {d}, expected ~30 km"


def test_haversine_symmetric():
    """Distance(A,B) == Distance(B,A)."""
    a = haversine_km(13.5, -89.0, 13.6, -89.1)
    b = haversine_km(13.6, -89.1, 13.5, -89.0)
    assert abs(a - b) < 0.001


def test_haversine_uses_correct_earth_radius():
    """Defensive: max possible Earth distance is half-circumference ~20020km."""
    half_circ = haversine_km(0.0, 0.0, 0.0, 180.0)
    expected = math_pi() * EARTH_RADIUS_KM
    assert abs(half_circ - expected) < 1.0


def math_pi() -> float:
    import math
    return math.pi


# ── compute_dist_airport_km — preferred path (haversine) ──────────────

def test_haversine_path_when_latlng_present():
    """Listing with lat/lng → uses haversine, not zone table."""
    sal_lat, sal_lng = AIRPORTS_LAT_LNG["SAL"]
    li = _li(zone="el-tunco", lat=sal_lat, lng=sal_lng)   # exactly at SAL
    km, method = compute_dist_airport_km(li)
    assert method == "haversine"
    assert km == 0.0


def test_haversine_picks_nearest_airport():
    """Listing near AeP coords → AeP wins over SAL."""
    aep_lat, aep_lng = AIRPORTS_LAT_LNG["AeP"]
    li = _li(zone=None, lat=aep_lat + 0.01, lng=aep_lng + 0.01)
    km, method = compute_dist_airport_km(li)
    assert method == "haversine"
    assert km < 5   # very close to AeP


def test_haversine_works_without_zone():
    """When lat/lng are present, zone is irrelevant."""
    sal_lat, sal_lng = AIRPORTS_LAT_LNG["SAL"]
    li = {"zone": None, "lat": sal_lat, "lng": sal_lng}
    km, method = compute_dist_airport_km(li)
    assert method == "haversine"
    assert km == 0.0


# ── compute_dist_airport_km — fallback (zone table) ───────────────────

def test_zone_table_fallback_when_no_latlng():
    """Listing with only zone → uses pre-computed table from pulpo/airports.py."""
    li = _li(zone="el-tunco", lat=None, lng=None)
    km, method = compute_dist_airport_km(li)
    assert method == "zone_table"
    assert km is not None
    assert 30 <= km <= 50   # el-tunco's nearest airport (SAL) is ~36km


def test_zone_table_eastern_zones_use_aep():
    """el-cuco/conchagua use AeP (closer than SAL)."""
    km, method = compute_dist_airport_km(_li(zone="el-cuco"))
    assert method == "zone_table"
    # AeP is 21 km from el-cuco; SAL is 103
    assert km < 50


def test_zone_table_returns_min_across_airports():
    """The result for a zone with both SAL and AeP entries should be the minimum."""
    # conchagua is closer to AeP (15) than to SAL (130) → 15 wins
    km, _ = compute_dist_airport_km(_li(zone="conchagua"))
    assert km is not None and km < 50


# ── compute_dist_airport_km — fallback failure ────────────────────────

def test_no_zone_no_latlng_returns_none():
    li = {"zone": None, "lat": None, "lng": None}
    km, method = compute_dist_airport_km(li)
    assert km is None
    assert method == "no_zone_no_latlng"


def test_unknown_zone_no_latlng_returns_none():
    li = _li(zone="some-unknown-zone")
    km, method = compute_dist_airport_km(li)
    assert km is None
    assert method == "no_zone_no_latlng"


# ── apply_distances — bulk path ───────────────────────────────────────

def test_apply_sets_dist_airport_km(tmp_path):
    listings = [_li(zone="el-tunco")]
    # history_path → tmp_path so the test never appends to the real
    # production sidecar at web/data/distance_fields_history.jsonl.
    apply_distances(listings, history_path=tmp_path / "h.jsonl")
    assert listings[0]["dist_airport_km"] is not None
    assert 30 <= listings[0]["dist_airport_km"] <= 50


def test_apply_does_not_overwrite_when_unscoreable(tmp_path):
    """Listings with no zone + no latlng leave existing dist_airport_km alone."""
    li = {"zone": None, "lat": None, "lng": None, "dist_airport_km": 99.0}
    apply_distances([li], history_path=tmp_path / "h.jsonl")
    assert li["dist_airport_km"] == 99.0   # unchanged


def test_apply_metrics_shape(tmp_path):
    listings = [
        _li(zone="el-tunco"),                              # zone_table
        _li(zone=None, lat=13.5, lng=-89.0),               # haversine
        _li(zone=None, lat=None, lng=None),                # unscoreable
    ]
    metrics = apply_distances(listings, history_path=tmp_path / "h.jsonl")
    assert metrics["scored_from_latlng"] == 1
    assert metrics["scored_from_zone"] == 1
    assert metrics["unscored"] == 1
    assert metrics["scored_total"] == 2


def test_apply_handles_large_catalog(tmp_path):
    """Smoke: 100 listings, mix of paths."""
    listings = []
    for _ in range(50):
        listings.append(_li(zone="el-tunco"))
    for _ in range(30):
        listings.append({"zone": "el-cuco", "lat": None, "lng": None,
                         "dist_airport_km": None})
    for _ in range(20):
        listings.append({"zone": None, "lat": 13.5, "lng": -89.0,
                         "dist_airport_km": None})
    metrics = apply_distances(listings, history_path=tmp_path / "h.jsonl")
    assert metrics["scored_total"] == 100


# ── telemetry sidecar ──────────────────────────────────────────────────

def test_telemetry_history_row_written(tmp_path):
    """One row per nightly run is appended to the history JSONL."""
    import json
    history = tmp_path / "distance_fields_history.jsonl"
    apply_distances([_li(zone="el-tunco")], history_path=history)
    assert history.exists()
    rows = [json.loads(line) for line in history.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert "ts" in row
    assert row["scored_total"] == 1
    assert row["scored_from_zone"] == 1


def test_telemetry_appends_across_runs(tmp_path):
    """Multiple runs accumulate rows append-only."""
    import json
    history = tmp_path / "h.jsonl"
    apply_distances([_li(zone="el-tunco")], history_path=history)
    apply_distances([_li(zone="el-cuco")], history_path=history)
    rows = [json.loads(line) for line in history.read_text().splitlines() if line.strip()]
    assert len(rows) == 2


def test_telemetry_includes_median_distance(tmp_path):
    """Median dist_airport_km computed across scored listings."""
    import json
    history = tmp_path / "h.jsonl"
    listings = [_li(zone="el-tunco"), _li(zone="el-cuco"), _li(zone="conchagua")]
    apply_distances(listings, history_path=history)
    row = json.loads(history.read_text().strip())
    assert row["median_dist_airport_km"] is not None
    assert 10 <= row["median_dist_airport_km"] <= 50  # all three are <50km from nearest airport


def test_telemetry_includes_by_zone_breakdown(tmp_path):
    """by_zone counter shows which zones contributed."""
    import json
    history = tmp_path / "h.jsonl"
    listings = [_li(zone="el-tunco"), _li(zone="el-tunco"), _li(zone="el-cuco")]
    apply_distances(listings, history_path=history)
    row = json.loads(history.read_text().strip())
    assert row["by_zone"]["el-tunco"] == 2
    assert row["by_zone"]["el-cuco"] == 1


def test_telemetry_write_failure_is_non_fatal(tmp_path):
    """If the history path can't be written, scoring still happens."""
    # Use a path under a file (not a dir) — write will fail
    bad_path = tmp_path / "is_a_file"
    bad_path.write_text("blocking")
    history = bad_path / "h.jsonl"  # parent isn't a dir
    listings = [_li(zone="el-tunco")]
    metrics = apply_distances(listings, history_path=history)
    assert metrics["scored_total"] == 1
    assert listings[0]["dist_airport_km"] is not None


# ── PR-8.5: dist_beach_km ─────────────────────────────────────────────

def test_dist_beach_km_close_to_zero_for_coastal_listing(tmp_path):
    """A listing at El Tunco (a curated coastline point) should be < 1km
    from the nearest reference point."""
    from automation.distance_fields import compute_dist_beach_km
    li = _li(zone="el-tunco", lat=13.487, lng=-89.6133)
    km = compute_dist_beach_km(li)
    assert km is not None
    assert km < 1.0


def test_dist_beach_km_large_for_inland_listing(tmp_path):
    """San Salvador metro (~13.7, -89.2) is ~30km north of the coast."""
    from automation.distance_fields import compute_dist_beach_km
    li = _li(zone="san-salvador", lat=13.7, lng=-89.2)
    km = compute_dist_beach_km(li)
    assert km is not None
    assert 20.0 <= km <= 50.0


def test_dist_beach_km_none_when_no_latlng(tmp_path):
    from automation.distance_fields import compute_dist_beach_km
    li = _li(zone="el-tunco", lat=None, lng=None)
    assert compute_dist_beach_km(li) is None


def test_apply_distances_sets_dist_beach_km_alongside_airport(tmp_path):
    """A coastal listing with lat/lng gets BOTH dist_airport_km and
    dist_beach_km on the same pass."""
    history = tmp_path / "h.jsonl"
    li = _li(zone="el-tunco", lat=13.487, lng=-89.6133)
    metrics = apply_distances([li], history_path=history)
    assert li["dist_airport_km"] is not None
    assert li["dist_beach_km"] is not None
    assert metrics["scored_beach"] == 1


def test_apply_distances_skips_dist_beach_km_when_no_latlng(tmp_path):
    """The zone-table fallback covers airport but NOT beach (no zone
    table for coastline yet). Listing with zone but no lat/lng gets
    airport km but not beach."""
    history = tmp_path / "h.jsonl"
    li = _li(zone="el-tunco")  # no lat/lng
    metrics = apply_distances([li], history_path=history)
    assert li["dist_airport_km"] is not None    # zone-table hit
    # dist_beach_km stays at the dataclass default (None) — apply_distances
    # only writes when there's a number to write.
    assert li.get("dist_beach_km") is None
    assert metrics["scored_beach"] == 0
