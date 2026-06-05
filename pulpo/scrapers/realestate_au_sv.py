"""Realtor.com International SV scraper — PRD C7 [DRAFT skeleton].

Site: https://www.realtor.com/international/sv/
Status: SKELETON. **Calibration AND legal/ToS clearance required**.

Pre-calibration decision points:

1. **Legal/ToS clearance.** realtor.com is a US-based franchise; their
   ToS may prohibit scraping. Confirm Pulpo has authorization before
   the calibration pass. PR should not graduate from DRAFT until
   cleared.

2. **Anti-bot.** US-major-portal scrapers usually require a residential
   proxy or curl_cffi to bypass Cloudflare / Akamai bot rules. Plan
   to escalate transport in ``pulpo/scrapers/_policy.py`` (likely
   ``transport="curl_cffi"``) before live runs.

3. **Coverage.** PRD-stated target is 633 listings. If the dev crawl
   yields <50% of that, the source is partially blocked — open an
   issue and decide whether to keep the scraper or drop it.

Calibration steps in pulpo/scrapers/_skeleton_helper.py.
"""
from __future__ import annotations

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


class RealtorIntlSvScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="realtor_intl_sv",
        base_url="https://www.realtor.com",
        list_url="https://www.realtor.com/international/sv/",  # PLACEHOLDER
        page_param="page",
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+listings\s+(?:found|available)",
            r"(\d[\d,.]*)\s+results",
        ),
        max_pages=70,  # ~633 listings expected per PRD
    )


register(SOURCES, "realtor_intl_sv", RealtorIntlSvScraper())
