"""Xitios scraper — PRD C1 (DRAFT / skeleton).

Site:   https://www.xitios.com.sv
Status: **SKELETON — NOT PRODUCTION READY.**

This file is the reference pattern for Phase C of the inventory-
expansion workstream. It demonstrates how a new scraper should
compose the ``pulpo/scrapers/lib/*`` primitives introduced in PR B1:

  - ``lib.paginator.paginate`` — page walker.
  - ``lib.jsonld.find_jsonld`` — JSON-LD card extraction.
  - ``lib.target_discoverer.discover_target`` — parse the source's
    own "X listings" UI claim so the coverage gauge has a denominator.
  - ``lib.coverage_logger.log_coverage`` — write per-scrape coverage
    row to ``web/data/scraper_coverage_history.jsonl``.
  - ``lib.dedup_hasher.listing_fingerprint`` — stable content
    fingerprint for cross-source overlap detection.

What's still needed before this scraper goes live
-------------------------------------------------
1. **Capture real HTML.** The patterns below are PLACEHOLDERS based on
   educated guesses at Xitios's markup. Walk the live site, capture a
   listing page + a catalog page, drop them under
   ``samples/xitios/``, and refine:
     - ``LISTING_CARD_SELECTOR`` (the catalog card root)
     - ``DETAIL_PRICE_SELECTOR``, ``DETAIL_AREA_SELECTOR``,
       ``DETAIL_TITLE_SELECTOR`` (the detail-page fields)
     - ``TARGET_DISCOVERY_PATTERNS`` (the "X propiedades" UI claim)
2. **Add a Policy row** at ``pulpo/scrapers/_policy.py`` keyed
   ``"xitios"`` (UA rotation + rate limit + transport). Until added,
   the scraper falls back to ``DEFAULT_POLICY`` — safe but un-tuned.
3. **Calibrate coverage**: run, observe
   ``coverage_ratio_vs_discovered``, iterate ``MAX_PAGES`` /
   selectors until the ratio ≥ 0.8. PR-merge gate is ratio ≥ 0.8 on
   a dev run.
4. **Move out of DRAFT**: open the PR for review once the calibration
   pass is done and the offline fixture reflects real HTML.

The skeleton ships with a SYNTHETIC offline fixture (``samples/xitios/
sample_listings.json``) just so the offline-mode contract test passes
and the scraper module imports cleanly. The real fixture replaces it
during step 1.

Schema produced
---------------
Same as every Pulpo scraper: ``finalize_record(...)`` returns a dict
with the canonical Listing fields (source, source_id, url, title,
description, price_usd, area_m2, photo_urls, raw_size_text,
property_type, ...).
"""
from __future__ import annotations

import re
from typing import Optional

from pulpo.agents import SOURCES, register
from pulpo.scrapers._base import OfflineFixtureMixin, finalize_record
from pulpo.scrapers.lib import (
    discover_target,
    find_jsonld,
    log_coverage,
    paginate,
)


BASE_URL    = "https://www.xitios.com.sv"
LIST_URL    = f"{BASE_URL}/propiedades"     # placeholder — verify against live site
MAX_PAGES   = 50
FIXTURE_FILE = "sample_listings.json"


# Patterns for the source's own "X propiedades" UI claim. Each pattern
# is tried in order; first match wins. Live calibration may need to
# add Spanish + English variants.
TARGET_DISCOVERY_PATTERNS: list[str] = [
    r"(\d[\d,.]*)\s+propiedades",
    r"(\d[\d,.]*)\s+inmuebles",
    r"Mostrando\s+(\d[\d,.]*)",
    r"Total[:\s]+(\d[\d,.]*)",
]


# Placeholder selectors — REPLACE WITH REAL ONES after capturing HTML.
LISTING_CARD_SELECTOR = "div.property-card"
DETAIL_TITLE_SELECTOR = "h1.property-title"
DETAIL_PRICE_SELECTOR = ".property-price"
DETAIL_AREA_SELECTOR  = ".property-area"


_PRICE_NUM_RE = re.compile(r"(\d[\d,.]*)")
_AREA_NUM_RE  = re.compile(r"(\d[\d,.]*)\s*(?:m²|m2|m|varas?)")


def _parse_number(raw: Optional[str]) -> Optional[float]:
    if not isinstance(raw, str):
        return None
    cleaned = re.sub(r"[,.\s]", "", raw)
    if not cleaned.isdigit():
        return None
    return float(cleaned)


def _extract_price(html: str) -> Optional[float]:
    match = _PRICE_NUM_RE.search(html or "")
    if not match:
        return None
    return _parse_number(match.group(1))


def _extract_area(html: str) -> Optional[float]:
    match = _AREA_NUM_RE.search(html or "")
    if not match:
        return None
    return _parse_number(match.group(1))


class XitiosScraper(OfflineFixtureMixin):
    """Xitios SV-native real-estate portal. Phase C1 skeleton.

    Today's implementation:
      - Offline fixture path (used by tests + CI in offline mode):
        loads ``samples/xitios/sample_listings.json`` via
        ``OfflineFixtureMixin._offline_or_fixtures``.
      - Online path: skeleton only. Pagination + extraction selectors
        are PLACEHOLDERS pending real-HTML capture (see module
        docstring).
    """

    slug = "xitios"
    country = "SV"
    FIXTURE_FILE = FIXTURE_FILE

    def __init__(self, offline: bool | None = None) -> None:
        self.offline = offline

    def crawl(self, limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
        fixture = self._offline_or_fixtures(limit, override_offline=offline)
        if fixture is not None:
            return self._finalize_batch(fixture)
        return self._crawl_online(limit)

    def _finalize_batch(self, raws: list[dict]) -> list[dict]:
        out: list[dict] = []
        for raw in raws:
            final = finalize_record(raw, slug=self.slug, broker_type="agency")
            if final is not None:
                out.append(final)
        return out

    def _crawl_online(self, limit: int) -> list[dict]:
        """Online path — SKELETON. Walks paginated catalog pages,
        extracts JSON-LD card blocks where available. Logs coverage
        at the end.

        TODO (calibration pass, see module docstring):
          - Verify TARGET_DISCOVERY_PATTERNS against the live page.
          - Verify LISTING_CARD_SELECTOR / DETAIL_*_SELECTOR + add
            the CSS-selector fallback path (currently only JSON-LD).
          - Confirm ?page=N vs /page/N/ pagination shape.
          - Add a Policy(...) row in _policy.py if rate-limit needs tuning.
          - Call `_extract_price` / `_extract_area` from the CSS-selector
            fallback once selectors are known (they're unused today but
            kept in module-scope as the eventual call surface).
        """
        # Import here to defer the policy-resolution cost when offline.
        from pulpo.agents.html_crawler import HTTPX_OK, make_client
        from pulpo.scrapers._base import polite_get_for

        if not HTTPX_OK:
            return []

        raw_records: list[dict] = []
        target_discovered: Optional[int] = None

        get = polite_get_for(self.slug)
        with make_client() as client:
            for page_num, resp in paginate(
                fetch=lambda url: get(client, url),
                base_url=LIST_URL,
                page_param="page",
                start=1,
                max_pages=MAX_PAGES,
                # No stop_signal yet — calibrate against the live "no
                # results" page during the HTML capture step.
            ):
                body = getattr(resp, "text", "") or ""
                if page_num == 1 and target_discovered is None:
                    target_discovered = discover_target(body, TARGET_DISCOVERY_PATTERNS)

                # Prefer JSON-LD when the site exposes it (every modern
                # real-estate stack should, including WordPress + Yoast).
                for ld_block in find_jsonld(body, schema_type="Residence"):
                    raw_records.append(self._from_jsonld(ld_block))

                if len(raw_records) >= limit:
                    break

        out = self._finalize_batch(raw_records[:limit])

        log_coverage(
            self.slug,
            raw_count=len(raw_records),
            kept_count=len(out),
            target_prd=None,
            target_discovered=target_discovered,
        )
        return out

    def _from_jsonld(self, block: dict) -> dict:
        """Map a JSON-LD Residence block to the raw-record dict shape
        the downstream finalize_record pipeline expects.

        TODO calibration: the field names below assume Schema.org's
        Residence type. Some sites use Product or RealEstateListing —
        adapt during the HTML capture pass.
        """
        url = block.get("url") or ""
        offers = block.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price_raw = offers.get("price") if isinstance(offers, dict) else None
        photos = block.get("image") or []
        if isinstance(photos, str):
            photos = [photos]
        area = (
            block.get("floorSize", {}).get("value")
            if isinstance(block.get("floorSize"), dict)
            else None
        )
        return {
            "source":    self.slug,
            "source_id": str(block.get("identifier") or url.rsplit("/", 1)[-1]),
            "url":       url,
            "title":     block.get("name") or block.get("description") or "",
            "description": block.get("description") or "",
            "price_usd": _parse_number(price_raw),
            "area_m2":   _parse_number(str(area)) if area is not None else None,
            "photo_urls": photos if isinstance(photos, list) else [],
            "raw_size_text": block.get("floorSize", {}).get("unitText") if isinstance(block.get("floorSize"), dict) else None,
            "property_type": None,  # let finalize_record's multi-signal classifier decide
        }


_scraper = XitiosScraper()
register(SOURCES, "xitios", _scraper)
