"""CSBR — Cámara Salvadoreña de Bienes Raíces scraper — PRD C6 [DRAFT skeleton].

Site: https://www.camarabienesraices.com.sv
Status: SKELETON. Calibration steps in pulpo/scrapers/_skeleton_helper.py.

Pre-calibration note: CSBR is the official Salvadoran real-estate
industry association. Member agencies only — institutional
inventory with high data completeness. Lower volume (~100 listings
expected per PRD) but high quality. Source is marked
``institutional`` so the soft quality_score leg gives it the +1
bonus (see pulpo/quality_score.INSTITUTIONAL_SOURCES — already
includes "csbr" forward-looking).
"""
from __future__ import annotations

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


class CsbrScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="csbr",
        base_url="https://www.camarabienesraices.com.sv",
        list_url="https://www.camarabienesraices.com.sv/propiedades",  # PLACEHOLDER
        page_param="page",
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+propiedades",
            r"(\d[\d,.]*)\s+inmuebles",
        ),
        max_pages=15,  # ~100 listings expected per PRD
    )


register(SOURCES, "csbr", CsbrScraper())
