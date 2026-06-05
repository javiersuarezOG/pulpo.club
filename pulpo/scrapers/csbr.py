"""CSBR — Cámara Salvadoreña de Bienes Raíces scraper — PRD C6.

Site: https://www.camarabienesraices.com.sv

Calibration notes (2026-06-05):

- Catalog at ``/resultado-busqueda/`` with URL-encoded ``type[]`` filters
  for fincas + playa + terrenos returns 293 results across 19 pages
  (16 listings per page).
- Pagination is the WordPress ``/page/N/`` shape — CSBR runs Houzez on
  WordPress. ``url_pattern`` carries the URL-encoded params verbatim
  so each page request preserves the filter set.
- Detail-page URLs: ``/propiedad/<slug>/`` with Unicode-emoji slugs.
- Detail JSON-LD: ``RealEstateListing`` lives inside a ``@graph`` array
  alongside ``WebPage``, ``ImageObject``, ``BreadcrumbList``,
  ``WebSite``, ``Organization``. ``find_jsonld_ci`` already flattens
  ``@graph`` so the listing block is directly accessible.
- ``force_vacation_gate=True`` per CLAUDE.md decision — CSBR is the
  authoritative coastal/lake gate-keeper among Phase C sources.
- Institutional source — already registered in
  ``pulpo.quality_score.INSTITUTIONAL_SOURCES`` for the +1 ranking
  nudge.
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

_PRICE_RE = re.compile(r'class="item-price"[^>]*>\s*\$?\s*([\d.,]+)')
_AREA_RE = re.compile(r'(\d[\d.,]*)\s*(?:m\s*[²2]|mts\s*[²2]?|vrs\s*[²2]?|varas?)', re.IGNORECASE)


class CsbrScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="csbr",
        base_url="https://www.camarabienesraices.com.sv",
        list_url=(
            "https://www.camarabienesraices.com.sv/resultado-busqueda/"
            "?keyword=&type%5B0%5D=fincas&type%5B1%5D=playa&type%5B2%5D=terrenos"
        ),
        page_param=None,
        url_pattern=(
            "https://www.camarabienesraices.com.sv/resultado-busqueda/page/{page}/"
            "?keyword&type%5B0%5D=fincas&type%5B1%5D=playa&type%5B2%5D=terrenos"
        ),
        detail_url_pattern=(
            r'href="((?:https?://www\.camarabienesraices\.com\.sv)?'
            r'/propiedad/[^"#]+/)"'
        ),
        extract_strategy="detail_jsonld",
        jsonld_schema_types=(
            "RealEstateListing", "Residence", "House",
            "Product", "Place", "WebPage",
        ),
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+Resultados\s+encontrados",
            r"(\d[\d,.]*)\s+resultados",
            r"(\d[\d,.]*)\s+propiedades",
        ),
        max_pages=40,  # ~293 listings × 16/page = ~19 pages; allow 2× headroom
        force_vacation_gate=False,  # type-filtered catalog (fincas+playa+terrenos) — let downstream rank
    )

    def _extract_detail(self, body: str, url: str, *, strategy: str) -> Optional[dict]:
        """Override: CSBR's JSON-LD ``RealEstateListing`` carries name +
        image + breadcrumb but NOT price. Pull price from the Houzez
        ``<li class="item-price">`` element and area from the visible
        spec block.
        """
        blocks = find_jsonld_ci(body, self.CONFIG.jsonld_schema_types)
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
            m = _PRICE_RE.search(body)
            if m:
                record["price_usd"] = _to_float(m.group(1))
        if record.get("area_m2") is None:
            m = _AREA_RE.search(body)
            if m:
                record["area_m2"] = _to_float(m.group(1))
                record["raw_size_text"] = m.group(0)
        return record


register(SOURCES, "csbr", CsbrScraper())


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return CsbrScraper(offline=offline).crawl(limit)
