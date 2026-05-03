"""
Tests for the Nexo Inmobiliario scraper (pulpo/scrapers/nexo.py).

Runs in offline mode against the fixture in
samples/calibration/nexo/sample_listings.json.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.nexo import NexoScraper, _parse_listing_page, _abs  # noqa: E402


# ── Offline fixture crawl ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def offline_records():
    scraper = NexoScraper(offline=True)
    return scraper.crawl(limit=10, offline=True)


def test_offline_returns_records(offline_records):
    assert len(offline_records) >= 1


def test_required_fields_present(offline_records):
    for r in offline_records:
        assert r.get("source_id"), f"Missing source_id: {r}"
        assert r.get("url", "").startswith("https://nexo.com.sv"), f"Bad url: {r}"
        assert r.get("title"), f"Missing title: {r}"
        assert r.get("property_type") == "land"
        assert isinstance(r.get("photo_urls"), list), "photo_urls must be a list"
        assert r.get("location_text"), "location_text must not be empty"


def test_photo_urls_are_absolute(offline_records):
    """All photo URLs must be absolute (https://...) and non-empty when present."""
    for r in offline_records:
        for u in r.get("photo_urls", []):
            assert u.startswith("https://"), f"Non-absolute photo URL: {u}"


def test_no_thumbnail_in_photo_urls(offline_records):
    """Hero photo URL must not be the thumbnail variant."""
    for r in offline_records:
        for u in r.get("photo_urls", []):
            assert "_thumbnail" not in u, f"Thumbnail in photo_urls: {u}"


def test_el_salvador_in_location(offline_records):
    """El Salvador must appear in location_text for every listing."""
    for r in offline_records:
        assert "El Salvador" in r.get("location_text", ""), (
            f"El Salvador missing from location: {r['location_text']!r}"
        )


def test_price_text_contains_dollar(offline_records):
    for r in offline_records:
        if r.get("raw_price_text"):
            assert "$" in r["raw_price_text"], f"Price text missing $: {r['raw_price_text']!r}"


# ── Unit tests for helper functions ───────────────────────────────────

def test_abs_resolves_relative():
    assert _abs("../nexocrm/imagenes/x.jpg") == "https://nexo.com.sv/nexocrm/imagenes/x.jpg"


def test_abs_passthrough_absolute():
    url = "https://nexo.com.sv/images/logo.png"
    assert _abs(url) == url


def test_abs_empty_string():
    assert _abs("") == ""


def test_parse_listing_page_minimal_html():
    """Parser must return empty list (not crash) on minimal/empty HTML."""
    result = _parse_listing_page("<html><body></body></html>")
    assert result == []


def test_photo_urls_empty_list_when_no_photos():
    """If no image in the card, photo_urls must be [] not None."""
    html = """<div class="dresultado">
      <h2 itemprop="name">Test Terreno</h2>
      <a href="../6/99/Test-Terreno">VER</a>
      <P class="price">US<span itemprop="price">$50,000</span></P>
    </div>"""
    records = _parse_listing_page(html)
    if records:
        assert isinstance(records[0]["photo_urls"], list)
