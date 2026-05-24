"""
Realty El Salvador scraper — realtyelsalvador.com

El Salvador-focused English-language real estate broker.
Stack: WordPress + RealHomes theme.

Why HTML, not the WP REST API
-----------------------------
Until 2026-05-06 we used ``/wp-json/wp/v2/propiedades?_embed`` and the
output schema was clean (~140 land listings). Then Cloudflare started
returning HTTP 403 to that endpoint from GitHub Actions runner IPs
(Azure datacenter ranges). Browser-realistic headers were attempted
(PR #297, see git history) and didn't help — the gate is IP-based on
the API surface. From an end-user IP both the API and the HTML site
work; from runner IPs only the HTML site works. So the scraper hits
the HTML site exclusively now.

Strategy
--------
1. Paginate ``/tipo-de-propiedad/terrenos/page/N/`` — the WordPress
   archive view filtered to the ``terrenos`` (land) taxonomy.
2. Extract listing detail URLs from each archive page.
3. For each detail page: read JSON-LD (``@type: RealEstateListing``)
   for the canonical fields (name, description, price, locality,
   area). Fall through to HTML for fields JSON-LD doesn't carry
   (photo gallery URLs, post id).
4. Use the polite-request layer (``pulpo.scrapers._runtime.polite_get``)
   for UA rotation, jitter, rate-limit, and Retry-After honoring.

Resilience
----------
- Offline mode loads from ``fixtures/sample_listings.json`` filtered
  by source — same contract as the rest of the scrapers.
- On any HTTP failure during the live crawl, the scraper attaches the
  failing request URL + last response to ``self.last_*`` attributes so
  the Phase-1 diagnostic-capture in ``automation/run.py`` can record a
  proper snapshot. Without those breadcrumbs the run.py snapshot is
  exception-only and misses the response body.
- Pagination is capped at ``MAX_PAGES`` (well above the current ~21
  page count of the terrenos archive) to bound runtime.
- Listing cap at ``MAX_LISTINGS`` keeps the request budget bounded
  even if the site adds inventory faster than we can crawl politely.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

from pulpo.agents.html_crawler import (
    HTTPX_OK,
    SELECTOLAX_OK,
    is_offline,
    load_fixtures,
    make_client,
)
from pulpo.agents import SOURCES, register
from pulpo.scrapers._policy import get_policy
from pulpo.scrapers._runtime import polite_get
from pulpo.scrapers._photo_url_upgrade import upgrade_photo_urls

BASE         = "https://realtyelsalvador.com"
ARCHIVE_URL  = f"{BASE}/tipo-de-propiedad/terrenos/page/{{page}}/"
ARCHIVE_FIRST = f"{BASE}/tipo-de-propiedad/terrenos/"
FIXTURE_FILE = "sample_listings.json"

# Bounds — kept conservative on purpose. The archive serves 6 listings/
# page and currently spans ~21 pages (~126 land listings total). We cap
# at 100 to be a polite citizen and to keep the request budget bounded
# if the site grows fast. Pagination cap is its own ceiling — protects
# against the WP archive looping infinitely when our page indexer
# overflows the real last page.
MAX_LISTINGS = 100
MAX_PAGES    = 25

# Detail-page URL pattern. The archive links every listing as
#   https://realtyelsalvador.com/propiedades/<slug>/
_DETAIL_URL_RE = re.compile(
    r'href="(https://realtyelsalvador\.com/propiedades/[^"#?]+/)"'
)

# Body class includes ``postid-NNNNN`` which is the WP post id — same id
# the deprecated WP REST API exposed as ``rec["id"]``. Keeping the same
# source_id keeps downstream first-seen / repeat-listing tracking stable
# across the WP-REST → HTML migration.
_POSTID_RE = re.compile(r'<body[^>]*class="[^"]*postid-(\d+)')

# JSON-LD blob — RealHomes embeds exactly one Product/RealEstateListing
# block per detail page. We take the first match (DOTALL crosses line
# boundaries because the payload is pretty-printed multi-line JSON).
_JSONLD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# Listing photo URL pattern. The site stores user-uploaded listing
# photos as wp-content/uploads/file-<unix-timestamp>.<ext>. Brand /
# theme assets (agent headshots, favicons, cropped-img variants) use a
# different prefix and must NOT bleed into our gallery. The check is
# strict: prefix must be exactly ``file-`` to qualify.
_PHOTO_URL_RE = re.compile(
    r'https://realtyelsalvador\.com/wp-content/uploads/file-\d+(?:-\d+x\d+)?\.(?:jpe?g|png|webp)',
    re.IGNORECASE,
)

# og:image — the canonical hero photo. Listed first in our output.
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"'
)

# Strip WP-thumbnail size suffix ``-WIDTHxHEIGHT`` so the photo upgrade
# step (``_photo_url_upgrade``) sees the canonical filename.
_SIZE_SUFFIX_RE = re.compile(r"-\d+x\d+(\.[a-z]+)$", re.IGNORECASE)


# ── parsing helpers ───────────────────────────────────────────────────


def _strip_size_suffix(url: str) -> str:
    return _SIZE_SUFFIX_RE.sub(r"\1", url)


def parse_archive_urls(html: str) -> list[str]:
    """Return unique detail-page URLs found in an archive-page HTML."""
    urls = list(dict.fromkeys(_DETAIL_URL_RE.findall(html)))
    return urls


def _extract_jsonld(html: str) -> Optional[dict]:
    """Return the first RealEstateListing/Product JSON-LD block as a dict."""
    for raw in _JSONLD_RE.findall(html):
        raw = raw.strip()
        if not raw:
            continue
        try:
            blob = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(blob, list):
            for entry in blob:
                if isinstance(entry, dict) and entry.get("@type") in {
                    "RealEstateListing", "Product"
                }:
                    return entry
        elif isinstance(blob, dict):
            if blob.get("@type") in {"RealEstateListing", "Product"}:
                return blob
    return None


def _extract_postid(html: str) -> Optional[str]:
    m = _POSTID_RE.search(html)
    return m.group(1) if m else None


def _extract_photos(html: str) -> list[str]:
    """Return de-duplicated photo URLs for the listing.

    Order: og:image first (if it matches the listing-photo pattern),
    then any other ``file-<ts>.<ext>`` URLs in DOM order. Size suffixes
    are stripped so the upgrader sees the canonical filename.
    """
    seen: dict[str, None] = {}
    og_match = _OG_IMAGE_RE.search(html)
    if og_match:
        candidate = _strip_size_suffix(og_match.group(1))
        if _PHOTO_URL_RE.match(candidate):
            seen[candidate] = None
    for raw_url in _PHOTO_URL_RE.findall(html):
        canonical = _strip_size_suffix(raw_url)
        seen.setdefault(canonical, None)
    return list(seen.keys())


def _parse_price_usd(jsonld: dict) -> tuple[Optional[float], str]:
    offers = jsonld.get("offers") or {}
    raw = offers.get("price") or offers.get("priceSpecification") or ""
    if isinstance(raw, dict):
        raw = raw.get("price") or ""
    raw_str = str(raw).strip().replace(",", "")
    if not raw_str:
        return None, ""
    try:
        return float(raw_str), f"${raw_str}"
    except (ValueError, TypeError):
        return None, ""


def _parse_size_text(jsonld: dict) -> str:
    """Return ``"<value> <unit>"`` from JSON-LD additionalProperty[Area Size].

    The site reports area in m² (Spanish: ``metros cuadrados``) and
    occasionally in manzanas. Pulpo's normalizer accepts either; we pass
    the raw string through so the normalizer's existing unit-handling
    code runs unchanged.
    """
    for prop in (jsonld.get("additionalProperty") or []):
        if not isinstance(prop, dict):
            continue
        name = (prop.get("name") or "").lower()
        if "area" in name or "size" in name or "tama" in name:
            value = str(prop.get("value") or "").strip()
            unit  = str(prop.get("unitText") or "").strip()
            if value:
                return f"{value} {unit}".strip()
    return ""


def _parse_location(jsonld: dict) -> str:
    addr = jsonld.get("address") or {}
    if isinstance(addr, dict):
        parts = [
            addr.get("addressLocality") or "",
            addr.get("addressRegion")   or "",
        ]
        loc = ", ".join(p for p in parts if p).strip(", ")
    else:
        loc = ""
    if not loc:
        loc = "El Salvador"
    elif "El Salvador" not in loc:
        loc = f"{loc}, El Salvador"
    return loc


def parse_detail(html: str, url: str) -> Optional[dict]:
    """Parse a detail-page HTML into our raw record schema. Returns None
    if the page is missing the essentials (title or post-id)."""
    jsonld = _extract_jsonld(html)
    if not jsonld:
        return None

    title = (jsonld.get("name") or "").strip()
    if not title:
        return None
    title = re.sub(r"\s+", " ", title)

    postid = _extract_postid(html)
    if not postid:
        # Fall back to the URL slug hash — rare path, but better than
        # dropping the listing entirely. Normalize as a stable ID.
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        postid = f"slug:{slug}"

    description = (jsonld.get("description") or "").strip()[:1500]

    price_usd, raw_price_text = _parse_price_usd(jsonld)
    raw_size_text = _parse_size_text(jsonld)
    location_text = _parse_location(jsonld)

    photo_urls = _extract_photos(html)
    photo_urls = upgrade_photo_urls("realtyelsalvador", photo_urls)

    return {
        "source_id":      str(postid),
        "url":            url,
        "title":          title,
        "description":    description,
        "location_text":  location_text,
        "price_usd":      price_usd,
        "raw_price_text": raw_price_text,
        "raw_size_text":  raw_size_text,
        "property_type":  "land",
        "photo_urls":     photo_urls,
        "days_listed":    None,
        "is_repriced":    False,
    }


# ── crawler ───────────────────────────────────────────────────────────


class RealtyElSalvadorScraper:
    slug = "realtyelsalvador"

    def __init__(self, offline: bool | None = None):
        self.offline = offline
        # Breadcrumbs for Phase-1 diagnostic capture. ``automation/run.py``
        # reads these via getattr after an exception to enrich the snapshot.
        self.last_request_url: Optional[str] = None
        self.last_request_headers: Optional[dict] = None
        self.last_response = None

    def crawl(self, limit: int = MAX_LISTINGS, offline: bool | None = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        if not (HTTPX_OK and SELECTOLAX_OK):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        effective_limit = min(limit, MAX_LISTINGS)
        policy = get_policy(self.slug)

        client = make_client()
        try:
            return self._crawl_live(client, policy, effective_limit)
        finally:
            client.close()

    def _crawl_live(self, client, policy, limit: int) -> list[dict]:
        out: list[dict] = []
        seen_urls: set[str] = set()
        last_had_results = False

        for page in range(1, MAX_PAGES + 1):
            archive_url = ARCHIVE_FIRST if page == 1 else ARCHIVE_URL.format(page=page)
            self.last_request_url = archive_url
            resp = polite_get(client, archive_url, source=self.slug, policy=policy)
            self.last_response = resp

            if resp.status_code != 200:
                print(f"[realtyelsalvador] archive page {page} HTTP {resp.status_code}")
                break

            page_urls = parse_archive_urls(resp.text)
            if not page_urls:
                # Walked past the last real page — WP archives wrap and
                # show a generic landing once N exceeds the count. Stop.
                break

            new_this_page = False
            for durl in page_urls:
                if len(out) >= limit:
                    break
                durl = urljoin(BASE, durl) if not durl.startswith("http") else durl
                if durl in seen_urls:
                    continue
                seen_urls.add(durl)
                new_this_page = True

                self.last_request_url = durl
                d_resp = polite_get(client, durl, source=self.slug, policy=policy)
                self.last_response = d_resp
                if d_resp.status_code != 200:
                    print(f"[realtyelsalvador] detail {durl} HTTP {d_resp.status_code}")
                    continue

                rec = parse_detail(d_resp.text, durl)
                if rec is None:
                    continue
                rec["source"]     = self.slug
                rec["scraped_at"] = datetime.now(timezone.utc).isoformat()
                out.append(rec)

            last_had_results = new_this_page
            if len(out) >= limit:
                break
            if not new_this_page:
                break

        # Honest about pagination — caller knows if there might be more.
        self._last_max_pages_hit = (page >= MAX_PAGES) and last_had_results
        self._last_limit_hit     = len(out) >= limit
        return out

    def crawl_with_meta(
        self,
        limit: int = MAX_LISTINGS,
        offline: bool | None = None,
        max_pages: Optional[int] = None,  # noqa: ARG002  # accepted for parity
    ) -> dict:
        records = self.crawl(limit, offline)
        return {
            "records":       records,
            "max_pages_hit": getattr(self, "_last_max_pages_hit", False),
            "limit_hit":     getattr(self, "_last_limit_hit", False),
        }


_scraper = RealtyElSalvadorScraper()
register(SOURCES, "realtyelsalvador", _scraper)


def crawl(limit: int = MAX_LISTINGS, offline: bool | None = None) -> list[dict]:
    return RealtyElSalvadorScraper(offline=offline).crawl(limit)
