"""Vivo Latam scraper — PRD C5 [DRAFT skeleton].

Site: https://www.vivolatam.com/es/el-salvador/real-estate
Status: SKELETON. Calibration steps in pulpo/scrapers/_skeleton_helper.py.

Pre-calibration note: Vivo Latam is multi-country (Costa Rica,
Panama, Guatemala, Honduras, Nicaragua, El Salvador). We MUST filter
to SV listings at the scraper level — the multi-country listings
would otherwise pollute the SV catalog.

Country-hardcode guardrail: when filtering to SV, read the country
code from ``pulpo.countries.active()``, NOT a hardcoded "SV"
literal. See ``automation/validation.py``'s dynamic country pattern
for the canonical idiom.
"""
from __future__ import annotations

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


class VivolatamScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="vivolatam",
        base_url="https://www.vivolatam.com",
        list_url="https://www.vivolatam.com/es/el-salvador/real-estate",  # SV-scoped path
        page_param="page",
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+propiedades",
            r"(\d[\d,.]*)\s+inmuebles",
        ),
        max_pages=50,  # ~400 listings expected per PRD
    )


register(SOURCES, "vivolatam", VivolatamScraper())
