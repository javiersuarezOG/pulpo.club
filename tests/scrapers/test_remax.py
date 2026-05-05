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
