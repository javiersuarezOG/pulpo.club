"""
Tests for automation/prd_feasibility.py — pins keyword-extraction behavior,
verdict mapping, and aggregation logic so future keyword-dictionary edits
are visible.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.prd_feasibility import (   # noqa: E402
    _text_blob,
    _verdict,
    nlp_feasibility,
    description_quality,
    us01_cohort,
    existing_inventory,
    UI_GATE_PCT,
)


def _li(**kwargs) -> dict:
    base = {
        "title":         "",
        "description":   "",
        "location_text": "",
        "raw_size_text": "",
        "raw_price_text":"",
        "source":        "test",
        "source_id":     "001",
        "url":           "",
        "first_seen_at": "2026-05-04T12:00:00+00:00",
    }
    base.update(kwargs)
    return base


# ── _text_blob — concatenation + lowercasing ───────────────────────────

def test_text_blob_concatenates_and_lowercases():
    blob = _text_blob(_li(title="Lot With Water", description="Has POWER too"))
    assert "lot with water" in blob
    assert "has power too" in blob
    assert "Lot" not in blob   # original-case form must be gone


def test_text_blob_handles_missing_fields():
    blob = _text_blob({"source": "x"})  # only source set, no title/desc
    assert blob.strip() == ""


# ── _verdict — green/amber/red mapping ─────────────────────────────────

def test_verdict_meets_target():
    # PRD target 40%, hit 45% → GREEN
    assert _verdict(45.0, 40) == "GREEN"


def test_verdict_above_gate_below_target():
    # PRD target 40%, hit 25% → AMBER (above 15% gate, below target)
    assert _verdict(25.0, 40) == "AMBER"


def test_verdict_at_gate_no_target():
    # No PRD target, but >= UI gate → GREEN (surface-eligible)
    assert _verdict(UI_GATE_PCT, 0) == "GREEN"


def test_verdict_below_gate():
    assert _verdict(8.0, 0) == "AMBER"   # computed-only


def test_verdict_red_below_5pct():
    assert _verdict(2.0, 0) == "RED"


# ── nlp_feasibility — happy path against a synthetic catalog ──────────

def test_nlp_feasibility_finds_water_keyword():
    catalog = [
        _li(description="Tiene agua y luz."),
        _li(description="Listing without utilities."),
        _li(description="Con pozo y energía eléctrica."),
    ]
    rows = nlp_feasibility(catalog, len(catalog))
    by_field = {r["field"]: r for r in rows}
    # 2 of 3 listings mention water-related terms
    assert by_field["has_water"]["hits"] == 2
    assert by_field["has_water"]["pct"] == round(200/3, 1)
    # has_power: "luz" + "energía eléctrica" → 2 hits
    assert by_field["has_power"]["hits"] == 2


def test_nlp_feasibility_handles_empty_catalog_safely():
    rows = nlp_feasibility([], 0)
    # All fields should be present with 0 hits, 0%, no division-by-zero
    assert all(r["hits"] == 0 for r in rows)
    assert all(r["pct"] == 0 for r in rows)


# ── description_quality buckets ────────────────────────────────────────

def test_description_quality_buckets():
    catalog = [
        _li(description=""),
        _li(description="x" * 10),     # <50
        _li(description="x" * 100),    # 50-200
        _li(description="x" * 300),    # 200-500
        _li(description="x" * 600),    # >=500
    ]
    q = description_quality(catalog, len(catalog))
    counts = {b["bucket"]: b["count"] for b in q["buckets"]}
    assert counts["empty"] == 1
    assert counts["<50 chars"] == 1
    assert counts["50-200"] == 1
    assert counts["200-500"] == 1
    assert counts[">=500"] == 1


def test_description_quality_per_source_breakdown():
    catalog = [
        _li(description="x"*1000, source="bienesraices"),
        _li(description="",       source="century21"),
        _li(description="x"*100,  source="bienesraices"),
    ]
    q = description_quality(catalog, len(catalog))
    by_src = {s["source"]: s for s in q["per_source"]}
    assert by_src["bienesraices"]["n"] == 2
    assert by_src["century21"]["pct_short_lt50"] == 100.0


# ── us01_cohort — water + power + paved ────────────────────────────────

def test_us01_cohort_any_vs_all():
    catalog = [
        _li(description="Has agua, luz, asfalto."),  # ALL 3
        _li(description="Has agua only."),            # 1 of 3
        _li(description="Nothing relevant."),         # 0 of 3
    ]
    out = us01_cohort(catalog, len(catalog))
    assert out["all_three_signals"]["hits"] == 1
    assert out["any_one_signal"]["hits"] == 2
    assert out["all_three_signals"]["pct"] == round(100/3, 1)


# ── existing_inventory ─────────────────────────────────────────────────

def test_existing_inventory_counts_populated_fields():
    catalog = [
        _li(url="https://x.com/1", title="A", price_usd=100, area_m2=500,
            zone="el-tunco", zone_confidence="specific"),
        _li(url="https://x.com/2", title="B", price_usd=200, area_m2=600,
            zone="el-cuco", zone_confidence="specific"),
    ]
    rows = existing_inventory(catalog, len(catalog))
    by_field = {r["field"]: r for r in rows}
    assert by_field["url"]["pct"] == 100.0
    assert by_field["zone"]["pct"] == 100.0
    assert by_field["zone_specific"]["pct"] == 100.0
    # broker_name not set → 0%
    assert by_field["broker_name"]["pct"] == 0.0
