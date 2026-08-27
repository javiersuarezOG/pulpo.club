"""
Tests for automation/geo_enrichment/_cache.py — the cell-keying, TTL and
retention contract that makes the enrichment pass nearly free after the
first backfill.

Pure functions + tmp_path file I/O. No network, no clock dependence
(every freshness test injects `now`).
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.geo_enrichment._cache import (   # noqa: E402
    STATUS_NA,
    STATUS_OK,
    append_history,
    cell_center,
    cell_id,
    cell_key,
    entry_fresh,
    iso,
    load_cache,
    make_entry,
    parse_iso,
    prune,
    save_cache,
)

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


# ── cell_id ───────────────────────────────────────────────────────────

def test_cell_id_snaps_to_grid():
    assert cell_id(13.6989, -89.1914, 0.5, 1) == "13.5,-89.0"
    assert cell_id(13.6989, -89.1914, 0.01, 2) == "13.70,-89.19"


def test_cell_id_is_stable_for_nearby_coords():
    """The whole point: neighbours collapse onto one API call."""
    a = cell_id(13.4931, -89.3797, 0.5, 1)
    b = cell_id(13.4102, -89.4400, 0.5, 1)
    assert a == b == "13.5,-89.5"


def test_cell_id_handles_float_artifacts():
    """round(13.47/0.05)*0.05 is 13.450000000000001 — must never key a cache."""
    cid = cell_id(13.47, -89.42, 0.05, 2)
    assert cid == "13.45,-89.40"
    assert "0000" not in cid


def test_cell_id_negative_and_zero_have_no_negative_zero():
    assert cell_id(-0.004, 0.004, 0.5, 1) == "0.0,0.0"
    assert cell_id(-13.6, -89.2, 0.25, 2) == "-13.50,-89.25"


def test_cell_center_round_trips():
    cid = cell_id(13.6989, -89.1914, 0.5, 1)
    assert cell_center(cid) == (13.5, -89.0)


def test_cell_key_embeds_version():
    assert cell_key("nasa_power", "13.5,-89.0", 2) == "nasa_power|13.5,-89.0|v2"


# ── freshness ─────────────────────────────────────────────────────────

def test_static_entry_never_expires():
    old = make_entry(STATUS_OK, {"x": 1}, "static", NOW - timedelta(days=3650))
    assert entry_fresh(old, ttl_class="static", refresh_days=0, now=NOW)


def test_slow_entry_expires_after_refresh_days():
    entry = make_entry(STATUS_OK, {"x": 1}, "slow", NOW - timedelta(days=8))
    assert not entry_fresh(entry, ttl_class="slow", refresh_days=7, now=NOW)
    assert entry_fresh(entry, ttl_class="slow", refresh_days=30, now=NOW)


def test_na_entry_counts_as_fresh():
    """`na` is a definitive answer ('no modeled river here'), so it caches."""
    entry = make_entry(STATUS_NA, None, "static", NOW)
    assert entry_fresh(entry, ttl_class="static", refresh_days=0, now=NOW)


def test_missing_or_malformed_entry_is_not_fresh():
    assert not entry_fresh(None, ttl_class="static", refresh_days=0, now=NOW)
    assert not entry_fresh({"status": "failed"}, ttl_class="static",
                           refresh_days=0, now=NOW)
    assert not entry_fresh({"status": "ok"}, ttl_class="slow",
                           refresh_days=7, now=NOW)  # no fetched_at


def test_parse_iso_round_trip():
    assert parse_iso(iso(NOW)) == NOW
    assert parse_iso("garbage") is None
    assert parse_iso(None) is None


# ── prune ─────────────────────────────────────────────────────────────

def test_prune_drops_superseded_versions_only():
    cache = {
        "nasa_power|13.5,-89.0|v1": make_entry(STATUS_OK, {}, "static", NOW),
        "nasa_power|13.5,-89.0|v2": make_entry(STATUS_OK, {}, "static", NOW),
        "soilgrids|13.5,-89.0|v1":  make_entry(STATUS_OK, {}, "static", NOW),
    }
    dropped = prune(cache, current_versions={"nasa_power": 2})
    assert dropped == 1
    assert "nasa_power|13.5,-89.0|v1" not in cache
    assert "nasa_power|13.5,-89.0|v2" in cache
    # A provider absent from current_versions wasn't registered this run —
    # its entries stay valid rather than costing a refetch on re-enable.
    assert "soilgrids|13.5,-89.0|v1" in cache


def test_prune_drops_malformed_keys():
    cache = {"nonsense": {}, "a|b|v1": make_entry(STATUS_OK, {}, "static", NOW)}
    assert prune(cache, current_versions={}) == 1
    assert "nonsense" not in cache


def test_prune_row_caps_oldest_first():
    cache = {}
    for i in range(30):
        cache[f"p|{i}|v1"] = make_entry(STATUS_OK, {"i": i}, "static",
                                        NOW - timedelta(days=30 - i))
    prune(cache, current_versions={"p": 1}, max_rows=20)
    assert len(cache) <= 20
    assert "p|29|v1" in cache   # newest survives
    assert "p|0|v1" not in cache  # oldest evicted


# ── file I/O ──────────────────────────────────────────────────────────

def test_save_and_load_cache_round_trip(tmp_path):
    path = tmp_path / "geo_cells.json"
    cache = {"p|13.5,-89.0|v1": make_entry(STATUS_OK, {"elevation_m": 651},
                                           "static", NOW)}
    save_cache(path, cache)
    assert load_cache(path) == cache


def test_save_cache_is_compact(tmp_path):
    """This file is committed nightly — indentation would double the diff."""
    path = tmp_path / "geo_cells.json"
    save_cache(path, {"p|1,1|v1": make_entry(STATUS_OK, {"a": 1}, "static", NOW)})
    assert "\n" not in path.read_text().strip()


def test_load_cache_tolerates_missing_and_corrupt(tmp_path):
    assert load_cache(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_cache(bad) == {}


def test_append_history_caps_rows(tmp_path):
    path = tmp_path / "history.jsonl"
    for i in range(12):
        append_history(path, {"ts": f"row-{i}"}, max_rows=5)
    rows = [json.loads(x) for x in path.read_text().strip().splitlines()]
    assert len(rows) == 5
    assert rows[-1]["ts"] == "row-11"
    assert rows[0]["ts"] == "row-7"


def test_append_history_never_raises_on_bad_path(tmp_path):
    """Telemetry must not be able to break the pipeline."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file")
    append_history(blocker / "nested" / "history.jsonl", {"ts": "x"})
