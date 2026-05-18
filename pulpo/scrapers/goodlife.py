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
import re
from typing import Optional

from pulpo.agents.html_crawler import (
    SELECTOLAX_OK, is_offline, load_fixtures, make_client,
    walk as _walk, walk_with_meta as _walk_meta,
    DEFAULT_REQUEST_DELAY as REQUEST_DELAY,
)
from pulpo.agents import SOURCES, register
from pulpo.scrapers._type_classifier import classify_property_type
from pulpo.scrapers._photo_url_upgrade import upgrade_photo_urls
from automation.property_types import VACATION_ZONES, WATERFRONT_KEYWORDS

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser  # noqa: F401

# Vacation-zone filter for house/condo. Land is exempt — inland lots stay
# (parity with bienesraices PR #65 / remax PR #90 / c21 PR #91).
# Renamed from coastal/beachfront to vacation/waterfront when lake zones
# (Coatepeque + Ilopango) joined the eligible set (PR #161, 2026-05-08).
_WATERFRONT_RE = re.compile("|".join(WATERFRONT_KEYWORDS), re.IGNORECASE)

# Bed/bath summary lives in the third mkdf icon-box title, e.g.
# "1 Bed, 1 Bath" / "3 Bed, 3 Bath". Captures the leading integers
# only; "1.5 Bath" hasn't been observed but we keep bathrooms as float
# in case it appears.
_BED_BATH_RE = re.compile(
    r"(\d+)\s*Bed[s]?\s*,\s*([\d.]+)\s*Bath", re.IGNORECASE
)

# Area icon-box. Two observed shapes:
#   "840 m2; Construction 190 m2"      → house with split lot/built
#   "105.39 m2 / 1,134 sqft"           → condo with single (interior) area
# For house we take the first m2 number as lot, second as built; for
# condo we treat the first m2 number as built (no lot for a unit).
_AREA_M2_RE  = re.compile(r"([\d,]+\.?\d*)\s*m2", re.IGNORECASE)
_BUILT_M2_RE = re.compile(r"construction[^0-9]+([\d,]+\.?\d*)\s*m2", re.IGNORECASE)

BASE_URL = "https://goodlifeelsalvador.com/"
LIST_URL = "https://goodlifeelsalvador.com/land/?page={page}"
MAX_PAGES = 50
FIXTURE_FILE = "sample_listings.json"


class GoodLifeScraper:
    slug = "goodlife"

    # ---- selectors (calibrated 2026-04-28, icon-box area updated 2026-05-02) ----
    INDEX_CARD_SEL = "div.mkdf-ips-item-content"
    INDEX_LINK_SEL = "a.mkdf-ips-item-link"
    _TOGGLE_PRICE_KEYS = {"asking price", "price", "precio"}
    _TOGGLE_LOC_KEYS = {"location", "ubicación", "ubicacion"}
    _TOGGLE_AREA_KEYS = {
        "area", "área", "lot size", "land size", "size", "lot area",
        "tamaño", "superficie", "metraje",
    }
    # Theme changed: area moved from vc_toggle to mkdf icon-box widget.
    # First mkdf-icon-box-title on the page is always the area value, e.g.
    # "2,434.61 v2; 1,701.57 m2" or "1014.41 m2" — parse_area handles both.
    DETAIL_AREA_ICONBOX_SEL = "div.mkdf-icon-box-title"

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
        # Fallback: area moved to mkdf icon-box widget ("2,434.61 v2; 1,701.57 m2")
        if not raw_size:
            box = tree.css_first(self.DETAIL_AREA_ICONBOX_SEL)
            if box:
                raw_size = box.text(strip=True)
        location = first(self._TOGGLE_LOC_KEYS) or title

        desc_node = tree.css_first("div.wpb_text_column")
        description = desc_node.text(strip=True) if desc_node else ""

        # Photos — try gallery containers first, then Open Graph hero as fallback
        photo_urls: list[str] = []
        seen: set[str] = set()
        for img in tree.css(
            "div.gallery img, div.wp-block-gallery img, "
            ".mkdf-lightbox-gallery img, .property-gallery img, "
            "div[class*='gallery'] img, div[class*='slider'] img"
        ):
            u = img.attributes.get("data-src") or img.attributes.get("src") or ""
            if u.startswith("http") and u not in seen:
                seen.add(u)
                photo_urls.append(u)
        if not photo_urls:
            og = tree.css_first('meta[property="og:image"]')
            if og:
                u = og.attributes.get("content") or ""
                if u.startswith("http"):
                    photo_urls.append(u)
        photo_urls = upgrade_photo_urls("goodlife", photo_urls)

        # Multi-signal classifier — supersedes the previous hardcode of
        # "land". The hardcode misclassified built listings (real example:
        # "3 Villas Complex in Costa del Sol" with 27 villa-* photo files
        # was typed as land). The classifier reads URL slug, photo file
        # names, title, and description with weighted signals; uncertain
        # listings fall back to "land" (goodlife's dominant type) and are
        # flagged so a human can review.
        url = partial.get("url") or ""
        ptype, signals, confidence, total = classify_property_type({
            "url":         url,
            "photo_urls":  photo_urls,
            "title":       title,
            "description": description,
        }, fallback_type="land")
        rec = {
            "title": title,
            "raw_price_text": raw_price,
            "raw_size_text": raw_size,
            "location_text": location,
            "description": description[:1500],
            "property_type": ptype,
            "photo_urls": photo_urls,
            # Classifier signals piggyback on the record so automation/run.py
            # can write a per-listing log without re-running classification.
            "_type_signals":    [s.to_dict() for s in signals],
            "_type_confidence": confidence,
            "_type_total":      total,
        }
        if confidence == "uncertain":
            rec["validation_status"] = "flagged"
            rec["validation_warnings"] = ["type_uncertain"]

        # Phase C — type-specific fields for house/condo. Land path is
        # untouched (parity with bienesraices PR #65 / remax PR #90 /
        # c21 PR #91). The icon-box layout is the same on both house and
        # condo detail pages; what differs is which numbers populate.
        if ptype in ("house", "condo"):
            iconbox_titles = [
                box.text(strip=True)
                for box in tree.css(self.DETAIL_AREA_ICONBOX_SEL)
            ]
            area_box = iconbox_titles[0] if iconbox_titles else ""
            bed_bath_box = (
                iconbox_titles[2]
                if len(iconbox_titles) >= 3
                else (iconbox_titles[-1] if iconbox_titles else "")
            )

            # Built area: explicit "Construction X m2" wins; otherwise for
            # condos the leading m2 is the unit interior; for houses with
            # only one m2 number (no construction split) we leave built
            # absent rather than guess.
            m_built = _BUILT_M2_RE.search(area_box)
            if m_built:
                try:
                    rec["built_area_m2"] = float(m_built.group(1).replace(",", ""))
                except ValueError:
                    pass
            elif ptype == "condo":
                m_area = _AREA_M2_RE.search(area_box)
                if m_area:
                    try:
                        rec["built_area_m2"] = float(m_area.group(1).replace(",", ""))
                    except ValueError:
                        pass
                # A condo unit has no lot; clear raw_size_text so normalize
                # doesn't attribute the unit's interior area to area_m2.
                rec["raw_size_text"] = ""

            m_bb = _BED_BATH_RE.search(bed_bath_box)
            if m_bb:
                try:
                    rec["bedrooms"] = int(m_bb.group(1))
                except ValueError:
                    pass
                try:
                    rec["bathrooms"] = float(m_bb.group(2))
                except ValueError:
                    pass

            # Vacation-zone filter — drop inland house/condo. Same
            # logic as remax/c21: zone match (ocean coast OR lake) OR
            # waterfront keyword in text wins.
            loc_blob = location.lower().replace(" ", "-")
            zone_is_vacation = any(z in loc_blob for z in VACATION_ZONES)
            text_blob = f"{title}\n{description}"
            has_waterfront_kw = bool(_WATERFRONT_RE.search(text_blob))
            if not zone_is_vacation and not has_waterfront_kw:
                return None

        return rec

    def report_total(self, client) -> Optional[int]:
        """Fetch the land index and return the advertised listing count, or None."""
        try:
            r = client.get("https://goodlifeelsalvador.com/land/")
            r.raise_for_status()
        except Exception:
            return None
        html = r.text
        for pattern in [
            r'Showing\s+(?:all\s+)?(\d+)\s+results?',
            r'(\d+)\s+(?:listings?|properties|results?)\s+found',
            r'woocommerce-result-count[^>]*>\s*(?:[^<]*of\s+)?(\d+)',
        ]:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                return int(m.group(1))
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


_scraper = GoodLifeScraper()
register(SOURCES, "goodlife", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return GoodLifeScraper(offline=offline).crawl(limit)
