"""Unit tests for pulpo.scrapers.lib.sitemap."""
from __future__ import annotations

from pulpo.scrapers.lib import extract_loc_urls


def test_extract_loc_urls_basic_sitemap():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.test/a</loc></url>
  <url><loc>https://example.test/b</loc></url>
  <url><loc>https://example.test/c</loc></url>
</urlset>"""
    assert extract_loc_urls(xml) == [
        "https://example.test/a",
        "https://example.test/b",
        "https://example.test/c",
    ]


def test_extract_loc_urls_unescapes_entity_encoded():
    """sitemap.org allows ``&amp;`` inside <loc> per RFC 3986; unescape on read."""
    xml = "<url><loc>https://example.test/path?a=1&amp;b=2</loc></url>"
    assert extract_loc_urls(xml) == ["https://example.test/path?a=1&b=2"]


def test_extract_loc_urls_tolerates_whitespace_around_url():
    xml = "<url><loc>\n  https://example.test/x  \n</loc></url>"
    assert extract_loc_urls(xml) == ["https://example.test/x"]


def test_extract_loc_urls_empty_input():
    assert extract_loc_urls("") == []
    assert extract_loc_urls(None) == []  # type: ignore[arg-type]


def test_extract_loc_urls_preserves_input_order():
    xml = (
        "<url><loc>https://example.test/3</loc></url>"
        "<url><loc>https://example.test/1</loc></url>"
        "<url><loc>https://example.test/2</loc></url>"
    )
    assert extract_loc_urls(xml) == [
        "https://example.test/3",
        "https://example.test/1",
        "https://example.test/2",
    ]
