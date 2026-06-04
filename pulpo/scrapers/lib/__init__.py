"""Scraper primitives — PRD B1.

Additive library of reusable building blocks for the Phase C scrapers
(Xitios, Agentiz, Santizo, CityMax Surf City, Vivo Latam, CSBR,
Realtor.com Intl, JamesEdition). Existing scrapers under
``pulpo/scrapers/`` are NOT touched — they continue to import from
``pulpo.scrapers._base`` as before.

Five primitives:

- ``paginator`` — URL pagination over ?page=N and /page/N/ shapes.
- ``jsonld`` — find + filter JSON-LD blocks by @type.
- ``dedup_hasher`` — stable per-listing fingerprint for cross-source dedup.
- ``coverage_logger`` — append per-scrape coverage row to
  ``web/data/scraper_coverage_history.jsonl``.
- ``target_discoverer`` — read the source's own "X listings" UI claim
  via regex, so we can iterate the scraper until kept-count ≈ stated
  inventory. This is the "stated number" feedback loop from the
  events-discovery playbook.

Medium-grade seam (zero runtime cost today, ToolSpec-retrofit-ready)
lives next door at ``pulpo/scrapers/_metadata.py``.
"""
from __future__ import annotations

from pulpo.scrapers.lib.coverage_logger import log_coverage
from pulpo.scrapers.lib.dedup_hasher import listing_fingerprint
from pulpo.scrapers.lib.jsonld import find_jsonld
from pulpo.scrapers.lib.paginator import paginate
from pulpo.scrapers.lib.target_discoverer import discover_target

__all__ = [
    "discover_target",
    "find_jsonld",
    "listing_fingerprint",
    "log_coverage",
    "paginate",
]
