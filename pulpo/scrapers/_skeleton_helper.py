"""Shared scaffold for Phase C scrapers (Xitios, Agentiz, Santizo,
CityMax Surf City, Vivo Latam, CSBR, Realestate.com.au International
SV, JamesEdition).

Five extraction strategies, dispatched by ``SkeletonConfig.extract_strategy``:

  ``"detail_jsonld"`` (default)
      Paginate the catalog URL, extract detail-page URLs from each
      catalog page via ``detail_url_pattern`` regex (or a per-source
      override of :meth:`_extract_detail_urls_from_catalog_page`),
      fetch each detail, parse JSON-LD via
      ``pulpo.scrapers.lib.find_jsonld_ci`` with case-insensitive
      ``@type`` matching across ``jsonld_schema_types``. Optional
      HTML-entity unescape via ``jsonld_html_unescape`` (realestate.com.au
      ships SSR JSON-LD with ``&quot;`` quotes).

  ``"detail_og_meta"``
      Same catalog walk, but each detail page is parsed via
      ``lib.extract_og`` and source-specific price / area regex
      patterns (``og_price_patterns``, ``og_area_patterns``). Xitios
      has no JSON-LD; this is its path.

  ``"sitemap"``
      Skip the catalog walk entirely. Fetch ``sitemap_url``, enumerate
      ``<loc>`` entries, fetch each detail, parse JSON-LD. Vivolatam's
      catalog is hydrated client-side so its sitemap is the only
      reliable URL source.

  ``"static_urls"``
      Skip discovery entirely. Iterate ``static_urls`` as detail
      pages. Agentiz exposes ~5 hardcoded type-slot URLs and no
      catalog grid; this is its path.

  ``"catalog_jsonld"`` (legacy)
      Original behaviour: parse JSON-LD on each catalog page. None
      of the eight Phase C sources actually fit this pattern; kept
      for backward compatibility.

In every strategy, the source's own "X listings" UI claim is captured
once (where available — sitemap and static_urls derive the discovered
count from the URL list itself), the coverage row is logged, and each
record runs through ``finalize_record`` for the standard photo
upgrade + vacation gate + type classifier pipeline.

Per-source customisation hook: subclasses may override
:meth:`_extract_detail_urls_from_catalog_page` for cases where regex
isn't enough — citymax_sc does this to parse the catalog's
``ItemList`` JSON-LD block (more reliable than href regex).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal, Optional
from urllib.parse import urljoin, urlsplit

from pulpo.scrapers._base import OfflineFixtureMixin, finalize_record
from pulpo.scrapers.lib import (
    discover_target,
    extract_loc_urls,
    extract_og,
    find_first,
    find_jsonld,
    find_jsonld_ci,
    log_coverage,
    paginate,
)


ExtractStrategy = Literal[
    "detail_jsonld",
    "detail_og_meta",
    "sitemap",
    "static_urls",
    "catalog_jsonld",
]


@dataclass
class SkeletonConfig:
    """Per-source skeleton parameters. Defaults match the most common
    shape (detail-page JSON-LD walk over ?page=N pagination)."""

    slug: str
    base_url: str
    list_url: str = ""
    # Pagination shape — choose one. Ignored for sitemap / static_urls.
    page_param: Optional[str] = "page"
    url_pattern: Optional[str] = None
    # Source's own UI listing-count regex patterns. First match wins.
    target_discovery_patterns: tuple[str, ...] = field(default_factory=tuple)
    # Cap on pages walked; calibrate against source's actual catalog size.
    max_pages: int = 50
    # Broker classification ("agency" or "private") used by finalize_record.
    broker_type: str = "agency"
    # Force vacation-gate (all property types, not just house/condo).
    force_vacation_gate: bool = True
    # Extraction strategy — see module docstring.
    extract_strategy: ExtractStrategy = "detail_jsonld"
    # Regex applied to catalog HTML to find detail-page URLs. May be
    # absolute or relative; the helper resolves against ``base_url``.
    detail_url_pattern: Optional[str] = None
    # Accepted JSON-LD ``@type`` values, case-insensitive. Used by
    # ``detail_jsonld`` and ``sitemap`` strategies.
    jsonld_schema_types: tuple[str, ...] = (
        "RealEstateListing", "Residence", "House", "Product",
    )
    # When True, html.unescape() each <script> body before json.loads
    # (realestate.com.au).
    jsonld_html_unescape: bool = False
    # Used by ``static_urls`` strategy.
    static_urls: tuple[str, ...] = field(default_factory=tuple)
    # Used by ``sitemap`` strategy.
    sitemap_url: Optional[str] = None
    # Optional path-substring filter applied to sitemap URLs (e.g.
    # require ``/el-salvador/`` so a multi-country sitemap stays scoped).
    # Accepts a single substring OR a tuple of substrings — when a
    # tuple, ALL substrings must appear in the URL (AND semantics).
    sitemap_url_filter: Optional[object] = None
    # og-meta extractors — regex patterns over og:description.
    og_price_patterns: tuple[str, ...] = field(default_factory=tuple)
    og_area_patterns: tuple[str, ...] = field(default_factory=tuple)
    # Conversion factor applied to og-meta area capture when units are
    # not metric (xitios reports "varas cuadradas"; 1 vara² ≈ 0.6987 m²).
    og_area_unit_factor: float = 1.0
    # Hard cap on detail-page fetches per crawl. Defends against runaway
    # walks while letting "exhaustive" runs pass ``limit=500+`` through
    # ``crawl()``. Defaults to the max_pages cap × 24 (~typical per-page
    # listing count) so the default behaviour is exhaustive.
    detail_fetch_cap: int = 2000


class SkeletonScraper(OfflineFixtureMixin):
    """Reusable skeleton scraper. Subclasses set ``CONFIG`` to a
    ``SkeletonConfig`` instance and may override the extraction hooks
    listed at the bottom of this docstring for source-specific quirks.

    Override hooks (all default impls usable as-is for the common case):

    - :meth:`_extract_detail_urls_from_catalog_page(body, page_num)`
    - :meth:`_finalize_jsonld_block(block, url)` — transform raw JSON-LD
      into a record dict. Default impl handles RealEstateListing /
      Residence / House / Product field shapes.
    - :meth:`_post_finalize_filter(record)` — last-mile drop hook
      (e.g. santizo drops cross-country listings here).
    """

    CONFIG: SkeletonConfig
    country: str = "SV"
    FIXTURE_FILE: str = "sample_listings.json"

    def __init__(self, offline: bool | None = None) -> None:
        self.offline = offline
        self.slug = self.CONFIG.slug

    # ── public entry point ──────────────────────────────────────────

    def crawl(self, limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
        fixture = self._offline_or_fixtures(limit, override_offline=offline)
        if fixture is not None:
            return self._finalize_batch(fixture)
        return self._crawl_online(limit)

    # ── strategy dispatch ───────────────────────────────────────────

    def _crawl_online(self, limit: int) -> list[dict]:
        strategy = self.CONFIG.extract_strategy
        try:
            from pulpo.agents.html_crawler import HTTPX_OK
        except ImportError:
            HTTPX_OK = False
        if not HTTPX_OK and strategy != "static_urls":
            return []

        if strategy == "static_urls":
            return self._crawl_static_urls(limit)
        if strategy == "sitemap":
            return self._crawl_sitemap(limit)
        if strategy == "catalog_jsonld":
            return self._crawl_catalog_jsonld(limit)
        # detail_jsonld + detail_og_meta share the catalog walk.
        return self._crawl_via_catalog_walk(limit, strategy=strategy)

    # ── strategy: catalog walk → detail fetch ───────────────────────

    def _crawl_via_catalog_walk(self, limit: int, *, strategy: str) -> list[dict]:
        from pulpo.agents.html_crawler import make_client
        from pulpo.scrapers._base import polite_get_for

        get = polite_get_for(self.CONFIG.slug)
        detail_urls: list[str] = []
        seen: set[str] = set()
        target_discovered: Optional[int] = None

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
                if page_num == 1 and self.CONFIG.target_discovery_patterns:
                    target_discovered = discover_target(
                        body, list(self.CONFIG.target_discovery_patterns)
                    )
                page_urls = self._extract_detail_urls_from_catalog_page(body, page_num)
                # Dedup within the page AND across pages — the catalog
                # often repeats the same listing URL across photo / title
                # / "view details" hrefs.
                fresh: list[str] = []
                for u in page_urls:
                    if u in seen:
                        continue
                    seen.add(u)
                    fresh.append(u)
                    detail_urls.append(u)
                if not fresh:
                    break
                if len(detail_urls) >= self.CONFIG.detail_fetch_cap:
                    break

            raw_records = self._fetch_detail_batch(
                client, get, detail_urls[:limit], strategy=strategy,
            )

        out = self._finalize_batch(raw_records)
        log_coverage(
            self.CONFIG.slug,
            raw_count=len(raw_records),
            kept_count=len(out),
            target_prd=None,
            target_discovered=target_discovered if target_discovered is not None
                              else (len(detail_urls) or None),
        )
        return out

    # ── strategy: sitemap → detail fetch ────────────────────────────

    def _crawl_sitemap(self, limit: int) -> list[dict]:
        from pulpo.agents.html_crawler import make_client
        from pulpo.scrapers._base import polite_get_for

        if not self.CONFIG.sitemap_url:
            return []
        get = polite_get_for(self.CONFIG.slug)
        with make_client() as client:
            resp = get(client, self.CONFIG.sitemap_url)
            body = getattr(resp, "text", "") if resp is not None else ""
            urls = extract_loc_urls(body)
            needles = self.CONFIG.sitemap_url_filter
            if isinstance(needles, str):
                urls = [u for u in urls if needles in u]
            elif isinstance(needles, (tuple, list)):
                urls = [u for u in urls if all(n in u for n in needles)]
            raw_records = self._fetch_detail_batch(
                client, get, urls[:limit], strategy="detail_jsonld",
            )

        out = self._finalize_batch(raw_records)
        log_coverage(
            self.CONFIG.slug,
            raw_count=len(raw_records),
            kept_count=len(out),
            target_prd=None,
            target_discovered=len(urls) or None,
        )
        return out

    # ── strategy: static URL set ────────────────────────────────────

    def _crawl_static_urls(self, limit: int) -> list[dict]:
        try:
            from pulpo.agents.html_crawler import make_client
        except ImportError:
            return []
        from pulpo.scrapers._base import polite_get_for

        urls = list(self.CONFIG.static_urls)[:limit]
        get = polite_get_for(self.CONFIG.slug)
        with make_client() as client:
            raw_records = self._fetch_detail_batch(
                client, get, urls, strategy="detail_jsonld",
            )

        out = self._finalize_batch(raw_records)
        log_coverage(
            self.CONFIG.slug,
            raw_count=len(raw_records),
            kept_count=len(out),
            target_prd=None,
            target_discovered=len(self.CONFIG.static_urls) or None,
        )
        return out

    # ── strategy: legacy catalog-jsonld path ────────────────────────

    def _crawl_catalog_jsonld(self, limit: int) -> list[dict]:
        """Preserved for backward compat. Walks catalog pages, parses
        JSON-LD on each page directly (no detail fetch)."""
        from pulpo.agents.html_crawler import make_client
        from pulpo.scrapers._base import polite_get_for

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
                    raw_records.append(self._finalize_jsonld_block(ld_block, url=body[:0]))
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

    # ── detail fetching ─────────────────────────────────────────────

    def _fetch_detail_batch(
        self,
        client,
        get: Callable,
        urls: Iterable[str],
        *,
        strategy: str,
    ) -> list[dict]:
        records: list[dict] = []
        for url in urls:
            resp = get(client, url)
            if resp is None:
                continue
            body = getattr(resp, "text", "") or ""
            record = self._extract_detail(body, url, strategy=strategy)
            if record is not None:
                records.append(record)
        return records

    def _extract_detail(self, body: str, url: str, *, strategy: str) -> Optional[dict]:
        if strategy == "detail_og_meta":
            return self._extract_og_detail(body, url)
        # default: detail_jsonld
        blocks = find_jsonld_ci(
            body,
            self.CONFIG.jsonld_schema_types,
            unescape=self.CONFIG.jsonld_html_unescape,
        )
        if not blocks:
            return None
        return self._finalize_jsonld_block(blocks[0], url=url)

    # ── override hooks ──────────────────────────────────────────────

    def _extract_detail_urls_from_catalog_page(
        self, body: str, page_num: int,
    ) -> list[str]:
        """Default: apply ``detail_url_pattern`` regex over the page
        body. Subclasses override for source-specific URL discovery
        (e.g. citymax_sc parses an ItemList JSON-LD block instead).
        Returned URLs are resolved to absolute against ``base_url``."""
        pattern = self.CONFIG.detail_url_pattern
        if not pattern:
            return []
        urls: list[str] = []
        for match in re.findall(pattern, body, re.IGNORECASE):
            urls.append(urljoin(self.CONFIG.base_url, match))
        return urls

    def _finalize_jsonld_block(self, block: dict, *, url: str = "") -> dict:
        """Map a JSON-LD block (Residence / RealEstateListing / Product /
        House) into the raw-record dict shape ``finalize_record`` expects.
        """
        block_url = block.get("url") or url or ""
        offers = block.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price_raw = offers.get("price") if isinstance(offers, dict) else None
        if price_raw is None:
            price_raw = block.get("price")
        photos = block.get("image") or []
        if isinstance(photos, str):
            photos = [photos]
        elif isinstance(photos, dict):
            photos = [photos.get("url") or photos.get("contentUrl") or ""]
            photos = [p for p in photos if p]
        floor_size = block.get("floorSize")
        area = floor_size.get("value") if isinstance(floor_size, dict) else None
        area_unit = floor_size.get("unitText") if isinstance(floor_size, dict) else None
        address = block.get("address") or {}
        location_text = ""
        if isinstance(address, dict):
            parts = [address.get("addressLocality"), address.get("addressRegion"),
                     address.get("addressCountry")]
            location_text = ", ".join(p for p in parts if isinstance(p, str) and p)
        return {
            "source": self.CONFIG.slug,
            "source_id": str(
                block.get("identifier")
                or block.get("sku")
                or _slug_from_url(block_url)
                or "unknown"
            ),
            "url": block_url,
            "title": block.get("name") or block.get("description") or "",
            "description": block.get("description") or "",
            "price_usd": _parse_number(price_raw),
            "area_m2": _parse_number(str(area)) if area is not None else None,
            "photo_urls": photos if isinstance(photos, list) else [],
            "raw_size_text": area_unit,
            "property_type": _property_type_from_jsonld(block),
            "location_text": location_text,
            "_jsonld_country": _country_from_jsonld(block),
        }

    def _extract_og_detail(self, body: str, url: str) -> Optional[dict]:
        og = extract_og(body)
        if not og:
            return None
        title = og.get("title") or ""
        description = og.get("description") or ""
        price_str = find_first(description, self.CONFIG.og_price_patterns) or \
                    find_first(title, self.CONFIG.og_price_patterns)
        area_str = find_first(description, self.CONFIG.og_area_patterns) or \
                   find_first(title, self.CONFIG.og_area_patterns)
        area_m2 = _parse_number(area_str) if area_str else None
        if area_m2 is not None and self.CONFIG.og_area_unit_factor != 1.0:
            area_m2 = area_m2 * self.CONFIG.og_area_unit_factor
        photos = og.get("image") or []
        return {
            "source": self.CONFIG.slug,
            "source_id": _slug_from_url(url),
            "url": url,
            "title": title,
            "description": description,
            "price_usd": _parse_number(price_str) if price_str else None,
            "area_m2": area_m2,
            "photo_urls": photos if isinstance(photos, list) else [photos] if photos else [],
            "raw_size_text": area_str,
            "property_type": None,
            "location_text": "",
        }

    def _post_finalize_filter(self, record: dict) -> Optional[dict]:
        """Last-mile drop hook. Default no-op. Subclasses (santizo)
        override to enforce country scope or other late filters."""
        return record

    # ── finalize ────────────────────────────────────────────────────

    def _finalize_batch(self, raws: list[dict]) -> list[dict]:
        out: list[dict] = []
        for raw in raws:
            filtered = self._post_finalize_filter(raw)
            if filtered is None:
                continue
            final = finalize_record(
                filtered,
                slug=self.CONFIG.slug,
                broker_type=self.CONFIG.broker_type,
                force_vacation_gate=self.CONFIG.force_vacation_gate,
            )
            if final is not None:
                out.append(final)
        return out


# ── helpers ─────────────────────────────────────────────────────────


_PROPERTY_TYPE_HINTS = {
    "house": "house",
    "casa": "house",
    "residence": "house",
    "apartment": "condo",
    "condo": "condo",
    "condominium": "condo",
    "apartamento": "condo",
    "land": "land",
    "terreno": "land",
    "lot": "land",
    "lote": "land",
    "finca": "land",
}


def _property_type_from_jsonld(block: dict) -> Optional[str]:
    t = block.get("@type")
    types: list[str] = []
    if isinstance(t, str):
        types.append(t)
    elif isinstance(t, list):
        types.extend(x for x in t if isinstance(x, str))
    additional = block.get("additionalType")
    if isinstance(additional, str):
        types.append(additional)
    for raw in types:
        norm = raw.lower()
        for hint, mapped in _PROPERTY_TYPE_HINTS.items():
            if hint in norm:
                return mapped
    return None


def _country_from_jsonld(block: dict) -> Optional[str]:
    address = block.get("address")
    if isinstance(address, dict):
        c = address.get("addressCountry")
        if isinstance(c, str):
            return c
        if isinstance(c, dict):
            return c.get("name") or c.get("alternateName")
    return None


def _slug_from_url(url: str) -> str:
    if not url:
        return ""
    path = urlsplit(url).path.rstrip("/")
    if not path:
        return ""
    return path.rsplit("/", 1)[-1]


def _parse_number(raw):
    """Tolerant number parser. Returns float on success, None on miss.

    Handles US-format ("350,000.50"), EU-format ("350.000,50"), and
    plain ("350000"). Returns None on garbage.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    # Strip currency symbols / unit text — keep digits, ., , and -.
    s = re.sub(r"[^0-9.,\-]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        # Pick the rightmost separator as decimal.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # If the comma chunk after it is 3 digits, treat as thousands.
        tail = s.split(",")[-1]
        if len(tail) == 3 and tail.isdigit():
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
