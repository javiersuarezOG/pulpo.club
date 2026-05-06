import json
from pulpo.scrapers.century21 import _extract_results, Century21Scraper, LAND_TYPES

SYNTHETIC_LAND_RECORD = {
    "id": 12345,
    "encabezado": "Lote en El Zonte frente al mar",
    "precio": 150000,
    "moneda": "USD",
    "m2T": 500.0,
    "tipoPropiedad": "lote_residencial",   # in LAND_TYPES
    "municipio": "Tamanique",
    "estado": "La Libertad",
    "calle": "",
    "urlCorrectaPropiedad": "/propiedad/12345_lote-el-zonte/oficina_4942",
    "asesorNombre": "Juan Pérez",
    "whatsapp": "+50312345678",
    "email": "juan@century21.com",
}
SYNTHETIC_NON_LAND_RECORD = {
    "id": 99999,
    "encabezado": "Casa en San Salvador",
    "precio": 200000,
    "moneda": "USD",
    "m2T": 200.0,
    "tipoPropiedad": "casa",  # NOT in LAND_TYPES
    "municipio": "San Salvador",
    "estado": "San Salvador",
    "calle": "",
    "urlCorrectaPropiedad": "/propiedad/99999_casa-ss/oficina_4942",
    "asesorNombre": "Maria López",
    "whatsapp": "+50398765432",
    "email": "maria@century21.com",
}

def _make_html(records: list) -> str:
    blob = json.dumps(records)
    return f'window.REP_LOG_APP_PROPS = {{ isLoggedIn: false, data: {{ "results": {blob} }} }};'

def test_extract_results_finds_array():
    html = _make_html([SYNTHETIC_LAND_RECORD, SYNTHETIC_NON_LAND_RECORD])
    results = _extract_results(html)
    assert len(results) == 2

def test_extract_results_empty_when_no_marker():
    assert _extract_results("<html>no results here</html>") == []

def test_crawl_filters_non_land():
    html = _make_html([SYNTHETIC_LAND_RECORD, SYNTHETIC_NON_LAND_RECORD])
    results = _extract_results(html)
    land = [r for r in results if r.get("tipoPropiedad") in LAND_TYPES]
    assert len(land) == 1
    assert land[0]["id"] == 12345

def test_map_produces_canonical_dict():
    scraper = Century21Scraper(offline=True)
    rec = scraper._map(SYNTHETIC_LAND_RECORD)
    assert rec is not None
    assert rec["title"] == "Lote en El Zonte frente al mar"
    assert "150000" in rec["raw_price_text"]
    assert rec["raw_size_text"] == "500.0 m2"
    assert rec["broker_name"] == "Juan Pérez"
    assert rec["source"] == "century21"


def test_map_extracts_photos_from_real_omnimls_dict_shape():
    """OmniMLS exposes photos as a DICT, not a list:
        fotos: {totalFotos: int, propiedadThumbnail: [url, url, ...]}
    Earlier code iterated the dict (yielding its keys) and produced 0 photos
    for every century21 listing. Lock the real shape in."""
    scraper = Century21Scraper(offline=True)
    rec_with_photos = dict(SYNTHETIC_LAND_RECORD)
    rec_with_photos["fotos"] = {
        "totalFotos": 3,
        "propiedadThumbnail": [
            "https://cdn.21online.lat/p/1.jpg",
            "https://cdn.21online.lat/p/2.jpg",
            "https://cdn.21online.lat/p/3.jpg",
        ],
    }
    out = scraper._map(rec_with_photos)
    assert out["photo_urls"] == [
        "https://cdn.21online.lat/p/1.jpg",
        "https://cdn.21online.lat/p/2.jpg",
        "https://cdn.21online.lat/p/3.jpg",
    ]


def test_map_returns_empty_photos_when_fotos_missing_or_unexpected():
    """Missing/None fotos → []. Unexpected types must not raise."""
    scraper = Century21Scraper(offline=True)
    for v in (None, {}, {"totalFotos": 0, "propiedadThumbnail": []}, "string-not-dict", 42):
        rec = dict(SYNTHETIC_LAND_RECORD)
        if v is None:
            rec.pop("fotos", None)
        else:
            rec["fotos"] = v
        out = scraper._map(rec)
        assert out is not None and out["photo_urls"] == [], (
            f"fotos={v!r} should yield photo_urls=[]"
        )


# ── Phase C: house + condo broadening ──────────────────────────────────
# OmniMLS exposes tipoPropiedad as a structured string. We map known
# strings to property_type and run the coastal filter on house/condo.
# Field shape (m2C, recamaras, banos, medioBanos, estacionamientos,
# mantenimiento, niveles) verified against live 2026-05-06 casa sample
# (cid 888677 RESIDENCIAS TERRAZAS DEL ENCANTO).

from pulpo.scrapers.century21 import _broker_type_for, HOUSE_TYPES, CONDO_TYPES  # noqa: E402

SYNTHETIC_COASTAL_HOUSE = {
    "id": 888678,
    "encabezado": "Casa frente al mar en El Tunco",
    "precio": 425000,
    "moneda": "USD",
    "tipoPropiedad": "casa",
    "m2T": 300.0,         # lot
    "m2C": 169.0,         # built
    "recamaras": 3,
    "banos": 2,
    "medioBanos": 1,
    "estacionamientos": 2,
    "mantenimiento": " + 150 mantenimiento",
    "municipio": "El Tunco",
    "estado": "La Libertad",
    "calle": "",
    "urlCorrectaPropiedad": "/propiedad/888678_casa-el-tunco/oficina_4942",
    "asesorNombre": "Test Agent",
}

SYNTHETIC_INLAND_HOUSE = {
    **SYNTHETIC_COASTAL_HOUSE,
    "id": 888679,
    "encabezado": "Casa moderna en Zaragoza",
    "municipio": "Zaragoza",
    "estado": "La Libertad",
}


def test_broker_type_for_handles_known_types():
    assert _broker_type_for("lote_residencial") == "land"
    assert _broker_type_for("casa") == "house"
    assert _broker_type_for("Villa") == "house"  # case-insensitive
    assert _broker_type_for("apartamento") == "condo"
    assert _broker_type_for("local") is None  # commercial — skipped
    assert _broker_type_for("") is None
    assert _broker_type_for(None) is None


def test_house_type_sets_disjoint_from_land():
    """No type string should claim both land and house — guard against
    accidental overlap when adding new types."""
    assert HOUSE_TYPES.isdisjoint(CONDO_TYPES)
    assert HOUSE_TYPES.isdisjoint({"lote_residencial","lote_comercial","lote",
                                    "terreno","tierra","finca","rancho",
                                    "hacienda","propiedad_de_desarrollo"})


def test_map_coastal_house_populates_type_specific_fields():
    """House in El Tunco (a COASTAL_ZONE) survives the coastal filter
    and lands all type-specific fields from OmniMLS."""
    s = Century21Scraper(offline=True)
    out = s._map(SYNTHETIC_COASTAL_HOUSE, broker_type="house")
    assert out is not None
    assert out["property_type"] == "house"
    assert out["bedrooms"] == 3
    assert out["bathrooms"] == 2.5
    assert out["built_area_m2"] == 169.0
    assert out["parking_spaces"] == 2
    assert out["hoa_fee_usd_monthly"] == 150.0


def test_map_drops_inland_house_with_no_beachfront_keyword():
    """Casa in Zaragoza (inland, no COASTAL_ZONE match, no beachfront kw)
    must be DROPPED. This is the dominant case for live c21 data: all 8
    casa records on 2026-05-06 are inland."""
    s = Century21Scraper(offline=True)
    out = s._map(SYNTHETIC_INLAND_HOUSE, broker_type="house")
    assert out is None


def test_map_keeps_inland_house_with_beachfront_keyword_in_title():
    """Beachfront-keyword fallback: an inland-municipio casa that mentions
    'frente al mar' in the title still passes the coastal filter."""
    s = Century21Scraper(offline=True)
    rec = {**SYNTHETIC_INLAND_HOUSE,
           "encabezado": "Casa frente al mar Acajutla"}
    out = s._map(rec, broker_type="house")
    assert out is not None
    assert out["property_type"] == "house"


def test_map_built_area_zero_treated_as_missing():
    """Zero is the OmniMLS placeholder for unknown — treat as missing."""
    s = Century21Scraper(offline=True)
    rec = {**SYNTHETIC_COASTAL_HOUSE, "m2C": 0}
    out = s._map(rec, broker_type="house")
    assert out is not None
    assert "built_area_m2" not in out


def test_map_emits_classifier_signals_for_house():
    s = Century21Scraper(offline=True)
    out = s._map(SYNTHETIC_COASTAL_HOUSE, broker_type="house")
    assert "_type_signals" in out
    assert "_type_confidence" in out
    assert out["_type_confidence"] in {"high", "medium", "low", "uncertain"}


def test_map_land_path_unchanged_no_type_specific_fields():
    """Regression guard for the 15 land listings on production today —
    land must not gain bedrooms/bathrooms/built_area_m2 fields."""
    s = Century21Scraper(offline=True)
    rec = {**SYNTHETIC_LAND_RECORD, "recamaras": 99, "banos": 99, "m2C": 999}
    out = s._map(rec, broker_type="land")
    assert out is not None
    assert out["property_type"] == "land"
    assert "bedrooms" not in out
    assert "bathrooms" not in out
    assert "built_area_m2" not in out
