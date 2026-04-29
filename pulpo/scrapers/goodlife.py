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
from .base import BaseScraper, SELECTOLAX_OK

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser  # noqa: F401

class GoodLifeScraper(BaseScraper):
    SOURCE = "goodlife"
    BASE_URL = "https://goodlifeelsalvador.com/"
    # /land/ is the actual server-rendered listings page; the previously
    # configured /property-search/ URL 404s.
    LIST_URL = "https://goodlifeelsalvador.com/land/?page={page}"
    FIXTURE_FILE = "sample_listings.json"
    MAX_PAGES = 6

    # ---- selectors (calibrated 2026-04-28 against /land/ + /property-item/) ----
    # Site uses Mikado/Kastell theme: an "intelligent property search" (mkdf-ips)
    # widget on /land/ for index, and Visual Composer "vc_toggle" accordions
    # on detail pages whose semantic meaning is encoded in their <h4> title
    # (Amenities / Location / Asking Price). Because selectolax does not
    # support :contains/:has reliably, the calibration selectors below match
    # broad regions whose text contains the field; downstream pulpo/units.py
    # and pulpo/normalize.py regex-extract the actual values.
    INDEX_CARD_SEL = "div.mkdf-ips-item-content"
    INDEX_LINK_SEL = "a.mkdf-ips-item-link"
    DETAIL_TITLE_SEL = "h1.entry-title"
    # Title text already contains the asking price (e.g. "Lot in El Zonte, $350,000")
    # and parse_price_usd extracts it. Toggles act as fallback.
    DETAIL_PRICE_SEL = "h1.entry-title, div.vc_toggle_content"
    # No semantic area markup; whole property holder is scanned and parse_area
    # picks the first <number><unit> pair.
    DETAIL_AREA_SEL = "div.mkdf-property-single-holder, div.vc_toggle_content"
    # Title also encodes a zone token (El Zonte, El Cuco…) which detect_zone matches.
    DETAIL_LOC_SEL = "h1.entry-title, div.vc_toggle_content"
    DETAIL_DESC_SEL = "div.wpb_text_column"

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

    # Map of vc_toggle <h4> titles (lowercased) -> our field names.
    # The Mikado/Kastell theme renders property metadata as Visual Composer
    # accordions: <div class="vc_toggle"><h4>Asking Price</h4><div class="vc_toggle_content">$X</div>...</div>.
    # We key off the title text rather than DOM position so reorderings don't
    # silently misroute a value into the wrong field.
    _TOGGLE_PRICE_KEYS = {"asking price", "price", "precio"}
    _TOGGLE_LOC_KEYS = {"location", "ubicación", "ubicacion"}
    _TOGGLE_AREA_KEYS = {
        "area", "área", "lot size", "land size", "size", "lot area",
        "tamaño", "superficie", "metraje",
    }

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        if not SELECTOLAX_OK:
            return None
        tree = HTMLParser(html)

        title_node = tree.css_first("h1.entry-title")
        title = title_node.text(strip=True) if title_node else ""
        if not title:
            return None

        # Walk each vc_toggle and index by lowercased title.
        # Note: themes often render the same toggle twice (responsive variants).
        # That's fine — last-wins on dict insert; the content text is identical.
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

        def first(keys: set[str]) -> str:
            for k in keys:
                if k in toggles and toggles[k]:
                    return toggles[k]
            return ""

        raw_price = first(self._TOGGLE_PRICE_KEYS)
        raw_size = first(self._TOGGLE_AREA_KEYS)
        location = first(self._TOGGLE_LOC_KEYS)

        # Fall back to the title only when a toggle is genuinely absent. The
        # title regularly carries both the price ("…, $350,000") and a zone
        # token ("…El Zonte…"), so units.parse_price_usd and
        # normalize.detect_zone can recover when toggles are missing — without
        # us pulling in unrelated text from a "related properties" widget.
        if not raw_price:
            raw_price = title
        if not location:
            location = title
        # Deliberately do NOT fall back for raw_size: if the listing doesn't
        # publish a size we want area_m2 to be None, not an erroneous value
        # scavenged from elsewhere on the page.

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

def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return GoodLifeScraper(offline=offline).crawl(limit)
