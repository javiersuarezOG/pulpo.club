"""
Oceanside El Salvador scraper.

Site: https://oceansideelsalvador.com/
Stack signals: WordPress, RealHomes / Houzez-style theme. Listings under
/properties/ or /property-category/land-for-sale/.
"""
from __future__ import annotations
import re
from typing import Optional

from pulpo.agents.html_crawler import (
    SELECTOLAX_OK, is_offline, load_fixtures, make_client,
    walk as _walk, walk_with_meta as _walk_meta,
)
from pulpo.agents import SOURCES, register

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

BASE_URL = "https://oceansideelsalvador.com/"
LIST_URL = "https://oceansideelsalvador.com/lands/page/{page}/"
MAX_PAGES = 50
REQUEST_DELAY = 1.5
FIXTURE_FILE = "sample_listings.json"


class OceansideScraper:
    slug = "oceanside"
    INDEX_CARD_SEL = "li.fusion-grid-column.post-card, .fusion-post-cards-grid-column"
    INDEX_LINK_SEL = "a.fusion-column-anchor"
    DETAIL_TITLE_SEL = "h1.fusion-title-heading, h1.entry-title, h1"
    _BAD_TITLES = {"contact us", "contactanos", "contáctanos", "contact", "inquire"}

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
        if not title or title.lower().strip() in self._BAD_TITLES:
            t_node = tree.css_first("title")
            if t_node:
                raw = t_node.text(strip=True)
                title = re.split(r'\s[–—|]\s|\s-\s', raw)[0].strip()
            if not title or title.lower().strip() in self._BAD_TITLES:
                return None
        post_content = text_of("div.post-content")
        return {
            "title": title,
            "raw_price_text": post_content,
            "raw_size_text": _extract_area_text(post_content),
            "location_text": post_content,
            "description": post_content[:1500],
            "property_type": "land",
        }

    def report_total(self, client) -> Optional[int]:
        """Fetch the land index and return the advertised listing count, or None."""
        try:
            r = client.get("https://oceansideelsalvador.com/lands/")
            r.raise_for_status()
        except Exception:
            return None
        html = r.text
        # Avada/Fusion pagination: look for "Page 1 of N" or a data attribute
        for pattern in [
            r'Page\s+1\s+of\s+(\d+)',
            r'data-pages=["\'](\d+)["\']',
            r'(\d+)\s+(?:listings?|properties|results?)',
        ]:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                val = int(m.group(1))
                # If it's a page count, multiply by cards-per-page estimate
                if "of" in pattern.lower() or "pages" in pattern.lower():
                    cards = len(self.parse_index_page(html))
                    return val * max(cards, 1) if cards else None
                return val
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
        """Like crawl() but returns {"records", "max_pages_hit", "limit_hit"}."""
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


_scraper = OceansideScraper()
register(SOURCES, "oceanside", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return OceansideScraper(offline=offline).crawl(limit)
