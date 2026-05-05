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
