"""CityMax Surf City scraper — PRD C4 [DRAFT skeleton].

Site: https://www.citymax-sc.com
Status: SKELETON. Calibration steps in pulpo/scrapers/_skeleton_helper.py.

Pre-calibration decision: the existing ``citymax`` scraper handles the
SV-wide CityMax branch. CityMax Surf City is the coastal/Surf City
sibling. They MAY share the same CMS — if so, this scraper can copy
``pulpo/scrapers/citymax.py``'s selectors verbatim with only BASE_URL
changed. Verify inventory is genuinely distinct (not the same
listings cross-published) via the D1 dedup_audit overlap matrix.
"""
from __future__ import annotations

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


class CitymaxScScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="citymax_sc",
        base_url="https://www.citymax-sc.com",
        list_url="https://www.citymax-sc.com/propiedades",  # PLACEHOLDER
        page_param="page",
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+propiedades",
        ),
        max_pages=40,  # ~300 listings expected per PRD
    )


register(SOURCES, "citymax_sc", CitymaxScScraper())
