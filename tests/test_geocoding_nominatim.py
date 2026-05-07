"""
Tests for automation/geocoding_nominatim.py — pin the cache + rate-limit
+ SV-bbox-rejection contract for the OSM Nominatim fallback geocoder.

No real network calls — every test passes a stub `http_get` that
returns synthetic Nominatim responses. Same applies to `sleep_fn`
(injected so the rate-limit logic is exercised without 1.1s waits).
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.geocoding_nominatim import (   # noqa: E402
    GeocodeResult,
    build_query,
    geocode_listings,
    geocode_one,
    load_cache,
    save_cache,
    SV_BBOX_LAT,
    SV_BBOX_LNG,
)


# ── stub HTTP layer ───────────────────────────────────────────────────

class _StubResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _StubGet:
    """Records calls + serves canned responses by query."""
    def __init__(self, responses_by_query: dict):
        self.responses = responses_by_query
        self.calls: list[dict] = []

    def __call__(self, url, params, headers, timeout):
        self.calls.append({"url": url, "params": params, "headers": headers})
        q = params.get("q")
        return self.responses.get(q, _StubResponse(200, []))


# ── build_query ───────────────────────────────────────────────────────

def test_build_query_zone_municipality_department():
    li = {"zone": "el-tunco", "municipality": "Tamanique", "department": "La Libertad"}
    assert build_query(li) == "El Tunco, Tamanique, La Libertad, El Salvador"


def test_build_query_pretty_zone_slug():
    li = {"zone": "san-blas", "municipality": None, "department": None}
    assert build_query(li) == "San Blas, El Salvador"


def test_build_query_returns_none_when_no_signal():
    """A listing with only country=SV → can't query."""
    assert build_query({"zone": None, "municipality": None, "department": None}) is None
    assert build_query({}) is None


def test_build_query_skips_empty_strings():
    li = {"zone": "  ", "municipality": "", "department": "La Libertad"}
    assert build_query(li) == "La Libertad, El Salvador"


# ── geocode_one ───────────────────────────────────────────────────────

def test_geocode_one_returns_result_on_valid_response():
    stub = _StubGet({
        "El Tunco, El Salvador": _StubResponse(200, [
            {"lat": "13.4870", "lon": "-89.6133", "display_name": "El Tunco, La Libertad, El Salvador"}
        ])
    })
    result = geocode_one("El Tunco, El Salvador", http_get=stub)
    assert isinstance(result, GeocodeResult)
    assert result.lat == 13.487
    assert result.lng == -89.6133
    assert "El Tunco" in result.display_name
    # Header check — Nominatim policy requires User-Agent
    assert stub.calls[0]["headers"].get("User-Agent")


def test_geocode_one_rejects_outside_sv_bbox():
    """A query that resolves to coords in another country must reject."""
    # Mexico coords
    stub = _StubGet({
        "Ambiguous Place, El Salvador": _StubResponse(200, [
            {"lat": "19.43", "lon": "-99.13", "display_name": "Ciudad de México"}
        ])
    })
    assert geocode_one("Ambiguous Place, El Salvador", http_get=stub) is None


def test_geocode_one_handles_empty_response():
    stub = _StubGet({})
    assert geocode_one("Unknown Place, El Salvador", http_get=stub) is None


def test_geocode_one_handles_http_error():
    stub = _StubGet({"Q, El Salvador": _StubResponse(500, None)})
    assert geocode_one("Q, El Salvador", http_get=stub) is None


def test_geocode_one_handles_malformed_lat_lng():
    stub = _StubGet({"Q, El Salvador": _StubResponse(200, [
        {"lat": "not-a-number", "lon": "-89.0"}
    ])})
    assert geocode_one("Q, El Salvador", http_get=stub) is None


# ── geocode_listings: cache + rate-limit + skip rules ────────────────

def test_geocode_listings_skips_already_geocoded(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    listings = [{"zone": "el-tunco", "lat": 13.487, "lng": -89.613}]
    stub = _StubGet({})
    metrics = geocode_listings(listings, cache_path, http_get=stub, sleep_fn=lambda s: None)
    assert metrics["skipped_already_geocoded"] == 1
    assert metrics["api_calls"] == 0
    assert stub.calls == []


def test_geocode_listings_skips_when_no_query_signal(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    listings = [{"zone": None, "municipality": None, "department": None,
                 "lat": None, "lng": None}]
    stub = _StubGet({})
    metrics = geocode_listings(listings, cache_path, http_get=stub, sleep_fn=lambda s: None)
    assert metrics["skipped_no_query"] == 1
    assert metrics["api_calls"] == 0


def test_geocode_listings_writes_lat_lng_on_api_hit(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    li = {"zone": "el-tunco", "municipality": None, "department": None,
          "lat": None, "lng": None}
    stub = _StubGet({
        "El Tunco, El Salvador": _StubResponse(200, [
            {"lat": "13.487", "lon": "-89.613", "display_name": "El Tunco"}
        ])
    })
    metrics = geocode_listings([li], cache_path, http_get=stub, sleep_fn=lambda s: None)
    assert metrics["api_hits"] == 1
    assert li["lat"] == 13.487
    assert li["lng"] == -89.613
    assert li.get("geocoding_source") == "nominatim"


def test_geocode_listings_uses_cache_on_second_run(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    li_a = {"zone": "el-tunco", "lat": None, "lng": None}
    li_b = {"zone": "el-tunco", "lat": None, "lng": None}
    stub = _StubGet({
        "El Tunco, El Salvador": _StubResponse(200, [
            {"lat": "13.487", "lon": "-89.613", "display_name": "El Tunco"}
        ])
    })
    # First run hits the API
    geocode_listings([li_a], cache_path, http_get=stub, sleep_fn=lambda s: None)
    assert len(stub.calls) == 1
    # Second run hits the cache — no new API call
    metrics2 = geocode_listings([li_b], cache_path, http_get=stub, sleep_fn=lambda s: None)
    assert len(stub.calls) == 1   # unchanged
    assert metrics2["cache_hits"] == 1
    assert li_b["lat"] == 13.487


def test_geocode_listings_caches_misses_too(tmp_path: Path):
    """A query that returned nothing should be cached as 'miss' so we
    don't retry on the same run."""
    cache_path = tmp_path / "cache.json"
    li_a = {"zone": "obscuro", "lat": None, "lng": None}
    li_b = {"zone": "obscuro", "lat": None, "lng": None}
    stub = _StubGet({})  # always returns empty
    geocode_listings([li_a, li_b], cache_path, http_get=stub, sleep_fn=lambda s: None)
    # Both listings hit the same query; only one API call should fire.
    # (The second listing sees the "miss" sentinel in the cache.)
    assert len(stub.calls) == 1


def test_geocode_listings_rate_limits_via_sleep_fn(tmp_path: Path):
    """Two cache misses in a row → sleep is called once between them
    with the configured RATE_LIMIT_SLEEP_S."""
    cache_path = tmp_path / "cache.json"
    listings = [
        {"zone": "el-tunco", "lat": None, "lng": None},
        {"zone": "el-zonte", "lat": None, "lng": None},
    ]
    stub = _StubGet({
        "El Tunco, El Salvador": _StubResponse(200, [
            {"lat": "13.487", "lon": "-89.613", "display_name": "El Tunco"}
        ]),
        "El Zonte, El Salvador": _StubResponse(200, [
            {"lat": "13.498", "lon": "-89.555", "display_name": "El Zonte"}
        ]),
    })
    sleep_calls: list[float] = []
    geocode_listings(listings, cache_path, http_get=stub,
                     sleep_fn=lambda s: sleep_calls.append(s))
    # Should have slept at least once (between the two API calls).
    assert len(sleep_calls) >= 1
    # Sleep duration is > 0 (paced)
    assert sleep_calls[0] > 0


# ── load_cache / save_cache ───────────────────────────────────────────

def test_save_then_load_roundtrip(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    save_cache(cache_path, {"k": {"lat": 13.5, "lng": -89.0}})
    loaded = load_cache(cache_path)
    assert loaded == {"k": {"lat": 13.5, "lng": -89.0}}


def test_load_cache_returns_empty_dict_when_missing(tmp_path: Path):
    assert load_cache(tmp_path / "nope.json") == {}


def test_load_cache_returns_empty_dict_on_corrupt_json(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("not json")
    assert load_cache(cache_path) == {}


# ── SV bounding box constants pin ──────────────────────────────────────

def test_sv_bbox_constants_unchanged():
    """Pin the bbox so a future tightening doesn't silently shrink the
    accepted region. If you legitimately want to update, edit this test
    and re-run a calibration script."""
    assert SV_BBOX_LAT == (13.0, 14.6)
    assert SV_BBOX_LNG == (-90.6, -87.6)
