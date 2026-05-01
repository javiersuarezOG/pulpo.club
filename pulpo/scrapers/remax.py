"""
RE/MAX El Salvador scraper.

Site: https://www.remax.com.sv/
Stack signals: RE/MAX runs a custom listings platform across most of its
LATAM franchises with a recognizable URL shape — /listings/?... — and a
JSON-rendered card grid. The HTML shipped on the listings page is
typically server-rendered enough for selectolax to grab title, price,
area, and location from each card; detail pages follow a `/listing/<id>`
pattern with a structured features block.

Implementation note: `LIST_URL` below is scoped to `type=land` and
operación venta. If RE/MAX SV uses a different filter syntax (some
franchises namespace it as `category=lots`), recalibrate against a saved
results page and update the URL — the rest of the parser keys off the
card class names, which are stable across regions.

NOTE: live selectors below are best-effort starting points based on the
RE/MAX Global / RE/MAX LATAM template. Calibrate against saved samples in
`samples/calibration/remax/` before flipping PULPO_OFFLINE=0 in production
cron — see automation/calibrate.py.
"""
from __future__ import annotations
from typing import Optional

from pulpo.agents.html_crawler import (
    SELECTOLAX_OK, is_offline, load_fixtures, make_client,
    walk as _walk, walk_with_meta as _walk_meta,
)
from pulpo.agents import SOURCES, register

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser  # noqa: F401

BASE_URL = "https://www.remax.com.sv/"
LIST_URL = (
    "https://www.remax.com.sv/listings/buy"
    "?page={page}&type=land&pageSize=24"
)
MAX_PAGES = 50
REQUEST_DELAY = 1.5
FIXTURE_FILE = "sample_listings.json"


class RemaxScraper:
    slug = "remax"

    # ---- selectors (PLACEHOLDER — calibrate before live use) ----
    INDEX_CARD_SEL = (
        "article.listing-card, div.listing-card, div.card.listing, "
        "div.property-card"
    )
    INDEX_LINK_SEL = "a.card-link, a.listing-link, h3 a, a.property-link"
    DETAIL_TITLE_SEL = "h1.listing-title, h1.property-title, h1"
    DETAIL_PRICE_SEL = ".listing-price, .property-price, .price"
    DETAIL_AREA_SEL = (
        ".listing-features .feature-item, .property-features li, "
        ".details-list li, li[data-feature='lot-size']"
    )
    DETAIL_LOC_SEL = ".listing-address, .property-address, .address, .location"
    DETAIL_DESC_SEL = ".listing-description, .property-description, .description"

    def __init__(self, offline: bool | None = None):
        self.offline = offline

    def parse_index_page(self, html: str) -> list[dict]:
        if not SELECTOLAX_OK:
            return []
        tree = HTMLParser(html)
        out: list[dict] = []
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

        feature_nodes = tree.css(self.DETAIL_AREA_SEL)
        feature_text = " | ".join(
            n.text(strip=True) for n in feature_nodes if n is not None
        )

        raw_price = text_of(self.DETAIL_PRICE_SEL) or feature_text or title
        raw_size = feature_text
        location = text_of(self.DETAIL_LOC_SEL) or title
        description = text_of(self.DETAIL_DESC_SEL)

        return {
            "title": title,
            "raw_price_text": raw_price,
            "raw_size_text": raw_size,
            "location_text": location,
            "description": description[:1500],
            "property_type": "land",
        }

    def report_total(self, client) -> None:  # noqa: ARG002
        """DNS does not resolve — supplier count unavailable."""
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


_scraper = RemaxScraper()
register(SOURCES, "remax", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return RemaxScraper(offline=offline).crawl(limit)
