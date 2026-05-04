"""
Tests for pulpo/schema_validator.py — pins type / required / enum / format
behavior so future schema-tightening changes are visible.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pulpo.schema_validator import validate, load_schema, _is_typed   # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────

def _minimal_record(**overrides) -> dict:
    """A record that satisfies all `required` fields in v1."""
    base = {
        "source":     "goodlife",
        "source_id":  "GL-001",
        "url":        "https://example.com/listing/1",
        "title":      "Lot for sale",
        "country":    "SV",
        "scraped_at": "2026-05-04T12:00:00+00:00",
    }
    base.update(overrides)
    return base


# ── Required-field checks ──────────────────────────────────────────────

def test_minimal_record_passes():
    schema = load_schema()
    result = validate(_minimal_record(), schema)
    assert result.ok, f"unexpected errors: {result.errors}"


def test_missing_required_field_fails():
    schema = load_schema()
    record = _minimal_record()
    del record["url"]
    result = validate(record, schema)
    assert not result.ok
    assert any("url" in e for e in result.errors)


def test_empty_required_field_fails():
    schema = load_schema()
    result = validate(_minimal_record(title=""), schema)
    assert not result.ok
    assert any("title" in e for e in result.errors)


# ── Type checks ────────────────────────────────────────────────────────

def test_type_int_for_integer_field():
    schema = load_schema()
    result = validate(_minimal_record(days_listed=12), schema)
    assert result.ok, result.errors


def test_type_float_for_number_field():
    schema = load_schema()
    result = validate(_minimal_record(price_usd=185000.0), schema)
    assert result.ok, result.errors


def test_type_mismatch_string_for_number():
    schema = load_schema()
    result = validate(_minimal_record(price_usd="185000"), schema)
    assert not result.ok
    assert any("price_usd" in e for e in result.errors)


def test_null_allowed_on_nullable_field():
    schema = load_schema()
    result = validate(_minimal_record(price_usd=None), schema)
    assert result.ok, result.errors


def test_bool_check():
    assert _is_typed(True, "boolean")
    assert _is_typed(False, "boolean")
    # bool is a subclass of int — make sure we don't mistake it for one
    assert not _is_typed(True, "integer")
    assert not _is_typed(False, "number")


# ── Enum checks ────────────────────────────────────────────────────────

def test_enum_valid_value_passes():
    schema = load_schema()
    result = validate(_minimal_record(source_type="on_market"), schema)
    assert result.ok


def test_enum_invalid_value_fails():
    schema = load_schema()
    result = validate(_minimal_record(source_type="bogus"), schema)
    assert not result.ok
    assert any("source_type" in e for e in result.errors)


# ── Bounds ─────────────────────────────────────────────────────────────

def test_lat_lng_bounds():
    schema = load_schema()
    assert validate(_minimal_record(lat=13.5, lng=-89.0), schema).ok
    assert not validate(_minimal_record(lat=91.0), schema).ok
    assert not validate(_minimal_record(lng=181.0), schema).ok


# ── format=uri ─────────────────────────────────────────────────────────

def test_uri_valid():
    schema = load_schema()
    result = validate(_minimal_record(url="https://example.com/path?q=1"), schema)
    assert result.ok


def test_uri_invalid():
    schema = load_schema()
    result = validate(_minimal_record(url="not a url"), schema)
    assert not result.ok
    assert any("not a valid URI" in e for e in result.errors)


# ── format=date-time ───────────────────────────────────────────────────

def test_iso_datetime_valid():
    schema = load_schema()
    result = validate(_minimal_record(scraped_at="2026-05-04T12:00:00.123456+00:00"), schema)
    assert result.ok


def test_iso_datetime_z_suffix():
    schema = load_schema()
    result = validate(_minimal_record(scraped_at="2026-05-04T12:00:00Z"), schema)
    assert result.ok


def test_iso_datetime_invalid():
    schema = load_schema()
    result = validate(_minimal_record(scraped_at="May 4 2026 noon"), schema)
    assert not result.ok


# ── additionalProperties=true ─────────────────────────────────────────

def test_unknown_field_is_silently_accepted():
    """v1 schema is intentionally permissive — unknown fields shouldn't fail."""
    schema = load_schema()
    result = validate(_minimal_record(some_future_field="hello"), schema)
    assert result.ok


# ── Real ranked.json sample ────────────────────────────────────────────

def test_validates_a_realistic_post_normalize_record():
    """A record matching today's pipeline output — the v1 baseline contract."""
    schema = load_schema()
    record = {
        "source":            "bienesraices",
        "source_id":         "2074",
        "url":               "https://bienesraicesenelsalvador.com/propiedad/terreno-001",
        "scraped_at":        "2026-05-03T12:00:00+00:00",
        "title":             "Terreno en El Capulín",
        "description":       "Terreno plano de 5000 vrs² con agua y electricidad.",
        "country":           "SV",
        "department":        "La Libertad",
        "zone":              "el-tunco",
        "zone_confidence":   "specific",
        "location_text":     "El Capulín, Colón",
        "lat":               None,
        "lng":               None,
        "area_m2":           5000.0,
        "price_usd":         300000.0,
        "price_per_m2":      60.0,
        "property_type":     "land",
        "is_beachfront":     False,
        "is_in_development": False,
        "has_paved_access":  False,
        "has_water":         True,
        "has_power":         True,
        "is_repriced":       False,
        "photos_count":      0,
        "photo_urls":        [],
    }
    result = validate(record, schema)
    assert result.ok, f"realistic record failed: {result.errors}"
