"""
GoodLife El Salvador scraper.

Site: https://goodlifeelsalvador.com/
Stack signals: WordPress + likely a real-estate plugin (Estatik or similar
custom CPT). Listings live under /listings/ or /property/.

NOTE: live selectors below are best-effort starting points based on common
WordPress real-estate plugin DOM patterns. After first live run, calibrate
against actual HTML by saving one detail page locally and adjusting the
selectors. The fixture fallback lets the pipeline run without live access.
"""
from __future__ import annotations
from typing import Optional

from pulpo.agents.html_crawler import (
    SELECTOLAX_OK, is_offline, load_fixtures, make_client, walk as _walk,
)
from pulpo.agents import SOURCES, register

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser  # noqa: F401

BASE_URL = "https://goodlifeelsalvador.com/"
LIST_URL = "https://goodlifeelsalvador.com/land/?page={page}"
MAX_PAGES = 6
REQUEST_DELAY = 1.5
FIXTURE_FILE = "sample_listings.json"


class GoodLifeScraper:
    slug = "goodlife"

    # ---- selectors (calibrated 2026-04-28 against /land/ + /property-item/) ----
    INDEX_CARD_SEL = "div.mkdf-ips-item-content"
    INDEX_LINK_SEL = "a.mkdf-ips-item-link"
    _TOGGLE_PRICE_KEYS = {"asking price", "price", "precio"}
    _TOGGLE_LOC_KEYS = {"location", "ubicación", "ubicacion"}
    _TOGGLE_AREA_KEYS = {
        "area", "área", "lot size", "land size", "size", "lot area",
        "tamaño", "superficie", "metraje",
    }

    def __init__(self, offline: bool | None = None):
        # offline stored for backward-compat; crawl() calls is_offline() directly
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

        title_node = tree.css_first("h1.entry-title")
        title = title_node.text(strip=True) if title_node else ""
        if not title:
            return None

        toggles: dict[str, str] = {}
        for tog in tree.css("div.vc_toggle"):
            head = tog.css_first(".vc_toggle_title") or tog.css_first("h4")
            body = tog.css_first(".vc_toggle_content")
            if head is None or body is None:
                continue
            key = head.text(strip=True).lower()
            val = body.text(strip=True)
            if key:
                toggles[key] = val

        def first(keys: set) -> str:
            for k in keys:
                if k in toggles and toggles[k]:
                    return toggles[k]
            return ""

        raw_price = first(self._TOGGLE_PRICE_KEYS) or title
        raw_size = first(self._TOGGLE_AREA_KEYS)
        location = first(self._TOGGLE_LOC_KEYS) or title

        desc_node = tree.css_first("div.wpb_text_column")
        description = desc_node.text(strip=True) if desc_node else ""

        return {
            "title": title,
            "raw_price_text": raw_price,
            "raw_size_text": raw_size,
            "location_text": location,
            "description": description[:1500],
            "property_type": "land",
        }

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


_scraper = GoodLifeScraper()
register(SOURCES, "goodlife", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return GoodLifeScraper(offline=offline).crawl(limit)
