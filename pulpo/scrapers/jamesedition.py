"""JamesEdition scraper — PRD C8 [DRAFT skeleton].

Site: https://www.jamesedition.com/es/real_estate/house-lago-de-coatepeque-el-salvador
Status: SKELETON. Calibration steps in pulpo/scrapers/_skeleton_helper.py.

Pre-calibration notes:

- **Luxury-only.** JamesEdition lists houses at $1.5M+ around
  Coatepeque. Low volume (~50 listings expected per PRD) but high-
  value. Some listings will exceed
  ``automation.validation_bounds.PRICE_FLAG_MAX`` ($20M); validation
  will FLAG (keep + warn) which is the correct behavior for luxury
  inventory.

- **JSON-LD.** Modern luxury portals almost always expose
  ``Schema.org Residence`` blocks for SEO. The skeleton's default
  extraction path should work without much calibration.

- **Niche filter.** Default ``force_vacation_gate=True`` is fine —
  Coatepeque is in ``VACATION_ZONES`` so legitimate listings pass.
"""
from __future__ import annotations

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


class JameseditionScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="jamesedition",
        base_url="https://www.jamesedition.com",
        list_url="https://www.jamesedition.com/es/real_estate/lago-de-coatepeque-el-salvador",  # PLACEHOLDER
        page_param="page",
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+(?:listings|propiedades|inmuebles)",
        ),
        max_pages=10,  # ~50 listings expected per PRD
    )


register(SOURCES, "jamesedition", JameseditionScraper())
