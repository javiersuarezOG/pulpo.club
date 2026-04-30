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
from .base import BaseScraper, SELECTOLAX_OK

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser  # noqa: F401


class RemaxScraper(BaseScraper):
    SOURCE = "remax"
    BASE_URL = "https://www.remax.com.sv/"
    # RE/MAX's listings index. Filters: type=land (terreno), operation=sale.
    # Pagination is `?page=N` (LATAM template); confirm during calibration.
    LIST_URL = (
        "https://www.remax.com.sv/listings/buy"
        "?page={page}&type=land&pageSize=24"
    )
    FIXTURE_FILE = "sample_listings.json"
    MAX_PAGES = 6

    # ---- selectors (PLACEHOLDER — calibrate before live use) ----
    # RE/MAX Global card markup: each property is a `.card` (or
    # `.listing-card`) within `.listings-grid`. Detail pages render the
    # headline price as `.listing-price`, the lot size inside a
    # `.listing-features` / `.feature-item` block, and the location in
    # `.listing-address`. These are best-effort defaults from the RE/MAX
    # LATAM template; adjust per saved page.
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
            # RE/MAX detail URLs look like /listing/<numeric-id>/<slug> or
            # /listings/<id>; the last non-empty path segment is a stable id.
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

        # `.listing-features .feature-item` is a list of <li>-shaped chips
        # like "Lot Size 5,200 m²", "Bedrooms 0", "Year built —". Joining
        # the chips into one blob lets parse_area pick the first <num><unit>
        # pair (lot-size always ranks ahead of bedrooms in RE/MAX's
        # ordering, so the first regex hit is the right one).
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


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return RemaxScraper(offline=offline).crawl(limit)
