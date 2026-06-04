"""Tests for automation.kpi_dashboard — KPI dashboard emission.

The dashboard is the single source of truth for the four PRD sign-off
KPIs (total visible, per-category, active sources, % coverage). PR A1
ships the baseline snapshot; PR D3 produces the after-snapshot and a
before/after Markdown table.
"""
from __future__ import annotations

import json

from automation.kpi_dashboard import (
    MIN_REAL_LISTINGS,
    PRD_TARGETS,
    compute_kpi,
    write,
)


def _li(**fields):
    base = {
        "source": "encuentra24",
        "source_id": "x",
        "url": "https://example.test/x",
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


def test_visible_count_excludes_incomplete_and_agricultural():
    listings = [
        _li(source_id="visible"),
        _li(source_id="incomplete", is_incomplete=True),
        _li(source_id="agricultural", is_agricultural=True),
    ]
    payload = compute_kpi(listings, registered_sources=["encuentra24"])
    assert payload["kpi"]["total_visible_listings"] == 1
    assert payload["kpi"]["total_in_dataset"] == 3


def test_per_shelf_counts_route_correctly():
    listings = [
        _li(source_id="a", master_category="beach", subcategory="land"),
        _li(source_id="b", master_category="beach", subcategory="land"),
        _li(source_id="c", master_category="lake",  subcategory="homes",
            property_type="house", zone="lago-coatepeque"),
    ]
    payload = compute_kpi(listings, registered_sources=["encuentra24"])
    per_shelf = payload["kpi"]["per_shelf_visible"]
    assert per_shelf["beach_land"]["count"] == 2
    assert per_shelf["lake_homes"]["count"] == 1
    assert per_shelf["beach_homes"]["count"] == 0


def test_renders_on_homepage_flag_uses_min_real_listings():
    listings = [_li(source_id=str(i)) for i in range(MIN_REAL_LISTINGS)]
    payload = compute_kpi(listings, registered_sources=["encuentra24"])
    assert payload["kpi"]["per_shelf_visible"]["beach_land"]["renders_on_homepage"] is True
    # One fewer than threshold — no render.
    payload2 = compute_kpi(listings[:-1], registered_sources=["encuentra24"])
    assert payload2["kpi"]["per_shelf_visible"]["beach_land"]["renders_on_homepage"] is False


def test_active_sources_counts_only_contributors():
    listings = [
        _li(source="encuentra24"),
        _li(source="remax"),
    ]
    payload = compute_kpi(
        listings,
        registered_sources=["encuentra24", "remax", "citymax"],
    )
    assert payload["kpi"]["active_sources"] == 2
    assert payload["kpi"]["registered_sources"] == 3


def test_per_source_coverage_uses_discovered_target_when_available():
    listings = [_li(source="encuentra24") for _ in range(50)]
    coverage = {"encuentra24": {"target_discovered": 100}}
    payload = compute_kpi(
        listings,
        coverage=coverage,
        registered_sources=["encuentra24"],
    )
    per_source = payload["kpi"]["per_source_coverage"]["encuentra24"]
    assert per_source["kept"] == 50
    assert per_source["target_discovered"] == 100
    assert per_source["coverage_pct_vs_discovered"] == 50.0


def test_per_source_coverage_falls_back_to_prd_target():
    """When no discovered target yet (coverage_logger empty), the PRD-stated
    count from PRD_TARGETS is used as the denominator. Encuentra24's PRD
    target is 2947."""
    listings = [_li(source="encuentra24") for _ in range(295)]
    payload = compute_kpi(listings, registered_sources=["encuentra24"])
    per_source = payload["kpi"]["per_source_coverage"]["encuentra24"]
    assert per_source["target_prd"] == 2947
    assert per_source["target_discovered"] is None
    # 295 / 2947 * 100 ≈ 10.0
    assert per_source["coverage_pct_vs_discovered"] == 10.0


def test_per_source_coverage_is_none_when_no_target_available():
    """A source without PRD target AND without discovered target gets
    a null coverage percentage — explicit signal that we don't know
    what 'full coverage' means."""
    listings = [_li(source="remax")]
    payload = compute_kpi(listings, registered_sources=["remax"])
    per_source = payload["kpi"]["per_source_coverage"]["remax"]
    assert per_source["target_prd"] is None
    assert per_source["coverage_pct_vs_discovered"] is None


def test_shelves_rendering_tally():
    """6 shelves total; each renders iff visible count >= MIN_REAL_LISTINGS."""
    listings = []
    for shelf in ("beach", "lake"):
        for sub, pt in (("land", "land"), ("homes", "house")):
            for i in range(MIN_REAL_LISTINGS):
                listings.append(_li(
                    source_id=f"{shelf}_{sub}_{i}",
                    master_category=shelf,
                    subcategory=sub,
                    property_type=pt,
                    zone="el-zonte" if shelf == "beach" else "lago-coatepeque",
                ))
    payload = compute_kpi(listings, registered_sources=["encuentra24"])
    assert payload["kpi"]["shelves_rendering"] == 4  # 2 shelves × 2 subs filled
    assert payload["kpi"]["shelves_total"] == 6


def test_write_creates_json_file(tmp_path):
    write(
        [_li()],
        tmp_path,
        registered_sources=["encuentra24"],
    )
    out = tmp_path / "kpi_dashboard.json"
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk["kpi"]["total_visible_listings"] == 1


def test_prd_targets_include_new_phase_c_sources():
    """The PRD-stated counts for new scrapers must be discoverable here
    so the coverage gauge has a denominator from day 1. C* PR coverage
    checks rely on this table."""
    for slug in (
        "santizo", "citymax_sc", "vivolatam", "csbr",
        "realtor_intl_sv", "jamesedition",
    ):
        assert slug in PRD_TARGETS, f"missing PRD target for {slug}"


def test_compute_kpi_with_empty_inputs_is_safe():
    payload = compute_kpi([], registered_sources=[])
    assert payload["kpi"]["total_visible_listings"] == 0
    assert payload["kpi"]["total_in_dataset"] == 0
    assert payload["kpi"]["active_sources"] == 0
    assert payload["kpi"]["registered_sources"] == 0
    assert payload["kpi"]["shelves_rendering"] == 0
    assert payload["kpi"]["shelves_total"] == 6
