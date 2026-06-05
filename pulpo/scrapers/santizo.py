"""Santizo Real Estate scraper — PRD C3 [DRAFT skeleton].

Site: https://santizorealestate.com
Status: SKELETON. Calibration steps in pulpo/scrapers/_skeleton_helper.py.

Pre-calibration note: Santizo's site looks like WordPress; pagination
is likely /page/N/ (set url_pattern accordingly). The agency also
publishes inventory on Encuentra24 — expect overlap with the existing
encuentra24 scraper; verify via the D1 dedup_audit overlap matrix
after first nightly.
"""
from __future__ import annotations

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


class SantizoScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="santizo",
        base_url="https://santizorealestate.com",
        list_url="https://santizorealestate.com/s/casa/ventas",  # PLACEHOLDER
        page_param=None,
        url_pattern="https://santizorealestate.com/s/casa/ventas/page/{page}/",
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+propiedades",
            r"(\d[\d,.]*)\s+inmuebles",
        ),
        max_pages=20,  # ~150 listings expected per PRD; 10 per page
    )


register(SOURCES, "santizo", SantizoScraper())
