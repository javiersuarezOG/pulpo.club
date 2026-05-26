"""Tests for automation/ig_triggers.py.

Same single-field-flip pattern as test_ig_photo_gate.  Each detector has
its own group of tests; orchestration tests live at the bottom.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_triggers import (   # noqa: E402
    BARGAIN_ALERT,
    COMPARABLE_CRASH,
    FRESH_AND_HOT,
    PRICE_DROP,
    TOP_RANK,
    ZONE_DOMINATION,
    _detect_bargain,
    _detect_comparable_crash,
    _detect_fresh_and_hot,
    _detect_price_drop,
    _detect_top_rank,
    _detect_zone_domination,
    apply_caps,
    detect_all,
    main as triggers_main,
)


# Default config matching env defaults.
_CFG = {
    "bargain_pct_threshold":   -20.0,
    "bargain_cap_per_week":    2,
    "top_rank_threshold":      15,
    "top_rank_cap_per_week":   2,
    "price_drop_cap_per_week": 2,
    "fresh_days_threshold":    7,
    "fresh_rank_threshold":    100,
    "fresh_cap_per_week":      1,
    "zone_dom_count":          3,
    "zone_dom_top_n":          50,
    "zone_dom_cap_per_week":   1,
    "comp_crash_ratio":        0.40,
    "comp_crash_min_comps":    3,
    "comp_crash_cap_per_week": 1,
}


def _li(**override) -> dict:
    """Listing that passes the IG photo gate AND has all trigger-relevant
    fields populated.  Tests override one field at a time."""
    base = {
        # ig_photo_gate.passes_gate requirements
        "source":                   "bienesraices",
        "source_id":                "test_001",
        "property_type":            "land",
        "subcategory":              "land",
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
        # trigger-relevant fields
        "rank":                     49,
        "rank_score":               74.3,
        "zone":                     "el-cuco",
        "price_per_m2":             11.82,
        "price_vs_zone_pct":        -93.0,
        "price_vs_zone_median":     170.0,
        "zone_comp_count":          15,
        "is_repriced":              False,
        "previous_price":           None,
        "days_listed":              12,
    }
    base.update(override)
    return base


# ── BARGAIN_ALERT ──────────────────────────────────────────────────────

def test_bargain_fires_at_minus_93():
    r = _detect_bargain(_li(price_vs_zone_pct=-93.0), _CFG)
    assert r is not None
    assert r["trigger"] == BARGAIN_ALERT
    assert r["data"]["price_vs_zone_pct"] == -93.0
    assert "93%" in r["rationale"]


def test_bargain_fires_at_exact_threshold():
    """Boundary: −20.0 exactly should fire (≤ threshold)."""
    assert _detect_bargain(_li(price_vs_zone_pct=-20.0), _CFG) is not None


def test_bargain_does_not_fire_above_threshold():
    assert _detect_bargain(_li(price_vs_zone_pct=-19.9), _CFG) is None
    assert _detect_bargain(_li(price_vs_zone_pct=0.0), _CFG) is None
    assert _detect_bargain(_li(price_vs_zone_pct=15.0), _CFG) is None


def test_bargain_does_not_fire_when_pct_missing():
    """Defensive: a null price_vs_zone_pct must not fire (could happen
    when the zone has no comps yet)."""
    assert _detect_bargain(_li(price_vs_zone_pct=None), _CFG) is None


# ── TOP_RANK ───────────────────────────────────────────────────────────

def test_top_rank_fires_at_rank_11():
    """Listing #11 (super-rank in user's brief) should fire."""
    r = _detect_top_rank(_li(rank=11), _CFG)
    assert r is not None
    assert r["trigger"] == TOP_RANK
    assert r["data"]["rank"] == 11


def test_top_rank_fires_at_exact_threshold():
    assert _detect_top_rank(_li(rank=15), _CFG) is not None


def test_top_rank_does_not_fire_below_threshold():
    assert _detect_top_rank(_li(rank=16), _CFG) is None
    assert _detect_top_rank(_li(rank=100), _CFG) is None


def test_top_rank_does_not_fire_when_rank_missing():
    assert _detect_top_rank(_li(rank=None), _CFG) is None


# ── PRICE_DROP ─────────────────────────────────────────────────────────

def test_price_drop_fires_when_repriced_and_lower():
    r = _detect_price_drop(
        _li(is_repriced=True, previous_price=500_000, price_usd=400_000), _CFG
    )
    assert r is not None
    assert r["trigger"] == PRICE_DROP
    assert r["data"]["previous_price"] == 500_000
    assert r["data"]["current_price"] == 400_000
    assert r["data"]["delta_pct"] == -20.0
    assert "20%" in r["rationale"]


def test_price_drop_does_not_fire_if_price_went_up():
    """is_repriced=True but new > old (rare but possible)."""
    r = _detect_price_drop(
        _li(is_repriced=True, previous_price=400_000, price_usd=500_000), _CFG
    )
    assert r is None


def test_price_drop_does_not_fire_if_not_repriced():
    """is_repriced=False short-circuits even if previous_price is set."""
    r = _detect_price_drop(
        _li(is_repriced=False, previous_price=500_000, price_usd=400_000), _CFG
    )
    assert r is None


def test_price_drop_does_not_fire_if_previous_missing():
    r = _detect_price_drop(
        _li(is_repriced=True, previous_price=None, price_usd=400_000), _CFG
    )
    assert r is None


# ── FRESH_AND_HOT ──────────────────────────────────────────────────────

def test_fresh_fires_for_new_high_rank():
    r = _detect_fresh_and_hot(_li(days_listed=3, rank=50), _CFG)
    assert r is not None
    assert r["trigger"] == FRESH_AND_HOT
    assert r["data"]["days_listed"] == 3


def test_fresh_does_not_fire_for_old_listing():
    assert _detect_fresh_and_hot(_li(days_listed=8, rank=50), _CFG) is None


def test_fresh_does_not_fire_for_low_rank():
    """7 days but rank 200 — doesn't qualify."""
    assert _detect_fresh_and_hot(_li(days_listed=7, rank=200), _CFG) is None


def test_fresh_does_not_fire_when_fields_missing():
    assert _detect_fresh_and_hot(_li(days_listed=None, rank=50), _CFG) is None
    assert _detect_fresh_and_hot(_li(days_listed=3, rank=None), _CFG) is None


# ── COMPARABLE_CRASH ───────────────────────────────────────────────────

def test_comparable_crash_fires_when_well_below_comps():
    """price_per_m2=$11.82 vs zone_median=$170 → ratio 0.07 → fires."""
    r = _detect_comparable_crash(
        _li(price_per_m2=11.82, price_vs_zone_median=170.0, zone_comp_count=15),
        _CFG,
    )
    assert r is not None
    assert r["trigger"] == COMPARABLE_CRASH
    assert r["data"]["ratio"] < 0.4
    assert r["data"]["comp_count"] == 15


def test_comparable_crash_does_not_fire_above_ratio():
    """ppm=$80 vs median=$170 → ratio 0.47 → doesn't fire (threshold 0.40)."""
    assert _detect_comparable_crash(
        _li(price_per_m2=80.0, price_vs_zone_median=170.0, zone_comp_count=15),
        _CFG,
    ) is None


def test_comparable_crash_requires_min_comps():
    """Need ≥3 comparables; with 2, don't fire."""
    assert _detect_comparable_crash(
        _li(price_per_m2=11.82, price_vs_zone_median=170.0, zone_comp_count=2),
        _CFG,
    ) is None


def test_comparable_crash_safe_when_fields_missing():
    assert _detect_comparable_crash(
        _li(price_per_m2=None, price_vs_zone_median=170.0, zone_comp_count=15),
        _CFG,
    ) is None
    assert _detect_comparable_crash(
        _li(price_per_m2=11.82, price_vs_zone_median=None, zone_comp_count=15),
        _CFG,
    ) is None
    assert _detect_comparable_crash(
        _li(price_per_m2=11.82, price_vs_zone_median=0, zone_comp_count=15),
        _CFG,
    ) is None


# ── ZONE_DOMINATION ────────────────────────────────────────────────────

def test_zone_domination_fires_when_zone_has_3_plus_in_top_50():
    listings = [
        _li(source_id=str(i), zone="el-tunco", rank=r)
        for i, r in enumerate([3, 8, 12, 25, 40])
    ] + [
        _li(source_id=f"x{i}", zone="el-cuco", rank=r)
        for i, r in enumerate([200, 300, 400])
    ]
    records = _detect_zone_domination(listings, _CFG)
    triggers_by_zone = {r["data"]["zone"]: r for r in records}
    assert "el-tunco" in triggers_by_zone
    assert triggers_by_zone["el-tunco"]["data"]["count_in_top_n"] == 5
    # el-cuco has 0 in top 50, so no record.
    assert "el-cuco" not in triggers_by_zone


def test_zone_domination_does_not_fire_below_threshold():
    """el-zonte has 2 in top-50, threshold is 3 → no record."""
    listings = [
        _li(source_id=str(i), zone="el-zonte", rank=r) for i, r in enumerate([5, 20])
    ]
    assert _detect_zone_domination(listings, _CFG) == []


def test_zone_domination_picks_highest_ranked_representative():
    """The poster will feature one listing — must be the best-ranked
    in the dominating zone (lowest rank number)."""
    listings = [
        _li(source_id="a", zone="el-zonte", rank=8),
        _li(source_id="b", zone="el-zonte", rank=12),
        _li(source_id="c", zone="el-zonte", rank=20),
    ]
    records = _detect_zone_domination(listings, _CFG)
    assert len(records) == 1
    assert records[0]["source_id"] == "a"
    assert records[0]["rank"] == 8


def test_zone_domination_ignores_listings_without_zone():
    listings = [
        _li(source_id=str(i), zone=None, rank=r) for i, r in enumerate([3, 8, 12])
    ]
    assert _detect_zone_domination(listings, _CFG) == []


# ── caps ───────────────────────────────────────────────────────────────

def test_apply_caps_per_trigger():
    """Cap bargain at 2, top_rank at 2.  Generate 5 of each, expect 2+2."""
    records = (
        [{"trigger": BARGAIN_ALERT, "priority": 4, "rank": r} for r in range(5)] +
        [{"trigger": TOP_RANK,      "priority": 3, "rank": r} for r in range(5)]
    )
    capped = apply_caps(records, _CFG)
    bargain = [r for r in capped if r["trigger"] == BARGAIN_ALERT]
    top = [r for r in capped if r["trigger"] == TOP_RANK]
    assert len(bargain) == 2
    assert len(top) == 2


def test_apply_caps_orders_by_priority_then_rank():
    """Within-trigger: best rank (lowest number) wins."""
    records = [
        {"trigger": BARGAIN_ALERT, "priority": 4, "rank": 99},
        {"trigger": BARGAIN_ALERT, "priority": 4, "rank": 5},   # better
        {"trigger": BARGAIN_ALERT, "priority": 4, "rank": 50},
    ]
    capped = apply_caps(records, _CFG)
    assert capped[0]["rank"] == 5


def test_apply_caps_final_sort_priority_desc():
    """Output sorted by priority desc then rank asc — queue builder
    relies on this to pick the most newsworthy injection first."""
    records = [
        {"trigger": ZONE_DOMINATION, "priority": 1, "rank": 1},
        {"trigger": PRICE_DROP,      "priority": 5, "rank": 99},
        {"trigger": BARGAIN_ALERT,   "priority": 4, "rank": 30},
    ]
    capped = apply_caps(records, _CFG)
    assert [r["trigger"] for r in capped] == [
        PRICE_DROP, BARGAIN_ALERT, ZONE_DOMINATION,
    ]


# ── orchestration: detect_all ──────────────────────────────────────────

def test_detect_all_pipes_through_to_capped_output():
    listings = [
        _li(source_id="a", rank=5,  price_vs_zone_pct=-93.0),   # bargain + top-rank
        _li(source_id="b", rank=14, price_vs_zone_pct=-30.0),   # bargain + top-rank
        _li(source_id="c", rank=20, price_vs_zone_pct=-50.0),   # bargain only
        _li(source_id="d", rank=200, price_vs_zone_pct=5.0,
            is_repriced=True, previous_price=500_000, price_usd=400_000),  # price drop
        _li(source_id="e", rank=80, days_listed=2, price_vs_zone_pct=0.0),  # fresh
    ]
    payload = detect_all(listings, cfg=_CFG)

    by_trigger = {}
    for r in payload["triggers"]:
        by_trigger.setdefault(r["trigger"], []).append(r)

    # Bargain cap is 2 — only the two highest-ranked (lowest rank #) survive.
    assert len(by_trigger.get(BARGAIN_ALERT, [])) == 2
    bargain_ids = {r["source_id"] for r in by_trigger[BARGAIN_ALERT]}
    assert bargain_ids == {"a", "b"}
    # Top rank cap is 2 — both a and b qualify.
    assert len(by_trigger.get(TOP_RANK, [])) == 2
    # Price drop, Fresh — single records.
    assert len(by_trigger.get(PRICE_DROP, [])) == 1
    assert len(by_trigger.get(FRESH_AND_HOT, [])) == 1


def test_detect_all_requires_ig_gate_by_default():
    """A listing that fails the photo gate (e.g. agricultural) must not
    produce triggers, even if its numbers would qualify."""
    bad = _li(source_id="ag", rank=5, price_vs_zone_pct=-50.0, is_agricultural=True)
    payload = detect_all([bad], cfg=_CFG)
    assert payload["triggers"] == []


def test_detect_all_skip_gate_flag_lets_through():
    bad = _li(source_id="ag", rank=5, price_vs_zone_pct=-50.0, is_agricultural=True)
    payload = detect_all([bad], cfg=_CFG, require_ig_gate=False)
    assert len(payload["triggers"]) >= 1


def test_detect_all_payload_shape():
    payload = detect_all([_li()], cfg=_CFG)
    assert set(payload.keys()) == {
        "version", "computed_at", "config", "stats", "triggers"
    }
    assert set(payload["stats"].keys()) == {
        "scanned", "candidates_per_trigger",
        "after_cap_per_trigger", "total_after_cap",
    }


def test_detect_all_empty_input():
    payload = detect_all([], cfg=_CFG)
    assert payload["stats"]["scanned"] == 0
    assert payload["triggers"] == []


# ── CLI ────────────────────────────────────────────────────────────────

def test_main_writes_output(tmp_path):
    ranked = tmp_path / "ranked.json"
    out = tmp_path / "triggers.json"
    ranked.write_text(json.dumps([_li(rank=5, price_vs_zone_pct=-50.0)]))
    rc = triggers_main(["--ranked", str(ranked), "--output", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["stats"]["scanned"] == 1
    assert len(payload["triggers"]) >= 1


def test_main_handles_missing_input(tmp_path):
    rc = triggers_main([
        "--ranked", str(tmp_path / "nope.json"),
        "--output", str(tmp_path / "out.json"),
    ])
    assert rc == 2


def test_main_skip_gate_flag(tmp_path):
    """A listing that fails the photo gate still produces triggers when
    --skip-gate is set.  Useful for diagnostics."""
    ranked = tmp_path / "ranked.json"
    out = tmp_path / "triggers.json"
    bad = _li(rank=5, price_vs_zone_pct=-50.0, is_agricultural=True)
    ranked.write_text(json.dumps([bad]))
    # without --skip-gate: no triggers
    triggers_main(["--ranked", str(ranked), "--output", str(out)])
    assert json.loads(out.read_text())["stats"]["total_after_cap"] == 0
    # with --skip-gate: triggers fire
    triggers_main(["--ranked", str(ranked), "--output", str(out), "--skip-gate"])
    assert json.loads(out.read_text())["stats"]["total_after_cap"] >= 1
