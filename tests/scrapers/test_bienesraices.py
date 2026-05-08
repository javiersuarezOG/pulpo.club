"""
Tests for the BienesRaíces El Salvador scraper (pulpo/scrapers/bienesraices.py).

Runs in offline mode against the shared fixture in
fixtures/sample_listings.json (filtered to source='bienesraices').
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.bienesraices import BienesRaicesScraper, _NEXT_DATA_RE  # noqa: E402


# ── Offline fixture crawl ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def offline_records():
    return BienesRaicesScraper(offline=True).crawl(limit=20, offline=True)


def test_offline_returns_records(offline_records):
    if not offline_records:
        pytest.skip("No bienesraices fixture records — add to fixtures/sample_listings.json")
    assert len(offline_records) >= 1


def test_required_fields_present(offline_records):
    if not offline_records:
        pytest.skip("No fixture records")
    for r in offline_records:
        assert r.get("source") == "bienesraices"
        assert r.get("source_id"), f"Missing source_id: {r}"
        assert r.get("url", "").startswith("https://"), f"Bad url: {r}"
        assert r.get("title"), "Missing title"
        assert r.get("property_type") == "land"
        assert isinstance(r.get("photo_urls", []), list), "photo_urls must be a list"


# ── Parsing unit tests (no fixture needed) ─────────────────────────────

def test_next_data_regex_matches_basic_payload():
    html = '<html><script id="__NEXT_DATA__" type="application/json">{"foo":1}</script></html>'
    m = _NEXT_DATA_RE.search(html)
    assert m
    assert m.group(1) == '{"foo":1}'


def test_next_data_regex_handles_multiline():
    """Real Next.js payloads span many lines — regex must be DOTALL."""
    html = '<html><script id="__NEXT_DATA__" type="application/json">{\n"a":1,\n"b":2\n}</script></html>'
    m = _NEXT_DATA_RE.search(html)
    assert m
    assert "a" in m.group(1)


def test_parse_skips_when_next_data_missing():
    """Parser returns None on pages without __NEXT_DATA__ (404, redirects)."""
    s = BienesRaicesScraper()
    result = s._parse("<html><body>not found</body></html>", "https://example.com")
    assert result is None


def test_parse_skips_non_land_category():
    """Listings whose category isn't land/lote/finca are dropped."""
    import json
    s = BienesRaicesScraper()
    payload = {"props": {"pageProps": {"property": {
        "name": "Casa en venta",
        "category": {"name": "Apartamento"},
        "cid": "12345",
    }}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    result = s._parse(html, "https://example.com")
    assert result is None


def test_parse_extracts_photos_from_images_array():
    import json
    s = BienesRaicesScraper()
    payload = {"props": {"pageProps": {"property": {
        "name": "Terreno El Salvador",
        "category": {"name": "Terreno"},
        "cid": "9999",
        "sale_price": 100000,
        "terrain_area": 500,
        "terrain_area_measurer": "m2",
        "province": "La Libertad",
        "city": "Tamanique",
        "agents": [],
        "description": "Test",
        "images": [
            {"url": "https://cdn.example.com/photo1.jpg"},
            {"photo": "https://cdn.example.com/photo2.jpg"},
        ],
    }}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    result = s._parse(html, "https://example.com/test")
    assert result is not None
    assert len(result["photo_urls"]) == 2
    assert "photo1.jpg" in result["photo_urls"][0]
    assert "photo2.jpg" in result["photo_urls"][1]


def test_parse_photo_urls_empty_list_when_no_images():
    """No images field → photo_urls=[] (not None, not missing)."""
    import json
    s = BienesRaicesScraper()
    payload = {"props": {"pageProps": {"property": {
        "name": "Terreno", "category": {"name": "Terreno"}, "cid": "1",
        "agents": [], "description": "",
    }}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    result = s._parse(html, "https://example.com")
    assert result is not None
    assert result["photo_urls"] == []


def test_parse_extracts_photos_from_real_alterestate_shape():
    """The live AlterEstate __NEXT_DATA__ uses featured_image (string) + gallery_image
    (list of dicts with `image` key). The earlier extractor looked for the field
    name 'images' which never appears, so 100% of bienesraices listings shipped
    with photos_count=0. Lock the real shape in."""
    import json
    s = BienesRaicesScraper()
    payload = {"props": {"pageProps": {"property": {
        "name": "Terreno",
        "category": {"name": "Terreno"},
        "cid": "1",
        "agents": [],
        "description": "",
        "featured_image": "https://cdn.example.com/hero.jpg",
        "gallery_image": [
            {"image": "https://cdn.example.com/g1.jpg", "image_wm": None},
            {"image": "https://cdn.example.com/g2.jpg", "image_wm": None},
        ],
    }}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    result = s._parse(html, "https://example.com")
    assert result is not None
    assert result["photo_urls"] == [
        "https://cdn.example.com/hero.jpg",
        "https://cdn.example.com/g1.jpg",
        "https://cdn.example.com/g2.jpg",
    ], "featured_image must come first, gallery_image follows in order"


def test_parse_dedupes_when_featured_appears_in_gallery():
    """If featured_image URL also appears in gallery_image, it should not
    appear twice — dedup by exact URL."""
    import json
    s = BienesRaicesScraper()
    payload = {"props": {"pageProps": {"property": {
        "name": "Terreno", "category": {"name": "Terreno"}, "cid": "1",
        "agents": [], "description": "",
        "featured_image": "https://cdn.example.com/hero.jpg",
        "gallery_image": [
            {"image": "https://cdn.example.com/hero.jpg"},  # dup of featured
            {"image": "https://cdn.example.com/g2.jpg"},
        ],
    }}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    result = s._parse(html, "https://example.com")
    assert result["photo_urls"] == [
        "https://cdn.example.com/hero.jpg",
        "https://cdn.example.com/g2.jpg",
    ]


# ── Phase A: house + condo ingestion ───────────────────────────────────
# Field shape mirrors live AlterEstate __NEXT_DATA__ samples (cid 2346 for
# Casas, cid 2350 for Apartamentos, captured 2026-05-05).

def _wrap(payload: dict) -> str:
    """Inline payload as the page's __NEXT_DATA__ block."""
    import json
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'


def _coastal_house_payload(**overrides) -> dict:
    """Synthetic but field-shape-faithful AlterEstate house in El Tunco."""
    base = {
        "name": "Venta de Casa Moderna en El Tunco",
        "category": {"name": "Casas"},
        "cid": "9001",
        "forSale": True,
        "sale_price": 425000,
        "currency_sale": "USD",
        "province": "La Libertad",
        "city":     "La Libertad Costa",
        "sector":   "El Tunco",
        "agents":   [],
        "description": "Casa frente al mar con vista al océano.",
        "room": 3, "bathroom": 2, "half_bathrooms": 1, "parkinglot": 2,
        "property_area": 169, "property_area_measurer": "Mt2",
        "terrain_area": 300, "terrain_area_measurer": "v2",
        "year_construction": "2020",
    }
    base.update(overrides)
    return {"props": {"pageProps": {"property": base}}}


def _coastal_condo_payload(**overrides) -> dict:
    base = {
        "name": "Apartamento frente al mar Costa del Sol",
        "category": {"name": "Apartamentos"},
        "cid": "9002",
        "forSale": True,
        "sale_price": 230000,
        "currency_sale": "USD",
        "province": "La Paz",
        "city":     "La Paz Centro",
        "sector":   "Costa del Sol",
        "agents":   [],
        "description": "Apartamento con vista al mar.",
        "room": 2, "bathroom": 2, "half_bathrooms": 0, "parkinglot": 1,
        "property_area": 95, "property_area_measurer": "Mt2",
        "floor_level": 4,
        "maintenance_fee": 180,
        "currency_maintenance": "USD",
    }
    base.update(overrides)
    return {"props": {"pageProps": {"property": base}}}


def test_parse_house_populates_type_specific_fields():
    s = BienesRaicesScraper()
    out = s._parse(_wrap(_coastal_house_payload()),
                   "https://bienesraicesenelsalvador.com/propiedad/casa-el-tunco-9001")
    assert out is not None
    assert out["property_type"] == "house"
    assert out["price_usd"] == 425000.0
    assert out["bedrooms"] == 3
    assert out["bathrooms"] == 2.5  # 2 full + 1 half
    assert out["built_area_m2"] == 169.0
    assert out["parking_spaces"] == 2
    assert out["year_built"] == 2020


def test_parse_condo_populates_floor_and_hoa():
    s = BienesRaicesScraper()
    out = s._parse(_wrap(_coastal_condo_payload()),
                   "https://bienesraicesenelsalvador.com/propiedad/condo-cds-9002")
    assert out is not None
    assert out["property_type"] == "condo"
    assert out["bedrooms"] == 2
    assert out["bathrooms"] == 2.0
    assert out["floor"] == 4
    assert out["hoa_fee_usd_monthly"] == 180.0
    assert out["built_area_m2"] == 95.0
    # Land-only fields not populated
    assert out.get("year_built") is None  # not in fixture


def test_parse_drops_inland_house_with_no_beachfront_keyword():
    """Per spec: house/condo not in VACATION_ZONES AND no waterfront
    keyword must be DROPPED at scrape time. Inland house in San
    Salvador, generic description with no playa / frente al mar /
    frente al lago — must be skipped."""
    s = BienesRaicesScraper()
    out = s._parse(_wrap(_coastal_house_payload(
        province="San Salvador", city="San Salvador Centro",
        sector="Escalón",
        description="Casa moderna en colonia residencial tranquila.",
    )), "https://x.com/casa-escalon")
    assert out is None, "inland house with no beachfront keyword must be dropped"


def test_parse_keeps_inland_house_when_title_says_frente_al_mar():
    """Beachfront-keyword fallback: an inland-zoned house that mentions
    'frente al mar' in the description survives the coastal filter."""
    s = BienesRaicesScraper()
    out = s._parse(_wrap(_coastal_house_payload(
        province="Ahuachapán", city="Ahuachapán Centro", sector="Sonsonate",
        description="Casa frente al mar (zona costera).",
    )), "https://x.com/x")
    assert out is not None
    assert out["property_type"] == "house"


def test_parse_drops_house_marked_not_for_sale():
    """Rentals (forSale: False) must be dropped — we don't surface rentals.
    Land is exempt from this gate (many lots have no sale_price but are
    still for sale)."""
    s = BienesRaicesScraper()
    out = s._parse(_wrap(_coastal_house_payload(forSale=False)),
                   "https://x.com/casa-rental")
    assert out is None


def test_parse_drops_unknown_category():
    """Categories outside the broker_type map (Comercial, Industrial, etc.)
    are dropped at the category check before any field extraction runs."""
    s = BienesRaicesScraper()
    out = s._parse(_wrap(_coastal_house_payload(
        category={"name": "Comercial"})), "https://x.com/x")
    assert out is None


def test_parse_emits_classifier_signals_for_house():
    """The classifier runs after the broker-field decision, so its signals
    + confidence land on the record for the shadow log + future tightening."""
    s = BienesRaicesScraper()
    out = s._parse(_wrap(_coastal_house_payload()), "https://x.com/casa-el-tunco-9001")
    assert "_type_signals" in out
    assert "_type_confidence" in out
    assert isinstance(out["_type_signals"], list)
    assert out["_type_confidence"] in {"high", "medium", "low", "uncertain"}


def test_parse_flags_when_classifier_disagrees_with_broker():
    """If broker says 'Casas' but URL/photos/title all scream 'condo',
    the listing ships with broker_type but is FLAGGED for human review."""
    s = BienesRaicesScraper()
    out = s._parse(_wrap(_coastal_house_payload(
        name="Apartamento Loft Modern Condo en El Tunco",
        description="Apartamento condominio departamento frente al mar.",
    )), "https://x.com/apartamento-condominio-9001")
    assert out is not None
    assert out["property_type"] == "house"  # broker_type wins for shipping
    assert out.get("validation_status") == "flagged"
    assert "type_classifier_disagree" in out.get("validation_warnings", [])


def test_parse_land_path_unchanged_no_type_specific_fields():
    """Regression guard: land listings must not gain bedrooms/bathrooms/etc.
    fields. Type-specific extraction is gated behind broker_type in
    ('house', 'condo')."""
    import json
    s = BienesRaicesScraper()
    payload = {"props": {"pageProps": {"property": {
        "name": "Terreno en Costa del Sol",
        "category": {"name": "Terreno"},
        "cid": "8001", "forSale": True,
        "sale_price": 60000, "currency_sale": "USD",
        "province": "La Paz", "city": "La Paz Centro", "sector": "Costa del Sol",
        "agents": [], "description": "Terreno plano frente al mar.",
        "terrain_area": 1000, "terrain_area_measurer": "v2",
        # These would populate if the gate broke:
        "room": 99, "bathroom": 99, "property_area": 999,
    }}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    out = s._parse(html, "https://x.com/terreno-cds")
    assert out["property_type"] == "land"
    assert "bedrooms" not in out
    assert "bathrooms" not in out
    assert "built_area_m2" not in out
