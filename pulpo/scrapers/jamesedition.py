"""JamesEdition scraper — PRD C8.

Site: https://www.jamesedition.com/es/real_estate/house-lago-de-coatepeque-el-salvador

Calibration notes (2026-06-05):

- **Cloudflare-fronted.** Live probe with plain httpx returned HTTP 403
  + "Just a moment..." JS challenge. Transport is ``curl_cffi`` with
  Chrome impersonation, same pattern as ``nexo`` / ``realtyelsalvador``
  / ``elagente`` in ``_policy.py``. ``auto_repair=False`` because an
  LLM cannot talk its way past a TLS-fingerprint WAF.

- **Luxury-only.** Houses at $1.5M+ around Coatepeque. Low volume
  (~50 listings expected per PRD) but high-value. Some listings
  exceed ``automation.validation_bounds.PRICE_FLAG_MAX`` ($20M); the
  validation layer FLAGs them (kept + warned) which is the correct
  behaviour for luxury inventory.

- **JSON-LD.** Schema.org ``RealEstateListing`` / ``Residence`` is
  exposed on detail pages for SEO. ``find_jsonld_ci`` handles the
  case mix.

- **Niche filter.** ``force_vacation_gate=True`` is appropriate —
  Coatepeque is in ``VACATION_ZONES`` so legitimate listings pass,
  and any San-Salvador-luxury bleed gets filtered.
"""
from __future__ import annotations

from typing import Optional

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


class JameseditionScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="jamesedition",
        base_url="https://www.jamesedition.com",
        list_url="https://www.jamesedition.com/es/real_estate/house-lago-de-coatepeque-el-salvador",
        page_param="page",
        url_pattern=None,
        detail_url_pattern=(
            r'href="((?:https?://www\.jamesedition\.com)?'
            r'/(?:es/)?real_estate/[a-z0-9\-]+/\d+)"'
        ),
        extract_strategy="detail_jsonld",
        jsonld_schema_types=(
            "RealEstateListing", "Residence", "House",
            "Product", "Place",
        ),
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+(?:listings|propiedades|inmuebles|results)",
            r"de\s+(\d[\d,.]*)\s+(?:resultados|listings)",
        ),
        max_pages=20,
        force_vacation_gate=True,
    )


register(SOURCES, "jamesedition", JameseditionScraper())


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return JameseditionScraper(offline=offline).crawl(limit)
