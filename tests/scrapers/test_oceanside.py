from pulpo.scrapers.oceanside import OceansideScraper


def test_detail_page_parses_title(load_sample):
    html = load_sample("oceanside", "detail.html")
    scraper = OceansideScraper(offline=True)
    result = scraper.parse_detail_page(html, {})
    assert result is not None
    assert result["title"] == "The Cliff: Where Luxury Meets the Ocean"
    assert result["property_type"] == "land"


def test_detail_page_extracts_area(load_sample):
    html = load_sample("oceanside", "detail.html")
    scraper = OceansideScraper(offline=True)
    result = scraper.parse_detail_page(html, {})
    assert result is not None
    assert "1,171.53" in result["raw_size_text"]
    assert "m²" in result["raw_size_text"] or "m2" in result["raw_size_text"]


def test_detail_page_price_in_blob(load_sample):
    html = load_sample("oceanside", "detail.html")
    scraper = OceansideScraper(offline=True)
    result = scraper.parse_detail_page(html, {})
    assert result is not None
    assert "$187,916.80" in result["raw_price_text"]


def test_index_page_extracts_urls(load_sample):
    html = load_sample("oceanside", "index.html")
    scraper = OceansideScraper(offline=True)
    partials = scraper.parse_index_page(html)
    assert len(partials) >= 1
    assert any("cerromar" in p["url"] for p in partials)
    assert all(p.get("source_id") for p in partials)
