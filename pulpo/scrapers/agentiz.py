"""Agentiz scraper — PRD C2.

Site: https://sv.agentiz.com

Calibration notes (2026-06-05):

- Agentiz exposes **no catalog grid**. The SV-host landing
  (``sv.agentiz.com/en``) just enumerates ~5 hardcoded type-slot
  URLs (``/en/for-sale-land-{residential,commercial}-property/id-sv<X>``).
  Each "slot" URL IS a single listing detail.
- Detail pages ship Schema.org JSON-LD with
  ``@type=["RealEstateListing","Product"]`` populated.
- No pagination. No "X listings" UI count text. ``extract_strategy``
  is ``static_urls``; ``target_discovered`` falls back to
  ``len(static_urls)``.
- ``force_vacation_gate=False`` — the inventory is too small to
  meaningfully scope, and the 5 listings cover a mix of land types.

Low-volume by design — expect ~5 listings until Agentiz expands its
SV inventory. The watchdog at scripts/check_source_health.py will
treat ~5 as the historic floor, not a degradation signal.
"""
from __future__ import annotations

from typing import Optional

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


_TYPE_SLOTS = (
    "https://sv.agentiz.com/en/for-sale-land-residential-property/id-svf",
    "https://sv.agentiz.com/en/for-sale-land-residential-property/id-svh",
    "https://sv.agentiz.com/en/for-sale-land-residential-property/id-svw",
    "https://sv.agentiz.com/en/for-sale-land-commercial-property/id-sv3",
    "https://sv.agentiz.com/en/for-sale-land-commercial-property/id-sv5",
)


class AgentizScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="agentiz",
        base_url="https://sv.agentiz.com",
        list_url="",  # unused — static-urls strategy bypasses catalog
        page_param=None,
        url_pattern=None,
        extract_strategy="static_urls",
        static_urls=_TYPE_SLOTS,
        jsonld_schema_types=(
            "RealEstateListing", "Residence", "House",
            "Product", "Place",
        ),
        force_vacation_gate=False,
        target_discovery_patterns=(),
        max_pages=1,
    )


register(SOURCES, "agentiz", AgentizScraper())


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return AgentizScraper(offline=offline).crawl(limit)
