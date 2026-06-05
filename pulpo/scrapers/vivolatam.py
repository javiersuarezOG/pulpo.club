"""Vivo Latam scraper — PRD C5.

Site: https://www.vivolatam.com

Calibration notes (2026-06-05):

- The catalog page is **client-side rendered** (Next.js hydration).
  The SSR HTML carries Organization / WebSite / ContactPoint JSON-LD
  but **zero listing-level structured data**, and there are no
  card hrefs to scrape from the SSR body.
- The ``/sitemap/property_listings.xml`` feed exposes every property
  detail URL — 204 entries on 2026-06-05, all SV. The sitemap is the
  reliable URL source.
- Detail pages are fully SSR'd with JSON-LD:
  Organization / RealEstateAgent / WebSite / **RealEstateListing** /
  BreadcrumbList. The ``RealEstateListing`` block carries name, url,
  description, image, offers.
- Country scoping: per the country-hardcode guardrail
  (``scripts/check_country_hardcodes.py``), filter on path
  ``/<active-country>/`` rather than literal ``"SV"`` /
  ``"el-salvador"`` strings. ``pulpo.countries.active()`` provides the
  slug used to construct the path filter.
- ``force_vacation_gate=False`` — vivolatam carries broad SV
  inventory (urban + rural + coastal); the gate would over-trim.
"""
from __future__ import annotations

from typing import Optional

from pulpo.agents import SOURCES, register
from pulpo.countries import active as _active_country
from pulpo.scrapers._skeleton_helper import SkeletonConfig, SkeletonScraper


def _country_path_filter() -> str:
    """Return the sitemap-URL substring filter for the active country.

    Reads the active country slug at module-import time so this scraper
    is multi-country-ready. The current SV manifest gives ``el-salvador``;
    a future PA manifest would give ``panama``, etc.
    """
    code = (_active_country().code or "SV").lower()
    return {
        "sv": "/el-salvador/",
        "pa": "/panama/",
        "gt": "/guatemala/",
        "hn": "/honduras/",
        "ni": "/nicaragua/",
        "cr": "/costa-rica/",
    }.get(code, f"/{code}/")


class VivolatamScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="vivolatam",
        base_url="https://www.vivolatam.com",
        list_url="",  # unused — sitemap strategy bypasses pagination
        page_param=None,
        url_pattern=None,
        extract_strategy="sitemap",
        sitemap_url="https://www.vivolatam.com/sitemap/property_listings.xml",
        sitemap_url_filter=(_country_path_filter(), "for-sale"),
        jsonld_schema_types=(
            "RealEstateListing", "Residence", "House",
            "Product", "Place", "Apartment",
        ),
        force_vacation_gate=False,
        target_discovery_patterns=(),  # sitemap entry count is the signal
        max_pages=1,
    )


register(SOURCES, "vivolatam", VivolatamScraper())


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return VivolatamScraper(offline=offline).crawl(limit)
