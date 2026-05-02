"""
Regression harness for the Oceanside WP REST API scraper.

Loads the fixture at tests/fixtures/oceanside_lots.json (a verbatim snapshot
of the live /wp-json/wp/v2/rental-details?property-type=122&per_page=100
response) and asserts field-completeness baselines established on 2026-05-02.

No network calls — pure fixture load.  Runs in <1s.

To refresh the fixture after a live change:
    python3 scripts/refresh_oceanside_fixture.py

── Baseline summary ──────────────────────────────────────────────────────────
Total records from API:          27
Survived stub filter:            14  (have price OR area in content)
Successfully normalized:         13  (1 stub survives raw but has bad price)
─────────────────────────────────────────────────────────────────────────────
Phase-1 gap (area_m2 = None after normalize):
  ID 11079 "The Cliff" — case (c): broker publishes only "$5,000 deposit";
  no per-lot area.  $5 000 is the minimum threshold; listing is kept by
  normalize() because price_usd=5000.0 ≠ None.  area_m2 stays None.

Phase-3 zone note:
  class_list location-* slugs are DEPARTMENT-level (la-libertad, san-miguel,
  sonsonate), not zone-level.  Migrating zone detection to class_list primary
  would downgrade 24 listings from specific zones (el-tunco, el-zonte) to the
  generic 'la-libertad' department slug.
  Current implementation already passes class_list → location_text → detect_zone
  which correctly resolves the specific zone from title/content — no migration.
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

REPO    = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "oceanside_lots.json"

# ── Baselines (lock in on 2026-05-02) ─────────────────────────────────────────
TOTAL_FROM_API         = 27
N_SURVIVED_STUB        = 14   # records with at least price or area in content
N_NORMALIZED           = 13   # records that pass normalize()

# Field completeness fractions — (min_count, total, min_pct)
# min_pct is floor to 1 below measured so CI fails only on regression
COMPLETENESS_FLOOR = {
    "price_usd":       (8,  N_NORMALIZED),  # 69% → floor 61%
    "area_m2":         (11, N_NORMALIZED),  # 92% → floor 84%
    "zone":            (13, N_NORMALIZED),  # 100%
    "municipality":    (13, N_NORMALIZED),  # 100%
    "department":      (13, N_NORMALIZED),  # 100%
    "photos_count":    (13, N_NORMALIZED),  # 100%
    "days_listed":     (13, N_NORMALIZED),  # 100%
    "is_beachfront":   (3,  N_NORMALIZED),  # 31% → floor 23%
    "has_power":       (3,  N_NORMALIZED),  # 31% → floor 23%
}

# Snapshots for 3 stable listings (by source_id = str(WP ID))
# Format: source_id → {field: expected_value}
SNAPSHOTS: dict[str, dict] = {
    "13544": {
        "zone": "el-tunco",
        "area_m2": 859.1,
        "price_usd": 196742.0,
        "is_beachfront": False,
        "department": "La Libertad",
    },
    "12809": {
        "zone": "las-flores",
        "area_m2": 11760.0,
        "price_usd": 299000.0,
        "is_beachfront": True,
        "department": "La Unión",
    },
    "12706": {
        "zone": "la-libertad",
        "area_m2": 1012.8,
        "price_usd": 120000.0,
        "is_beachfront": False,
        "department": "La Libertad",
    },
}


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def raw_records() -> list[dict]:
    if not FIXTURE.exists():
        pytest.skip(f"Fixture not found: {FIXTURE}. Run scripts/refresh_oceanside_fixture.py")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def normalized_listings(raw_records):
    """Run _map + normalize on all fixture records; return surviving Listing objects."""
    import sys
    sys.path.insert(0, str(REPO))
    from pulpo.scrapers.oceanside import _map
    from pulpo.normalize import normalize

    LAND_ID = 122
    out = []
    for rec in raw_records:
        mapped = _map(rec, LAND_ID)
        if mapped is None:
            continue
        mapped["source"] = "oceanside"
        li = normalize(mapped, source="oceanside")
        if li:
            out.append(li)
    return out


# ── Tests ─────────────────────────────────────────────────────────────────────
def test_fixture_total_records(raw_records):
    assert len(raw_records) == TOTAL_FROM_API, (
        f"API returned {len(raw_records)} records; expected {TOTAL_FROM_API}. "
        "Refresh fixture if the live count changed."
    )


def test_stub_filter_count(raw_records):
    """Records that have at least price or area (survive normalize's hard gate)."""
    import sys; sys.path.insert(0, str(REPO))
    from pulpo.scrapers.oceanside import _map

    LAND_ID = 122
    survived = 0
    for rec in raw_records:
        mapped = _map(rec, LAND_ID)
        if mapped and (mapped["raw_price_text"] or mapped["raw_size_text"]):
            survived += 1
    assert survived == N_SURVIVED_STUB, (
        f"Stub filter let through {survived}; expected {N_SURVIVED_STUB}"
    )


def test_normalized_count(normalized_listings):
    assert len(normalized_listings) == N_NORMALIZED, (
        f"normalize() produced {len(normalized_listings)} listings; "
        f"expected {N_NORMALIZED}."
    )


def test_all_normalized_have_source_id(normalized_listings):
    for li in normalized_listings:
        assert li.source_id, f"Missing source_id on {li.title!r}"


def test_all_normalized_have_url(normalized_listings):
    for li in normalized_listings:
        assert li.url.startswith("https://oceansideelsalvador.com/"), (
            f"Bad URL on {li.source_id}: {li.url!r}"
        )


@pytest.mark.parametrize("field,min_count,total", [
    (f, mn, t) for f, (mn, t) in COMPLETENESS_FLOOR.items()
])
def test_field_completeness_floor(field, min_count, total, normalized_listings):
    """Each tracked field must meet or exceed its floor count."""
    BOOL_FIELDS = {"is_beachfront", "has_paved_access", "has_water", "has_power", "is_repriced"}
    if field in BOOL_FIELDS:
        count = sum(1 for li in normalized_listings if getattr(li, field, False) is True)
    else:
        count = sum(
            1 for li in normalized_listings
            if getattr(li, field, None) not in (None, "", 0)
        )
    assert count >= min_count, (
        f"{field}: {count}/{total} populated; floor is {min_count}/{total}"
    )


@pytest.mark.parametrize("source_id,expected", list(SNAPSHOTS.items()))
def test_snapshot_listings(source_id, expected, normalized_listings):
    """Exact-match snapshot for 3 stable listings."""
    listing = next(
        (li for li in normalized_listings if li.source_id == source_id), None
    )
    assert listing is not None, (
        f"Snapshot listing id={source_id} not found in normalized output. "
        "Was it deleted from the live site?"
    )
    for field, value in expected.items():
        actual = getattr(listing, field)
        if isinstance(value, float):
            assert abs((actual or 0) - value) < 1.0, (
                f"id={source_id} {field}: {actual} ≠ {value}"
            )
        else:
            assert actual == value, f"id={source_id} {field}: {actual!r} ≠ {value!r}"


def test_phase1_gap_listing_zone(normalized_listings):
    """ID 11079 (The Cliff) — case (c) gap: area_m2=None, zone kept from content."""
    cliff = next(
        (li for li in normalized_listings if li.source_id == "11079"), None
    )
    assert cliff is not None, "ID 11079 was dropped entirely — expected to survive on price"
    assert cliff.area_m2 is None, "ID 11079 should still have area_m2=None (case c)"
    assert cliff.zone is not None, "ID 11079 should have a zone from title/content"
