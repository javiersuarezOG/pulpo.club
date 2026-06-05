"""Minimal sitemap XML parser — extract ``<loc>`` URLs without lxml.

Vivolatam's SSR catalog ships zero listings (hydrated client-side),
but its ``/sitemap/property_listings.xml`` enumerates every property
URL. Same shape works for any sitemap.org-compliant feed.

Regex-based by design — sitemap XML is constrained enough that a real
parser is overkill, and adding lxml to requirements.txt for one
helper isn't worth it.
"""
from __future__ import annotations

import html
import re


_LOC_RE = re.compile(r"<loc>\s*([^<\s][^<]*?)\s*</loc>", re.IGNORECASE)


def extract_loc_urls(xml: str) -> list[str]:
    """Return the ordered list of URLs from a sitemap XML body.

    Tolerates entity-escaped URLs (``&amp;``), trailing whitespace,
    and BOM-prefixed bodies. Returns ``[]`` for empty or malformed
    input.

    Used by ``SkeletonScraper`` when ``extract_strategy="sitemap"``.
    """
    if not xml:
        return []
    return [html.unescape(loc) for loc in _LOC_RE.findall(xml)]
