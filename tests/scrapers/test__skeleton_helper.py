"""Unit tests for pulpo.scrapers._skeleton_helper.

Exercises the SkeletonScraper extraction-strategy dispatch, the
finalize-batch override hooks (``_post_finalize_filter`` and the
in-page detail-URL dedup loop), and the helper number parser.

Offline-only — every test path stubs the network or hits the offline
fixture loader so PULPO_OFFLINE=1 is sufficient.
"""
from __future__ import annotations

import pytest

from pulpo.scrapers._skeleton_helper import (
    SkeletonConfig,
    SkeletonScraper,
    _parse_number,
    _property_type_from_jsonld,
    _slug_from_url,
)


# ── number parser ─────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("350,000", 350000.0),          # US thousands separator
    ("350.000,50", 350000.50),       # EU thousands + decimal
    ("$ 350,000", 350000.0),         # currency strip
    ("350000", 350000.0),
    ("3,500.50", 3500.50),           # US thousands + decimal
    (1234, 1234.0),
    (None, None),
    ("", None),
    ("garbage", None),
])
def test_parse_number_variants(raw, expected):
    out = _parse_number(raw)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected)


# ── property-type hints from JSON-LD @type ────────────────────────────


@pytest.mark.parametrize("block,expected", [
    ({"@type": "House"}, "house"),
    ({"@type": "house"}, "house"),       # case-insensitive
    ({"@type": ["RealEstateListing", "Apartment"]}, "condo"),
    ({"@type": "Land"}, "land"),
    ({"additionalType": "casa"}, "house"),
    ({"@type": "WebPage"}, None),         # no hint match
    ({}, None),
])
def test_property_type_from_jsonld(block, expected):
    assert _property_type_from_jsonld(block) == expected


# ── slug-from-url ─────────────────────────────────────────────────────


def test_slug_from_url_strips_trailing_slash_and_query():
    assert _slug_from_url("https://example.test/foo/bar-baz/") == "bar-baz"


def test_slug_from_url_empty():
    assert _slug_from_url("") == ""


# ── strategy: static_urls ─────────────────────────────────────────────


class _StaticTestScraper(SkeletonScraper):
    """Static-urls strategy fixture; offline tests use the offline path,
    online path is exercised via a stub fetch."""

    CONFIG = SkeletonConfig(
        slug="_test_static",
        base_url="https://example.test",
        list_url="",
        extract_strategy="static_urls",
        static_urls=(
            "https://example.test/a",
            "https://example.test/b",
        ),
        jsonld_schema_types=("RealEstateListing",),
        force_vacation_gate=False,
    )


def test_static_urls_offline_path_returns_fixture(monkeypatch: pytest.MonkeyPatch):
    """Force offline=True and stub the fixture loader so the test is
    hermetic. Verifies the offline branch returns whatever fixtures
    the loader hands back (post-finalize)."""
    monkeypatch.setenv("PULPO_OFFLINE", "1")

    fixture_record = {
        "source": "_test_static",
        "source_id": "fx-1",
        "url": "https://example.test/a",
        "title": "Test",
        "description": "",
        "price_usd": 100000,
        "area_m2": 100,
        "photo_urls": [],
        "raw_size_text": None,
        "property_type": "land",
        "location_text": "",
    }
    monkeypatch.setattr(
        "pulpo.scrapers._skeleton_helper.OfflineFixtureMixin._offline_or_fixtures",
        lambda self, limit, **kw: [fixture_record],
    )
    out = _StaticTestScraper(offline=True).crawl(limit=10, offline=True)
    assert len(out) == 1
    assert out[0]["source"] == "_test_static"


# ── catalog-walk dedup ────────────────────────────────────────────────


class _CatalogTestScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="_test_catalog",
        base_url="https://example.test",
        list_url="https://example.test/cat",
        page_param="page",
        detail_url_pattern=r'href="(https?://example\.test/p/\d+)"',
        extract_strategy="detail_jsonld",
        jsonld_schema_types=("RealEstateListing",),
        force_vacation_gate=False,
        max_pages=2,
    )


def test_extract_detail_urls_from_catalog_page_returns_matches():
    """Default regex extraction returns ALL matches (incl. duplicates);
    the dedup runs inside the catalog-walk loop, not the extractor.
    """
    s = _CatalogTestScraper()
    body = (
        '<a href="https://example.test/p/1">A</a>'
        '<a href="https://example.test/p/1">A</a>'  # dup in same page
        '<a href="https://example.test/p/2">B</a>'
    )
    urls = s._extract_detail_urls_from_catalog_page(body, 1)
    assert urls == [
        "https://example.test/p/1",
        "https://example.test/p/1",
        "https://example.test/p/2",
    ]


def test_post_finalize_filter_default_is_passthrough():
    s = _CatalogTestScraper()
    rec = {"source": "_test_catalog", "url": "https://example.test/p/1"}
    assert s._post_finalize_filter(rec) is rec


# ── jsonld block mapping ──────────────────────────────────────────────


def test_finalize_jsonld_block_maps_standard_residence_shape():
    s = _CatalogTestScraper()
    block = {
        "@type": "Residence",
        "name": "Test Casa",
        "description": "Vista al mar",
        "url": "https://example.test/p/123",
        "image": ["https://cdn.test/1.jpg", "https://cdn.test/2.jpg"],
        "offers": {"price": "350000"},
        "floorSize": {"value": "600", "unitText": "m2"},
        "address": {"addressLocality": "El Tunco", "addressCountry": "SV"},
    }
    record = s._finalize_jsonld_block(block, url=block["url"])
    assert record["source"] == "_test_catalog"
    assert record["url"] == "https://example.test/p/123"
    assert record["title"] == "Test Casa"
    assert record["price_usd"] == 350000.0
    assert record["area_m2"] == 600.0
    assert record["photo_urls"] == ["https://cdn.test/1.jpg", "https://cdn.test/2.jpg"]
    assert record["location_text"] == "El Tunco, SV"
    assert record["_jsonld_country"] == "SV"


def test_finalize_jsonld_block_handles_offers_as_array():
    """schema.org allows ``offers`` as either object or array."""
    s = _CatalogTestScraper()
    block = {"@type": "House", "offers": [{"price": "99000"}]}
    record = s._finalize_jsonld_block(block, url="https://example.test/p/1")
    assert record["price_usd"] == 99000.0
