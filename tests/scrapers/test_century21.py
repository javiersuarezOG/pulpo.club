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
