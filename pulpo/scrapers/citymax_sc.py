"""CityMax Surf City scraper — PRD C4.

Site: https://www.citymax-sc.com

Calibration notes (2026-06-05):

- Catalog URL: ``/inmuebles/venta/el-salvador`` returns every for-sale
  listing. The PRD-suggested ``?in=terrenos%2cfincas`` filter does NOT
  constrain results (page 2 returns casas + bodegas regardless) — drop
  it to avoid pretending to scope.
- Pagination: ``?page=N``. ~14 pages × 12 listings ≈ 168 total.
- Detail-page URL discovery: the catalog ships an ``ItemList`` JSON-LD
  block carrying every listing URL on the page. That's more reliable
  than scraping hrefs from the HTML (cards repeat the same URL 3×).
  ``_extract_detail_urls_from_catalog_page`` is overridden to parse
  ``ItemList.itemListElement[].url`` directly.
- Detail JSON-LD: ``@type=RealEstateListing`` with ``name``,
  ``description``, ``url``, ``image``, ``offers``. Clean Schema.org.
- ``target_discovery_patterns`` captures the "Mostrando 1 de 14"
  text — that's PAGE count, not listing count. Coverage logger will
  also fall back to the dedup'd URL count, which is the better signal.
- ``force_vacation_gate=False`` because Surf City's catalog covers
  mixed inland/coastal inventory; the gate would over-trim.
"""
from __future__ import annotations

from typing import Optional

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper
from pulpo.scrapers.lib import find_jsonld


class CitymaxScScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="citymax_sc",
        base_url="https://www.citymax-sc.com",
        list_url="https://www.citymax-sc.com/inmuebles/venta/el-salvador",
        page_param="page",
        url_pattern=None,
        # Fallback regex used if ItemList parsing comes up empty.
        detail_url_pattern=(
            r'href="((?:https?://www\.citymax-sc\.com)?'
            r'/\d{5,}/[a-z0-9\-]+)"'
        ),
        extract_strategy="detail_jsonld",
        jsonld_schema_types=(
            "RealEstateListing", "Residence", "House",
            "Product", "Place", "Apartment",
        ),
        target_discovery_patterns=(
            r"Mostrando\s+\d+\s+de\s+(\d[\d,.]*)",
            r"(\d[\d,.]*)\s+inmuebles",
            r"(\d[\d,.]*)\s+propiedades",
        ),
        max_pages=30,  # 14 pages observed; allow 2× growth
        force_vacation_gate=False,
    )

    def _extract_detail_urls_from_catalog_page(
        self, body: str, page_num: int,
    ) -> list[str]:
        """Override: parse the catalog's ``ItemList`` JSON-LD block.

        Each catalog page ships an ItemList with 12 ListItem entries
        carrying ``url``. That's the canonical listing URL — preferred
        over href regex which double-counts photo + title + view-detail
        links.
        """
        urls: list[str] = []
        for block in find_jsonld(body, schema_type="ItemList"):
            items = block.get("itemListElement") or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                u = item.get("url")
                if isinstance(u, str) and u:
                    urls.append(u)
        if urls:
            return urls
        # Fallback: href regex over the page body.
        return super()._extract_detail_urls_from_catalog_page(body, page_num)


register(SOURCES, "citymax_sc", CitymaxScScraper())


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return CitymaxScScraper(offline=offline).crawl(limit)
