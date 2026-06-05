"""Shared scaffold for Phase C skeleton scrapers (DRAFT).

The Phase C scrapers (Agentiz, Santizo, CityMax Surf City, Vivo Latam,
CSBR, Realtor.com Intl, JamesEdition) all follow the same pattern:

  - fetch paginated catalog pages via ``lib.paginator.paginate``
  - extract JSON-LD ``Residence`` cards via ``lib.jsonld.find_jsonld``
  - parse the source's own "X listings" UI claim via
    ``lib.target_discoverer.discover_target``
  - log per-scrape coverage via ``lib.coverage_logger.log_coverage``
  - finalize each record through the existing
    ``pulpo.scrapers._base.finalize_record`` pipeline

Until the per-source calibration pass replaces placeholder selectors
with real HTML-capture-driven ones, the skeleton just exercises the
offline-fixture path (so the contract test in
``tests/test_source_integration.py`` passes) and demonstrates how to
compose the lib primitives. Each scraper file calls
``SkeletonConfig(...)`` with its site-specific parameters; this module
implements the shared crawl logic.

Calibration steps to graduate a scraper from DRAFT to ready:

  1. Capture real HTML for the source's catalog + a listing detail page.
     Save under ``samples/<slug>/`` (or just inspect with curl).
  2. Update the per-scraper ``SkeletonConfig`` with real
     ``LIST_URL``, ``TARGET_DISCOVERY_PATTERNS``, and the page-walk
     shape (``page_param`` or ``url_pattern``).
  3. If JSON-LD is absent, add a CSS-selector fallback at the
     extraction site below (search for ``CALIBRATION HOOK``).
  4. Add a ``Policy(...)`` row in ``pulpo/scrapers/_policy.py`` if
     rate-limit or transport tuning is needed.
  5. Run dev crawl; observe ``coverage_ratio_vs_discovered`` from the
     coverage logger row. Iterate until >= 0.8.
  6. Promote the PR from DRAFT to ready.

The skeleton intentionally does NOT call ``finalize_record`` with
fixture records that won't pass the vacation gate — the offline path
trusts the synthesized fixtures to be in-niche.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pulpo.scrapers._base import OfflineFixtureMixin, finalize_record
from pulpo.scrapers.lib import (
    discover_target,
    find_jsonld,
    log_coverage,
    paginate,
)


@dataclass
class SkeletonConfig:
    """Per-source skeleton parameters. Defaults are sensible placeholders
    that need replacement during the calibration pass."""

    slug: str
    base_url: str
    list_url: str
    # Choose ONE pagination shape:
    page_param: Optional[str] = "page"
    url_pattern: Optional[str] = None
    # Source's own UI listing-count regex patterns. First match wins.
    target_discovery_patterns: tuple[str, ...] = field(default_factory=tuple)
    # Cap on pages walked; calibrate against source's actual catalog size.
    max_pages: int = 50
    # Broker classification ("agency" or "private") used by finalize_record.
    broker_type: str = "agency"
    # Force vacation-gate (house/condo must be in vacation zone OR carry
    # waterfront keywords). True by default; legitimate non-vacation
    # sources should NOT be Phase C inventory anyway.
    force_vacation_gate: bool = True


class SkeletonScraper(OfflineFixtureMixin):
    """Reusable skeleton scraper. Subclasses set ``CONFIG`` to a
    ``SkeletonConfig`` instance."""

    CONFIG: SkeletonConfig
    country: str = "SV"
    FIXTURE_FILE: str = "sample_listings.json"

    def __init__(self, offline: bool | None = None) -> None:
        self.offline = offline
        # Subclasses set self.slug from CONFIG so the OfflineFixtureMixin
        # contract is satisfied.
        self.slug = self.CONFIG.slug

    def crawl(self, limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
        fixture = self._offline_or_fixtures(limit, override_offline=offline)
        if fixture is not None:
            return self._finalize_batch(fixture)
        return self._crawl_online(limit)

    def _finalize_batch(self, raws: list[dict]) -> list[dict]:
        out: list[dict] = []
        for raw in raws:
            final = finalize_record(
                raw,
                slug=self.CONFIG.slug,
                broker_type=self.CONFIG.broker_type,
                force_vacation_gate=self.CONFIG.force_vacation_gate,
            )
            if final is not None:
                out.append(final)
        return out

    def _crawl_online(self, limit: int) -> list[dict]:
        """Online path — SKELETON. Walks pages, extracts JSON-LD,
        logs coverage. Placeholder selectors per CONFIG.

        TODO (calibration pass — see _skeleton_helper.py docstring):
          - Verify CONFIG.target_discovery_patterns against the live UI.
          - Verify page_param vs url_pattern (most sites use ?page=N;
            WordPress uses /page/N/).
          - CALIBRATION HOOK: add CSS-selector fallback below when
            JSON-LD is absent. Skipped in the skeleton.
        """
        # Defer the policy-resolution import so offline mode never
        # touches httpx / Playwright.
        from pulpo.agents.html_crawler import HTTPX_OK, make_client
        from pulpo.scrapers._base import polite_get_for

        if not HTTPX_OK:
            return []

        raw_records: list[dict] = []
        target_discovered: Optional[int] = None

        get = polite_get_for(self.CONFIG.slug)
        with make_client() as client:
            for page_num, resp in paginate(
                fetch=lambda url: get(client, url),
                base_url=self.CONFIG.list_url,
                page_param=self.CONFIG.page_param,
                url_pattern=self.CONFIG.url_pattern,
                start=1,
                max_pages=self.CONFIG.max_pages,
            ):
                body = getattr(resp, "text", "") or ""
                if page_num == 1 and target_discovered is None and self.CONFIG.target_discovery_patterns:
                    target_discovered = discover_target(
                        body, list(self.CONFIG.target_discovery_patterns)
                    )
                for ld_block in find_jsonld(body, schema_type="Residence"):
                    raw_records.append(self._from_jsonld(ld_block))
                if len(raw_records) >= limit:
                    break

        out = self._finalize_batch(raw_records[:limit])

        log_coverage(
            self.CONFIG.slug,
            raw_count=len(raw_records),
            kept_count=len(out),
            target_prd=None,
            target_discovered=target_discovered,
        )
        return out

    def _from_jsonld(self, block: dict) -> dict:
        """Map a Schema.org ``Residence`` block to the raw-record dict
        shape expected by ``finalize_record``. Defensive against missing
        sub-objects."""
        url = block.get("url") or ""
        offers = block.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price_raw = offers.get("price") if isinstance(offers, dict) else None
        photos = block.get("image") or []
        if isinstance(photos, str):
            photos = [photos]
        floor_size = block.get("floorSize")
        area = floor_size.get("value") if isinstance(floor_size, dict) else None
        area_unit = floor_size.get("unitText") if isinstance(floor_size, dict) else None
        return {
            "source": self.CONFIG.slug,
            "source_id": str(block.get("identifier") or url.rsplit("/", 1)[-1] or "unknown"),
            "url": url,
            "title": block.get("name") or block.get("description") or "",
            "description": block.get("description") or "",
            "price_usd": _parse_number(price_raw),
            "area_m2": _parse_number(str(area)) if area is not None else None,
            "photo_urls": photos if isinstance(photos, list) else [],
            "raw_size_text": area_unit,
            "property_type": None,
        }


def _parse_number(raw):
    """Tolerant number parser. Returns float on success, None on miss."""
    if not isinstance(raw, str):
        return float(raw) if isinstance(raw, (int, float)) else None
    import re
    cleaned = re.sub(r"[,.\s]", "", raw)
    if not cleaned.isdigit():
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
