"""
Tests for the Realty El Salvador HTML scraper (pulpo/scrapers/realtyelsalvador.py).

Two layers:
1. Offline-fixture crawl — same contract as the other scrapers
   (load from ``fixtures/sample_listings.json``).
2. Calibration-HTML parsers — exercise ``parse_archive_urls`` and
   ``parse_detail`` against real captured HTML in
   ``samples/calibration/realtyelsalvador/``. This protects against
   selector / JSON-LD shape drift even when the offline-fixture path
   passes (the fixture has no HTML, so a parser regression would
   otherwise ship silently).
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.realtyelsalvador import (  # noqa: E402
    RealtyElSalvadorScraper,
    parse_archive_urls,
    parse_detail,
    _extract_jsonld,
    _extract_postid,
    _extract_photos,
    _parse_price_usd,
    _parse_size_text,
    _parse_location,
    _PHOTO_URL_RE,
)


CALIBRATION_DIR = REPO / "samples" / "calibration" / "realtyelsalvador"
ARCHIVE_HTML    = CALIBRATION_DIR / "archive_page_1.html"
DETAIL_HTML     = CALIBRATION_DIR / "detail_terreno_chinameca.html"


# ── Offline fixture crawl (unchanged contract) ─────────────────────────


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


# ── Archive-page parser ────────────────────────────────────────────────


def test_parse_archive_urls_returns_unique_detail_urls():
    pytest.importorskip("selectolax")
    if not ARCHIVE_HTML.exists():
        pytest.skip("calibration archive HTML not present")
    html = ARCHIVE_HTML.read_text(encoding="utf-8")
    urls = parse_archive_urls(html)
    assert len(urls) >= 1, "no listing URLs found in archive HTML"
    # No duplicates.
    assert len(urls) == len(set(urls))
    # All match the expected detail-URL pattern.
    for u in urls:
        assert u.startswith("https://realtyelsalvador.com/propiedades/"), u
        assert u.endswith("/"), u


def test_parse_archive_urls_skips_non_listing_links():
    """Hits to /tipo-de-propiedad/, /lista-de-propiedades/, social links,
    etc. must not be returned. Easy regression to ship if someone widens
    the regex without thinking."""
    html = (
        '<a href="https://realtyelsalvador.com/tipo-de-propiedad/terrenos/">Land</a>'
        '<a href="https://realtyelsalvador.com/propiedades/test-listing/">Listing</a>'
        '<a href="https://facebook.com/ventadecasas">FB</a>'
    )
    urls = parse_archive_urls(html)
    assert urls == ["https://realtyelsalvador.com/propiedades/test-listing/"]


# ── Detail-page parser ─────────────────────────────────────────────────


def test_parse_detail_against_calibration_html():
    if not DETAIL_HTML.exists():
        pytest.skip("calibration detail HTML not present")
    html = DETAIL_HTML.read_text(encoding="utf-8")
    url = "https://realtyelsalvador.com/propiedades/terreno-de-montana-con-arboles-frutales-en-valle-el-boqueron-a-6-min-de-chinameca/"
    rec = parse_detail(html, url)
    assert rec is not None
    assert rec["source_id"] == "14194"
    assert rec["url"] == url
    assert "Boquerón" in rec["title"] or "Boqueron" in rec["title"]
    assert rec["property_type"] == "land"
    assert rec["price_usd"] == 40000.0
    assert "$40000" in rec["raw_price_text"]
    assert "3,444" in rec["raw_size_text"] or "3444" in rec["raw_size_text"]
    assert "metros" in rec["raw_size_text"].lower()
    assert "El Salvador" in rec["location_text"]
    # Chinameca is the locality.
    assert "Chinameca" in rec["location_text"]


def test_parse_detail_returns_none_without_jsonld():
    html = "<html><body>no structured data</body></html>"
    assert parse_detail(html, "https://realtyelsalvador.com/propiedades/x/") is None


def test_parse_detail_returns_none_without_title():
    html = '<script type="application/ld+json">{"@type":"RealEstateListing","name":""}</script>'
    assert parse_detail(html, "https://realtyelsalvador.com/propiedades/x/") is None


def test_extract_jsonld_picks_realestate_listing_from_array():
    """Some WP pages emit a JSON-LD list — Organization first, then
    RealEstateListing. We must pick the latter."""
    html = '''
    <script type="application/ld+json">
    [{"@type":"Organization","name":"Realty"},
     {"@type":"RealEstateListing","name":"X","offers":{"price":"1"}}]
    </script>
    '''
    blob = _extract_jsonld(html)
    assert blob is not None
    assert blob["@type"] == "RealEstateListing"
    assert blob["name"] == "X"


def test_extract_postid_from_body_class():
    html = '<body class="post-template-default single single-propiedades postid-12345 ">'
    assert _extract_postid(html) == "12345"


def test_extract_postid_falls_back_to_slug_when_missing():
    """When no postid is in the body class, parse_detail must still
    produce a stable source_id — it builds one from the URL slug."""
    html = '<script type="application/ld+json">{"@type":"RealEstateListing","name":"X"}</script>'
    url = "https://realtyelsalvador.com/propiedades/cool-terreno-12345/"
    rec = parse_detail(html, url)
    assert rec is not None
    assert rec["source_id"] == "slug:cool-terreno-12345"


# ── Photo extraction ──────────────────────────────────────────────────


def test_photo_url_regex_only_matches_file_prefix():
    """Theme assets (agent headshots ``img-wendy-de-velis-*``, favicons
    ``cropped-img-*``) must NOT bleed into our gallery."""
    assert _PHOTO_URL_RE.match(
        "https://realtyelsalvador.com/wp-content/uploads/file-1773964123.jpeg"
    )
    assert not _PHOTO_URL_RE.match(
        "https://realtyelsalvador.com/wp-content/uploads/img-wendy-de-velis-1717986023.jpg"
    )
    assert not _PHOTO_URL_RE.match(
        "https://realtyelsalvador.com/wp-content/uploads/cropped-img-1717986358.png"
    )


def test_extract_photos_strips_size_suffix():
    """Wordpress generates -WIDTHxHEIGHT thumbnails for the same source
    photo. We dedupe to the canonical filename so the photo upgrader
    sees one entry per real photo, not 8."""
    html = (
        '<meta property="og:image" content="https://realtyelsalvador.com/wp-content/uploads/file-12345.jpg">'
        '<img src="https://realtyelsalvador.com/wp-content/uploads/file-12345-150x150.jpg">'
        '<img src="https://realtyelsalvador.com/wp-content/uploads/file-12345-300x300.jpg">'
    )
    photos = _extract_photos(html)
    assert photos == ["https://realtyelsalvador.com/wp-content/uploads/file-12345.jpg"]


def test_extract_photos_against_calibration_html():
    if not DETAIL_HTML.exists():
        pytest.skip("calibration detail HTML not present")
    html = DETAIL_HTML.read_text(encoding="utf-8")
    photos = _extract_photos(html)
    assert len(photos) >= 1, "expected at least one listing photo"
    # Hero (og:image) must come first.
    assert "file-1773964123" in photos[0]
    # No theme-asset leakage.
    for p in photos:
        assert "wendy-de-velis" not in p, f"agent headshot leaked into gallery: {p}"
        assert "cropped-img" not in p, f"favicon leaked into gallery: {p}"


# ── JSON-LD field parsers ──────────────────────────────────────────────


def test_parse_price_usd_handles_string_and_dict():
    assert _parse_price_usd({"offers": {"price": "50000"}})        == (50000.0, "$50000")
    assert _parse_price_usd({"offers": {"price": "50,000"}})       == (50000.0, "$50000")
    assert _parse_price_usd({"offers": {"price": ""}})             == (None, "")
    assert _parse_price_usd({"offers": {"price": "not-a-number"}}) == (None, "")
    assert _parse_price_usd({"offers": {}})                        == (None, "")


def test_parse_size_text_handles_metros_cuadrados():
    jsonld = {
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "Area Size", "value": "3,444", "unitText": "metros cuadrados"}
        ]
    }
    assert "3,444" in _parse_size_text(jsonld)
    assert "metros cuadrados" in _parse_size_text(jsonld)


def test_parse_size_text_returns_empty_when_no_area():
    assert _parse_size_text({}) == ""
    assert _parse_size_text({"additionalProperty": [{"name": "Other", "value": "1"}]}) == ""


def test_parse_location_appends_el_salvador():
    assert _parse_location({"address": {"addressLocality": "Chinameca"}}) == "Chinameca, El Salvador"
    assert _parse_location({"address": {"addressLocality": "Chinameca", "addressRegion": "San Miguel"}}) == "Chinameca, San Miguel, El Salvador"
    assert _parse_location({}) == "El Salvador"
    # Already includes El Salvador — don't double-suffix.
    assert _parse_location({"address": {"addressLocality": "El Salvador"}}).count("El Salvador") == 1
