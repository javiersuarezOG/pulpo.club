"""Unit tests for pulpo.scrapers.lib.og_meta."""
from __future__ import annotations

from pulpo.scrapers.lib import extract_og, find_first


def test_extract_og_basic_tags():
    html = (
        '<meta property="og:title" content="Casa en El Tunco"/>'
        '<meta property="og:description" content="Vista al mar"/>'
        '<meta property="og:image" content="https://example.test/1.jpg"/>'
    )
    out = extract_og(html)
    assert out["title"] == "Casa en El Tunco"
    assert out["description"] == "Vista al mar"
    assert out["image"] == ["https://example.test/1.jpg"]


def test_extract_og_multiple_images_dedup_and_order():
    html = (
        '<meta property="og:image" content="https://example.test/1.jpg"/>'
        '<meta property="og:image" content="https://example.test/2.jpg"/>'
        '<meta property="og:image" content="https://example.test/1.jpg"/>'
    )
    assert extract_og(html)["image"] == [
        "https://example.test/1.jpg",
        "https://example.test/2.jpg",
    ]


def test_extract_og_handles_name_attribute_variant():
    """Some CMS templates emit ``name="og:..."`` instead of ``property="og:..."``."""
    html = '<meta name="og:title" content="Hello"/>'
    assert extract_og(html)["title"] == "Hello"


def test_extract_og_handles_reversed_attribute_order():
    """The OG fallback regex catches content-before-property attribute orders."""
    html = '<meta content="Reversed" property="og:title">'
    assert extract_og(html)["title"] == "Reversed"


def test_extract_og_empty_html_returns_empty_dict():
    assert extract_og("") == {}
    assert extract_og(None) == {}  # type: ignore[arg-type]


def test_find_first_returns_capture_group():
    text = "Precio $ 590,000 USD"
    assert find_first(text, (r"\$\s*([\d,\.]+)",)) == "590,000"


def test_find_first_iterates_patterns_in_order():
    text = "Area: 600 m²"
    out = find_first(text, (r"(\d+)\s*manz", r"(\d+)\s*m[²2]"))
    assert out == "600"


def test_find_first_returns_none_on_no_match():
    assert find_first("nothing here", (r"(\$\d+)",)) is None
    assert find_first("", (r"x",)) is None
