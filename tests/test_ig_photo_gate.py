"""Tests for automation/ig_photo_gate.py.

Strategy: feed in synthetic listings with one field flipped at a time and
assert the gate accepts/rejects for the expected reason.  Real ranked.json
shape varies enough that a fixture-based test would be brittle; the
single-field-flip pattern keeps the suite stable across future field
additions to ranked.json.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_photo_gate import (   # noqa: E402
    build_candidates,
    evaluate_listing,
    main as gate_main,
    order_photo_indices,
    passes_gate,
    select_hero_index,
    suggest_palette,
)


# ── fixture: a known-passing terreno ───────────────────────────────────

def _good_terreno(**override) -> dict:
    """Listing that passes every default predicate.  Tests override one
    field at a time to trigger a specific rejection."""
    base = {
        "source":                   "remax",
        "source_id":                "test_001",
        "rank":                     11,
        "rank_score":               81.6,
        "property_type":            "land",
        "subcategory":              "land",
        "zone":                     "el-zonte",
        "department":               "La Libertad",
        "photos_count":             6,
        "hero_eligible":            True,
        "card_eligible":            True,
        "hero_photo_quality_score": 80,
        "has_text_overlay":         False,
        "has_marketing_overlay":    None,
        "data_quality_score":       0.7,
        "is_incomplete":            False,
        "is_agricultural":          False,
        "validation_status":        None,
        "price_usd":                667295.0,
        "area_m2":                  18917.05,
        "price_per_m2":             35.27,
        "price_vs_zone_pct":        -10.0,
        "dist_beach_km":            1.4,
    }
    base.update(override)
    return base


# Default config (matches env defaults).
_CFG = {
    "min_photos": 4,
    "min_hero_score": 60,
    "min_data_quality": 0.55,
    "terrenos_only": True,
    "exclude_agricultural": True,
    "max_candidates": 0,
}


# ── happy path ─────────────────────────────────────────────────────────

def test_good_terreno_passes():
    li = _good_terreno()
    ok, reason = evaluate_listing(li, _CFG)
    assert ok is True
    assert reason is None
    assert passes_gate(li, _CFG) is True


# ── one rejection per predicate ────────────────────────────────────────

@pytest.mark.parametrize("override,expected_reason", [
    ({"price_usd": None},                         "missing_price"),
    ({"price_usd": 0},                            "missing_price"),
    ({"area_m2": None},                           "missing_area"),
    ({"area_m2": 0},                              "missing_area"),
    ({"source_id": None},                         "missing_source_id"),
    ({"property_type": "house"},                  "not_terreno"),
    ({"property_type": "condo"},                  "not_terreno"),
    ({"property_type": None},                     "not_terreno"),
    ({"is_agricultural": True},                   "agricultural"),
    ({"photos_count": 3},                         "low_photos"),
    ({"photos_count": 0},                         "low_photos"),
    ({"photos_count": None},                      "low_photos"),
    ({"card_eligible": False, "hero_eligible": False}, "not_eligible"),
    ({"has_text_overlay": True},                  "text_overlay"),
    ({"has_marketing_overlay": True},             "marketing_overlay"),
    ({"is_incomplete": True},                     "incomplete"),
    ({"data_quality_score": 0.40},                "low_data_quality"),
    ({"data_quality_score": None},                "low_data_quality"),
    ({"hero_photo_quality_score": 30},            "low_hero_score"),
    ({"hero_photo_quality_score": None},          "low_hero_score"),
    ({"validation_status": "rejected"},           "validation_rejected"),
])
def test_each_predicate_rejects_for_correct_reason(override, expected_reason):
    li = _good_terreno(**override)
    ok, reason = evaluate_listing(li, _CFG)
    assert ok is False, f"expected reject, got pass for {override}"
    assert reason == expected_reason, (
        f"override {override} expected reason {expected_reason}, got {reason}"
    )


# ── config toggles ─────────────────────────────────────────────────────

def test_terrenos_only_flag_lets_houses_through_when_off():
    cfg = {**_CFG, "terrenos_only": False}
    li = _good_terreno(property_type="house")
    assert passes_gate(li, cfg) is True


def test_exclude_agricultural_flag_off_lets_agricultural_through():
    cfg = {**_CFG, "exclude_agricultural": False}
    li = _good_terreno(is_agricultural=True)
    assert passes_gate(li, cfg) is True


def test_lower_min_photos_threshold_lets_thin_listing_through():
    cfg = {**_CFG, "min_photos": 1}
    li = _good_terreno(photos_count=2)
    assert passes_gate(li, cfg) is True


# ── hero + photo ordering ──────────────────────────────────────────────

def test_select_hero_index_returns_zero_today():
    """Current pipeline shuffles photo_urls so hero is at index 0.
    Pin the contract — if select_hero_index ever changes, the
    publisher needs to know."""
    assert select_hero_index(_good_terreno()) == 0


@pytest.mark.parametrize("count,expected", [
    (0,  []),
    (1,  [0]),
    (5,  [0, 1, 2, 3, 4]),
    (10, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),
    (15, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),  # capped at 10 for IG carousel
])
def test_order_photo_indices_cap(count, expected):
    li = _good_terreno(photos_count=count)
    assert order_photo_indices(li) == expected


def test_order_photo_indices_None_safe():
    li = _good_terreno(photos_count=None)
    assert order_photo_indices(li) == []


# ── palette suggestion ─────────────────────────────────────────────────

def test_palette_default_for_normal_terreno():
    """Above the bargain threshold → ink mode (the editorial default)."""
    li = _good_terreno(price_vs_zone_pct=10.0)
    assert suggest_palette(li) == "ink"


def test_palette_paper_for_bargain():
    """≤ −20% vs zone → paper (the bargain alert palette)."""
    li = _good_terreno(price_vs_zone_pct=-25.0)
    assert suggest_palette(li) == "paper"


def test_palette_paper_at_exact_bargain_threshold():
    """Boundary: exactly −20% triggers bargain palette."""
    li = _good_terreno(price_vs_zone_pct=-20.0)
    assert suggest_palette(li) == "paper"


def test_palette_default_when_zone_delta_missing():
    li = _good_terreno(price_vs_zone_pct=None)
    assert suggest_palette(li) == "ink"


# ── build_candidates aggregation ───────────────────────────────────────

def test_build_candidates_empty_input():
    payload = build_candidates([], cfg=_CFG, computed_at="2026-05-26T00:00:00+00:00")
    assert payload["version"] == 1
    assert payload["stats"]["scanned"] == 0
    assert payload["stats"]["passed"] == 0
    assert payload["candidates"] == []


def test_build_candidates_mixed_input():
    listings = [
        _good_terreno(source="a", source_id="1", rank_score=80),
        _good_terreno(source="b", source_id="2", rank_score=90),
        _good_terreno(source="c", source_id="3", property_type="house"),    # rejected
        _good_terreno(source="d", source_id="4", is_agricultural=True),     # rejected
        _good_terreno(source="e", source_id="5", photos_count=1),           # rejected
    ]
    payload = build_candidates(listings, cfg=_CFG)
    assert payload["stats"]["scanned"] == 5
    assert payload["stats"]["passed"] == 2
    assert payload["stats"]["rejection_reasons"]["not_terreno"] == 1
    assert payload["stats"]["rejection_reasons"]["agricultural"] == 1
    assert payload["stats"]["rejection_reasons"]["low_photos"] == 1
    # candidates ordered by rank_score desc — b (90) before a (80)
    assert [c["listing_id"] for c in payload["candidates"]] == ["b__2", "a__1"]


def test_build_candidates_orders_by_rank_score_descending():
    listings = [
        _good_terreno(source="x", source_id=str(i), rank_score=score)
        for i, score in enumerate([50, 90, 70, 80, 95])
    ]
    payload = build_candidates(listings, cfg=_CFG)
    scores = [c["rank_score"] for c in payload["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_build_candidates_respects_max_cap():
    cfg = {**_CFG, "max_candidates": 2}
    listings = [
        _good_terreno(source="a", source_id=str(i), rank_score=100 - i)
        for i in range(5)
    ]
    payload = build_candidates(listings, cfg=cfg)
    assert payload["stats"]["passed"] == 2
    # Top 2 by score = a__0 (100), a__1 (99)
    assert [c["source_id"] for c in payload["candidates"]] == ["0", "1"]


def test_build_candidates_listing_id_format():
    """listing_id must be '{source}__{source_id}' — the publisher and
    queue both key off this exact format."""
    listings = [_good_terreno(source="oceanside", source_id="15463")]
    payload = build_candidates(listings, cfg=_CFG)
    assert payload["candidates"][0]["listing_id"] == "oceanside__15463"


def test_build_candidates_payload_shape():
    """The output JSON shape is contract — the publisher and queue
    builder both parse it.  Don't add/remove top-level keys without
    bumping the version and updating consumers."""
    payload = build_candidates([_good_terreno()], cfg=_CFG)
    assert set(payload.keys()) == {
        "version", "computed_at", "config", "stats", "candidates"
    }
    assert set(payload["stats"].keys()) == {
        "scanned", "passed", "by_property_type", "rejection_reasons"
    }
    candidate = payload["candidates"][0]
    required = {
        "listing_id", "source", "source_id", "rank", "rank_score",
        "property_type", "subcategory", "zone", "department",
        "photos_count", "hero_photo_quality_score",
        "hero_index", "photo_indices_ordered", "palette_suggested",
        "price_usd", "area_m2", "price_per_m2", "price_vs_zone_pct",
        "dist_beach_km", "passes_at",
    }
    assert required.issubset(candidate.keys()), (
        f"missing: {required - candidate.keys()}"
    )


# ── CLI / file I/O ─────────────────────────────────────────────────────

def test_main_writes_output_json(tmp_path):
    ranked_in = tmp_path / "ranked.json"
    candidates_out = tmp_path / "ig_candidates.json"

    ranked_in.write_text(json.dumps([
        _good_terreno(source="a", source_id="1"),
        _good_terreno(source="b", source_id="2", property_type="house"),
    ]))

    rc = gate_main(["--ranked", str(ranked_in), "--output", str(candidates_out)])
    assert rc == 0

    written = json.loads(candidates_out.read_text())
    assert written["stats"]["scanned"] == 2
    assert written["stats"]["passed"] == 1
    assert written["candidates"][0]["listing_id"] == "a__1"


def test_main_handles_missing_input(tmp_path):
    missing = tmp_path / "nope.json"
    rc = gate_main(["--ranked", str(missing), "--output", str(tmp_path / "out.json")])
    assert rc == 2


def test_main_respects_limit_flag(tmp_path):
    ranked_in = tmp_path / "ranked.json"
    candidates_out = tmp_path / "ig_candidates.json"

    ranked_in.write_text(json.dumps([
        _good_terreno(source="a", source_id=str(i)) for i in range(10)
    ]))

    rc = gate_main([
        "--ranked", str(ranked_in),
        "--output", str(candidates_out),
        "--limit", "3",
    ])
    assert rc == 0
    written = json.loads(candidates_out.read_text())
    assert written["stats"]["scanned"] == 3
