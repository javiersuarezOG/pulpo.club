"""Agentiz scraper — PRD C2 [DRAFT skeleton].

Site: https://sv.agentiz.com/en
Status: SKELETON. Calibration steps in pulpo/scrapers/_skeleton_helper.py.

Pre-calibration decision: investigate whether Agentiz exposes a public
JSON API at agentiz.com. Agency CRMs frequently do. If yes, prefer the
API over HTML scraping — replace ``LIST_URL`` with the API endpoint
and adapt ``_from_jsonld`` to map JSON-API records.
"""
from __future__ import annotations

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


class AgentizScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="agentiz",
        base_url="https://sv.agentiz.com",
        list_url="https://sv.agentiz.com/en/properties",  # PLACEHOLDER
        page_param="page",
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+(?:properties|listings)",
            r"(\d[\d,.]*)\s+propiedades",
        ),
    )


register(SOURCES, "agentiz", AgentizScraper())
