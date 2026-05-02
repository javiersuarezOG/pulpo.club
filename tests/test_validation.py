"""
Tests for the validation layer (automation/validation.py).

Covers country exclusion, zone extraction, numeric bounds,
cross-attribute checks, and the validation log structure.
Each Phase 7 case from the spec is represented here, using real
production listing data as fixtures where noted.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.validation import validate, ValidationResult  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────

def _listing(**kwargs) -> dict:
    """Minimal valid listing dict for validation testing."""
    base = {
        "source": "bienesraices",
        "source_id": "test-001",
        "url": "https://bienesraicesenelsalvador.com/propiedad/terreno-el-tunco-123",
        "title": "Terreno en venta El Tunco, La Libertad, El Salvador",
        "description": "",
        "zone": "el-tunco",
        "price_usd": 80_000.0,
        "area_m2": 400.0,
        "price_per_m2": 200.0,
        "days_listed": 30,
        "photos_count": 5,
        "is_beachfront": False,
    }
    base.update(kwargs)
    return base


# ── Phase 7.1 — Country filter: real Guatemala URL is DROPPED ─────────

def test_country_url_guatemala_dropped():
    """Real production URL from bienesraicesenelsalvador.com listing Guatemala."""
    li = _listing(
        url=(
            "https://bienesraicesenelsalvador.com/propiedad/"
            "fincas-en-venta-en-guatemala-5916-mz-inversion-multiple-usos"
        ),
        title="Fincas en Venta en Guatemala 5916 Mz Inversión Múltiples Usos",
        zone=None,
        price_usd=18_800_000.0,
        area_m2=41_566_396.0,
        price_per_m2=0.45,
    )
    result = validate(li)
    assert result.disposition == "DROP", f"Expected DROP, got {result.disposition}: {result.reasons}"
    assert any("country_exclusion" in r for r in result.reasons)


# ── Phase 7.2 — Country filter false-positive prevention ─────────────

def test_country_title_comparative_not_dropped():
    """'Guatemala' in a comparative context must NOT trigger the country filter."""
    li = _listing(
        title="Land in El Salvador, similar quality to Guatemala fincas",
        zone="el-tunco",
        price_usd=150_000.0,
        area_m2=1_000.0,
        price_per_m2=150.0,
    )
    result = validate(li)
    # Country check must not fire — Guatemala here is comparative, not locational
    country_drops = [r for r in result.reasons if "country_exclusion" in r]
    assert not country_drops, f"False-positive country drop: {country_drops}"


# ── Phase 7.3 — Zone extraction from structured title ─────────────────

def test_jiquilisco_structured_title_zone():
    """'Jiquilisco, Usulután, El Salvador' in title → zone='jiquilisco'."""
    from pulpo.normalize import normalize

    raw = {
        "source_id": "jiq-001",
        "url": "https://example.com/jiquilisco",
        "title": "Land for Sale – Jiquilisco, Usulután, El Salvador",
        "description": "Large coastal parcel near Bahía de Jiquilisco.",
        "location_text": "Jiquilisco, Usulután",
        "price_usd": 250_000.0,
        "area_m2": 10_000.0,
        "raw_price_text": "$250,000",
        "raw_size_text": "10000 m2",
        "property_type": "land",
    }
    li = normalize(raw, source="bienesraices")
    assert li is not None
    assert li.zone == "jiquilisco", f"Expected zone='jiquilisco', got {li.zone!r}"
    assert li.department == "Usulután", f"Expected dept='Usulután', got {li.department!r}"


# ── Phase 7.4 — Country filter is the reliable guard for out-of-country listings

def test_el_zonte_description_guard():
    """Guatemala listing mentioning 'El Zonte' is DROPPED by the country filter.

    Zone detection may or may not pick up 'El Zonte' from the description —
    the important guarantee is that validate() drops Guatemala listings before
    they reach ranked.json, regardless of what zone was detected.
    """
    from pulpo.normalize import normalize

    raw = {
        "source_id": "guard-001",
        "url": "https://bienesraicesenelsalvador.com/propiedad/finca-en-guatemala-gran-oportunidad",
        "title": "Finca en Guatemala — gran oportunidad de inversión",
        "description": (
            "Great investment opportunity similar to beach areas like El Zonte "
            "in El Salvador, but located in Guatemala."
        ),
        "location_text": "Guatemala",
        "price_usd": 5_000_000.0,
        "area_m2": 35_000_000.0,
        "raw_price_text": "$5,000,000",
        "raw_size_text": "35000000 m2",
        "property_type": "land",
    }
    li = normalize(raw, source="bienesraices")
    # The guarantee: even if zone detection fires on "El Zonte" in the description,
    # the country filter in validate() catches and drops the Guatemala listing.
    if li is not None:
        result = validate(li.to_dict())
        assert result.disposition == "DROP", (
            f"Guatemala listing must be DROPPED. Got {result.disposition}: {result.reasons}"
        )
        assert any("country_exclusion" in r for r in result.reasons)


# ── Phase 7.5 — Bounds: price_usd DROP and FLAG ───────────────────────

def test_price_drop_below_minimum():
    """price_usd < $1000 is DROPPED."""
    li = _listing(price_usd=500.0, price_per_m2=1.25, area_m2=400.0)
    result = validate(li)
    assert result.disposition == "DROP"
    assert any("price_usd" in r for r in result.reasons)


def test_price_flag_suspicious_low():
    """price_usd = $3000 is suspicious (< $5k flag threshold) — FLAGGED."""
    li = _listing(price_usd=3_000.0, price_per_m2=7.5, area_m2=400.0)
    result = validate(li)
    assert result.disposition == "FLAG"
    assert any("price_usd" in r for r in result.reasons)


def test_price_pass_normal():
    """Normal price passes."""
    li = _listing(price_usd=80_000.0)
    result = validate(li)
    assert result.disposition == "PASS"


# ── Phase 7.6 — Cross-attribute: $/m² inconsistency FLAGGED ──────────

def test_ppm_inconsistency_flagged():
    """Stored $/m²=15 but actual (10000/1000)=10 — diverges >10%, FLAG."""
    li = _listing(
        price_usd=10_000.0,
        area_m2=1_000.0,
        price_per_m2=15.0,   # should be 10.0
    )
    result = validate(li)
    assert result.disposition == "FLAG"
    assert any("ppm_inconsistency" in r for r in result.reasons)


def test_ppm_consistency_passes():
    """Correct $/m² = price/area passes the consistency check."""
    li = _listing(price_usd=100_000.0, area_m2=1_000.0, price_per_m2=100.0)
    result = validate(li)
    # No ppm_inconsistency reason
    assert not any("ppm_inconsistency" in r for r in result.reasons)


# ── Phase 7.7 — Manzana unit suspicion ───────────────────────────────

def test_manzana_unit_suspicion_flagged():
    """Title says '5 manzanas' (≈35k m²) but area_m2=2000 — FLAG."""
    li = _listing(
        title="Terreno 5 manzanas en La Libertad",
        area_m2=2_000.0,
        price_per_m2=40.0,
        price_usd=80_000.0,
    )
    result = validate(li)
    assert result.disposition == "FLAG"
    assert any("unit_suspicion" in r for r in result.reasons)


# ── Phase 7.8 — Guatemala $0/m² synthetic case is DROPPED ────────────

def test_zero_ppm_from_large_area_dropped():
    """Guatemala listing: $18.8M ÷ 41.5M m² = $0.45/m² — below DROP threshold."""
    li = _listing(
        url=(
            "https://bienesraicesenelsalvador.com/propiedad/"
            "fincas-en-venta-en-guatemala-5916-mz-inversion-multiple-usos"
        ),
        title="Fincas en Venta en Guatemala",
        zone=None,
        price_usd=18_800_000.0,
        area_m2=41_566_396.0,
        price_per_m2=0.45,   # rounds to $0 displayed; below PPM_DROP_MIN=0.5
    )
    result = validate(li)
    assert result.disposition == "DROP"
    # At least one of: country exclusion or ppm bound violation
    assert any(
        "country_exclusion" in r or "price_per_m2" in r
        for r in result.reasons
    ), f"Expected country or ppm drop reason, got: {result.reasons}"


# ── Phase 7.9 — Validation log structure ─────────────────────────────

def test_validation_log_structure(tmp_path):
    """validate() returns a ValidationResult with required fields."""
    li = _listing()
    result = validate(li)
    assert isinstance(result, ValidationResult)
    assert result.disposition in ("PASS", "FLAG", "DROP")
    assert isinstance(result.reasons, list)
    # All reasons are non-empty strings
    for r in result.reasons:
        assert isinstance(r, str) and r


# ── Additional edge cases ─────────────────────────────────────────────

def test_clean_listing_passes():
    """A well-formed listing with all fields in range gets PASS."""
    li = _listing(
        price_usd=120_000.0,
        area_m2=600.0,
        price_per_m2=200.0,
        days_listed=45,
        photos_count=8,
        zone="el-tunco",
    )
    result = validate(li)
    assert result.disposition == "PASS", f"Unexpected: {result.reasons}"


def test_stale_no_photos_flagged():
    """Listing older than 730 days with 0 photos is FLAGGED."""
    li = _listing(days_listed=800, photos_count=0)
    result = validate(li)
    assert result.disposition == "FLAG"
    assert any("stale_no_photos" in r for r in result.reasons)


def test_zone_unresolved_flagged():
    """Missing zone field is FLAGGED (not dropped — zone miss should be visible)."""
    li = _listing(zone=None)
    result = validate(li)
    assert result.disposition == "FLAG"
    assert any("zone_unresolved" in r for r in result.reasons)


def test_drop_beats_flag():
    """When a listing triggers both DROP and FLAG rules, disposition is DROP."""
    li = _listing(
        url="https://example.com/finca-en-venta-en-guatemala-massive",
        title="Finca en venta en Guatemala",    # → DROP country
        price_usd=3_000.0,                      # → FLAG price
        price_per_m2=7.5,
        area_m2=400.0,
    )
    result = validate(li)
    assert result.disposition == "DROP"
    assert len(result.reasons) >= 2


@pytest.mark.parametrize("country_url,slug", [
    ("https://bienesraicesenelsalvador.com/propiedad/en-honduras-land", "honduras"),
    ("https://example.com/propiedad/costa-rica-beach-lot",              "costa-rica"),
    ("https://example.com/nicaragua-finca-grande",                      "nicaragua"),
])
def test_various_country_urls_dropped(country_url, slug):
    li = _listing(url=country_url, zone=None)
    result = validate(li)
    assert result.disposition == "DROP", f"Expected DROP for {slug}, got {result.disposition}"
