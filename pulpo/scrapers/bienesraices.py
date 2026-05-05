"""
Bienes Raíces En El Salvador scraper.

Site: https://bienesraicesenelsalvador.com/
Stack: Next.js SPA powered by AlterEstate SaaS. Listings are loaded
client-side, but each detail page server-renders full property data in
the __NEXT_DATA__ JSON block.

Strategy:
  1. Fetch the sitemap API (returns all UIDs + slugs, no auth needed)
  2. Filter candidates by land keywords in the slug
  3. Fetch each candidate's detail page and extract __NEXT_DATA__
  4. Confirm category is land, map to our schema
"""
from __future__ import annotations
import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import HTTPX_OK, is_offline, load_fixtures, make_client, with_retries, DEFAULT_REQUEST_DELAY
from pulpo.agents import SOURCES, register
from pulpo.scrapers._type_classifier import classify_property_type
from automation.property_types import COASTAL_ZONES, BEACHFRONT_KEYWORDS

if HTTPX_OK:
    import httpx  # noqa: F401

BASE = "https://bienesraicesenelsalvador.com"
SITEMAP_URL = "https://secure.alterestate.com/api/v1/properties/sitemap/"
SITEMAP_HEADERS = {"domain": "bienesraicesenelsalvador.com"}

# Slug keywords used to filter the AlterEstate sitemap (per-listing detail
# fetches are expensive — narrow upfront). Broadened beyond land in the
# Phase A houses+condos PR; the type-specific category check at parse-time
# is what actually decides whether the listing flows through.
LAND_SLUG_KEYWORDS = {
    "terreno", "lote", "finca", "parcela",
    "hacienda", "rancho", "manzana", "hectarea", "tierra", "campo",
}
HOUSE_SLUG_KEYWORDS = {
    "casa", "villa", "residencia", "chalet", "house",
}
CONDO_SLUG_KEYWORDS = {
    "apartamento", "condominio", "departamento", "depa", "loft", "apto",
}
ALL_SLUG_KEYWORDS = LAND_SLUG_KEYWORDS | HOUSE_SLUG_KEYWORDS | CONDO_SLUG_KEYWORDS

# Category-name → property_type. AlterEstate's `category.name` is the
# strongest possible broker_field signal; we map it explicitly. Unknown
# categories fall through to the multi-signal classifier in `_parse`.
_CATEGORY_TO_TYPE = {
    # Land
    "terreno": "land", "terrenos": "land", "lote": "land", "lotes": "land",
    "finca": "land", "fincas": "land", "parcela": "land", "parcelas": "land",
    # House
    "casa": "house", "casas": "house", "villa": "house", "villas": "house",
    "residencia": "house", "house": "house",
    # Condo
    "apartamento": "condo", "apartamentos": "condo",
    "condominio": "condo", "condominios": "condo", "condo": "condo",
    "departamento": "condo", "departamentos": "condo",
}

# Compiled beachfront-keyword fallback for the coastal filter on house/condo.
_BEACHFRONT_RE = re.compile("|".join(BEACHFRONT_KEYWORDS), re.IGNORECASE)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

FIXTURE_FILE = "sample_listings.json"


class BienesRaicesScraper:
    slug = "bienesraices"

    def __init__(self, offline: bool | None = None):
        self.offline = offline
        # PULPO_REQUEST_DELAY env var honoured by DEFAULT_REQUEST_DELAY (html_crawler).
        self.REQUEST_DELAY = DEFAULT_REQUEST_DELAY

    def report_total(self, client) -> None:  # noqa: ARG002
        """Supplier count not available as a reliable pre-fetch number.

        The AlterEstate sitemap returns 1 143 slugs; our keyword filter gives
        ~556 candidates, but some have non-land categories and get dropped at
        the detail-page stage. Reporting 556 as 'supplier' makes coverage look
        like 84% when the true figure is ~100% (all genuine land listings are
        pulled). Return None so the audit shows '?' instead of a misleading %.
        """
        return None

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)

        client = make_client()
        try:
            # Step 1: sitemap
            time.sleep(self.REQUEST_DELAY)
            try:
                resp = with_retries(lambda: client.get(SITEMAP_URL, headers={**dict(client.headers), **SITEMAP_HEADERS}))
                resp.raise_for_status()
                sitemap = resp.json()
            except Exception as e:
                print(f"[{self.slug}] sitemap failed: {e}")
                return []

            # Step 2: filter relevant candidates by slug keyword (land, house,
            # or condo). Per-listing category check + classifier decides the
            # actual type at parse time — slugs are just a coarse pre-filter
            # to avoid fetching ~370 unkeyworded entries.
            candidates = [
                item for item in sitemap
                if any(k in item.get("slug", "") for k in ALL_SLUG_KEYWORDS)
            ]

            # Step 3: fetch detail pages
            out: list[dict] = []
            for item in candidates:
                if len(out) >= limit:
                    break
                slug = item.get("slug", "")
                if not slug:
                    continue
                url = f"{BASE}/propiedad/{slug}"
                time.sleep(self.REQUEST_DELAY)
                try:
                    detail = with_retries(lambda: client.get(url))
                    detail.raise_for_status()
                except Exception as e:
                    print(f"[{self.slug}] detail failed {slug}: {e}")
                    continue
                rec = self._parse(detail.text, url)
                if rec:
                    out.append(rec)

            return out
        finally:
            client.close()

    def _parse(self, html: str, url: str) -> Optional[dict]:
        m = _NEXT_DATA_RE.search(html)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None

        prop = data.get("props", {}).get("pageProps", {}).get("property", {})
        if not prop:
            return None

        # Resolve type from the broker's `category.name`. Unknown categories
        # are dropped here — they're typically commercial / industrial /
        # rentals we don't surface today.
        cat = (prop.get("category") or {}).get("name", "").strip().lower()
        broker_type = _CATEGORY_TO_TYPE.get(cat)
        if broker_type is None:
            return None

        # House/condo: only sales, not rentals. Land is sale-only by nature
        # so we don't apply the same gate (and many lots have no sale_price
        # but are still for sale).
        if broker_type in ("house", "condo") and not prop.get("forSale", True):
            return None

        title = prop.get("name", "").strip()
        if not title:
            return None

        price = prop.get("sale_price") or prop.get("us_saleprice")

        province = prop.get("province") or ""
        city = prop.get("city") or ""
        sector = prop.get("sector") or ""
        loc_parts = [p for p in [sector, city, province, "El Salvador"] if p]
        location_text = ", ".join(loc_parts)

        agents = prop.get("agents") or []
        agent = agents[0] if agents else {}
        fname = agent.get("first_name") or ""
        lname = agent.get("last_name") or ""
        broker_name = f"{fname} {lname}".strip()
        broker_phone = agent.get("phone") or ""
        broker_email = agent.get("email") or ""

        desc_html = prop.get("description") or ""
        description = re.sub(r"<[^>]+>", " ", desc_html).strip()[:1500]

        # Photos — AlterEstate's __NEXT_DATA__ exposes:
        #   featured_image: single string URL (the hero, used as photos[0])
        #   gallery_image:  list of {image, image_wm, external_url, ...} dicts
        photo_urls: list[str] = []
        seen: set[str] = set()
        def _add(u: str) -> None:
            u = (u or "").strip()
            if u.startswith("http") and u not in seen:
                seen.add(u)
                photo_urls.append(u)

        _add(prop.get("featured_image") or "")
        for img in prop.get("gallery_image") or prop.get("images") or prop.get("photos") or []:
            if isinstance(img, dict):
                _add(img.get("image") or img.get("photo") or img.get("url") or img.get("src") or "")
            elif isinstance(img, str):
                _add(img)

        # Build the base record. The lot-area field (`terrain_area`) is the
        # `area_m2` for ALL types: for land it's THE area; for houses it's
        # the lot the house sits on; condos rarely have it. The BUILT area
        # lives in `built_area_m2` (from `property_area`) and is only used
        # for house/condo.
        terrain_val = prop.get("terrain_area")
        terrain_unit = (prop.get("terrain_area_measurer") or "v2").strip()
        raw_size = f"{terrain_val} {terrain_unit}" if terrain_val else ""

        rec: dict = {
            "source": self.slug,
            "source_id": str(prop.get("cid") or ""),
            "url": url,
            "title": title,
            "price_usd": float(price) if price else None,
            "raw_price_text": f"{price} USD" if price else "",
            "raw_size_text": raw_size,
            "location_text": location_text,
            "description": description,
            "property_type": broker_type,
            "photo_urls": photo_urls,
            "broker_name": broker_name,
            "broker_phone": broker_phone,
            "broker_email": broker_email,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

        # Type-specific fields for house / condo. AlterEstate field shapes
        # confirmed against live samples (Casas → cid 2346, Apartamentos →
        # cid 2350) during the Phase A diagnosis.
        if broker_type in ("house", "condo"):
            built_val = prop.get("property_area")
            if built_val and (prop.get("property_area_measurer") or "").lower() in ("mt2", "m2", ""):
                rec["built_area_m2"] = float(built_val)
            if prop.get("room") is not None:
                rec["bedrooms"] = int(prop["room"])
            full_baths = prop.get("bathroom") or 0
            half_baths = prop.get("half_bathrooms") or 0
            if full_baths or half_baths:
                rec["bathrooms"] = float(full_baths) + 0.5 * float(half_baths)
            if prop.get("parkinglot") is not None:
                rec["parking_spaces"] = int(prop["parkinglot"])
            if prop.get("year_construction"):
                try:
                    rec["year_built"] = int(prop["year_construction"])
                except (TypeError, ValueError):
                    pass
            if broker_type == "condo":
                if prop.get("floor_level") is not None:
                    rec["floor"] = int(prop["floor_level"])
                if prop.get("maintenance_fee"):
                    try:
                        rec["hoa_fee_usd_monthly"] = float(prop["maintenance_fee"])
                    except (TypeError, ValueError):
                        pass

        # Coastal filter (house/condo only). Per spec: drop a built listing
        # unless its zone is coastal OR title/description has a beachfront
        # keyword. Land is unaffected — inland lots are still ingested.
        # Zone resolution happens later in normalize.py; here we use a quick
        # sector/city/province lower-bag check against COASTAL_ZONES.
        if broker_type in ("house", "condo"):
            location_blob = " ".join(p.lower().replace(" ", "-")
                                     for p in (sector, city, province))
            zone_is_coastal = any(z in location_blob for z in COASTAL_ZONES)
            text_blob = f"{title}\n{description}"
            has_beachfront_kw = bool(_BEACHFRONT_RE.search(text_blob))
            if not zone_is_coastal and not has_beachfront_kw:
                return None

        # Multi-signal classifier confirmation. The broker_field signal
        # above already produced our type; running the classifier here
        # produces signals + confidence so the shadow log captures them
        # and any future tightening can compare broker_type vs predicted.
        ptype, signals, confidence, total = classify_property_type({
            "broker_type_field": cat,
            "url":               url,
            "photo_urls":        photo_urls,
            "title":             title,
            "description":       description,
        }, fallback_type=broker_type)
        rec["_type_signals"]    = [s.to_dict() for s in signals]
        rec["_type_confidence"] = confidence
        rec["_type_total"]      = total
        # Flag (don't drop) on classifier disagreement — the broker label is
        # authoritative for shipping but the disagreement is worth a human
        # eye. Existing validation_warnings list pattern preserved.
        if ptype != broker_type:
            rec["validation_status"] = "flagged"
            rec.setdefault("validation_warnings", []).append("type_classifier_disagree")

        return rec

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None  # noqa: ARG002
    ) -> dict:
        """Sitemap-based source — max_pages does not apply."""
        records = self.crawl(limit, offline)
        return {"records": records, "max_pages_hit": False, "limit_hit": len(records) >= limit}

    def parse_index_page(self, html: str) -> list[dict]:
        return []

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        return None


_scraper = BienesRaicesScraper(offline=None)
register(SOURCES, "bienesraices", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return BienesRaicesScraper(offline=offline).crawl(limit)
