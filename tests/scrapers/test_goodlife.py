from pulpo.scrapers.goodlife import GoodLifeScraper


def test_detail_page_parses_title_and_price(load_sample):
    html = load_sample("goodlife", "detail.html")
    scraper = GoodLifeScraper(offline=True)
    result = scraper.parse_detail_page(html, {})
    assert result is not None
    assert "$350,000" in result["title"]
    assert result["raw_price_text"] == "$350,000"
    assert result["property_type"] == "land"
    assert "El Zonte" in result["location_text"] or "El Zonte" in result["title"]


def test_detail_page_sold_title_is_returned(load_sample):
    # parse_detail_page returns the raw dict — normalize() is what drops SOLD listings
    html = load_sample("goodlife", "detail.html")
    scraper = GoodLifeScraper(offline=True)
    result = scraper.parse_detail_page(html, {})
    assert result is not None
    assert "sold" in result["title"].lower()


def test_index_page_extracts_urls(load_sample):
    html = load_sample("goodlife", "index.html")
    scraper = GoodLifeScraper(offline=True)
    partials = scraper.parse_index_page(html)
    assert len(partials) >= 1
    urls = [p["url"] for p in partials]
    assert any("rare-find-lot-in-el-zonte" in u for u in urls)
    assert all(p.get("source_id") for p in partials)
