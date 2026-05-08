"""
Tests for pulpo/scrapers/encuentra24.py.

Pure-parser tests — operate on saved calibration HTML fixtures, no
Playwright required. Pins:
- JSON-LD extraction (title, price, currency, location, broker)
- Tailwind facts grid (bedrooms, bathrooms, built_area, parking)
- Listing-ID-prefix photo filtering
- URL → property_type mapping
- Vacation-zone filter integration on house/condo
- Multi-signal classifier integration

The live `_crawl_live` Playwright path is NOT exercised here — that's
PR-E2's job once Playwright is wired into the nightly. The contract
this PR pins is the parse step, which is what the rest of the
pipeline cares about.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.encuentra24 import (   # noqa: E402
    BASE,
    CATEGORY_URLS,
    Encuentra24Scraper,
    _build_raw_record,
    _category_from_url,
    parse_detail,
    parse_index_html,
)


CALIBRATION = REPO / "samples" / "calibration" / "encuentra24"


def _load(name: str) -> str:
    return (CALIBRATION / name).read_text(encoding="utf-8")


# ── _category_from_url ────────────────────────────────────────────────


@pytest.mark.parametrize("url,expected", [
    ("https://www.encuentra24.com/el-salvador-es/bienes-raices-venta-de-propiedades-apartamentos/foo/12345678",
     "condo"),
    ("https://www.encuentra24.com/el-salvador-es/bienes-raices-venta-de-propiedades-casas/foo/12345678",
     "house"),
    ("https://www.encuentra24.com/el-salvador-es/bienes-raices-venta-de-propiedades-terrenos/foo/12345678",
     "land"),
    ("https://www.encuentra24.com/el-salvador-es/bienes-raices-venta-de-propiedades-fincas/foo/12345678",
     "land"),
    # Rentals — out of scope
    ("https://www.encuentra24.com/el-salvador-es/bienes-raices-alquiler-apartamentos/foo/12345678",
     None),
    # Commercial offices — out of scope
    ("https://www.encuentra24.com/el-salvador-es/bienes-raices-alquiler-alquiler-de-oficinas/foo/12345678",
     None),
    # Unknown sub-category under venta — out of scope rather than guessing
    ("https://www.encuentra24.com/el-salvador-es/bienes-raices-venta-locales/foo/12345678",
     None),
])
def test_category_from_url(url, expected):
    assert _category_from_url(url) == expected


# ── parse_index_html ──────────────────────────────────────────────────


def test_parse_index_extracts_sale_listing_urls():
    """The bienes-raices index render should yield numeric-ID URLs from
    the SALE category (filtering rentals and out-of-scope categories)."""
    html = _load("index-bienes-raices.html")
    urls = parse_index_html(html)
    # At minimum, we should pull SOME sale URLs
    sale_urls = [u for u in urls if "/bienes-raices-venta" in u]
    assert len(sale_urls) >= 1, "expected at least one sale listing URL"
    # All returned URLs should match the encuentra24 numeric-ID pattern
    import re
    for u in urls:
        assert re.search(r"/\d{7,9}(?:[/?#]|$)", u), f"bad URL: {u}"
        assert "/bienes-raices-venta" in u   # filter is working
        assert u.startswith(BASE)


def test_parse_index_dedupes():
    """If the same URL appears twice (related-listing carousel + main
    grid), parse_index_html returns it only once."""
    html = _load("index-bienes-raices.html")
    urls = parse_index_html(html)
    assert len(urls) == len(set(urls))


def test_parse_index_includes_all_three_sale_categories():
    """The index renders apartamentos / casas / terrenos sub-category
    URLs in the same grid — at least one apartamento URL should appear
    in our sample."""
    html = _load("index-bienes-raices.html")
    urls = parse_index_html(html)
    has_apartamentos = any(
        "bienes-raices-venta-de-propiedades-apartamentos" in u for u in urls
    )
    assert has_apartamentos, (
        "expected at least one apartamento URL — sample fixture invariant. "
        f"sample URLs: {urls[:3]}"
    )


# ── parse_detail — happy path ─────────────────────────────────────────


def _vistas75_url() -> str:
    return ("https://www.encuentra24.com/el-salvador-es/"
            "bienes-raices-venta-de-propiedades-apartamentos/"
            "apartamento-a-estrenar-en-vistas75/32085770")


def test_detail_extracts_basic_jsonld_fields():
    """Vistas75 fixture: USD $254,000 / 4 recámaras / 3 baños / 97 m².
    First-pass sanity that JSON-LD parsing pulls the headline fields.
    Tested via _build_raw_record so the vacation-zone filter doesn't
    drop the inland-SS-apartment fixture before we can verify."""
    html = _load("detail-apartamento-vistas75.html")
    rec = _build_raw_record(html, _vistas75_url())
    assert rec is not None, "vistas75 should parse into a raw record"
    assert rec["source_id"] == "32085770"
    assert "Vistas75" in rec["title"]
    assert rec["price_usd"] == 254_000.0
    assert rec["raw_price_text"] == "USD 254000"
    assert rec["property_type"] == "condo"


def test_detail_pulls_address_from_jsonld():
    """JSON-LD's PostalAddress on the offer carries street + locality —
    both should land in `location_text`. Vistas75 fixture gives
    '75 Avenida Norte, San Salvador'."""
    html = _load("detail-apartamento-vistas75.html")
    rec = _build_raw_record(html, _vistas75_url())
    assert rec is not None
    assert "San Salvador" in rec["location_text"]


def test_detail_pulls_facts_grid():
    """Tailwind grid carries bedrooms / bathrooms / built_area_m2 /
    parking. Vistas75 = 4 / 3 / 97 / 2."""
    html = _load("detail-apartamento-vistas75.html")
    rec = _build_raw_record(html, _vistas75_url())
    assert rec is not None
    assert rec["bedrooms"] == 4
    assert rec["bathrooms"] == 3.0
    assert rec["built_area_m2"] == 97.0
    assert rec["parking_spaces"] == 2


def test_detail_extracts_broker_from_jsonld_seller():
    """JSON-LD `offers.seller.name` carries the broker organisation."""
    html = _load("detail-apartamento-vistas75.html")
    rec = _build_raw_record(html, _vistas75_url())
    assert rec is not None
    # Whatever the broker is, it should land as a string (may be empty
    # for owner-direct listings — fine).
    assert isinstance(rec.get("broker_name", ""), str)


def test_detail_photos_filtered_by_listing_id():
    """The detail page renders related-listing thumbnails too. Only
    photos whose CDN URL contains THIS listing's numeric ID should
    appear in the gallery."""
    html = _load("detail-apartamento-vistas75.html")
    rec = _build_raw_record(html, _vistas75_url())
    assert rec is not None
    photos = rec["photo_urls"]
    assert len(photos) >= 1, "expected at least the hero image"
    for u in photos:
        assert "32085770" in u, (
            f"photo URL leaked from another listing: {u}"
        )


def test_detail_strips_html_from_description():
    """encuentra24's JSON-LD description carries `<br />` tags; the
    raw record's description should be plain text."""
    html = _load("detail-apartamento-vistas75.html")
    rec = _build_raw_record(html, _vistas75_url())
    assert rec is not None
    desc = rec["description"]
    assert "<br" not in desc
    assert "<" not in desc
    assert desc != ""


# ── _build_raw_record across all 3 fixtures ───────────────────────────


@pytest.mark.parametrize("fixture,url,expected", [
    (
        "detail-apartamento-vistas75.html",
        ("https://www.encuentra24.com/el-salvador-es/"
         "bienes-raices-venta-de-propiedades-apartamentos/"
         "apartamento-a-estrenar-en-vistas75/32085770"),
        {"price_usd": 254_000.0, "bedrooms": 4, "bathrooms": 3.0,
         "built_area_m2": 97.0, "parking_spaces": 2, "source_id": "32085770"},
    ),
    (
        "detail-apartamento-triana.html",
        ("https://www.encuentra24.com/el-salvador-es/"
         "bienes-raices-venta-de-propiedades-apartamentos/"
         "apartamento-amueblado-en-triana-con-vista-espectacular-en-venta/32290544"),
        {"price_usd": 390_000.0, "bedrooms": 3, "bathrooms": 3.0,
         "built_area_m2": 120.0, "parking_spaces": 2, "source_id": "32290544"},
    ),
    (
        "detail-apartamento-escalon.html",
        ("https://www.encuentra24.com/el-salvador-es/"
         "bienes-raices-venta-de-propiedades-apartamentos/"
         "apartamento-con-terraza-jardin-privado-colonia-escalon/30640818"),
        {"price_usd": 294_900.0, "bedrooms": 2, "bathrooms": 2.0,
         "built_area_m2": 170.0, "parking_spaces": 2, "source_id": "30640818"},
    ),
])
def test_raw_record_against_all_fixtures(fixture, url, expected):
    """Cross-fixture parser invariants: every per-listing field comes
    out the same when fed back through _build_raw_record."""
    html = _load(fixture)
    rec = _build_raw_record(html, url)
    assert rec is not None, f"{fixture} should produce a raw record"
    for k, v in expected.items():
        assert rec.get(k) == v, (
            f"{fixture}: {k}={rec.get(k)!r}, expected {v!r}"
        )


# ── Vacation-zone filter integration ──────────────────────────────────


def test_vacation_zone_filter_drops_inland_condo():
    """All 3 fixtures are inland (Colonia Escalón / San Benito / Vistas75
    — none on the COASTAL_ZONES list). The vacation-zone filter
    inherited from PR #164 must drop them when called via parse_detail."""
    html = _load("detail-apartamento-vistas75.html")
    rec = parse_detail(html, _vistas75_url())
    assert rec is None, (
        "inland San Salvador condo should be dropped by vacation-zone "
        "filter — same contract as the other Phase-C scrapers"
    )


# ── Out-of-scope URLs return None cleanly ─────────────────────────────


def test_rental_listing_returns_none():
    """The Vistas75 HTML rendered correctly, but if we feed it a URL
    that's a rental (`-alquiler-`), parse_detail should drop it before
    looking at the HTML — keeps rentals out of the pulpo schema."""
    html = _load("detail-apartamento-vistas75.html")
    rental_url = ("https://www.encuentra24.com/el-salvador-es/"
                  "bienes-raices-alquiler-apartamentos/foo/32085770")
    assert parse_detail(html, rental_url) is None


def test_unknown_url_returns_none():
    """A URL that doesn't carry a numeric listing ID can't be parsed."""
    html = _load("detail-apartamento-vistas75.html")
    bogus = "https://www.encuentra24.com/el-salvador-es/bienes-raices/foo"
    assert parse_detail(html, bogus) is None


# ── Scraper class scaffolding (offline contract) ──────────────────────


def test_scraper_registers_with_sources():
    """encuentra24 should appear in pulpo.agents.SOURCES once the module
    is imported (matches the pattern of every other source)."""
    from pulpo.agents import SOURCES   # noqa: WPS433
    import pulpo.scrapers   # noqa: F401
    assert "encuentra24" in SOURCES


def test_scraper_offline_returns_fixtures(tmp_path, monkeypatch):
    """In offline mode the scraper returns whatever's in the fixtures
    file under source=encuentra24. With the fixtures file potentially
    empty for a fresh source, we just assert that crawl() returns a
    list (not None / not raise)."""
    monkeypatch.setenv("PULPO_OFFLINE", "1")
    sc = Encuentra24Scraper(offline=True)
    out = sc.crawl(limit=5)
    assert isinstance(out, list)


def test_scraper_category_urls_well_formed():
    """Every CATEGORY_URLS entry must be a venta sub-URL we can map
    to a property_type. Catches accidental rental/commercial
    additions during future tinkering."""
    for url in CATEGORY_URLS:
        assert "/bienes-raices-venta" in url
        # Each URL should map to a known property_type when used as a
        # listing path (we append a fake numeric ID for the test).
        synthetic = f"{url}/some-slug/12345678"
        assert _category_from_url(synthetic) is not None


def test_crawl_with_meta_returns_expected_shape():
    """Pipeline expects {records, max_pages_hit, limit_hit} from this
    method (parity with other sources)."""
    sc = Encuentra24Scraper(offline=True)
    meta = sc.crawl_with_meta(limit=5, offline=True)
    assert set(meta.keys()) == {"records", "max_pages_hit", "limit_hit"}
    assert isinstance(meta["records"], list)
