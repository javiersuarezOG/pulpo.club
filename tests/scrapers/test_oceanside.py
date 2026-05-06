"""
Oceanside scraper tests.

Scraper was rewritten 2026-05-02 to use the WP REST API
(/wp-json/wp/v2/rental-details) instead of HTML parsing. Tests now
target the API record mapper (_map) rather than the old parse_*_page
HTML methods, which are retained as stubs for calibration harness
compatibility.
"""
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


# ── Phase C: house + condo broadening ──────────────────────────────────
# Adds /home-details CPT crawl alongside the existing /rental-details.
# Type-specific fields (bedrooms, bathrooms) regex-extracted from the
# unstructured content_text — oceanside has no ACF blob like AlterEstate.
# Live recon (2026-05-06): /home-details has ~38 records; the property-type
# taxonomy includes id=21 Houses (33), id=8 Apartments (7), id=114 Condo (3),
# id=116 Beach Villa (5). Hotels/Restaurants/Commercial-Land excluded.

from pulpo.scrapers.oceanside import (  # noqa: E402
    _BEDROOMS_RE, _BATHROOMS_RE, _HOUSE_SLUGS, _CONDO_SLUGS, _LAND_SLUGS,
)
# _map already imported at module top.


def _coastal_house_record(**override) -> dict:
    """Synthetic /home-details record — coastal location, has bed/bath
    keywords in content. Used to verify the broker_type='house' path."""
    base = {
        "id": 99001,
        "title":   {"rendered": "Beautiful Beach House in El Tunco"},
        "content": {"rendered": "<p>Stunning 3 bedroom 2 bath house frente al mar.</p>"},
        "link":    "https://oceansideelsalvador.com/home-details/beach-house-el-tunco/",
        "modified": "2026-04-01T12:00:00",
        "class_list": ["location-la-libertad"],
        "property-type": [21],  # Houses
        "featured_media": 12345,
    }
    base.update(override)
    return base


def _coastal_condo_record(**override) -> dict:
    base = {
        "id": 99002,
        "title":   {"rendered": "Luxury Oceanfront Condo Costa del Sol"},
        "content": {"rendered": "<p>Modern 2 bedroom 2 bath beachfront apartment.</p>"},
        "link":    "https://oceansideelsalvador.com/home-details/condo-costa-del-sol/",
        "modified": "2026-04-15T12:00:00",
        "class_list": ["location-la-paz"],
        "property-type": [8, 114],  # Apartments + Condo
        "featured_media": 12346,
    }
    base.update(override)
    return base


def test_house_condo_slug_sets_disjoint_from_land():
    """Guard against accidental overlap when adding new slugs."""
    assert _HOUSE_SLUGS.isdisjoint(_CONDO_SLUGS)
    assert _HOUSE_SLUGS.isdisjoint(_LAND_SLUGS)
    assert _CONDO_SLUGS.isdisjoint(_LAND_SLUGS)


def test_bedrooms_regex_handles_common_phrasings():
    for blob, expected in [
        ("3 bedroom house", "3"),
        ("2 beds 2 baths",  "2"),
        ("4-bed villa",     "4"),
        ("with 3 habitaciones", "3"),
        ("5 recamaras",     "5"),
        ("3BR oceanfront",  "3"),
    ]:
        m = _BEDROOMS_RE.search(blob)
        assert m, f"bedrooms regex failed on {blob!r}"
        assert m.group(1) == expected, f"{blob!r} → {m.group(1)} (expected {expected})"


def test_bathrooms_regex_handles_common_phrasings():
    for blob, expected in [
        ("2 bath",            "2"),
        ("2.5 bathrooms",     "2.5"),
        ("3 baños",           "3"),
        ("with 1 ba",         "1"),
    ]:
        m = _BATHROOMS_RE.search(blob)
        assert m, f"bathrooms regex failed on {blob!r}"
        assert m.group(1) == expected


def test_map_coastal_house_populates_type_specific_fields():
    """House in El Tunco (a COASTAL_ZONE) survives the coastal filter
    and lands the regex-extracted bedrooms + bathrooms."""
    out = _map(_coastal_house_record(), land_term_id=122, broker_type="house")
    assert out is not None
    assert out["property_type"] == "house"
    assert out["bedrooms"] == 3
    assert out["bathrooms"] == 2.0


def test_map_coastal_condo_populates_type_specific_fields():
    out = _map(_coastal_condo_record(), land_term_id=122, broker_type="condo")
    assert out is not None
    assert out["property_type"] == "condo"
    assert out["bedrooms"] == 2
    assert out["bathrooms"] == 2.0


def test_map_drops_inland_house_with_no_beachfront_keyword():
    """Per spec: house/condo not in COASTAL_ZONES AND no beachfront keyword
    must be DROPPED. Synthetic inland house in San Salvador, generic
    description with no beach reference → skip."""
    rec = _coastal_house_record(
        title={"rendered": "Modern house in San Salvador"},
        content={"rendered": "<p>Spacious 3 bedroom home in colonia residencial.</p>"},
        class_list=["location-san-salvador"],
    )
    out = _map(rec, land_term_id=122, broker_type="house")
    assert out is None


def test_map_keeps_house_with_beachfront_keyword_outside_coastal_zones():
    """Beachfront-keyword fallback: an inland-zoned house mentioning
    'frente al mar' in description still passes the coastal filter."""
    rec = _coastal_house_record(
        title={"rendered": "Casa Acajutla"},
        content={"rendered": "<p>3 bedroom house frente al mar.</p>"},
        class_list=["location-sonsonate"],  # not in COASTAL_ZONES
    )
    out = _map(rec, land_term_id=122, broker_type="house")
    assert out is not None
    assert out["property_type"] == "house"


def test_map_emits_classifier_signals_for_built():
    out = _map(_coastal_house_record(), land_term_id=122, broker_type="house")
    assert "_type_signals" in out
    assert "_type_confidence" in out
    assert out["_type_confidence"] in {"high", "medium", "low", "uncertain"}


def test_map_land_path_unchanged_no_type_specific_fields():
    """Regression guard for the existing 13 land listings — land must
    not gain bedrooms/bathrooms even if the content has those keywords
    by coincidence (e.g. 'lot suitable for 3 bedroom build')."""
    rec = {
        "id": 12345,
        "title":   {"rendered": "Lot in El Tunco"},
        "content": {"rendered": "<p>Lot suitable for 3 bedroom build, 1500 m².</p>"},
        "link":    "https://oceansideelsalvador.com/rental-details/lot-el-tunco/",
        "modified": "2026-04-20T12:00:00",
        "class_list": ["location-la-libertad"],
        "property-type": [122],
        "featured_media": 12347,
    }
    out = _map(rec, land_term_id=122, broker_type="land")
    assert out is not None
    assert out["property_type"] == "land"
    assert "bedrooms" not in out
    assert "bathrooms" not in out
