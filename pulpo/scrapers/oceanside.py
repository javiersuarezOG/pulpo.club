"""
Oceanside El Salvador scraper.

Site: https://oceansideelsalvador.com/
Stack signals: WordPress, RealHomes / Houzez-style theme. Listings under
/properties/ or /property-category/land-for-sale/.
"""
from __future__ import annotations
import re
from typing import Optional
from .base import BaseScraper, SELECTOLAX_OK

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser

# The Avada theme glues "Listed on <date>" to the lot-size m² value with no
# whitespace once the DOM text is flattened, e.g.:
#   "Listed on Sep 2, 2025243,080.00m2Lot"
# A generic <num><unit> extractor would pick "2025243,080.00" as the number
# (= 2 billion m²). We pluck out just the area portion by anchoring on the
# four-digit year and the m² suffix, ignoring case and tolerating an optional
# space between the number and "m2".
_AREA_AFTER_YEAR_RE = re.compile(
    r"20\d{2}\s*(\d[\d,\.]*)\s*m[2²]",
    re.IGNORECASE,
)
# Fallback: a clean "<num> m²" mention with proper whitespace. Needed for
# listings whose body text doesn't follow the "Listed on…" template.
_AREA_PLAIN_RE = re.compile(
    r"(?<![\d])(\d[\d,]*\.?\d*)\s+m[2²](?![a-zA-Z])",
)


def _extract_area_text(blob: str) -> str:
    """Return a clean '<num> m²' string from the .post-content blob, or ''."""
    if not blob:
        return ""
    m = _AREA_AFTER_YEAR_RE.search(blob) or _AREA_PLAIN_RE.search(blob)
    return f"{m.group(1)} m²" if m else ""

class OceansideScraper(BaseScraper):
    SOURCE = "oceanside"
    BASE_URL = "https://oceansideelsalvador.com/"
    # /lands/ is the server-rendered land archive; /property-category/land-for-sale/
    # 404s. Pagination is /lands/page/N/.
    LIST_URL = "https://oceansideelsalvador.com/lands/page/{page}/"
    FIXTURE_FILE = "sample_listings.json"
    MAX_PAGES = 6

    # ---- selectors (calibrated 2026-04-28 against /lands/ + /rental-details/) ----
    # Site runs Avada/Fusion theme. Land listings live under /rental-details/
    # (a quirk of the Avada CPT mapping, not actual rentals). The detail page
    # packs all property metadata — price, lot size, location — into a single
    # .post-content block whose visible text reads e.g.
    #   "$187,916.80 ... 1,171.53m2 ... La Libertad, El Salvador"
    # so each field-level selector reuses .post-content and lets the
    # downstream regex parsers pick the right substring.
    INDEX_CARD_SEL = "li.fusion-grid-column.post-card, .fusion-post-cards-grid-column"
    INDEX_LINK_SEL = "a.fusion-column-anchor"
    DETAIL_TITLE_SEL = "h1.fusion-title-heading, h1.entry-title, h1"
    DETAIL_PRICE_SEL = "div.post-content"
    DETAIL_AREA_SEL = "div.post-content"
    DETAIL_LOC_SEL = "div.post-content"
    DETAIL_DESC_SEL = "div.post-content"

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
        post_content = text_of(self.DETAIL_PRICE_SEL)  # = ".post-content"
        # raw_size_text is intentionally narrowed to a clean "<n> m²" token
        # extracted via a year-anchored regex. Passing the whole .post-content
        # blob would let parse_area latch onto "<year><area>" as a single
        # ~2-billion-m² number.
        return {
            "title": title,
            "raw_price_text": post_content,
            "raw_size_text": _extract_area_text(post_content),
            "location_text": post_content,
            "description": post_content[:1500],
            "property_type": "land",
        }

def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return OceansideScraper(offline=offline).crawl(limit)
