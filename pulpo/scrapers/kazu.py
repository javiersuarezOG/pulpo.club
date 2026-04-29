"""
Kazu Real Estate scraper.

Site: https://kazurealestate.com/
Stack signals: Nuxt 3 SPA. The shipped HTML is a 5KB shell — every route
returns the same `<div id="__nuxt">` with a Lottie loader. Property data is
loaded client-side from `https://panel.kazurealestate.com/api` (see the
`window.__NUXT__.config.public.apiBaseUrl` inline script).

Implication for this scraper:
  * CSS-selector calibration against the static HTML cannot work.
  * The `panel.kazurealestate.com` API host is currently NOT on the proxy
    allowlist — fetches return 403 "blocked-by-allowlist". Until that host
    is allowlisted, kazu remains in fixture-only / offline mode.
  * Once the API is reachable, this scraper should be reworked to call the
    JSON endpoints directly (no HTML parsing), so the DETAIL_*_SEL constants
    below are placeholders that the calibration harness expects but won't
    ever match a real shell.
"""
from __future__ import annotations
from typing import Optional
from .base import BaseScraper, SELECTOLAX_OK

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser

class KazuScraper(BaseScraper):
    SOURCE = "kazu"
    BASE_URL = "https://kazurealestate.com/"
    LIST_URL = "https://kazurealestate.com/properties/?property_type=land&page={page}"
    FIXTURE_FILE = "sample_listings.json"
    MAX_PAGES = 6

    INDEX_CARD_SEL = "div.es-grid-item, article.estatik-property, div.property-card"
    INDEX_LINK_SEL = "a.es-grid-image, h3 a, a.permalink"
    DETAIL_TITLE_SEL = "h1.entry-title, h1"
    DETAIL_PRICE_SEL = ".es-property-price, .price"
    DETAIL_AREA_SEL = ".es-property-area, .lot-area, li[data-feature='area']"
    DETAIL_LOC_SEL = ".es-property-address, .property-location"
    DETAIL_DESC_SEL = ".es-property-description, .entry-content"

    def parse_index_page(self, html: str) -> list[dict]:
        if not SELECTOLAX_OK:
            return []
        tree = HTMLParser(html)
        out = []
        for card in tree.css(self.INDEX_CARD_SEL):
            link = card.css_first(self.INDEX_LINK_SEL)
            if not link:
                continue
            href = link.attributes.get("href")
            if not href:
                continue
            sid = href.rstrip("/").rsplit("/", 1)[-1]
            out.append({"url": href, "source_id": sid})
        return out

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        if not SELECTOLAX_OK:
            return None
        tree = HTMLParser(html)
        def text_of(sel: str) -> str:
            n = tree.css_first(sel)
            return n.text(strip=True) if n else ""
        title = text_of(self.DETAIL_TITLE_SEL)
        if not title:
            return None
        return {
            "title": title,
            "raw_price_text": text_of(self.DETAIL_PRICE_SEL),
            "raw_size_text": text_of(self.DETAIL_AREA_SEL),
            "location_text": text_of(self.DETAIL_LOC_SEL),
            "description": text_of(self.DETAIL_DESC_SEL)[:1500],
            "property_type": "land",
        }

def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return KazuScraper(offline=offline).crawl(limit)
