"""Tests for automation.shelf_audit — per-shelf eligibility audit.

The audit is read-only telemetry: it mirrors the FE eligibility predicate
in ``web/app/home/HomeShelf.jsx::isShelfEligible`` and ALSO computes what
each strictness level (strict | moderate | lenient) would produce against
today's data. PR A2 wires the slider into the live ``derive_is_incomplete``;
this test locks down the audit shape so A2 lands without rewriting tests.
"""
from __future__ import annotations

import json

from automation.shelf_audit import (
    LEVELS,
    SHELF_KEYS,
    compute_audit,
    write_audit,
)


def _li(**fields):
    """Build a dict listing with sensible defaults; override per test."""
    base = {
        "source": "test",
        "source_id": "x",
        "url": "https://example.test/x",
        "title": "Sample",
        "price_usd": 100_000,
        "area_m2": 500,
        "property_type": "land",
        "zone": "el-zonte",
        "master_category": "beach",
        "subcategory": "land",
        "photos_count": 3,
        "is_agricultural": False,
        "is_incomplete": False,
    }
    base.update(fields)
    return base


def test_shelf_keys_are_six_master_sub_pairs():
    assert set(SHELF_KEYS) == {
        "beach_homes", "beach_condos", "beach_land",
        "lake_homes", "lake_condos", "lake_land",
    }


def test_audit_shape_for_empty_dataset():
    audit = compute_audit([])
    assert audit["total_in_dataset"] == 0
    assert audit["active_level"] == "moderate"
    assert set(audit["shelves"].keys()) == set(SHELF_KEYS)
    for shelf in audit["shelves"].values():
        assert shelf["total_in_cohort"] == 0
        assert shelf["eligible_strict"] == 0
        assert shelf["eligible_moderate"] == 0
        assert shelf["eligible_lenient"] == 0


def test_complete_beach_land_counts_in_beach_land_shelf():
    audit = compute_audit([_li()])
    assert audit["total_in_dataset"] == 1
    assert audit["shelves"]["beach_land"]["total_in_cohort"] == 1
    assert audit["shelves"]["beach_land"]["eligible_strict"] == 1
    assert audit["shelves"]["beach_land"]["eligible_moderate"] == 1
    assert audit["shelves"]["beach_land"]["eligible_lenient"] == 1
    # Other shelves untouched.
    assert audit["shelves"]["lake_homes"]["total_in_cohort"] == 0


def test_missing_area_passes_moderate_and_lenient_but_not_strict():
    """The PRD-defined moderate gate requires type+zone+price, NOT area.
    A complete-except-for-area listing is the litmus test for the slider:
    visible under moderate (PRD default), hidden under strict."""
    audit = compute_audit([_li(area_m2=None)])
    shelf = audit["shelves"]["beach_land"]
    assert shelf["eligible_strict"] == 0
    assert shelf["eligible_moderate"] == 1
    assert shelf["eligible_lenient"] == 1
    # No-photos blocker NOT triggered because area is the dominant
    # mutually-exclusive blocker under strict's priority chain.
    assert shelf["hidden_by_no_area"] == 1


def test_missing_zone_blocks_all_three_levels():
    """Without a zone, the listing cannot be assigned to any shelf —
    so even lenient hides it. The PRD calls this out as one of the three
    hard gates."""
    audit = compute_audit([_li(zone=None, master_category=None, subcategory=None)])
    assert audit["aggregate"]["eligible_strict"] == 0
    assert audit["aggregate"]["eligible_moderate"] == 0
    assert audit["aggregate"]["eligible_lenient"] == 1  # lenient drops zone requirement
    # Listing not assigned to any shelf (no master_category).
    for shelf in audit["shelves"].values():
        assert shelf["total_in_cohort"] == 0


def test_missing_property_type_blocks_all_levels():
    """property_type is required at EVERY level — even lenient. A listing
    without a type cannot be assigned to a shelf subcategory."""
    audit = compute_audit([_li(property_type=None, subcategory=None)])
    assert audit["aggregate"]["eligible_strict"] == 0
    assert audit["aggregate"]["eligible_moderate"] == 0
    assert audit["aggregate"]["eligible_lenient"] == 0
    assert audit["aggregate"]["hidden_by_no_type"] == 1


def test_missing_price_blocks_all_levels():
    """price_usd is in FLOOR_REQUIRED — no level lets a listing through
    without it. Per PRD: 'What is it? Where exactly? How much?'"""
    audit = compute_audit([_li(price_usd=None)])
    assert audit["aggregate"]["eligible_strict"] == 0
    assert audit["aggregate"]["eligible_moderate"] == 0
    assert audit["aggregate"]["eligible_lenient"] == 0
    assert audit["aggregate"]["hidden_by_no_price"] == 1


def test_no_photos_only_blocks_strict():
    """Photo gate fires only at strict. Moderate + lenient waive photos
    so the FE's shelf-aware placeholder fallback can render thin shelves."""
    audit = compute_audit([_li(photos_count=0)])
    shelf = audit["shelves"]["beach_land"]
    assert shelf["eligible_strict"] == 0
    assert shelf["eligible_moderate"] == 1
    assert shelf["eligible_lenient"] == 1
    assert shelf["hidden_by_no_photos"] == 1


def test_blockers_are_mutually_exclusive_priority_chain():
    """A listing missing both type AND zone counts only under
    hidden_by_no_type (priority: type → zone → price → area → photos →
    agricultural). This keeps the audit columns interpretable: one
    dominant blocker per hidden listing."""
    audit = compute_audit([_li(property_type=None, zone=None, price_usd=None)])
    assert audit["aggregate"]["hidden_by_no_type"] == 1
    assert audit["aggregate"]["hidden_by_no_zone"] == 0
    assert audit["aggregate"]["hidden_by_no_price"] == 0


def test_aggregate_is_sum_of_eligibility_across_dataset():
    listings = [
        _li(source_id="a"),                               # all 3 pass
        _li(source_id="b", area_m2=None),                 # strict fails
        _li(source_id="c", price_usd=None, subcategory=None),  # all 3 fail
        _li(source_id="d", photos_count=0),               # strict fails
    ]
    audit = compute_audit(listings)
    assert audit["total_in_dataset"] == 4
    assert audit["aggregate"]["eligible_strict"] == 1
    assert audit["aggregate"]["eligible_moderate"] == 3
    assert audit["aggregate"]["eligible_lenient"] == 3


def test_lake_homes_listing_routes_to_lake_homes_shelf():
    li = _li(
        master_category="lake",
        subcategory="homes",
        property_type="house",
        zone="lago-coatepeque",
    )
    audit = compute_audit([li])
    assert audit["shelves"]["lake_homes"]["total_in_cohort"] == 1
    assert audit["shelves"]["beach_land"]["total_in_cohort"] == 0


def test_agricultural_does_not_block_eligibility_but_is_reported():
    """Agricultural exclusion is enforced by consumers (use-listings,
    ig_photo_gate, HomeShelf) — NOT by the audit's eligibility predicate.
    The audit reports the count for visibility into the exclusion
    pipeline but the listing still counts as eligible at every level."""
    li = _li(is_agricultural=True)
    audit = compute_audit([li])
    # Agricultural is a separate signal — listing is still eligible at
    # all levels because it has type+zone+price+area+photos.
    assert audit["aggregate"]["eligible_moderate"] == 1
    # But the blocker chain reports the agricultural status (only when
    # nothing earlier in the priority chain blocked it).
    assert audit["aggregate"]["hidden_by_is_agricultural"] == 1


def test_write_audit_creates_json_file(tmp_path):
    web_data_dir = tmp_path / "data"
    web_data_dir.mkdir()
    audit = write_audit([_li()], web_data_dir)
    out = web_data_dir / "shelf_audit.json"
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk["total_in_dataset"] == 1
    assert on_disk["active_level"] == audit["active_level"]
    assert set(on_disk["shelves"].keys()) == set(SHELF_KEYS)


def test_levels_table_required_fields_include_floor():
    """Every level requires both price_usd and url — the immutable floor
    Sebas flagged in plan review. Even lenient cannot drop below."""
    for name, spec in LEVELS.items():
        assert "price_usd" in spec["required"], f"{name} dropped price"
        assert "url" in spec["required"], f"{name} dropped url"
        assert "property_type" in spec["required"], f"{name} dropped type"
