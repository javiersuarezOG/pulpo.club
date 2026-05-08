"""
Tests for the RE/MAX El Salvador scraper (pulpo/scrapers/remax.py).

Runs in offline mode against the shared fixture in
fixtures/sample_listings.json (filtered to source='remax').
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.remax import RemaxScraper, _parse_cards, _parse_detail  # noqa: E402


# ── Offline fixture crawl ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def offline_records():
    return RemaxScraper(offline=True).crawl(limit=20, offline=True)


def test_offline_returns_records(offline_records):
    if not offline_records:
        pytest.skip("No remax fixture records — add to fixtures/sample_listings.json")
    assert len(offline_records) >= 1


def test_required_fields_present(offline_records):
    if not offline_records:
        pytest.skip("No fixture records")
    for r in offline_records:
        assert r.get("source") == "remax"
        assert r.get("source_id"), f"Missing source_id: {r}"
        assert r.get("url", "").startswith("https://"), f"Bad url: {r}"
        assert r.get("title"), "Missing title"
        # property_type may be None on legacy fixture records — defaults to 'land' in normalize()
        assert r.get("property_type") in (None, "land"), f"Unexpected property_type: {r.get('property_type')}"
        assert isinstance(r.get("photo_urls", []), list)


# ── Parsing unit tests ────────────────────────────────────────────────

def test_parse_cards_returns_list_on_empty_html():
    """Parser must return [] (not crash) on empty/minimal HTML."""
    assert _parse_cards("<html><body></body></html>") == []


def test_parse_cards_handles_card_with_price_and_link():
    """A single card with the expected structure parses cleanly."""
    html = """<html><body>
      <div class="item">
        <a class="recent-16" href="/listing/12345/test-terreno"></a>
        <div class="recent-details">Terreno en venta El Tunco USD $150,000</div>
        <div class="recent-price">$150,000</div>
      </div>
    </body></html>"""
    cards = _parse_cards(html)
    assert len(cards) == 1
    c = cards[0]
    assert "12345" in c["source_id"]
    assert c["url"].startswith("https://")
    assert "Terreno en venta El Tunco" in c["title"]
    assert c["price_usd"] == 150000.0


def test_parse_detail_skips_when_no_title():
    """No <h3> + no partial title → returns None."""
    partial = {"source_id": "1", "url": "https://x.com", "title": "", "raw_price_text": ""}
    result = _parse_detail("<html><body></body></html>", partial)
    assert result is None


def test_parse_detail_extracts_area_and_photos():
    """Detail page with lot size + gallery image populates the dict.

    RE/MAX renders areas as 'Sq. Vr' or 'Sq. Mt' — see _AREA_RE in remax.py.
    """
    html = """<html><body>
      <h3>Beach Terreno El Tunco. For Sale</h3>
      <ul>
        <li>Lot size: <span class="det">5,000 Sq. Mt</span></li>
      </ul>
      <section><p>Beautiful beachfront lot near El Tunco.</p></section>
      <div class="property-gallery">
        <img src="https://remax.com/img/p1.jpg"/>
        <img src="https://remax.com/img/p2.jpg"/>
      </div>
    </body></html>"""
    partial = {"source_id": "777", "url": "https://remax.com/777/x",
               "title": "old", "raw_price_text": "$100,000", "price_usd": 100000.0}
    result = _parse_detail(html, partial)
    assert result is not None
    assert "El Tunco" in result["title"]
    assert "5000" in result["raw_size_text"]
    assert "Beautiful beachfront" in result["description"]
    assert len(result["photo_urls"]) == 2


def test_parse_detail_photo_urls_empty_when_no_gallery():
    """No images → photo_urls=[] (uses og:image fallback if present)."""
    html = """<html><body><h3>Terreno. For Sale</h3>
      <ul><li>Lot size: <span class="det">100 m²</span></li></ul>
      <section><p>Test.</p></section>
    </body></html>"""
    partial = {"source_id": "1", "url": "https://remax.com/1/x", "title": "", "raw_price_text": ""}
    result = _parse_detail(html, partial)
    assert result is not None
    assert result["photo_urls"] == []


def test_parse_detail_uses_og_image_fallback():
    """When no gallery div, og:image meta tag is used as hero."""
    html = """<html><head>
      <meta property="og:image" content="https://remax.com/og-hero.jpg"/>
    </head><body><h3>Terreno. For Sale</h3>
      <ul><li>Lot size: <span class="det">200 m²</span></li></ul>
      <section><p>Test.</p></section>
    </body></html>"""
    partial = {"source_id": "1", "url": "https://remax.com/1/x", "title": "", "raw_price_text": ""}
    result = _parse_detail(html, partial)
    assert result is not None
    assert result["photo_urls"] == ["https://remax.com/og-hero.jpg"]


# ── Phase C: house + condo ingestion ────────────────────────────────────
# Test the broadened crawl path. The remax detail page exposes
# bedrooms / bathrooms / built area / parking via labelled <li><span class="det">
# entries — same structure as the legacy "Tamaño de lote" lookup, just
# more labels. _parse_detail extracts these for house/condo, and applies
# the coastal-zone filter from automation/property_types.

def _detail_html(*, h3_title: str, dets: dict, has_og: bool = False) -> str:
    """Build a minimal detail-page HTML with the labelled <li> entries
    remax exposes. Each (label, value) becomes <li>{label}:<span class="det">{value}</span></li>."""
    li_rows = "".join(
        f'<li>{lbl}: <span class="det">{val}</span></li>' for lbl, val in dets.items()
    )
    og = ('<meta property="og:image" content="https://remax.com/og.jpg"/>'
          if has_og else "")
    return f"""<html><head>{og}</head><body>
      <h3>{h3_title}</h3>
      <ul>{li_rows}</ul>
      <section><p>A great property.</p></section>
    </body></html>"""


def _coastal_house_dets(**override) -> dict:
    base = {
        "Código de la propiedad": "001234567890",
        "Tipo de Propiedad":      "Casa/Villa",
        "Tipo de Contrato":       "En Venta",
        "Precio":                 "$ 450,000.00",
        "Baños":                  "2",
        "Habitaciones":           "3",
        "Espacios para vehículo": "2",
        "Tamaño de Construcción": "169.00 Sq. Mt.",
        "Tamaño de lote":         "300.00 Sq. Mt.",
    }
    base.update(override)
    return base


def _coastal_condo_dets(**override) -> dict:
    base = {
        "Código de la propiedad": "001234567891",
        "Tipo de Propiedad":      "Apto/Condominio",
        "Tipo de Contrato":       "En Venta",
        "Precio":                 "$ 285,000.00",
        "Baños":                  "2",
        "Habitaciones":           "2",
        "Espacios para vehículo": "1",
        "Tamaño de Construcción": "85.00 Sq. Mt.",
        "Tamaño de lote":         "85.00 Sq. Mt.",
    }
    base.update(override)
    return base


def test_parse_detail_house_populates_type_specific_fields():
    """Coastal house: type fields land, coastal filter passes via title."""
    html = _detail_html(
        h3_title="Casa frente al mar en El Tunco. En Venta",
        dets=_coastal_house_dets(),
        has_og=True,
    )
    partial = {
        "source_id": "001234567890",
        "url": "https://www.remax-elsalvador.com/001234567890",
        "title": "Casa frente al mar en El Tunco",
        "raw_price_text": "$ 450,000.00",
        "price_usd": 450000.0,
        "_source_property_type": "house",
    }
    rec = _parse_detail(html, partial)
    assert rec is not None
    assert rec["property_type"] == "house"
    assert rec["bedrooms"] == 3
    assert rec["bathrooms"] == 2.0
    assert rec["parking_spaces"] == 2
    assert rec["built_area_m2"] == 169.0
    # Lot area still populates raw_size_text (downstream normalize fills area_m2)
    assert "300" in rec["raw_size_text"]


def test_parse_detail_condo_populates_type_specific_fields():
    html = _detail_html(
        h3_title="Apartamento Costa del Sol. En Venta",
        dets=_coastal_condo_dets(),
    )
    partial = {
        "source_id": "001234567891",
        "url": "https://www.remax-elsalvador.com/001234567891",
        "title": "Apartamento Costa del Sol",
        "raw_price_text": "$ 285,000.00",
        "price_usd": 285000.0,
        "_source_property_type": "condo",
    }
    rec = _parse_detail(html, partial)
    assert rec is not None
    assert rec["property_type"] == "condo"
    assert rec["bedrooms"] == 2
    assert rec["bathrooms"] == 2.0
    assert rec["built_area_m2"] == 85.0


def test_parse_detail_built_area_v2_converted_to_m2():
    """Built area in 'Sq. Vr.' (varas²) must be converted to m² before
    landing in built_area_m2 — the field name promises m²."""
    dets = _coastal_house_dets(**{"Tamaño de Construcción": "200.00 Sq. Vr."})
    html = _detail_html(
        h3_title="Casa Costa del Sol. En Venta",
        dets=dets,
    )
    partial = {
        "source_id": "x", "url": "https://x.com/y",
        "title": "Casa Costa del Sol", "raw_price_text": "",
        "_source_property_type": "house",
    }
    rec = _parse_detail(html, partial)
    # 200 v² × 0.6987 = 139.74 m²
    assert rec["built_area_m2"] == 139.74


def test_parse_detail_built_area_zero_treated_as_missing():
    """Many remax houses ship '0.00 Sq. Vr.' as a placeholder for unknown.
    Treat as missing rather than zero — flagging would cascade."""
    dets = _coastal_house_dets(**{"Tamaño de Construcción": "0.00 Sq. Vr."})
    html = _detail_html(
        h3_title="Casa El Tunco. En Venta",
        dets=dets,
    )
    partial = {
        "source_id": "x", "url": "https://x.com/y",
        "title": "Casa El Tunco", "raw_price_text": "",
        "_source_property_type": "house",
    }
    rec = _parse_detail(html, partial)
    assert "built_area_m2" not in rec, "0.00 must not become built_area_m2=0.0"


def test_parse_detail_drops_inland_house_with_no_beachfront_keyword():
    """Per spec: house/condo not in VACATION_ZONES AND no waterfront
    keyword must be DROPPED. Inland house in Soyapango, no beach/lake
    reference → skip."""
    dets = _coastal_house_dets(**{"Tipo de Propiedad": "Casa/Villa"})
    html = _detail_html(
        h3_title="Casa moderna en Soyapango. En Venta",  # inland city
        dets=dets,
    )
    partial = {
        "source_id": "x", "url": "https://x.com/y",
        "title": "Casa moderna en Soyapango",  # no coastal zone, no beachfront kw
        "raw_price_text": "",
        "_source_property_type": "house",
    }
    rec = _parse_detail(html, partial)
    assert rec is None


def test_parse_detail_keeps_house_with_beachfront_keyword_outside_coastal_zones():
    """Beachfront-keyword fallback: a house in an unnamed-zone location
    that mentions 'frente al mar' in the title survives the coastal filter."""
    dets = _coastal_house_dets()
    html = _detail_html(
        h3_title="Casa frente al mar Acajutla. En Venta",  # 'frente al mar' triggers fallback
        dets=dets,
    )
    partial = {
        "source_id": "x", "url": "https://x.com/y",
        "title": "Casa frente al mar Acajutla",
        "raw_price_text": "",
        "_source_property_type": "house",
    }
    rec = _parse_detail(html, partial)
    assert rec is not None
    assert rec["property_type"] == "house"


def test_parse_detail_emits_classifier_signals_for_house():
    """Classifier runs after broker-type decision; signals + confidence
    land on the record for the shadow log."""
    html = _detail_html(
        h3_title="Casa El Tunco. En Venta",
        dets=_coastal_house_dets(),
    )
    partial = {
        "source_id": "x", "url": "https://x.com/casa-el-tunco",
        "title": "Casa El Tunco", "raw_price_text": "",
        "_source_property_type": "house",
    }
    rec = _parse_detail(html, partial)
    assert "_type_signals" in rec
    assert "_type_confidence" in rec
    assert rec["_type_confidence"] in {"high", "medium", "low", "uncertain"}


def test_parse_detail_land_path_unchanged_no_type_specific_fields():
    """Regression guard: land listings (the 306 production rows) must not
    gain bedrooms/bathrooms/built_area_m2 — type-specific extraction is
    gated on broker_type in ('house', 'condo')."""
    # Land detail page never carries Habitaciones/Baños — but if a malformed
    # one did, we shouldn't pick them up either.
    html = _detail_html(
        h3_title="Terreno El Tunco. En Venta",
        dets={
            "Código de la propiedad": "001",
            "Tipo de Propiedad":      "Lote/Terreno",
            "Tipo de Contrato":       "En Venta",
            "Precio":                 "$ 50,000.00",
            "Tamaño de lote":         "1000.00 Sq. Mt.",
            # Hostile inputs that shouldn't populate:
            "Habitaciones":           "99",
            "Baños":                  "99",
            "Tamaño de Construcción": "999.00 Sq. Mt.",
        },
    )
    partial = {
        "source_id": "001", "url": "https://x.com/terreno",
        "title": "Terreno El Tunco", "raw_price_text": "",
        "_source_property_type": "land",
    }
    rec = _parse_detail(html, partial)
    assert rec is not None
    assert rec["property_type"] == "land"
    assert "bedrooms" not in rec
    assert "bathrooms" not in rec
    assert "built_area_m2" not in rec


def test_prop_type_ids_to_fetch_covers_three_types():
    """Lock the (id, label) mapping. Audited live 2026-05-06 — IDs 1/2/3
    map to house/condo/land respectively. ID 4 is heterogeneous and
    intentionally excluded for now."""
    from pulpo.scrapers.remax import PROP_TYPE_IDS_TO_FETCH
    by_label = {label: type_id for type_id, label in PROP_TYPE_IDS_TO_FETCH}
    assert by_label == {"land": "3", "house": "1", "condo": "2"}, (
        "PROP_TYPE_IDS_TO_FETCH mapping changed — re-audit live remax"
    )
