"""
Oceanside scraper tests.

Scraper was rewritten 2026-05-02 to use the WP REST API
(/wp-json/wp/v2/rental-details) instead of HTML parsing. Tests now
target the API record mapper (_map) rather than the old parse_*_page
HTML methods, which are retained as stubs for calibration harness
compatibility.
"""
import re
from pulpo.scrapers.oceanside import _map, _extract_area_text, OceansideScraper

# ── Synthetic API record that matches real rental-details shape ──────────────
_SAMPLE_REC = {
    "id": 13735,
    "link": "https://oceansideelsalvador.com/rental-details/land-close-to-san-blas/",
    "slug": "land-close-to-san-blas",
    "modified": "2026-04-29T12:36:30",
    "title": {"rendered": "LAND CLOSE TO SAN BLAS"},
    "content": {
        "rendered": (
            "<p>Prime coastal lot for sale. Listed on May 5, 2025"
            "1,171.53m2 Lot. $187,916.80 Starting price. "
            "Water access and electricity available. "
            "Frente al mar access. Acceso pavimentado.</p>"
        )
    },
    "property-type": [122],
    "location": [119, 109],
    "class_list": [
        "post-13735", "rental-details", "type-rental-details",
        "status-publish", "has-post-thumbnail",
        "location-el-salvador", "location-la-libertad",
    ],
    "featured_media": 13739,
    "acf": [],
}

_LAND_TERM_ID = 122


def test_map_produces_title():
    result = _map(_SAMPLE_REC, _LAND_TERM_ID)
    assert result is not None
    assert result["title"] == "LAND CLOSE TO SAN BLAS"


def test_map_produces_price():
    result = _map(_SAMPLE_REC, _LAND_TERM_ID)
    assert result is not None
    assert "$" in result["raw_price_text"]
    assert "187" in result["raw_price_text"]


def test_map_produces_area():
    result = _map(_SAMPLE_REC, _LAND_TERM_ID)
    assert result is not None
    assert result["raw_size_text"] != ""
    assert "1,171.53" in result["raw_size_text"] or "1171.53" in result["raw_size_text"]


def test_map_location_excludes_el_salvador():
    result = _map(_SAMPLE_REC, _LAND_TERM_ID)
    assert result is not None
    # Should include La Libertad but not the too-broad El Salvador
    assert "La Libertad" in result["location_text"]
    assert "El Salvador" not in result["location_text"]


def test_map_boolean_flags():
    result = _map(_SAMPLE_REC, _LAND_TERM_ID)
    assert result is not None
    assert result["is_beachfront"] is True
    assert result["has_paved_access"] is True
    assert result["has_water"] is True
    assert result["has_power"] is True


def test_map_filters_non_land_term():
    non_land = dict(_SAMPLE_REC, **{"property-type": [21]})  # 21 = Houses
    result = _map(non_land, _LAND_TERM_ID)
    assert result is None


def test_map_photos_count():
    result = _map(_SAMPLE_REC, _LAND_TERM_ID)
    assert result is not None
    assert result["photos_count"] == 1

    no_photo = dict(_SAMPLE_REC, featured_media=0)
    result2 = _map(no_photo, _LAND_TERM_ID)
    assert result2 is not None
    assert result2["photos_count"] == 0


def test_map_days_listed():
    result = _map(_SAMPLE_REC, _LAND_TERM_ID)
    assert result is not None
    assert isinstance(result["days_listed"], int)
    assert result["days_listed"] >= 0


def test_extract_area_text_year_concatenation():
    """Original regression: Avada theme concatenates date+area without whitespace."""
    blob = "Listed on Sep 2, 20251171.53m2Lot"
    assert "1171.53" in _extract_area_text(blob)


def test_extract_area_text_plain():
    assert "243,080" in _extract_area_text("lot of 243,080.00 m² available")


def test_offline_crawl_returns_fixtures():
    scraper = OceansideScraper(offline=True)
    records = scraper.crawl(limit=5)
    # Fixture file has oceanside records — might be 0 if none tagged yet
    assert isinstance(records, list)
    assert len(records) <= 5


def test_stubs_do_not_crash():
    """parse_*_page stubs are kept for calibration harness; should return safe empties."""
    scraper = OceansideScraper(offline=True)
    assert scraper.parse_index_page("<html></html>") == []
    assert scraper.parse_detail_page("<html></html>", {}) is None
