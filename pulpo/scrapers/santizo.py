"""Santizo Real Estate scraper — PRD C3.

Site: https://santizorealestate.com

Calibration notes (2026-06-05):
- The base catalog at ``/s/ventas`` returns every for-sale listing
  across all property types. Walking it page-by-page is simpler than
  iterating ``id_property_type=11,17,32`` separately, and it surfaces
  inventory the type filters miss.
- Pagination is ``?page=N`` (the legacy WordPress ``/page/N/`` shape
  documented in the original skeleton is NOT how this site paginates).
- Detail-page URLs follow ``/<slug>/<6+digit-id>`` (e.g.
  ``/casa-venta-cumbres-de-escalon-san-salvador/9574852``).
- Detail JSON-LD ships with ``@type="house"`` lowercase — non-canonical
  but parseable via ``find_jsonld_ci``.
- Santizo carries cross-country inventory; the catalog mixes Salvadoran
  and Dominican Republic listings. ``_post_finalize_filter`` drops the
  non-SV ones based on URL slug + JSON-LD ``addressCountry``.

Expect overlap with the existing encuentra24 scraper; verify via the
dedup audit's overlap matrix after the first nightly.
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
from pulpo.scrapers.lib import extract_og, find_jsonld_ci


# City / country tokens that signal cross-country inventory leaking
# into santizo's catalog. Extend conservatively — false positives drop
# real SV listings.
_NON_SV_URL_TOKENS = frozenset({
    "punta-cana", "bavaro", "santo-domingo", "puerto-plata", "cabarete",
    "casa-de-campo", "las-terrenas",  # Dominican Republic
})

# Title-string country signals. Used when the listing URL slug claims
# SV but the actual property is elsewhere (santizo's editorial copy
# names the country explicitly in titles for cross-country units).
_NON_SV_TITLE_TOKENS = frozenset({
    "panama", "guatemala", "honduras", "nicaragua", "costa rica",
    "mexico", "méxico", "republica dominicana", "república dominicana",
    "punta cana", "playa del carmen", "tulum",
})


class SantizoScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="santizo",
        base_url="https://santizorealestate.com",
        list_url="https://santizorealestate.com/s/ventas",
        page_param="page",
        url_pattern=None,
        detail_url_pattern=(
            r'href="((?:https?://santizorealestate\.com)?'
            r'/[a-z][a-z0-9\-]+/\d{5,})"'
        ),
        extract_strategy="detail_jsonld",
        jsonld_schema_types=("house", "House", "Residence", "RealEstateListing", "Product"),
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+propiedades",
            r"(\d[\d,.]*)\s+inmuebles",
            r"(\d[\d,.]*)\s+resultados",
        ),
        max_pages=40,
        force_vacation_gate=False,  # broad SV inventory; gate would drop SS/inland houses
    )

    def _extract_detail(self, body: str, url: str, *, strategy: str) -> Optional[dict]:
        """Override: santizo's JSON-LD lacks ``offers`` / ``price``, so
        we read price + area from og:meta + page body to fill the gaps.
        """
        blocks = find_jsonld_ci(body, self.CONFIG.jsonld_schema_types)
        record: Optional[dict] = None
        if blocks:
            record = self._finalize_jsonld_block(blocks[0], url=url)
        og = extract_og(body) or {}
        if record is None:
            # No JSON-LD — synthesise from og:meta alone.
            record = {
                "source": self.CONFIG.slug,
                "source_id": url.rstrip("/").rsplit("/", 1)[-1] or "unknown",
                "url": url,
                "title": og.get("title") or "",
                "description": og.get("description") or "",
                "price_usd": None,
                "area_m2": None,
                "photo_urls": og.get("image") or [],
                "raw_size_text": None,
                "property_type": None,
                "location_text": "",
                "_jsonld_country": None,
            }
        # Price: og:title carries "US$X,XXX,XXX" — always preferred over
        # JSON-LD offers (which is empty on santizo today).
        og_title = og.get("title") or ""
        if record.get("price_usd") is None:
            m = re.search(r"US\$\s*([\d.,]+)|\$\s*([\d.,]+)", og_title)
            if m:
                raw = m.group(1) or m.group(2)
                if raw:
                    record["price_usd"] = _to_float(raw)
        # Area: detail page often carries "1,500 m²" / "1500 mts²" patterns
        # in the visible HTML; pull from body if JSON-LD lacks it.
        if record.get("area_m2") is None:
            m = re.search(r"([\d.,]+)\s*(?:m\s*[²2]|mts\s*[²2]?|metros)", body, re.IGNORECASE)
            if m:
                record["area_m2"] = _to_float(m.group(1))
                record["raw_size_text"] = m.group(0)
        return record

    def _post_finalize_filter(self, record: dict) -> Optional[dict]:
        url = (record.get("url") or "").lower()
        for token in _NON_SV_URL_TOKENS:
            if token in url:
                return None
        title_lower = (record.get("title") or "").lower()
        for token in _NON_SV_TITLE_TOKENS:
            if token in title_lower:
                return None
        country = record.get("_jsonld_country")
        if isinstance(country, str):
            c = country.strip().lower()
            if c and c not in ("sv", "slv", "el salvador", "salvador"):
                return None
        return record


register(SOURCES, "santizo", SantizoScraper())


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return SantizoScraper(offline=offline).crawl(limit)
