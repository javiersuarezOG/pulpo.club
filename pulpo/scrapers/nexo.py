"""
Nexo Inmobiliario scraper — nexo.com.sv

El Salvador-only real estate directory. The site was redesigned in
mid-2026 from a 2017 static-HTML Dreamweaver template to a Vite SPA
served behind Cloudflare managed-challenge mode. The previous HTML-
scrape path (parsing `div.dresultado` cards on
``/terrenos-en-venta-el-salvador/{page}``) stopped working on
2026-05-26 because:

  1. The HTML route now serves a single 5KB SPA shell — every URL on
     the host returns identical content. There are no `div.dresultado`
     cards anywhere on the new site.
  2. Cloudflare's `cf-mitigated: challenge` 403s every direct
     httpx/curl request regardless of IP or UA. The WAF gates on TLS
     handshake fingerprint (JA3/JA4).

The fix is twofold:

  - **Transport**: ``Policy(transport="curl_cffi")`` runs through
    curl-impersonate so the handshake matches a real Chrome 124 on
    macOS. That clears Cloudflare on every IP we've tested (residential
    + GitHub Actions runners). See ``pulpo/scrapers/_policy.py``.
  - **Source**: read directly from the SPA's own backing API at
    ``GET /api/v1/public/listings?skip=N&limit=M``. The payload is a
    clean JSON array of every published listing in the broker's CRM
    — the same data the SPA renders. No HTML parsing, no per-listing
    detail fetch, no DOM brittleness.

Schema (relevant fields)
------------------------
Each listing dict from ``/api/v1/public/listings`` carries:

    {
      "id":            1061,                       # numeric, used in slug-URL
      "listing_code":  "C-VE-TER-15-000-57812510", # stable per-listing
      "listing_type":  {"id": 15, "name": "Lotes Residenciales",
                        "category": "terrenos", "sale_rent": "venta"},
      "title":         "...",
      "description":   "...",
      "price":         "115000.00",                # string, USD
      "area":          "583.00",                   # string, square varas
      "address":       "Altos de la casona ...",
      "city":          {"name": "San José Villanueva"},   # may be null
      "zone":          {...},                              # may be null
      "listing_medias": [
        {"relative_path": "media/listings/.../foo.jpeg", "is_primary": true},
        ...
      ],
      "is_published":  true,
      "is_active":     true,
      "created_at":    "...",
      "updated_at":    "...",
    }

What this scraper produces
--------------------------
We narrow to ``listing_type.category == "terrenos"`` (land lots) and
``sale_rent == "venta"`` (for-sale). The "terrenos" bucket is what
Pulpo's existing nexo entries belong to; rentals + residential are out
of scope for now (consistent with the pre-rewrite behaviour).

Photo URLs use the public media path:
    https://nexo.com.sv/{relative_path}
``is_primary`` photo lands first.

Detail URL: the SPA route is ``/{listing_type_id}/{id}/{slug}``
where ``slug`` is the Spanish-accent-stripped, kebab-cased title.
Reverse-engineered from the bundle's ``Nr(...)`` builder.
"""
from __future__ import annotations
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import is_offline, load_fixtures
from pulpo.agents import SOURCES, register
from pulpo.scrapers._base import polite_get_for
from pulpo.scrapers._photo_url_upgrade import upgrade_photo_urls

BASE         = "https://nexo.com.sv"
API_PATH     = "/api/v1/public/listings"
FIXTURE_FILE = "sample_listings.json"

# Pagination — the API accepts skip+limit; the SPA fetches 100 at a
# time. We mirror that. The broker's catalogue is currently ~500
# listings, of which only ~1% are land-for-sale (the bucket we keep —
# see parse_listing). Cap at MAX_PAGES to bound runtime regardless of
# how thin the filter is; MAX_LISTINGS caps the post-filter output.
PAGE_SIZE     = 100
MAX_PAGES     = 20
MAX_LISTINGS  = 500


def _slugify(title: str) -> str:
    """Match the slugifier in nexo.com.sv's SPA bundle.

    JS implementation we're mirroring (from index-DGSh5zgw.js):
        s => (s ?? "").normalize("NFD")
                      .replace(/[\\u0300-\\u036f]/g, "")
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, "-")
                      .replace(/^-+|-+$/g, "") || "inmueble"

    Producing the URL the SPA itself produces means our detail-URL
    matches what the site canonicalises to. If they ever drift, fixing
    is a one-line change here.
    """
    s = title or ""
    # NFD: split accented chars into base + combining mark, then drop
    # the combining marks. Same as the SPA's normalize+regex sequence.
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "inmueble"


def _photo_urls(listing_medias: list[dict]) -> list[str]:
    """Build full-size photo URLs, primary first.

    Photos are served from ``https://nexo.com.sv/<relative_path>``. The
    thumbnail variant exists too (``thumb_relative_path``) but we want
    the full-size for Pulpo's hero/photo pipeline.
    """
    if not isinstance(listing_medias, list):
        return []
    # Sort primary-first while keeping the rest in API order.
    primary, rest = [], []
    for m in listing_medias:
        if not isinstance(m, dict):
            continue
        if m.get("media_type") and m["media_type"] != "image":
            continue
        rel = m.get("relative_path") or ""
        if not rel:
            continue
        url = f"{BASE}/{rel.lstrip('/')}"
        (primary if m.get("is_primary") else rest).append(url)
    return primary + rest


def _parse_price_usd(raw: object) -> tuple[Optional[float], str]:
    if raw in (None, "", 0):
        return None, ""
    try:
        val = float(str(raw).replace(",", "").strip())
    except (ValueError, TypeError):
        return None, ""
    if val <= 0:
        return None, ""
    return val, f"${val:,.0f}"


def _parse_location(listing: dict) -> str:
    """Return a Pulpo-style location string.

    Prefer ``city.name`` (always Spanish, matches the existing
    location_text format on other SV sources). Fall back to ``address``
    if city is null. Append ", El Salvador" so the normalizer's country
    inference is unambiguous — Pulpo's nexo records always carried
    that suffix in the pre-rewrite era so existing zone-matching code
    keeps working.
    """
    city = listing.get("city") or {}
    city_name = ""
    if isinstance(city, dict):
        city_name = (city.get("name") or "").strip()
    if city_name:
        return f"{city_name}, El Salvador"
    addr = (listing.get("address") or "").strip()
    if addr:
        return f"{addr}, El Salvador"
    return "El Salvador"


def _detail_url(listing: dict) -> str:
    """Build the SPA detail URL the way the site itself builds it.

    Route template: ``/{listing_type_id}/{id}/{slug}``. Mirrors the
    bundle's ``Nr(id, title, _, listingTypeId)`` URL builder.
    """
    lt = listing.get("listing_type") or {}
    lt_id = 1
    if isinstance(lt, dict):
        lt_id = int(lt.get("id") or 1)
    rid = int(listing.get("id") or 0)
    slug = _slugify(listing.get("title") or "")
    return f"{BASE}/{lt_id}/{rid}/{slug}"


def parse_listing(listing: dict) -> Optional[dict]:
    """Map one API listing to Pulpo's raw record schema.

    Returns None for listings that aren't published, aren't active,
    aren't ``terrenos/venta``, or are missing the essentials (title,
    id). The category gate keeps the rewrite behaviourally compatible
    with the pre-2026-05-26 HTML scrape (land lots only).
    """
    if not isinstance(listing, dict):
        return None
    if not listing.get("is_published") or not listing.get("is_active"):
        return None

    lt = listing.get("listing_type") or {}
    if not isinstance(lt, dict):
        return None
    if lt.get("category") != "terrenos" or lt.get("sale_rent") != "venta":
        return None

    title = (listing.get("title") or "").strip()
    if not title:
        return None
    rid = listing.get("id")
    if rid is None:
        return None

    price_usd, raw_price_text = _parse_price_usd(listing.get("price"))
    raw_area = str(listing.get("area") or "").strip()
    # The API reports area in square varas (Salvadoran customary unit).
    # Pulpo's normalizer accepts mixed units — pass the raw string with
    # the unit annotation so the unit-conversion code in normalize.py
    # runs unchanged.
    raw_size_text = f"{raw_area} v²" if raw_area else ""

    photos = _photo_urls(listing.get("listing_medias") or [])
    photos = upgrade_photo_urls("nexo", photos)

    return {
        # Use listing_code over numeric id: the code is the broker's
        # stable identifier and survives database resets, whereas
        # `id` is an auto-increment that could change if the CRM is
        # re-keyed. Falling back to id when code is missing keeps the
        # record alive either way.
        "source_id":      listing.get("listing_code") or f"id:{rid}",
        "url":            _detail_url(listing),
        "title":          title,
        "description":    (listing.get("description") or "").strip()[:1500],
        "location_text":  _parse_location(listing),
        "price_usd":      price_usd,
        "raw_price_text": raw_price_text,
        "raw_size_text":  raw_size_text,
        "property_type":  "land",
        "photo_urls":     photos,
        "days_listed":    None,
        "is_repriced":    False,
    }


class NexoScraper:
    slug = "nexo"
    country = "SV"

    def __init__(self, offline: bool | None = None):
        self.offline = offline
        # Phase-1 diagnostic breadcrumbs — automation/run.py duck-types
        # access via getattr on failure to build the snapshot.
        self.last_request_url: Optional[str] = None
        self.last_response = None

    def report_total(self, client=None) -> Optional[int]:
        """Count of for-sale land listings advertised by nexo.

        Kept for API parity with the prior HTML scraper. ``client`` is
        ignored — curl_cffi opens its own connection.
        """
        get = polite_get_for(self.slug)
        try:
            resp = get(None, f"{BASE}{API_PATH}?skip=0&limit={PAGE_SIZE}")
            if resp.status_code != 200:
                return None
            import json as _json
            data = _json.loads(resp.text)
            if not isinstance(data, list):
                return None
            return sum(
                1 for d in data
                if isinstance(d, dict)
                and (d.get("listing_type") or {}).get("category") == "terrenos"
                and (d.get("listing_type") or {}).get("sale_rent") == "venta"
                and d.get("is_published") and d.get("is_active")
            )
        except Exception:
            return None

    def crawl(self, limit: int = MAX_LISTINGS, offline: bool | None = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)

        effective_limit = min(limit, MAX_LISTINGS)
        get = polite_get_for(self.slug)
        out: list[dict] = []
        seen_ids: set[str] = set()
        max_pages_hit = False
        limit_hit = False

        # MAX_PAGES caps the pagination loop independently of
        # effective_limit. The catalogue is ~500 listings of which
        # ~1% match terreno/venta, so a literal limit-driven page
        # budget would walk into hundreds of pages chasing 5 rows.
        # The genuine end-of-data signal is ``len(data) < PAGE_SIZE``,
        # handled below.
        for page in range(MAX_PAGES):
            skip = page * PAGE_SIZE
            url = f"{BASE}{API_PATH}?skip={skip}&limit={PAGE_SIZE}"
            self.last_request_url = url

            try:
                resp = get(None, url)
            except Exception as e:
                print(f"[nexo] page skip={skip} request failed: {e}")
                break
            self.last_response = resp

            if resp.status_code != 200:
                print(f"[nexo] page skip={skip} HTTP {resp.status_code}")
                break

            try:
                import json as _json
                data = _json.loads(resp.text)
            except Exception as e:
                print(f"[nexo] page skip={skip} JSON decode failed: {e}")
                break

            if not isinstance(data, list) or not data:
                # Walked past the last page — API returns []. Stop.
                break

            new_this_page = 0
            for listing in data:
                if len(out) >= effective_limit:
                    limit_hit = True
                    break
                rec = parse_listing(listing)
                if rec is None:
                    continue
                sid = rec["source_id"]
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                rec["source"]     = self.slug
                rec["scraped_at"] = datetime.now(timezone.utc).isoformat()
                out.append(rec)
                new_this_page += 1

            if len(out) >= effective_limit:
                limit_hit = True
                break

            # Last page detected when the API returns fewer rows than
            # PAGE_SIZE — same convention every paginated REST API uses.
            if len(data) < PAGE_SIZE:
                break

        if page == MAX_PAGES - 1 and len(out) >= effective_limit:
            max_pages_hit = True

        self._last_max_pages_hit = max_pages_hit
        self._last_limit_hit     = limit_hit
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


_scraper = NexoScraper()
register(SOURCES, "nexo", _scraper)


def crawl(limit: int = MAX_LISTINGS, offline: bool | None = None) -> list[dict]:
    return NexoScraper(offline=offline).crawl(limit)
