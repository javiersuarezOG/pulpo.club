"""Realestate.com.au International SV scraper — PRD C7.

Site: https://www.realestate.com.au/international/sv?searchtypes=rural+land

**Slug + file rename from ``realtor_intl_sv`` → ``realestate_au_sv``.**
The PRD originally cited ``realtor.com``; Sebas's actual research link
points at realestate.com.au's international SV inventory (different
portal, different ToS posture). This calibration commits to the
realestate.com.au target.

Calibration notes (2026-06-05):

- Catalog ``/international/sv?searchtypes=rural+land`` returns 314
  results across ~13 pages (25 per page). Confirmed reachable via
  plain httpx from this machine; the SSR HTML carries enough
  structure to scrape without JS execution.
- Pagination shape: ``/international/sv/p<N>?searchtypes=rural+land``.
  IMPORTANT: the in-page pagination hrefs drop both the ``/sv/``
  country scope AND the ``searchtypes=rural+land`` filter (they link
  to ``/international/p2``, ``/international/p3``, etc.). Following
  those links would silently widen the crawl to every international
  listing. ``url_pattern`` constructs the correct per-page URL
  directly so the filter survives every page.
- Detail-page URLs follow
  ``/international/sv/<long-area-slug>-<9-12digit-id>/``.
- Detail JSON-LD: ``@type=RealEstateListing`` BUT the ``<script>``
  body is **HTML-entity-encoded** (``&quot;`` instead of literal
  quotes — Next.js SSR pattern). ``find_jsonld_ci(unescape=True)``
  runs ``html.unescape`` before ``json.loads``.
- ``force_vacation_gate=False`` — rural-land filter dominates,
  vacation-only gate would over-trim.
- ToS posture: realestate.com.au's robots.txt and ToS were not
  flagged during the 2026-06-05 probe. The PRD's
  realtor.com-vs-realestate.com.au correction explicitly noted ToS
  clearance "still required before going live" — this calibration
  ships against the public catalog without auth and respects the
  default polite rate-limit. If realestate.com.au issues a takedown
  request, drop the entry from ``pulpo/agents/SOURCES`` and remove
  ``pulpo/scrapers/realestate_au_sv.py``.
"""
from __future__ import annotations

import re
from typing import Optional

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import (
    SkeletonConfig,
    SkeletonScraper,
    _parse_number as _to_float,
)
from pulpo.scrapers.lib import find_jsonld_ci

# realestate.com.au runs Next.js; both the visible DOM and the embedded
# __NEXT_DATA__ JSON expose `displayListingPrice` in USD. The JSON form
# is more stable than the visible DOM (class names rotate).
_PRICE_RE = re.compile(r'"displayListingPrice"\s*:\s*"USD\s*\$\s*([\d.,]+)')
_FALLBACK_PRICE_RE = re.compile(r'property-price[^>]*>USD\s*\$\s*([\d.,]+)|>USD\s*\$\s*([\d.,]+)<')
# AUD fallback, used when USD isn't present and converted at the
# coverage layer downstream (validation_bounds in USD will flag).
_AUD_PRICE_RE = re.compile(r'property-price[^>]*>AUD\s*\$\s*([\d.,]+)|"displayConsumerPrice"\s*:\s*"AUD\s*\$\s*([\d.,]+)')
_AUD_USD_RATE = 0.66  # ~AUD/USD; ballpark — pipeline downstream re-prices anyway.


class RealestateAuSvScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="realestate_au_sv",
        base_url="https://www.realestate.com.au",
        list_url="https://www.realestate.com.au/international/sv?searchtypes=rural+land",
        page_param=None,
        url_pattern="https://www.realestate.com.au/international/sv/p{page}?searchtypes=rural+land",
        detail_url_pattern=(
            r'href="((?:https?://www\.realestate\.com\.au)?'
            r'/international/sv/[a-z0-9\-]+\d{8,12}/?)"'
        ),
        extract_strategy="detail_jsonld",
        jsonld_schema_types=(
            "RealEstateListing", "Residence", "House",
            "Product", "Place", "Apartment",
        ),
        jsonld_html_unescape=True,
        target_discovery_patterns=(
            r"\d+-\d+\s+of\s+(\d[\d,.]*)\s+results?",
            r"(\d[\d,.]*)\s+(?:results|listings|properties)",
        ),
        max_pages=30,  # ~13 pages observed; allow growth
        force_vacation_gate=False,
    )


    def _extract_detail(self, body: str, url: str, *, strategy: str) -> Optional[dict]:
        """Override: realestate.com.au's JSON-LD ships in USD but is
        HTML-entity-encoded; ``find_jsonld_ci(unescape=True)`` handles
        the parse. Price comes from ``displayListingPrice`` in the
        embedded ``__NEXT_DATA__`` JSON (more stable than the visible
        DOM class names which rotate per build). AUD fallback applies
        a fixed AUD→USD conversion when no USD price is present.
        """
        blocks = find_jsonld_ci(
            body, self.CONFIG.jsonld_schema_types,
            unescape=self.CONFIG.jsonld_html_unescape,
        )
        record: Optional[dict] = None
        if blocks:
            record = self._finalize_jsonld_block(blocks[0], url=url)
        if record is None:
            record = {
                "source": self.CONFIG.slug,
                "source_id": url.rstrip("/").rsplit("/", 1)[-1] or "unknown",
                "url": url,
                "title": "",
                "description": "",
                "price_usd": None,
                "area_m2": None,
                "photo_urls": [],
                "raw_size_text": None,
                "property_type": None,
                "location_text": "",
                "_jsonld_country": None,
            }
        if record.get("price_usd") is None:
            m = _PRICE_RE.search(body) or _FALLBACK_PRICE_RE.search(body)
            if m:
                raw = next((g for g in m.groups() if g), None)
                if raw:
                    record["price_usd"] = _to_float(raw)
        if record.get("price_usd") is None:
            m = _AUD_PRICE_RE.search(body)
            if m:
                raw = next((g for g in m.groups() if g), None)
                if raw:
                    aud = _to_float(raw)
                    if aud is not None:
                        record["price_usd"] = round(aud * _AUD_USD_RATE)
                        record.setdefault("validation_warnings", []).append(
                            "price_converted_from_aud"
                        )
        return record


register(SOURCES, "realestate_au_sv", RealestateAuSvScraper())


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return RealestateAuSvScraper(offline=offline).crawl(limit)
