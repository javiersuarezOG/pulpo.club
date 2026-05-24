"""
El Salvador Surf Real Estate scraper.

Site: https://elsalvadorsurfrealestate.com/
Stack: WordPress + AgentFire IDX (v3 listing plugin). The site exposes
a public listings API at:

  POST /wp-json/agentfire/v2/listing3/listings
  body: {"options": {"pageNumber": N}}    (9 listings per page, 24 pages)

The API payload is "thin" — it carries id, url, address, price, lat/lng,
images, specs (beds/baths/area), status, badges — but NOT title or
description. v1 of this scraper skips the per-listing detail fetch and
synthesizes title from the URL slug; the agency is a boutique 100% surf-
coast operator (Atami, San Blas, El Tunco, El Sunzal, El Zonte, Punta
Mango, Costa del Sol, Surf City, Las Flores) so the slug carries the
salient zone reliably.

Active-vs-sold gate
-------------------
~70% of the catalog is `status: "sold"` (143 of 208 audited 2026-05-25).
We drop them at parse time so they never enter the ranker — Pulpo only
ships listings currently for sale.

Rent-vs-sale gate
-----------------
A handful of URLs end in `-for-rent-*` instead of `-for-sale-*`. We drop
those too — Pulpo doesn't surface rentals.

Niche filter
------------
Standard house/condo vacation-zone gate from _base.passes_vacation_gate
(force=False). Land is exempt by convention. This agency is already
~100% in-niche so the gate primarily acts as defense-in-depth.

URL → Pulpo type
----------------
Audited 2026-05-25 across all 208 listings:
  home (56), villa, casa            → house
  lot (46), land (11), terreno (2)  → land
  condo (3), apartment (2)          → condo
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from pulpo.agents.html_crawler import HTTPX_OK, make_client
from pulpo.agents import SOURCES, register
from pulpo.scrapers._base import OfflineFixtureMixin, finalize_record
from pulpo.scrapers._policy import get_policy
from pulpo.scrapers._runtime import get_limiter, jitter_sleep

if HTTPX_OK:
    import httpx  # noqa: F401

API_BASE     = "https://elsalvadorsurfrealestate.com/wp-json/agentfire/v2"
LISTINGS_URL = f"{API_BASE}/listing3/listings"
MAX_PAGES    = 50              # the site reports count=24; cap higher for headroom
FIXTURE_FILE = "sample_listings.json"

_URL_TYPE_RE = re.compile(
    r"-(home|villa|casa|condo|apartment|lot|land|terreno|townhouse|townhome)-",
    re.IGNORECASE,
)
_URL_OPERATION_RE = re.compile(
    r"-(for[-_]sale|venta|sale)\b", re.IGNORECASE,
)
_URL_RENT_RE = re.compile(r"-for[-_]rent\b|-rent-", re.IGNORECASE)

# Map URL-slug type token → Pulpo type. Unknown tokens (e.g. -estate-,
# -residence-) default to "house" because the agency's mixed inventory
# is overwhelmingly homes; the multi-signal classifier in finalize_record
# will flag any genuine miscategorization.
_URL_TOKEN_TO_TYPE: dict[str, str] = {
    "home":      "house",
    "villa":     "house",
    "casa":      "house",
    "townhouse": "house",
    "townhome":  "house",
    "condo":     "condo",
    "apartment": "condo",
    "lot":       "land",
    "land":      "land",
    "terreno":   "land",
}

_PRICE_SUFFIX_RE = re.compile(r"-(\d{4,})$")


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1]


def _classify_from_url(url: str) -> Optional[str]:
    """Return the Pulpo property_type inferred from the URL slug.

    Returns None for a URL we can't classify — caller should drop the
    listing since broker_type is the strongest signal we have without
    a detail-page fetch.
    """
    slug = _slug_from_url(url)
    m = _URL_TYPE_RE.search(slug)
    if not m:
        return None
    return _URL_TOKEN_TO_TYPE.get(m.group(1).lower())


def _title_from_slug(slug: str) -> str:
    """Convert ``bahia-dorada-home-for-sale-460000`` → ``Bahia Dorada
    Home For Sale``. We strip the trailing -<price> suffix and the
    -for-sale operation token so the title reads naturally."""
    s = _PRICE_SUFFIX_RE.sub("", slug)
    s = _URL_OPERATION_RE.sub("", s)
    return " ".join(w.capitalize() for w in s.split("-") if w)


def _parse_area_from_specs(specs: dict) -> tuple[Optional[float], str]:
    """Extract a land/built area from the API's specs dict.

    The specs dict uses humanised keys ("square mts.", "vara cuadrada").
    Returns (value_m2, original_string) — or (None, "") if no area key
    is present. The string form goes into raw_size_text so the
    downstream units module gets the same input it does for other
    sources.
    """
    if not isinstance(specs, dict):
        return (None, "")
    for k, v in specs.items():
        kl = k.lower()
        if "square mts" in kl or "square mt" in kl or "mts." in kl or "m²" in kl or "m2" in kl:
            try:
                val = float(str(v).replace(",", "").strip())
                return (val, f"{val} m2")
            except (TypeError, ValueError):
                continue
    # No m² key — fall back to varas² (the EL Salvador native unit)
    for k, v in specs.items():
        if "vara" in k.lower():
            try:
                val = float(str(v).replace(",", "").strip())
                return (None, f"{val} v2")
            except (TypeError, ValueError):
                continue
    return (None, "")


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        n = int(float(str(v).replace(",", "")))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _to_positive_float(v) -> Optional[float]:
    """Parse to float, return None for missing/non-positive. For sizes
    and counts where 0 means 'unknown' (or 'invalid')."""
    if v is None:
        return None
    try:
        n = float(str(v).replace(",", ""))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _to_float(v) -> Optional[float]:
    """Parse to float, accept any value including 0 and negatives. Used
    for lat/lng (lng in El Salvador is always negative)."""
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _map(rec: dict) -> Optional[dict]:
    """Map one essurf API record to the Pulpo raw-dict shape."""
    if rec.get("status") != "active":
        return None
    url = rec.get("url") or ""
    if not url or _URL_RENT_RE.search(url):
        return None

    broker_type = _classify_from_url(url)
    if broker_type is None:
        return None

    slug = _slug_from_url(url)
    title = _title_from_slug(slug)
    if not title:
        return None

    price = rec.get("price") or 0
    raw_price_text = rec.get("priceString") or (f"${price}" if price else "")

    addr = rec.get("address") or {}
    location_text = addr.get("full") or ", ".join(
        v for v in [addr.get("street"), addr.get("city"), addr.get("state")] if v
    )
    if not location_text:
        location_text = "El Salvador"
    elif "El Salvador" not in location_text:
        location_text = f"{location_text}, El Salvador"

    specs = rec.get("specs") or {}
    lot_m2, raw_size_text = _parse_area_from_specs(specs)

    photo_urls: list[str] = []
    seen: set[str] = set()
    for candidate in [rec.get("thumb2x"), rec.get("thumb")] + list(rec.get("images") or []):
        if isinstance(candidate, str) and candidate.startswith("http") and candidate not in seen:
            seen.add(candidate)
            photo_urls.append(candidate)

    record: dict = {
        "source":         "essurf",
        "source_id":      str(rec.get("id") or ""),
        "url":            url,
        "title":          title,
        "price_usd":      float(price) if price else None,
        "raw_price_text": raw_price_text,
        "raw_size_text":  raw_size_text,
        "location_text":  location_text,
        "description":    "",  # not in API; detail-page fetch is a follow-up
        "property_type":  broker_type,
        "photo_urls":     photo_urls,
        "scraped_at":     datetime.now(timezone.utc).isoformat(),
    }

    lat = _to_float(rec.get("lat"))
    lng = _to_float(rec.get("lng"))
    if lat is not None and lng is not None:
        record["lat"] = lat
        record["lng"] = lng

    # Type-specific fields for house / condo.
    if broker_type in ("house", "condo"):
        beds = _to_int(rec.get("beds") or specs.get("beds"))
        if beds:
            record["bedrooms"] = beds
        baths_raw = rec.get("baths") or specs.get("baths")
        baths = _to_positive_float(baths_raw)
        if baths:
            record["bathrooms"] = baths
        # Built area: prefer specs."square mts." if it looks like a built
        # area (i.e. there's also a lot area in vara cuadrada). When only
        # one m² value is present we treat it as the lot — same convention
        # bienesraices uses.
        if lot_m2 and "vara cuadrada" in specs:
            record["built_area_m2"] = lot_m2

    return finalize_record(
        record, slug="essurf",
        broker_type=broker_type,
        broker_type_field=slug,
    )


class ESSurfScraper(OfflineFixtureMixin):
    slug = "essurf"

    def __init__(self, offline: bool | None = None):
        self.offline = offline

    def report_total(self, client) -> Optional[int]:
        """Total advertised by the API — includes sold. Not the active
        count, but useful as a coverage indicator."""
        policy = get_policy(self.slug)
        try:
            jitter_sleep(policy)
            resp = client.post(
                LISTINGS_URL,
                json={"options": {"pageNumber": 1}},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            t = (data.get("data") or {}).get("total")
            return int(t) if t else None
        except Exception:
            return None

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        return self.crawl_with_meta(limit, offline)["records"]

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None,
    ) -> dict:
        fix = self._offline_or_fixtures(limit, override_offline=offline)
        if fix is not None:
            return {"records": fix, "max_pages_hit": False, "limit_hit": len(fix) >= limit}

        page_cap = max_pages if max_pages is not None else MAX_PAGES
        policy = get_policy(self.slug)
        # POST requests don't fit polite_get's GET-only signature, but the
        # other half of the polite layer (rate-limit + jitter) we still
        # want — apply them by hand around client.post calls.
        limiter = get_limiter(self.slug, policy)

        client = make_client()
        out: list[dict] = []
        seen_ids: set[str] = set()
        max_pages_hit = False
        limit_hit = False
        try:
            for page in range(1, page_cap + 1):
                if len(out) >= limit:
                    limit_hit = True
                    break
                limiter.acquire()
                jitter_sleep(policy)
                try:
                    resp = client.post(
                        LISTINGS_URL,
                        json={"options": {"pageNumber": page}},
                        headers={"Content-Type": "application/json"},
                    )
                    resp.raise_for_status()
                except Exception as e:
                    print(f"[{self.slug}] page {page} fetch failed: {e}")
                    break

                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    break
                listings = (data.get("data") or {}).get("listings") or []
                paging   = (data.get("data") or {}).get("paging") or {}
                count    = int(paging.get("count") or page_cap)

                if not listings:
                    break

                for rec in listings:
                    if len(out) >= limit:
                        limit_hit = True
                        break
                    sid = str(rec.get("id") or "")
                    if not sid or sid in seen_ids:
                        continue
                    seen_ids.add(sid)
                    mapped = _map(rec)
                    if mapped is not None:
                        out.append(mapped)

                if page >= count:
                    break
                if page >= page_cap:
                    max_pages_hit = True
                    break
        finally:
            client.close()
        return {"records": out, "max_pages_hit": max_pages_hit, "limit_hit": limit_hit}

    def parse_index_page(self, html: str) -> list[dict]:  # noqa: ARG002
        return []

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:  # noqa: ARG002
        return None


_scraper = ESSurfScraper()
register(SOURCES, "essurf", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return ESSurfScraper(offline=offline).crawl(limit)
