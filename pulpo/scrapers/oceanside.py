"""
Oceanside El Salvador scraper — WP REST API client.

Replaced HTML walking (2026-05-02) with direct WP REST API calls.

Why: The Avada/Fusion theme exposed a public REST API at
  GET /wp-json/wp/v2/rental-details?per_page=100&property-type=<id>
returning clean JSON for all land listings in a single call. No more
Avada selector regressions, no more year+area concatenation hacks,
no per-listing detail-page fetches.

CPT mapping:
  - /rental-details  = land lots (Avada quirk: lots use the "rental" CPT)
  - /home-details    = houses/condos/hotels (excluded here)
  - property-type taxonomy id=122 slug="lot" = land filter

ACF block is empty on all records — price/area still parsed from
content.rendered (same blob the HTML scraper used).

class_list carries location-* slugs (e.g. location-la-libertad) which
complement the regex-based zone detection in normalize.py.
"""
from __future__ import annotations
import html as _html
import re
import time
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import is_offline, load_fixtures, make_client
from pulpo.agents import SOURCES, register

API_BASE   = "https://oceansideelsalvador.com/wp-json/wp/v2"
BASE_URL   = "https://oceansideelsalvador.com/"
PER_PAGE   = 100
MAX_PAGES  = 50         # safety cap: 50 × 100 = 5 000 records
REQUEST_DELAY = 1.5
FIXTURE_FILE  = "sample_listings.json"

# Land-type slugs we accept from the property-type taxonomy
_LAND_SLUGS = {
    "land", "lot", "lots", "lots-and-land",
    "terrenos", "lotes", "terreno", "lote",
}

# ── Area regexes (kept from HTML scraper to handle the same content blobs) ──
# The Avada theme concatenates "Listed on <date>" with the area value:
#   "Listed on Sep 2, 2025243,080.00m2Lot"
# Anchor on the four-digit year to avoid parsing the year as part of the number.
_AREA_AFTER_YEAR_RE = re.compile(
    r"20\d{2}\s*(\d[\d,\.]*)\s*m[2²]",
    re.IGNORECASE,
)
_AREA_PLAIN_RE = re.compile(
    r"(?<![\d])(\d[\d,]*\.?\d*)\s+m[2²](?![a-zA-Z])",
    re.IGNORECASE,
)

_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
_TAG_RE   = re.compile(r"<[^>]+>")


def _strip(html_str: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    return _html.unescape(re.sub(r"\s+", " ", _TAG_RE.sub(" ", html_str)).strip())


def _extract_area_text(blob: str) -> str:
    if not blob:
        return ""
    m = _AREA_AFTER_YEAR_RE.search(blob) or _AREA_PLAIN_RE.search(blob)
    return f"{m.group(1)} m²" if m else ""


def _find_land_term_id(client) -> Optional[int]:
    """Return the property-type term ID for land/lots, or None.

    Picks the matching term with the highest count so that a narrow
    niche term (e.g. 'commercial-land', count=1) never shadows the
    primary land term (e.g. 'lot', count=27).
    """
    try:
        r = client.get(f"{API_BASE}/property-type", params={"per_page": 100})
        r.raise_for_status()
        candidates = [
            t for t in r.json()
            if t.get("slug", "").lower() in _LAND_SLUGS
        ]
        if candidates:
            best = max(candidates, key=lambda t: t.get("count", 0))
            return best["id"]
    except Exception as e:
        print(f"[oceanside] could not fetch property-type terms: {e}")
    print("[oceanside] WARNING: no land-type term found; fetching all rental-details")
    return None


def _map(rec: dict, land_term_id: Optional[int]) -> Optional[dict]:
    """Map one WP REST record to the normalized raw-dict shape."""
    title = _strip(rec["title"]["rendered"])
    if not title:
        return None

    # If no term filter was applied server-side, verify in Python
    if land_term_id is None:
        pt = rec.get("property-type") or []
        # Fall back: keep if property-type list is empty or contains any land-ish slug
        # (we can't look up slugs here without an extra call, so keep all)
    else:
        pt = rec.get("property-type") or []
        if land_term_id not in pt:
            return None

    content_html = rec["content"]["rendered"]
    content_text = _strip(content_html)

    raw_price_text = ""
    pm = _PRICE_RE.search(content_text)
    if pm:
        raw_price_text = f"${pm.group(1)}"

    raw_size_text = _extract_area_text(content_text)

    # Location from class_list: "location-la-libertad" → "La Libertad"
    loc_slugs = [
        c[len("location-"):].replace("-", " ").title()
        for c in (rec.get("class_list") or [])
        if c.startswith("location-") and c != "location-el-salvador"
    ]
    location_text = ", ".join(loc_slugs) if loc_slugs else title

    # Days since last modified
    days_listed: Optional[int] = None
    modified = rec.get("modified") or ""
    if modified:
        try:
            mod_dt = datetime.fromisoformat(modified.rstrip("Z")).replace(
                tzinfo=timezone.utc
            )
            days_listed = (datetime.now(timezone.utc) - mod_dt).days
        except Exception:
            pass

    ct = content_text.lower()
    is_beachfront   = bool(re.search(r"frente\s+al\s+mar|beachfront|ocean.?front", ct))
    has_paved_access = bool(re.search(r"pavimentad|paved\s+road|paved\s+access|acceso\s+pavimentado", ct))
    has_water       = bool(re.search(r"\bagua\b|water\s+access|water\s+available|suministro\s+de\s+agua", ct))
    has_power       = bool(re.search(r"el[eé]ctric|energ[íi]a|l[íi]neas?\s+el[eé]ctric|power\s+available", ct))

    return {
        "source_id":       str(rec["id"]),
        "url":             rec["link"],
        "scraped_at":      datetime.now(timezone.utc).isoformat(),
        "title":           title,
        "description":     content_text[:1500],
        "raw_price_text":  raw_price_text,
        "raw_size_text":   raw_size_text,
        "location_text":   location_text,
        "property_type":   "land",
        "photos_count":    1 if rec.get("featured_media") else 0,
        "days_listed":     days_listed,
        "is_repriced":     False,
        "is_beachfront":   is_beachfront,
        "has_paved_access":has_paved_access,
        "has_water":       has_water,
        "has_power":       has_power,
    }


class OceansideScraper:
    slug = "oceanside"

    def __init__(self, offline: bool | None = None):
        self.offline = offline

    def report_total(self, client) -> Optional[int]:
        """Return advertised land listing count via X-WP-Total header."""
        try:
            time.sleep(REQUEST_DELAY)
            land_id = _find_land_term_id(client)
            params = {"per_page": 1}
            if land_id:
                params["property-type"] = land_id
            r = client.get(f"{API_BASE}/rental-details", params=params)
            r.raise_for_status()
            return int(r.headers.get("X-WP-Total") or 0) or None
        except Exception:
            return None

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        client = make_client()
        try:
            return self._fetch(client, limit)
        finally:
            client.close()

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None  # noqa: ARG002
    ) -> dict:
        if is_offline(offline if offline is not None else self.offline):
            records = load_fixtures(self.slug, FIXTURE_FILE, limit)
            return {"records": records, "max_pages_hit": False, "limit_hit": False}
        client = make_client()
        try:
            return self._fetch_with_meta(client, limit)
        finally:
            client.close()

    def _fetch(self, client, limit: int) -> list[dict]:
        return self._fetch_with_meta(client, limit)["records"]

    def _fetch_with_meta(self, client, limit: int) -> dict:
        time.sleep(REQUEST_DELAY)
        land_id = _find_land_term_id(client)

        out: list[dict] = []
        max_pages_hit = False
        limit_hit = False

        params: dict = {"per_page": PER_PAGE}
        if land_id:
            params["property-type"] = land_id

        for page in range(1, MAX_PAGES + 1):
            params["page"] = page
            time.sleep(REQUEST_DELAY)
            try:
                r = client.get(f"{API_BASE}/rental-details", params=params)
                r.raise_for_status()
            except Exception as e:
                print(f"[oceanside] API page {page} failed: {e}")
                break

            recs = r.json()
            total_pages = int(r.headers.get("X-WP-TotalPages") or 1)

            if not recs:
                break

            for rec in recs:
                if len(out) >= limit:
                    limit_hit = True
                    break
                mapped = _map(rec, land_id)
                if mapped:
                    out.append(mapped)

            if limit_hit:
                break

            if page >= total_pages:
                break

            if page >= MAX_PAGES:
                max_pages_hit = True
                break

        return {"records": out, "max_pages_hit": max_pages_hit, "limit_hit": limit_hit}

    # ── Kept for calibration harness compatibility ──────────────────────────
    def parse_index_page(self, html: str) -> list[dict]:
        """Stub — calibration harness may call this; API client doesn't use it."""
        return []

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        """Stub — calibration harness may call this; API client doesn't use it."""
        return None


_scraper = OceansideScraper()
register(SOURCES, "oceanside", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return OceansideScraper(offline=offline).crawl(limit)
