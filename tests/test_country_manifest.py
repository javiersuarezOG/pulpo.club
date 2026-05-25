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
