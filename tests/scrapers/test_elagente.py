"""
Tests for the El Agente Inmobiliario scraper (pulpo/scrapers/elagente.py).

Three surfaces:
  1. Offline-fixture smoke (source-integration contract).
  2. Pure-function tests on _parse_index, _is_rental,
     _infer_property_type, _extract_price, _extract_address,
     _extract_photo_urls against synthetic Houzez-shaped HTML.
  3. _parse_detail round-trip on a representative coastal listing.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.elagente import (  # noqa: E402
    ElAgenteScraper, _HOUZEZ_TYPE_TO_PULPO, _extract_address,
    _extract_photo_urls, _extract_price, _infer_property_type,
    _is_rental, _parse_detail, _parse_index,
)


# ── Offline-fixture smoke ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def offline_records():
    return ElAgenteScraper(offline=True).crawl(limit=20, offline=True)


def test_offline_returns_records(offline_records):
    if not offline_records:
        pytest.skip("No elagente fixture records — add to fixtures/sample_listings.json")
    assert len(offline_records) >= 1


def test_required_fields_present(offline_records):
    if not offline_records:
        pytest.skip("No fixture records")
    for r in offline_records:
        assert r.get("source") == "elagente"
        assert r.get("source_id"), f"Missing source_id: {r}"
        assert r.get("url", "").startswith("https://www.elagenteinmobiliario.com/propiedad/")
        assert r.get("title"), "Missing title"
        assert r.get("property_type") in {"land", "house", "condo"}
        assert isinstance(r.get("photo_urls", []), list)


# ── _parse_index ──────────────────────────────────────────────────────


def test_parse_index_extracts_detail_urls():
    html = '''
    <html><body>
      <a href="https://www.elagenteinmobiliario.com/propiedad/terreno-lago-de-coatepeque/">x</a>
      <a href="https://www.elagenteinmobiliario.com/propiedad/casa-test-1/">y</a>
      <a href="https://www.elagenteinmobiliario.com/casas/">arch</a>  <!-- not a detail URL -->
      <a href="https://www.elagenteinmobiliario.com/propiedad/terreno-lago-de-coatepeque/">dup</a>
    </body></html>
    '''
    out = _parse_index(html)
    urls = sorted(p["url"] for p in out)
    assert urls == [
        "https://www.elagenteinmobiliario.com/propiedad/casa-test-1",
        "https://www.elagenteinmobiliario.com/propiedad/terreno-lago-de-coatepeque",
    ]


def test_parse_index_empty_on_blank():
    assert _parse_index("<html><body></body></html>") == []


# ── _is_rental ────────────────────────────────────────────────────────


def test_is_rental_detects_slug_keyword():
    assert _is_rental("", "https://example.com/propiedad/apartamento-en-alquiler-test")
    assert _is_rental("", "https://example.com/propiedad/casa-for-rent")
    assert _is_rental("", "https://example.com/propiedad/depto-en-renta-centro")


def test_is_rental_detects_taxonomy_link():
    html = '''<a href="https://www.elagenteinmobiliario.com/etiqueta-de-propiedad/en-alquiler/">en alquiler</a>'''
    assert _is_rental(html, "https://example.com/propiedad/casa-test")


def test_is_rental_false_for_sale_listing():
    assert not _is_rental(
        '<a href="https://www.elagenteinmobiliario.com/estado/for-sale/">en venta</a>',
        "https://example.com/propiedad/terreno-test",
    )


# ── _infer_property_type ──────────────────────────────────────────────


def test_infer_type_from_overview_block():
    html = "<dt>Tipo de propiedad</dt><dd><a href='/casas/'>Casas</a></dd>"
    assert _infer_property_type(html, "https://x.com/propiedad/test") == "house"


def test_infer_type_from_taxonomy_link_in_overview_scope():
    """Taxonomy-link match only counts when it sits within ~600 chars of
    the 'Tipo de propiedad' label (i.e. inside the property-overview
    block). A bare link outside the overview block — e.g. a global nav
    link to /apartamentos/ — does NOT drive type inference."""
    html_in_scope = (
        '<dl>Tipo de propiedad'
        '<dd><a href="https://www.elagenteinmobiliario.com/terrenos/">Terrenos</a></dd>'
        '</dl>'
    )
    assert _infer_property_type(html_in_scope, "https://x.com/propiedad/test") == "land"


def test_infer_type_ignores_global_nav_link_when_no_label():
    """The global nav links to /casas/, /apartamentos/, /terrenos/ on
    every page. Without the 'Tipo de propiedad' anchor they must not
    drive type inference — falls through to URL slug."""
    html_no_label = '<a href="https://www.elagenteinmobiliario.com/apartamentos/">Apartamentos</a>'
    assert _infer_property_type(html_no_label, "https://x.com/propiedad/special-investment") is None


def test_infer_type_from_url_slug_when_html_silent():
    out = _infer_property_type("", "https://x.com/propiedad/casa-frente-al-mar-en-el-tunco")
    assert out == "house"
    out2 = _infer_property_type("", "https://x.com/propiedad/terreno-lago-de-coatepeque")
    assert out2 == "land"


def test_infer_type_returns_none_for_unknown():
    assert _infer_property_type("", "https://x.com/propiedad/special-investment-thing") is None


def test_houzez_type_map_covers_known_labels():
    """Every Houzez type label we audited maps to a known Pulpo type."""
    for label in ("casas", "casa", "apartamentos", "apartamento", "terrenos",
                  "terreno", "lotes", "lote", "fincas", "finca"):
        assert label in _HOUZEZ_TYPE_TO_PULPO


# ── _extract_price ────────────────────────────────────────────────────


def test_extract_price_parses_houzez_item_price():
    html = '<li class="item-price item-price-text price-single-listing-text">$295,000</li>'
    price, raw = _extract_price(html)
    assert price == 295000.0
    assert "$295,000" in raw


def test_extract_price_handles_no_price_element():
    price, raw = _extract_price("<html><body>nothing</body></html>")
    assert price is None
    assert raw == ""


def test_extract_price_tolerates_decimals():
    html = '<li class="item-price">$1,234,567.89</li>'
    price, _ = _extract_price(html)
    assert price == 1234567.89


# ── _extract_address ──────────────────────────────────────────────────


def test_extract_address_strips_inner_tags():
    html = '<address><i class="houzez-icon icon-pin me-1"></i>Lago de Coatepeque</address>'
    assert _extract_address(html) == "Lago de Coatepeque"


def test_extract_address_returns_empty_when_absent():
    assert _extract_address("<html><body></body></html>") == ""


# ── _extract_photo_urls ──────────────────────────────────────────────


def test_extract_photo_urls_finds_gallery_images():
    html = '''
    <div itemscope itemtype="http://schema.org/ImageGallery">
      <a href="https://www.elagenteinmobiliario.com/wp-content/uploads/2024/01/photo-1.jpg">img1</a>
      <a href="https://www.elagenteinmobiliario.com/wp-content/uploads/2024/01/photo-2.jpg">img2</a>
    </div></div>
    '''
    out = _extract_photo_urls(html)
    assert len(out) == 2
    assert out[0].endswith("photo-1.jpg")


def test_extract_photo_urls_skips_logo_and_favicon():
    html = '''
    <div itemscope itemtype="http://schema.org/ImageGallery">
      <img src="https://www.elagenteinmobiliario.com/wp-content/uploads/2020/07/web_logo.png"/>
      <img src="https://www.elagenteinmobiliario.com/wp-content/uploads/2020/07/cropped-favicon_2020-32x32.png"/>
      <img src="https://www.elagenteinmobiliario.com/wp-content/uploads/2024/01/real-photo.jpg"/>
    </div></div>
    '''
    out = _extract_photo_urls(html)
    assert len(out) == 1
    assert out[0].endswith("real-photo.jpg")


def test_extract_photo_urls_empty_when_no_uploads():
    assert _extract_photo_urls("<html><body></body></html>") == []


# ── _parse_detail: full pipeline ──────────────────────────────────────


def _coastal_terreno_detail_html() -> str:
    """Synthetic detail page mirroring the Houzez 3.x structure
    audited 2026-05-25 on /propiedad/terreno-lago-de-coatepeque/."""
    return '''
    <html><head>
      <meta property="og:title" content="Terreno Lago de Coatepeque - El Agente Inmobiliario"/>
      <meta property="og:description" content="Espectacular terreno frente al lago de Coatepeque."/>
      <meta property="og:image" content="https://www.elagenteinmobiliario.com/wp-content/uploads/2024/01/sample-coatepeque.jpeg"/>
    </head><body>
      <a href="https://www.elagenteinmobiliario.com/terrenos/">Terrenos</a>
      <address><i class="houzez-icon icon-pin"></i>Lago de Coatepeque</address>
      <li class="item-price item-price-text price-single-listing-text">$295,000</li>
      <div itemscope itemtype="http://schema.org/ImageGallery">
        <img src="https://www.elagenteinmobiliario.com/wp-content/uploads/2024/01/g1.jpg"/>
        <img src="https://www.elagenteinmobiliario.com/wp-content/uploads/2024/01/g2.jpg"/>
      </div></div>
      <p>Tamaño de área: 8,000 m²</p>
      <a href="https://www.elagenteinmobiliario.com/estado/for-sale/">En Venta</a>
    </body></html>
    '''


def test_parse_detail_extracts_lake_land():
    out = _parse_detail(
        _coastal_terreno_detail_html(),
        "https://www.elagenteinmobiliario.com/propiedad/terreno-lago-de-coatepeque",
    )
    assert out is not None
    assert out["source"] == "elagente"
    assert out["source_id"] == "terreno-lago-de-coatepeque"
    assert out["title"] == "Terreno Lago de Coatepeque"
    assert out["property_type"] == "land"
    assert out["price_usd"] == 295000.0
    assert "8000 m2" in out["raw_size_text"]
    assert "Lago de Coatepeque" in out["location_text"]
    # og:image inserted at index 0, gallery images dedup-merged
    assert len(out["photo_urls"]) >= 2


def test_parse_detail_drops_rental_via_slug():
    html = _coastal_terreno_detail_html()
    out = _parse_detail(html, "https://www.elagenteinmobiliario.com/propiedad/casa-en-alquiler-santa-rosa")
    assert out is None


def test_parse_detail_drops_inland_terreno_via_force_gate():
    """Inland Chalatenango terreno fails the niche filter even though
    Houzez category is Terrenos. force_vacation_gate=True is what
    makes elagente narrow to the coast + lakes."""
    html = '''
    <html><head>
      <meta property="og:title" content="Terreno en Chalatenango - El Agente Inmobiliario"/>
      <meta property="og:description" content="Terreno en la sierra de Chalatenango."/>
      <meta property="og:image" content="https://www.elagenteinmobiliario.com/wp-content/uploads/2024/01/sample-chala.jpeg"/>
    </head><body>
      <a href="https://www.elagenteinmobiliario.com/terrenos/">Terrenos</a>
      <address>Chalatenango Centro</address>
      <li class="item-price">$50,000</li>
      <a href="https://www.elagenteinmobiliario.com/estado/for-sale/">En Venta</a>
    </body></html>
    '''
    out = _parse_detail(html, "https://www.elagenteinmobiliario.com/propiedad/terreno-chalatenango")
    assert out is None


def test_parse_detail_house_with_beds_baths():
    html = '''
    <html><head>
      <meta property="og:title" content="Casa frente al mar en El Tunco - El Agente Inmobiliario"/>
      <meta property="og:description" content="Casa frente al mar con piscina."/>
      <meta property="og:image" content="https://www.elagenteinmobiliario.com/wp-content/uploads/2024/01/sample.jpg"/>
    </head><body>
      <a href="https://www.elagenteinmobiliario.com/casas/">Casas</a>
      <address>El Tunco, La Libertad</address>
      <li class="item-price">$650,000</li>
      <p>3 Habitaciones</p>
      <p>2 Baños</p>
    </body></html>
    '''
    out = _parse_detail(html, "https://www.elagenteinmobiliario.com/propiedad/casa-frente-al-mar-tunco")
    assert out is not None
    assert out["property_type"] == "house"
    assert out["bedrooms"] == 3
    assert out["bathrooms"] == 2.0


def test_parse_detail_drops_unknown_type():
    html = '''
    <html><head>
      <meta property="og:title" content="Special - El Agente Inmobiliario"/>
    </head><body><a href="https://www.elagenteinmobiliario.com/oficinas-locales/">Oficinas</a></body></html>
    '''
    out = _parse_detail(html, "https://www.elagenteinmobiliario.com/propiedad/special")
    assert out is None
