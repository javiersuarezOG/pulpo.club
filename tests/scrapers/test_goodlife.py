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


# ── Phase C: house + condo ingestion ──────────────────────────────────


def test_house_detail_extracts_per_type_fields(load_sample):
    """Atami house detail page → bedrooms, bathrooms, built_area_m2 land
    on the record; land path is unaffected."""
    html = load_sample("goodlife", "detail-house-live-1.html")
    scraper = GoodLifeScraper(offline=True)
    partial = {"url": "https://goodlifeelsalvador.com/property-item/3-bedroom-brand-new-house-in-atami-gated-community-450000/"}
    result = scraper.parse_detail_page(html, partial)
    assert result is not None
    assert result["property_type"] == "house"
    # icon-box[0] = "840 m2; Construction 190 m2"
    assert result.get("built_area_m2") == 190.0
    # icon-box[2] = "3 Bed, 3 Bath"
    assert result.get("bedrooms") == 3
    assert result.get("bathrooms") == 3.0


def test_condo_detail_extracts_built_and_clears_lot(load_sample):
    """Zonset condo → built_area_m2 from the leading icon-box; raw_size_text
    is cleared so normalize doesn't attribute the unit interior to area_m2
    (a condo has no lot)."""
    html = load_sample("goodlife", "detail-condo-live-1.html")
    scraper = GoodLifeScraper(offline=True)
    partial = {"url": "https://goodlifeelsalvador.com/property-item/1-bed-ocean-view-condominium-at-zonset-el-zonte-345150/"}
    result = scraper.parse_detail_page(html, partial)
    assert result is not None
    assert result["property_type"] == "condo"
    # icon-box[0] = "76.7 m2 / 825 sqft" → 76.7 → built (no lot for a unit)
    assert result.get("built_area_m2") == 76.7
    assert result["raw_size_text"] == ""
    # icon-box[2] = "1 Bed, 1 Bath"
    assert result.get("bedrooms") == 1
    assert result.get("bathrooms") == 1.0


def test_land_path_unchanged_no_type_specific_fields(load_sample):
    """Regression: land listings keep raw_size_text and don't get
    bedrooms/bathrooms/built_area_m2 spuriously populated."""
    html = load_sample("goodlife", "detail-live-1.html")
    scraper = GoodLifeScraper(offline=True)
    result = scraper.parse_detail_page(html, {})
    assert result is not None
    assert result["property_type"] == "land"
    assert result["raw_size_text"]   # populated as before
    assert "built_area_m2" not in result
    assert "bedrooms" not in result
    assert "bathrooms" not in result


def test_inland_house_without_beachfront_keyword_is_dropped():
    """Coastal filter — house in a non-coastal zone with no beachfront
    keyword in text → dropped (parity with remax/c21)."""
    # Construct a minimal HTML the parser will accept as house but whose
    # location + text carry no coastal signal.
    html = """<html><body>
        <h1 class="entry-title">3 Bedroom House in Cuscatancingo</h1>
        <div class="vc_toggle">
          <div class="vc_toggle_title">Asking Price</div>
          <div class="vc_toggle_content">$200,000</div>
        </div>
        <div class="vc_toggle">
          <div class="vc_toggle_title">Location</div>
          <div class="vc_toggle_content">Cuscatancingo, San Salvador</div>
        </div>
        <div class="mkdf-icon-box-title">300 m2; Construction 150 m2</div>
        <div class="mkdf-icon-box-title">Residential Property</div>
        <div class="mkdf-icon-box-title">3 Bed, 2 Bath</div>
        <div class="wpb_text_column">Modern inland family home — quiet
        residential street in San Salvador metropolitan area.</div>
    </body></html>"""
    scraper = GoodLifeScraper(offline=True)
    partial = {"url": "https://goodlifeelsalvador.com/property-item/3-bedroom-house-in-cuscatancingo-200000/"}
    result = scraper.parse_detail_page(html, partial)
    # Inland + no beachfront keyword → coastal filter drops it.
    assert result is None


def test_house_with_beachfront_keyword_in_text_is_kept():
    """Coastal filter — beachfront keyword in title/description rescues
    a listing whose declared zone isn't on COASTAL_ZONES list."""
    html = """<html><body>
        <h1 class="entry-title">Beachfront Villa near El Tunco</h1>
        <div class="vc_toggle">
          <div class="vc_toggle_title">Asking Price</div>
          <div class="vc_toggle_content">$650,000</div>
        </div>
        <div class="vc_toggle">
          <div class="vc_toggle_title">Location</div>
          <div class="vc_toggle_content">Tamanique, La Libertad</div>
        </div>
        <div class="mkdf-icon-box-title">800 m2; Construction 220 m2</div>
        <div class="mkdf-icon-box-title">Residential Property</div>
        <div class="mkdf-icon-box-title">3 Bed, 3 Bath</div>
        <div class="wpb_text_column">Direct beach access; oceanfront infinity pool.</div>
    </body></html>"""
    scraper = GoodLifeScraper(offline=True)
    partial = {"url": "https://goodlifeelsalvador.com/property-item/beachfront-villa-near-el-tunco/"}
    result = scraper.parse_detail_page(html, partial)
    assert result is not None
    assert result["property_type"] == "house"
    assert result["bedrooms"] == 3
