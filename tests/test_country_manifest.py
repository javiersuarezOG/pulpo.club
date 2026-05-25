"""PR-MC-1a — country manifest contract tests.

These tests enforce the two invariants that PR-MC-1a establishes:

  1. Every registered Source declares a ``country`` attribute, and that
     attribute matches a country manifest discoverable in
     ``pulpo/countries/``. CI fails if a contributor adds a scraper
     without declaring `country`, or declares one for a country with no
     manifest.

  2. ``pulpo.countries.active()`` returns SV by default and honors the
     ``PULPO_ACTIVE_COUNTRY`` env var when set. Required-field validation
     is enforced via ``CountryManifest.from_dict``.

PR-MC-1b will extend these tests to cover the zone-slug regex
(``^[a-z]{2}-[a-z0-9-]+$``) and the per-country reference-data moves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import pulpo.scrapers  # noqa: F401 — import side effect populates SOURCES
from pulpo.agents import SOURCES
from pulpo.countries import CountryManifest, active, load, loaded


# ── Manifest discovery ───────────────────────────────────────────────


def test_sv_manifest_loads():
    sv = load("SV")
    assert sv.code == "SV"
    assert sv.name_en == "El Salvador"
    assert sv.name_es == "El Salvador"
    assert sv.locale_es == "es-SV"
    assert sv.locale_en == "en-US"
    assert sv.currency == "USD"


def test_load_is_case_insensitive():
    upper = load("SV")
    lower = load("sv")
    assert upper.code == lower.code == "SV"


def test_load_missing_country_raises():
    with pytest.raises(FileNotFoundError):
        load("ZZ")


def test_loaded_returns_every_manifest_sorted():
    manifests = loaded()
    # At least SV is present.
    codes = [m.code for m in manifests]
    assert "SV" in codes
    # Sorted ascending so the order is deterministic across platforms.
    assert codes == sorted(codes)


def test_active_defaults_to_sv(monkeypatch):
    monkeypatch.delenv("PULPO_ACTIVE_COUNTRY", raising=False)
    assert active().code == "SV"


def test_active_reads_env(monkeypatch):
    monkeypatch.setenv("PULPO_ACTIVE_COUNTRY", "SV")
    assert active().code == "SV"


def test_active_missing_country_raises(monkeypatch):
    monkeypatch.setenv("PULPO_ACTIVE_COUNTRY", "ZZ")
    with pytest.raises(FileNotFoundError):
        active()


# ── from_dict validation ─────────────────────────────────────────────


def _valid_payload() -> dict:
    return {
        "code": "SV",
        "name_en": "El Salvador",
        "name_es": "El Salvador",
        "locale_es": "es-SV",
        "locale_en": "en-US",
        "currency": "USD",
        "centroid_lat": 13.7942,
        "centroid_lng": -88.8965,
    }


def test_from_dict_rejects_missing_required_fields():
    for missing in (
        "code", "name_en", "name_es", "locale_es",
        "locale_en", "currency", "centroid_lat", "centroid_lng",
    ):
        payload = _valid_payload()
        del payload[missing]
        with pytest.raises(ValueError) as exc:
            CountryManifest.from_dict(payload)
        assert missing in str(exc.value), (
            f"Error message should name the missing field {missing!r}; "
            f"got {exc.value!s}"
        )


def test_from_dict_rejects_bad_country_code():
    for bad in ("S", "SVA", "12", "Salvador", ""):
        payload = _valid_payload()
        payload["code"] = bad
        with pytest.raises(ValueError):
            CountryManifest.from_dict(payload)


def test_from_dict_normalizes_code_to_uppercase():
    payload = _valid_payload()
    payload["code"] = "sv"
    assert CountryManifest.from_dict(payload).code == "SV"


# ── Source contract ──────────────────────────────────────────────────


def test_every_source_declares_country():
    """Every registered Source must set a `country` class attribute.

    Without this attribute the multi-country orchestrator (PR-MC-3+)
    can't scope a nightly to one country. Failing CI here forces every
    new scraper to declare its country at registration time.
    """
    missing = [slug for slug, src in SOURCES.items()
               if not getattr(src, "country", None)]
    assert not missing, (
        f"Scrapers missing `country` class attribute: {missing!r}. "
        f"Add `country = \"<CC>\"` to the scraper class."
    )


def test_every_source_country_has_a_manifest():
    """Each Source's `country` must match a manifest file. Prevents a
    silent typo (e.g. country='SA' instead of 'SV') from quietly
    breaking ranking + enrichment for an entire source.
    """
    known = {m.code for m in loaded()}
    bad = {slug: src.country for slug, src in SOURCES.items()
           if src.country not in known}
    assert not bad, (
        f"Scrapers point at a country with no manifest in "
        f"pulpo/countries/: {bad!r}. Known: {known!r}."
    )


def test_every_source_country_matches_alpha2_format():
    """`country` must be a two-letter uppercase ISO-3166-1 alpha-2."""
    bad = {slug: src.country for slug, src in SOURCES.items()
           if not (isinstance(src.country, str)
                   and len(src.country) == 2
                   and src.country.isalpha()
                   and src.country.isupper())}
    assert not bad, (
        f"Scrapers with malformed `country` (must be uppercase alpha-2): "
        f"{bad!r}"
    )


# ── JSON well-formedness ─────────────────────────────────────────────


def test_every_manifest_json_is_loadable():
    """Catches malformed JSON before it reaches CountryManifest.from_dict.

    A JSON syntax error here is a much more confusing failure mode than
    a structured ValueError; this test surfaces it explicitly so a bad
    edit fails CI with a clear "JSON broken at line N" message rather
    than a downstream KeyError on `code`.
    """
    manifest_dir = Path(__file__).resolve().parent.parent / "pulpo" / "countries"
    for p in sorted(manifest_dir.glob("*.json")):
        with p.open("r", encoding="utf-8") as f:
            try:
                json.load(f)
            except json.JSONDecodeError as e:
                pytest.fail(f"{p.name}: invalid JSON: {e}")


# ── PR-MC-1b — SV reference data parity ─────────────────────────────
#
# The SV manifest now mirrors the hardcoded reference constants in
# pulpo/normalize.py, pulpo/ranker_legs/location.py,
# automation/property_types.py, automation/distance_fields.py,
# pulpo/airports.py, and automation/validation_bounds.py. The parity
# tests below assert byte-for-byte equality between the manifest read
# and the existing constants so that any future drift fails CI loudly.
#
# PR-MC-1c will switch each module to read from the manifest as the
# primary source and these parity tests will collapse to simple
# "manifest is non-empty" smoke tests.


def test_sv_departments_match_normalize():
    """SV manifest's departments map must equal pulpo.normalize._DEPT_CANONICAL."""
    from pulpo.normalize import _DEPT_CANONICAL
    sv = load("SV")
    assert sv.departments() == _DEPT_CANONICAL


def test_sv_zone_tier_matches_location_leg():
    """SV manifest's zone_tier must equal pulpo.ranker_legs.location.ZONE_TIER."""
    from pulpo.ranker_legs.location import ZONE_TIER
    sv = load("SV")
    assert sv.zone_tier() == ZONE_TIER


def test_sv_vacation_zones_match_property_types():
    """SV manifest's vacation_zones must equal automation.property_types.VACATION_ZONES."""
    from automation.property_types import VACATION_ZONES
    sv = load("SV")
    assert sv.vacation_zones() == VACATION_ZONES


def test_sv_coastal_zones_match_validation_bounds():
    """SV manifest's coastal_zones must equal automation.validation_bounds.COASTAL_ZONES."""
    from automation.validation_bounds import COASTAL_ZONES
    sv = load("SV")
    assert sv.coastal_zones() == COASTAL_ZONES


def test_sv_named_beaches_match_distance_fields():
    """SV manifest's named_beaches must equal automation.distance_fields.NAMED_BEACHES."""
    from automation.distance_fields import NAMED_BEACHES
    sv = load("SV")
    assert sv.named_beaches() == NAMED_BEACHES


def test_sv_airports_lat_lng_matches_distance_fields():
    """SV manifest's airports must carry the same lat/lng as
    automation.distance_fields.AIRPORTS_LAT_LNG.
    """
    from automation.distance_fields import AIRPORTS_LAT_LNG
    sv = load("SV")
    manifest = sv.airports()
    assert set(manifest.keys()) == set(AIRPORTS_LAT_LNG.keys())
    for code, (lat, lng) in AIRPORTS_LAT_LNG.items():
        assert manifest[code]["lat"] == lat, (
            f"airport {code} lat mismatch: manifest {manifest[code]['lat']} "
            f"vs distance_fields {lat}"
        )
        assert manifest[code]["lng"] == lng, (
            f"airport {code} lng mismatch: manifest {manifest[code]['lng']} "
            f"vs distance_fields {lng}"
        )


def test_sv_airport_distances_km_matches_airports_module():
    """SV manifest's airport_distances_km must equal
    pulpo.airports.ZONE_AIRPORT_DISTANCES_KM.
    """
    from pulpo.airports import ZONE_AIRPORT_DISTANCES_KM
    sv = load("SV")
    assert sv.airport_distances_km() == ZONE_AIRPORT_DISTANCES_KM


def test_sv_validation_bounds_match_validation_module():
    """SV manifest's validation_bounds must equal
    automation.validation_bounds.BOUNDS_BY_TYPE (with tuple-vs-list
    equality already normalized inside the manifest accessor).
    """
    from automation.validation_bounds import BOUNDS_BY_TYPE
    sv = load("SV")
    manifest = sv.validation_bounds()
    assert set(manifest.keys()) == set(BOUNDS_BY_TYPE.keys())
    for ptype, fields in BOUNDS_BY_TYPE.items():
        assert set(manifest[ptype].keys()) == set(fields.keys()), (
            f"validation_bounds[{ptype}] field set mismatch: "
            f"manifest {sorted(manifest[ptype].keys())} vs "
            f"validation_bounds {sorted(fields.keys())}"
        )
        for field_name, expected in fields.items():
            actual = manifest[ptype][field_name]
            assert tuple(float(x) for x in actual) == tuple(float(x) for x in expected), (
                f"validation_bounds[{ptype}][{field_name}] mismatch: "
                f"manifest {actual} vs validation_bounds {expected}"
            )


# ── Defensive defaults on a partial manifest ─────────────────────────


def _minimal_payload() -> dict:
    return {
        "code": "ZZ",
        "name_en": "Test",
        "name_es": "Test",
        "locale_es": "es-ZZ",
        "locale_en": "en-US",
        "currency": "USD",
        "centroid_lat": 0.0,
        "centroid_lng": 0.0,
    }


def test_accessors_default_safely_on_partial_manifest():
    """A new-country manifest with only required fields must not crash
    on accessor calls — every typed accessor returns an empty container.
    """
    m = CountryManifest.from_dict(_minimal_payload())
    assert m.departments() == {}
    assert m.zone_tier() == {}
    assert m.vacation_zones() == frozenset()
    assert m.coastal_zones() == frozenset()
    assert m.airports() == {}
    assert m.airport_distances_km() == {}
    assert m.named_beaches() == ()
    assert m.validation_bounds() == {}
