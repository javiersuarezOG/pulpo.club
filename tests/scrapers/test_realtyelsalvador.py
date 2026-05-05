"""
Tests for the Realty El Salvador scraper (pulpo/scrapers/realtyelsalvador.py).

Runs in offline mode against the fixture in
samples/calibration/realtyelsalvador/sample_listings.json.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.realtyelsalvador import (  # noqa: E402
    RealtyElSalvadorScraper,
    _map,
    _is_land,
    _extract_photo_urls,
    _API_HEADERS,
)


# ── Offline fixture crawl ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def offline_records():
    scraper = RealtyElSalvadorScraper(offline=True)
    return scraper.crawl(limit=10, offline=True)


def test_offline_returns_records(offline_records):
    assert len(offline_records) >= 1


def test_required_fields_present(offline_records):
    for r in offline_records:
        assert r.get("source_id"), f"Missing source_id: {r}"
        assert r.get("url", "").startswith("https://realtyelsalvador.com"), f"Bad url: {r}"
        assert r.get("title"), "Missing title"
        assert r.get("property_type") == "land"
        assert isinstance(r.get("photo_urls"), list), "photo_urls must be a list"


def test_el_salvador_in_location(offline_records):
    for r in offline_records:
        assert "El Salvador" in r.get("location_text", ""), (
            f"El Salvador missing: {r['location_text']!r}"
        )


def test_photo_urls_absolute_when_present(offline_records):
    for r in offline_records:
        for u in r.get("photo_urls", []):
            assert u.startswith("https://"), f"Non-absolute photo URL: {u}"


def test_empty_photo_urls_is_list_not_none(offline_records):
    """Listings with no photos must have photo_urls=[] not None."""
    no_photo = [r for r in offline_records if not r.get("photo_urls")]
    for r in no_photo:
        assert r["photo_urls"] == [], f"photo_urls must be [] not {r['photo_urls']!r}"


# ── _is_land unit tests ───────────────────────────────────────────────

def _fake_rec(term_slug: str, link: str = "") -> dict:
    return {
        "status": "publish",
        "link": link,
        "_embedded": {
            "wp:term": [[{"taxonomy": "tipo-de-propiedad", "slug": term_slug, "name": term_slug}]],
            "wp:featuredmedia": [],
        },
        "tipo-de-propiedad": [],
    }


def test_is_land_terreno():
    assert _is_land(_fake_rec("terrenos"))


def test_is_land_lote():
    assert _is_land(_fake_rec("lotes"))


def test_is_land_false_for_casa():
    rec = _fake_rec("casas")
    rec["link"] = "https://realtyelsalvador.com/propiedades/casa-en-venta"
    assert not _is_land(rec)


def test_is_land_fallback_url():
    """If taxonomy is ambiguous, URL containing 'terreno' should pass."""
    rec = _fake_rec("uncategorized", link="https://realtyelsalvador.com/propiedades/terreno-san-miguel")
    assert _is_land(rec)


# ── _map unit tests ───────────────────────────────────────────────────

def _minimal_record(property_meta: dict | None = None) -> dict:
    return {
        "id": 99999,
        "status": "publish",
        "link": "https://realtyelsalvador.com/propiedades/test-terreno/",
        "title": {"rendered": "Test Terreno"},
        "excerpt": {"rendered": "<p>Test description.</p>"},
        "content": {"rendered": ""},
        "modified_gmt": "2026-01-01T12:00:00",
        "property_meta": property_meta or {
            "REAL_HOMES_property_price": "50000",
            "REAL_HOMES_property_size": "500",
            "REAL_HOMES_property_size_postfix": "metros cuadrados",
            "REAL_HOMES_property_images": [],
        },
        "_embedded": {
            "wp:term": [[{"taxonomy": "tipo-de-propiedad", "slug": "terrenos", "name": "Terrenos"}]],
            "wp:featuredmedia": [],
        },
    }


def test_map_returns_dict_for_land():
    rec = _minimal_record()
    result = _map(rec)
    assert result is not None
    assert result["source_id"] == "99999"
    assert result["price_usd"] == 50000.0


def test_map_returns_none_for_house():
    rec = _minimal_record()
    rec["_embedded"]["wp:term"] = [[{"taxonomy": "tipo-de-propiedad", "slug": "casas", "name": "Casas"}]]
    rec["link"] = "https://realtyelsalvador.com/propiedades/casa-en-la-libertad/"
    result = _map(rec)
    assert result is None


def test_map_returns_none_for_draft():
    rec = _minimal_record()
    rec["status"] = "draft"
    assert _map(rec) is None


def test_map_price_none_when_missing():
    rec = _minimal_record({"REAL_HOMES_property_price": "", "REAL_HOMES_property_images": []})
    result = _map(rec)
    assert result is not None
    assert result["price_usd"] is None


def test_map_photo_urls_is_list_always():
    rec = _minimal_record()
    result = _map(rec)
    assert isinstance(result["photo_urls"], list)


def test_extract_photo_urls_from_featured_media():
    rec = {
        "_embedded": {
            "wp:featuredmedia": [{"source_url": "https://realtyelsalvador.com/wp-content/uploads/hero.jpg"}],
        },
        "property_meta": {"REAL_HOMES_property_images": []},
    }
    urls = _extract_photo_urls(rec)
    assert "https://realtyelsalvador.com/wp-content/uploads/hero.jpg" in urls


def test_extract_photo_urls_deduplicates():
    same_url = "https://realtyelsalvador.com/wp-content/uploads/photo.jpg"
    rec = {
        "_embedded": {
            "wp:featuredmedia": [{"source_url": same_url}],
        },
        "property_meta": {
            "REAL_HOMES_property_images": [{"source_url": same_url, "file": "photo.jpg", "sizes": {}}],
        },
    }
    urls = _extract_photo_urls(rec)
    assert urls.count(same_url) == 1


# ── Anti-403 headers ────────────────────────────────────────────────────
# The two prior nightlies returned 0 listings due to HTTP 403 from
# realtyelsalvador.com when the API is hit from GitHub Actions runner IPs.
# These tests pin the headers we send so a future cleanup doesn't silently
# strip them and reintroduce the regression.

def test_api_headers_include_browser_realistic_ua():
    """Pulpo's default UA returned 403 from runner IPs. The Safari UA in
    _API_HEADERS is the workaround. If this assertion fails the request
    will go out with whatever fallback the client supplies, very likely
    triggering the WAF block again."""
    assert "Mozilla/5.0" in _API_HEADERS["User-Agent"]
    assert "Safari" in _API_HEADERS["User-Agent"]


def test_api_headers_include_referer_and_sec_fetch():
    """Referer + Sec-Fetch-* headers are commonly weighted by WordPress /
    Cloudflare bot scoring. Pin them so a refactor doesn't drop them."""
    assert _API_HEADERS["Referer"].startswith("https://realtyelsalvador.com")
    assert _API_HEADERS["Sec-Fetch-Mode"] == "cors"
    assert _API_HEADERS["Sec-Fetch-Site"] == "same-origin"
    assert _API_HEADERS["Accept"].startswith("application/json")
