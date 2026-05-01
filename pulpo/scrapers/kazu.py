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

from pulpo.agents.html_crawler import (
    SELECTOLAX_OK, is_offline, load_fixtures, make_client,
    walk as _walk, walk_with_meta as _walk_meta,
)
from pulpo.agents import SOURCES, register

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser

BASE_URL = "https://kazurealestate.com/"
LIST_URL = "https://kazurealestate.com/properties/?property_type=land&page={page}"
MAX_PAGES = 50
REQUEST_DELAY = 1.5
FIXTURE_FILE = "sample_listings.json"


class KazuScraper:
    slug = "kazu"

    INDEX_CARD_SEL = "div.es-grid-item, article.estatik-property, div.property-card"
    INDEX_LINK_SEL = "a.es-grid-image, h3 a, a.permalink"
    DETAIL_TITLE_SEL = "h1.entry-title, h1"
    DETAIL_PRICE_SEL = ".es-property-price, .price"
    DETAIL_AREA_SEL = ".es-property-area, .lot-area, li[data-feature='area']"
    DETAIL_LOC_SEL = ".es-property-address, .property-location"
    DETAIL_DESC_SEL = ".es-property-description, .entry-content"

    def __init__(self, offline: bool | None = None):
        self.offline = offline

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

    def report_total(self, client) -> None:  # noqa: ARG002
        """API host is on denylist — supplier count unavailable."""
        return None

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        client = make_client()
        try:
            return _walk(
                client=client,
                base_url=BASE_URL,
                list_url=LIST_URL,
                parse_index=self.parse_index_page,
                parse_detail=self.parse_detail_page,
                max_pages=MAX_PAGES,
                request_delay=REQUEST_DELAY,
                limit=limit,
            )
        finally:
            client.close()

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None
    ) -> dict:
        if is_offline(offline if offline is not None else self.offline):
            records = load_fixtures(self.slug, FIXTURE_FILE, limit)
            return {"records": records, "max_pages_hit": False, "limit_hit": False}
        client = make_client()
        try:
            return _walk_meta(
                client=client,
                base_url=BASE_URL,
                list_url=LIST_URL,
                parse_index=self.parse_index_page,
                parse_detail=self.parse_detail_page,
                max_pages=max_pages if max_pages is not None else MAX_PAGES,
                request_delay=REQUEST_DELAY,
                limit=limit,
            )
        finally:
            client.close()


_scraper = KazuScraper()
register(SOURCES, "kazu", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return KazuScraper(offline=offline).crawl(limit)
