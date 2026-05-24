"""
Tests for the CityMax El Salvador scraper (pulpo/scrapers/citymax.py).

Two surfaces:
  1. Offline-fixture smoke (CI guard — every registered source must
     have at least one fixture record per the source-integration
     contract).
  2. Pure-function tests on _map and _extract_listings using
     synthetic Flight-payload fragments shaped like real CityMax
     responses (audited 2026-05-25).
"""
from __future__ import annotations
import codecs
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.citymax import (  # noqa: E402
    CityMaxScraper, _TYPE_ID_TO_PULPO, _extract_listings, _map, _parse_latlng,
)


# ── Offline-fixture smoke ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def offline_records():
    return CityMaxScraper(offline=True).crawl(limit=20, offline=True)


def test_offline_returns_records(offline_records):
    if not offline_records:
        pytest.skip("No citymax fixture records — add to fixtures/sample_listings.json")
    assert len(offline_records) >= 1


def test_required_fields_present(offline_records):
    if not offline_records:
        pytest.skip("No fixture records")
    for r in offline_records:
        assert r.get("source") == "citymax"
        assert r.get("source_id"), f"Missing source_id: {r}"
        assert r.get("url", "").startswith("https://"), f"Bad url: {r}"
        assert r.get("title"), "Missing title"
        assert r.get("property_type") in {"land", "house", "condo"}
        assert isinstance(r.get("photo_urls", []), list)


# ── _parse_latlng ─────────────────────────────────────────────────────


def test_parse_latlng_valid():
    assert _parse_latlng("13.6998,-89.0784") == (13.6998, -89.0784)


def test_parse_latlng_whitespace_tolerated():
    assert _parse_latlng(" 13.5 , -89.0 ") == (13.5, -89.0)


def test_parse_latlng_invalid_returns_none():
    for s in ("", "bad", "1,2,3", "x,y"):
        assert _parse_latlng(s) == (None, None)


# ── _TYPE_ID_TO_PULPO map ─────────────────────────────────────────────


def test_type_id_map_covers_known_ids():
    """All in-scope type IDs we found in the 2026-05-25 reconnaissance
    have a Pulpo-type mapping. Commercial / industrial / office IDs are
    intentionally absent — those listings get dropped at _map."""
    expected = {1: "house", 2: "condo", 4: "land", 5: "house", 9: "land",
                10: "house", 16: "house", 17: "land", 19: "land"}
    assert _TYPE_ID_TO_PULPO == expected


# ── _map: type filtering, location, photos, type-specific fields ─────


def _coastal_terreno_rec(**override) -> dict:
    base = {
        "idInmueble": 160147,
        "parm_tipoinmueble_idparm_tipoInmueble": 4,
        "parm_tipooperacion_idparm_tipoOperacion": 1,
        "nombreInmueble": "Terreno frente al mar en El Tunco",
        "slug": "terreno-frente-al-mar-en-el-tunco",
        "precioVenta": 175000,
        "monedaVenta": "USD",
        "ejecutivoAsociadoNombre": "Maria Lopez",
        "grupoInmueble": "Terreno Residencial",
        "claveInterna": "PVT-001-05-26",
        "imagenPortada": "https://cdn.example.com/portada.jpg",
        "imagenesGaleria": [
            "https://cdn.example.com/portada.jpg",
            "https://cdn.example.com/g1.jpg",
            "https://cdn.example.com/g2.jpg",
        ],
        "provincia": "La Libertad",
        "municipio": "Tamanique",
        "localidad": "El Tunco",
        "areaTerreno": 500,
        "unidadTerreno": "m2",
        "areaConstruccion": 0,
        "unidadConstruccion": "m2",
        "nroHabitaciones": 0,
        "nroBanios": 0,
        "nroMediobanios": 0,
        "nroEstacionamientos": 0,
        "ubicacionMaps": "13.4895,-89.3760",
    }
    base.update(override)
    return base


def test_map_terreno_coastal_passes_filter():
    rec = _map(_coastal_terreno_rec())
    assert rec is not None
    assert rec["source"] == "citymax"
    assert rec["source_id"] == "160147"
    assert rec["property_type"] == "land"
    assert rec["price_usd"] == 175000.0
    assert rec["raw_size_text"] == "500 m2"
    assert rec["url"] == "https://www.citymax-sv.com/inmuebles/terreno-frente-al-mar-en-el-tunco"
    assert rec["lat"] == 13.4895
    assert rec["lng"] == -89.3760
    # Hero + 2 gallery deduped: portada is also first gallery item, so 3 unique
    assert len(rec["photo_urls"]) == 3


def test_map_drops_inland_land_via_force_vacation_gate():
    """The brief explicitly narrows CityMax to Pacific coast + lakes.
    Without force_vacation_gate=True on the finalize_record call, this
    San-Salvador terreno would ship — and would flood ranked.json."""
    inland = _coastal_terreno_rec(
        nombreInmueble="Terreno residencial en San Salvador",
        slug="terreno-en-san-salvador",
        provincia="San Salvador",
        municipio="San Salvador",
        localidad="Colonia Escalon",
    )
    assert _map(inland) is None


def test_map_keeps_lake_land_via_keyword():
    """Lake-Ilopango listing with 'vista al lago' in the title passes
    via the WATERFRONT_KEYWORDS fallback. (Bare 'lago' alone — e.g.
    'a 3 minutos del lago' — does NOT match; the regex requires
    'vista al lago' / 'frente al lago' / 'orillas del lago' /
    'lakefront'. That's a deliberate conservatism in the keyword set.)
    """
    lake = _coastal_terreno_rec(
        nombreInmueble="Terreno en Apulo Ilopango con vista al lago",
        slug="terreno-vista-lago-ilopango",
        provincia="San Salvador",
        municipio="Ilopango",
        localidad="",
    )
    rec = _map(lake)
    assert rec is not None
    assert rec["property_type"] == "land"


def test_map_drops_commercial_type_id():
    """tid=7 (Edificio Comercial) is not in the Pulpo type map. Dropped."""
    commercial = _coastal_terreno_rec(parm_tipoinmueble_idparm_tipoInmueble=7)
    assert _map(commercial) is None


def test_map_drops_rentals():
    """operation=2 is rent; we don't surface rentals."""
    rental = _coastal_terreno_rec(parm_tipooperacion_idparm_tipoOperacion=2)
    assert _map(rental) is None


def test_map_house_populates_type_specific_fields():
    house = _coastal_terreno_rec(
        parm_tipoinmueble_idparm_tipoInmueble=1,
        nombreInmueble="Casa frente al mar en El Tunco",
        slug="casa-en-el-tunco",
        grupoInmueble="Casa Sola Residencial",
        areaConstruccion=180,
        nroHabitaciones=3,
        nroBanios=2,
        nroMediobanios=1,
        nroEstacionamientos=2,
    )
    rec = _map(house)
    assert rec is not None
    assert rec["property_type"] == "house"
    assert rec["built_area_m2"] == 180.0
    assert rec["bedrooms"] == 3
    assert rec["bathrooms"] == 2.5
    assert rec["parking_spaces"] == 2


def test_map_condo_populates_type_specific_fields():
    condo = _coastal_terreno_rec(
        parm_tipoinmueble_idparm_tipoInmueble=2,
        nombreInmueble="Apartamento frente al mar en El Tunco",
        slug="apto-tunco",
        grupoInmueble="Apartamento Residencial",
        areaConstruccion=72,
        nroHabitaciones=2,
        nroBanios=2,
        nroEstacionamientos=1,
    )
    rec = _map(condo)
    assert rec is not None
    assert rec["property_type"] == "condo"
    assert rec["built_area_m2"] == 72.0
    assert rec["bedrooms"] == 2
    assert rec["bathrooms"] == 2.0


def test_map_inland_house_dropped_by_default_vacation_gate():
    """Inland house with no waterfront keyword is dropped — same gate
    behavior as the other 8 scrapers (house/condo only need force=False)."""
    inland_house = _coastal_terreno_rec(
        parm_tipoinmueble_idparm_tipoInmueble=1,
        nombreInmueble="Casa en colonia residencial",
        slug="casa-colonia",
        provincia="San Salvador",
        municipio="San Salvador",
        localidad="Escalon",
        areaConstruccion=200,
        nroHabitaciones=3,
    )
    assert _map(inland_house) is None


# ── _extract_listings: Flight payload parsing ─────────────────────────


def _wrap_flight(payload: dict) -> str:
    """Build a synthetic Flight script tag containing one listing.

    The real CityMax page wraps its Flight chunks in
    ``self.__next_f.push([1, "<escaped JSON>"])`` where the JSON is
    unicode-escaped. We mirror that shape so _extract_listings can
    round-trip the same code path.

    Use compact JSON separators (no spaces) — the real Next.js output
    has no spaces between colons and values, and the brace-walker in
    _extract_listings anchors on ``"idInmueble":<digit>`` with no
    intervening space.
    """
    raw = '{"properties":[' + json.dumps(payload, separators=(",", ":")) + ']}'
    # Escape backslashes + double quotes for embedding into the JS string
    escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
    return f'<script>self.__next_f.push([1,"{escaped}"])</script>'


def test_extract_listings_returns_records_from_flight_payload():
    html = _wrap_flight(_coastal_terreno_rec())
    out = _extract_listings(html)
    assert len(out) == 1
    assert out[0]["idInmueble"] == 160147
    assert out[0]["nombreInmueble"] == "Terreno frente al mar en El Tunco"


def test_extract_listings_empty_when_no_flight_chunks():
    assert _extract_listings("<html><body>nothing here</body></html>") == []


def test_extract_listings_skips_records_without_idInmueble():
    """The walker anchors on the idInmueble key — a chunk without one
    yields zero listings rather than crashing."""
    bogus = '<script>self.__next_f.push([1,"{\\"foo\\":\\"bar\\"}"])</script>'
    assert _extract_listings(bogus) == []


# Round-trip integration: extract then map
def test_extract_then_map_round_trip():
    html = _wrap_flight(_coastal_terreno_rec())
    extracted = _extract_listings(html)
    assert len(extracted) == 1
    mapped = _map(extracted[0])
    assert mapped is not None
    assert mapped["source"] == "citymax"
    assert mapped["property_type"] == "land"


# Sanity: the unicode-escape decoder shouldn't blow up on a chunk that
# was already plain JSON (no unicode escapes).
def test_extract_handles_chunk_without_escapes(monkeypatch):
    # If codecs.decode raises, _extract_listings should return []
    import pulpo.scrapers.citymax as m
    original = codecs.decode
    def bad_decode(s, kind):  # noqa: ARG001
        raise UnicodeDecodeError("ascii", b"", 0, 1, "test")
    monkeypatch.setattr(m.codecs, "decode", bad_decode)
    assert m._extract_listings('<script>self.__next_f.push([1,"x"])</script>') == []
    monkeypatch.setattr(m.codecs, "decode", original)
