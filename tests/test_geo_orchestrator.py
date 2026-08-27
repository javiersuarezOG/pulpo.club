"""
Tests for automation/geo_enrichment's orchestrator — the cache/budget/
failure contract that keeps the nightly safe.

The pass is a soft-fail enrichment step, so most of what matters here is
what happens when things go wrong: a provider that starts 403ing, a
deadline that expires mid-run, a coordinate that moves. Each is pinned.

No network — `http_get` and `sleep_fn` are injected everywhere.
"""
from __future__ import annotations
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import automation.geo_enrichment as geo               # noqa: E402
from automation.geo_enrichment._cache import (         # noqa: E402
    cell_key, load_cache, make_entry, STATUS_OK,
)

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _online(monkeypatch):
    """The orchestrator no-ops under PULPO_OFFLINE=1 (conftest sets it)."""
    monkeypatch.delenv("PULPO_OFFLINE", raising=False)
    monkeypatch.delenv("PULPO_GEO_MAX_CALLS", raising=False)


class _StubResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        return self._payload


class _Elevation:
    """Stub transport for the elevation provider: echoes a value per coord."""
    def __init__(self, status_code=200, fail_times=0, exc=None):
        self.calls = []
        self.status_code = status_code
        self.fail_times = fail_times
        self.exc = exc

    def __call__(self, url, params, headers, timeout_s):
        self.calls.append(params)
        if self.fail_times > 0:
            self.fail_times -= 1
            if self.exc:
                raise self.exc
            return _StubResponse({}, status_code=self.status_code)
        n = len(str(params["latitude"]).split(","))
        return _StubResponse({"elevation": [100.0 + i for i in range(n)]})


def _listing(sid, lat, lng, **extra):
    base = {"source": "t", "source_id": sid, "lat": lat, "lng": lng,
            "country": "SV", "geocoding_source": "estimated",
            "geocoding_confidence": "medium"}
    base.update(extra)
    return base


def _run(listings, tmp_path, http_get, **kwargs):
    kwargs.setdefault("providers", ["open_meteo_elevation"])
    kwargs.setdefault("now_fn", lambda: NOW)
    return geo.enrich_listings(
        listings,
        cells_path=tmp_path / "geo_cells.json",
        sidecar_path=tmp_path / "geo_enrichment.json",
        http_get=http_get,
        sleep_fn=lambda _s: None,
        **kwargs,
    )


# ── the core value proposition ────────────────────────────────────────

def test_nearby_listings_collapse_to_one_cell(tmp_path):
    """Two listings ~200m apart must cost one lookup, not two."""
    get = _Elevation()
    m = _run([_listing("a", 13.6989, -89.1914),
              _listing("b", 13.6991, -89.1917)], tmp_path, get)
    assert m["listings_with_coords"] == 2
    assert m["cells_needed"] == 1
    assert m["assembled"] == 2


def test_warm_cache_makes_zero_api_calls(tmp_path):
    """The compounding claim: night two is free."""
    get = _Elevation()
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    first = len(get.calls)
    m = _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    assert len(get.calls) == first
    assert m["api_calls"] == 0
    assert m["cache_hits"] == 1
    assert m["assembled"] == 1


def test_new_listing_in_known_cell_is_free(tmp_path):
    get = _Elevation()
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    m = _run([_listing("a", 13.6989, -89.1914),
              _listing("new", 13.6990, -89.1915)], tmp_path, get)
    assert m["api_calls"] == 0
    assert m["assembled"] == 2


def test_sidecar_record_shape(tmp_path):
    get = _Elevation()
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    rec = json.loads((tmp_path / "geo_enrichment.json").read_text())["t|a"]
    assert rec["country"] == "SV"
    # What the enrichment was computed FROM — makes a later precision
    # upgrade visible rather than silently stale.
    assert rec["coords"]["geocoding_source"] == "estimated"
    assert rec["providers"]["open_meteo_elevation"]["status"] == "ok"
    assert rec["providers"]["open_meteo_elevation"]["cell"] == "13.70,-89.19"
    assert rec["elevation"]["elevation_m"] == 100


def test_elevation_batches_many_cells_into_few_calls(tmp_path):
    get = _Elevation()
    listings = [_listing(f"l{i}", 13.0 + i * 0.02, -89.0) for i in range(120)]
    m = _run(listings, tmp_path, get)
    assert m["cells_needed"] == 120
    assert m["api_calls"] == 2      # 100 + 20
    assert m["assembled"] == 120


# ── coordinate handling ───────────────────────────────────────────────

def test_listings_without_coords_are_counted_not_enriched(tmp_path):
    get = _Elevation()
    m = _run([_listing("a", 13.69, -89.19),
              _listing("b", None, None),
              _listing("c", 13.69, None)], tmp_path, get)
    assert m["listings_with_coords"] == 1
    assert m["listings_no_coords"] == 2
    assert "t|b" not in load_cache(tmp_path / "geo_enrichment.json")


def test_null_island_is_rejected(tmp_path):
    """(0,0) is 'the geocoder returned nothing', not a location."""
    get = _Elevation()
    m = _run([_listing("a", 0.0, 0.0)], tmp_path, get)
    assert m["listings_with_coords"] == 0
    assert m["listings_no_coords"] == 1


def test_coord_change_reassembles_from_the_new_cell(tmp_path):
    """A geocoding upgrade must not leave yesterday's data attached."""
    get = _Elevation()
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    _run([_listing("a", 14.9500, -89.5600)], tmp_path, get)
    rec = json.loads((tmp_path / "geo_enrichment.json").read_text())["t|a"]
    assert rec["providers"]["open_meteo_elevation"]["cell"] == "14.95,-89.56"
    assert rec["coords"]["lat"] == 14.95


def test_listings_without_identity_are_skipped(tmp_path):
    get = _Elevation()
    m = _run([{"source": "t", "lat": 13.6, "lng": -89.1}], tmp_path, get)
    assert m["listings_with_coords"] == 0


def test_accepts_dataclass_style_listings(tmp_path):
    """The backfill script passes dicts; the pipeline passes objects."""
    class L:
        source, source_id = "t", "obj"
        lat, lng = 13.6989, -89.1914
        country, geocoding_source, geocoding_confidence = "SV", "estimated", "high"

    m = _run([L()], tmp_path, _Elevation())
    assert m["assembled"] == 1
    assert "t|obj" in load_cache(tmp_path / "geo_enrichment.json")


# ── budget + failure posture ──────────────────────────────────────────

def test_expired_deadline_makes_no_calls_but_still_assembles(tmp_path):
    get = _Elevation()
    m = _run([_listing("a", 13.6989, -89.1914)], tmp_path, get,
             deadline=time.monotonic() - 1)
    assert m["api_calls"] == 0
    assert m["deadline_hit"] is True
    assert m["assembled"] == 1
    assert m["listings_pending"] == 1
    rec = json.loads((tmp_path / "geo_enrichment.json").read_text())["t|a"]
    assert rec["providers"]["open_meteo_elevation"]["status"] == "pending"
    assert rec["elevation"] is None


def test_deadline_leaves_already_cached_data_servable(tmp_path):
    """Budget exhaustion must not blank out what we already know."""
    get = _Elevation()
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    m = _run([_listing("a", 13.6989, -89.1914), _listing("b", 12.0, -88.0)],
             tmp_path, get, deadline=time.monotonic() - 1)
    recs = json.loads((tmp_path / "geo_enrichment.json").read_text())
    assert recs["t|a"]["elevation"]["elevation_m"] == 100
    assert recs["t|b"]["elevation"] is None
    assert m["listings_pending"] == 1


def test_global_call_cap_is_respected(tmp_path):
    get = _Elevation()
    listings = [_listing(f"l{i}", 13.0 + i * 0.02, -89.0) for i in range(300)]
    m = _run(listings, tmp_path, get, max_calls=2)
    assert m["api_calls"] == 2
    assert m["listings_pending"] > 0


def test_per_provider_cap_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PULPO_GEO_OPEN_METEO_ELEVATION_MAX_CALLS", "1")
    get = _Elevation()
    listings = [_listing(f"l{i}", 13.0 + i * 0.02, -89.0) for i in range(150)]
    m = _run(listings, tmp_path, get)
    assert m["api_calls"] == 1


def test_failed_cell_is_not_cached_so_tomorrow_retries(tmp_path):
    get = _Elevation(fail_times=99, exc=RuntimeError("boom"))
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    cells = load_cache(tmp_path / "geo_cells.json")
    assert cells == {}


def test_repeated_failures_disable_a_per_cell_provider(tmp_path):
    """An expired key or an IP ban fails identically on every cell —
    grinding through hundreds of them just burns the budget. Uses NASA
    POWER because it fetches one cell per call, which is the shape the
    throttled providers (SoilGrids, Overpass) have too."""
    get = _Elevation(fail_times=999, exc=RuntimeError("boom"))
    listings = [_listing(f"l{i}", 13.0 + i * 0.6, -89.0) for i in range(30)]
    m = _run(listings, tmp_path, get, providers=["nasa_power"])
    assert "nasa_power" in m["providers_disabled"]
    assert m["api_calls"] == geo._PROVIDER_FAILURE_LIMIT
    assert m["per_provider"]["nasa_power"]["cells_needed"] > 3   # it gave up early


def test_repeated_batch_failures_disable_a_batching_provider(tmp_path):
    """Same guard on the batch path: 3 failed batches, then stop."""
    get = _Elevation(fail_times=999, exc=RuntimeError("boom"))
    # >200 distinct 0.01-degree cells so there are at least 3 batches of 100.
    listings = [_listing(f"l{i}", 13.0 + i * 0.02, -89.0) for i in range(250)]
    m = _run(listings, tmp_path, get)
    assert "open_meteo_elevation" in m["providers_disabled"]
    assert m["api_calls"] == geo._PROVIDER_FAILURE_LIMIT


def test_auth_status_disables_provider_immediately(tmp_path):
    get = _Elevation(fail_times=999, status_code=403)
    listings = [_listing(f"l{i}", 13.0 + i * 0.5, -89.0) for i in range(20)]
    m = _run(listings, tmp_path, get)
    assert m["api_calls"] == 1
    assert m["per_provider"]["open_meteo_elevation"]["disabled_reason"] == "http_403"


def test_failed_listing_is_marked_failed_not_pending(tmp_path):
    get = _Elevation(fail_times=999, exc=RuntimeError("boom"))
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    rec = json.loads((tmp_path / "geo_enrichment.json").read_text())["t|a"]
    assert rec["providers"]["open_meteo_elevation"]["status"] == "failed"


def test_na_payload_is_cached_and_recorded(tmp_path):
    """'No data here' is an answer worth remembering, unlike a failure."""
    class _Null:
        calls = []
        def __call__(self, url, params, headers, timeout_s):
            return _StubResponse({"elevation": [None]})

    m = _run([_listing("a", 13.6989, -89.1914)], tmp_path, _Null())
    assert m["calls_na"] == 1
    rec = json.loads((tmp_path / "geo_enrichment.json").read_text())["t|a"]
    assert rec["providers"]["open_meteo_elevation"]["status"] == "na"
    assert rec["elevation"] is None
    assert len(load_cache(tmp_path / "geo_cells.json")) == 1


# ── versioning + staged rollout ───────────────────────────────────────

def test_version_bump_refetches_and_prunes_old_key(tmp_path, monkeypatch):
    get = _Elevation()
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    monkeypatch.setattr(geo.open_meteo_elevation, "VERSION", 2)
    m = _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    assert m["api_calls"] == 1
    cells = load_cache(tmp_path / "geo_cells.json")
    assert cell_key("open_meteo_elevation", "13.70,-89.19", 2) in cells
    assert cell_key("open_meteo_elevation", "13.70,-89.19", 1) not in cells


def test_provider_allowlist_narrows_the_run(tmp_path):
    get = _Elevation()
    m = _run([_listing("a", 13.6989, -89.1914)], tmp_path, get,
             providers=["open_meteo_elevation"])
    assert set(m["per_provider"]) == {"open_meteo_elevation"}


def test_unknown_provider_name_is_ignored_not_fatal(tmp_path):
    """The allowlist is an ops knob; a typo must not take the nightly down."""
    m = _run([_listing("a", 13.6989, -89.1914)], tmp_path, _Elevation(),
             providers=["nope"])
    assert m["per_provider"] == {}
    assert m["assembled"] == 1


def test_narrowed_run_preserves_other_providers_data(tmp_path):
    """A staged rollout must not delete yesterday's categories."""
    get = _Elevation()
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get,
         providers=["open_meteo_elevation"])
    side_path = tmp_path / "geo_enrichment.json"
    data = json.loads(side_path.read_text())
    data["t|a"]["solar_climate"] = {"ghi_kwh_m2_day": 5.8}
    data["t|a"]["providers"]["nasa_power"] = {"status": "ok", "cell": "13.5,-89.0",
                                              "version": 1}
    side_path.write_text(json.dumps(data))

    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get,
         providers=["open_meteo_elevation"])
    rec = json.loads(side_path.read_text())["t|a"]
    assert rec["solar_climate"] == {"ghi_kwh_m2_day": 5.8}
    assert rec["providers"]["nasa_power"]["status"] == "ok"


def test_slow_ttl_refetches_after_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(geo.open_meteo_elevation, "TTL_CLASS", "slow")
    monkeypatch.setattr(geo.open_meteo_elevation, "REFRESH_DAYS", 7)
    get = _Elevation()
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get, now_fn=lambda: NOW)
    m = _run([_listing("a", 13.6989, -89.1914)], tmp_path, get,
             now_fn=lambda: NOW + timedelta(days=8))
    assert m["api_calls"] == 1


# ── run modes ─────────────────────────────────────────────────────────

def test_offline_is_a_total_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv("PULPO_OFFLINE", "1")
    get = _Elevation()
    m = _run([_listing("a", 13.6989, -89.1914)], tmp_path, get)
    assert m["offline_skip"] is True
    assert get.calls == []
    assert not (tmp_path / "geo_cells.json").exists()
    assert not (tmp_path / "geo_enrichment.json").exists()


def test_dry_run_reports_need_without_touching_anything(tmp_path):
    get = _Elevation()
    m = _run([_listing("a", 13.6989, -89.1914)], tmp_path, get, dry_run=True)
    assert m["cells_needed"] == 1
    assert m["api_calls"] == 0
    assert get.calls == []
    assert not (tmp_path / "geo_cells.json").exists()


def test_max_listings_caps_the_slice(tmp_path):
    get = _Elevation()
    m = _run([_listing(f"l{i}", 13.0 + i * 0.5, -89.0) for i in range(10)],
             tmp_path, get, max_listings=3)
    assert m["listings_with_coords"] == 3


def test_history_row_records_coverage(tmp_path):
    get = _Elevation()
    _run([_listing("a", 13.6989, -89.1914)], tmp_path, get,
         history_path=tmp_path / "geo_enrichment_history.jsonl")
    rows = (tmp_path / "geo_enrichment_history.jsonl").read_text().strip().splitlines()
    row = json.loads(rows[-1])
    assert row["assembled"] == 1
    assert row["coverage"]["open_meteo_elevation"] == 1.0
