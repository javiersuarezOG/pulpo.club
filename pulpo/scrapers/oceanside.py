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

from pulpo.agents.html_crawler import is_offline, load_fixtures, make_client, with_retries
from pulpo.agents.html_crawler import DEFAULT_REQUEST_DELAY as REQUEST_DELAY
from pulpo.agents import SOURCES, register
from pulpo.scrapers._type_classifier import classify_property_type
from automation.property_types import VACATION_ZONES, WATERFRONT_KEYWORDS

API_BASE   = "https://oceansideelsalvador.com/wp-json/wp/v2"
BASE_URL   = "https://oceansideelsalvador.com/"
PER_PAGE   = 100
MAX_PAGES  = 50         # safety cap: 50 × 100 = 5 000 records
FIXTURE_FILE  = "sample_listings.json"

# Land-type slugs we accept from the property-type taxonomy.
# /rental-details CPT — handled by the existing flow.
_LAND_SLUGS = {
    "land", "lot", "lots", "lots-and-land",
    "terrenos", "lotes", "terreno", "lote",
}

# Built-type slugs from the same property-type taxonomy.
# /home-details CPT — Phase C broadening adds these.
# Audited live 2026-05-06: id=21 houses (33), id=8 apartments (7), id=114
# condo (3), id=116 beach-villa (5). Hotels (81), restaurant (117),
# commercial-land (123) intentionally skipped.
_HOUSE_SLUGS = {"houses", "house", "beach-villa", "casa", "casas", "villa", "villas"}
_CONDO_SLUGS = {"condo", "condos", "apartments", "apartment", "apartamento", "apartamentos"}

# Compiled waterfront-keyword fallback for the vacation-zone filter on
# house/condo. "Waterfront" covers ocean coast + lake (PR #161, 2026-05-08).
_WATERFRONT_RE = re.compile("|".join(WATERFRONT_KEYWORDS), re.IGNORECASE)

# ── Built-type field regexes (oceanside content_text is unstructured prose) ──
# Bedrooms: "3 bedroom", "3 beds", "tres habitaciones", "3-bed", "3BR".
_BEDROOMS_RE = re.compile(
    r"\b(\d+)\s*(?:bed(?:room)?s?|hab(?:itaci(?:ó|o)n(?:es)?)?|rec[áa]maras?|br|-bed)\b",
    re.IGNORECASE,
)
# Bathrooms: "2 bathroom", "2.5 baths", "2 baños", "2 ba".
_BATHROOMS_RE = re.compile(
    r"\b([\d.]+)\s*(?:bath(?:room)?s?|baños?|ba\b)",
    re.IGNORECASE,
)

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


def _find_built_term_ids(client) -> dict[int, str]:
    """Return {term_id: 'house'|'condo'} for the built-type taxonomy terms.

    Used by the /home-details branch (Phase C) to filter for built listings
    we want and tag each record with its broker_type. Multi-term records
    (e.g. [8, 21] = Apartments + Houses) get the FIRST hit in the priority
    order: condo → house. Classifier downstream confirms.
    """
    try:
        r = client.get(f"{API_BASE}/property-type", params={"per_page": 100})
        r.raise_for_status()
        out: dict[int, str] = {}
        for t in r.json():
            slug = (t.get("slug") or "").lower()
            if slug in _CONDO_SLUGS:
                out[t["id"]] = "condo"
            elif slug in _HOUSE_SLUGS:
                out[t["id"]] = "house"
        return out
    except Exception as e:
        print(f"[oceanside] could not fetch built-type terms: {e}")
        return {}


def _extract_photo_urls(rec: dict) -> list[str]:
    """Extract photo URLs from a WP REST record.

    Prefer the _embed response (featured media); fall back to the ACF gallery
    field if present. Returns a list with the hero URL first (may be empty).
    """
    urls: list[str] = []
    # Embedded featured media (requires _embed=wp:featuredmedia on the request)
    embedded = rec.get("_embedded") or {}
    fm_list  = embedded.get("wp:featuredmedia") or []
    if fm_list and isinstance(fm_list, list) and fm_list[0]:
        fm = fm_list[0]
        # Prefer 'full' size; fall back through sizes, then source_url
        sizes = (fm.get("media_details") or {}).get("sizes") or {}
        hero = (
            (sizes.get("full") or sizes.get("large") or sizes.get("medium") or {}).get("source_url")
            or fm.get("source_url")
        )
        if hero and hero.startswith("http"):
            urls.append(hero)
    # ACF gallery array (present on some listings)
    acf = rec.get("acf") or {}
    gallery = acf.get("gallery") or acf.get("photos") or []
    for item in gallery:
        if isinstance(item, dict):
            u = item.get("url") or item.get("source_url") or ""
        elif isinstance(item, str):
            u = item
        else:
            continue
        if u.startswith("http") and u not in urls:
            urls.append(u)
    return urls


def _map(rec: dict, land_term_id: Optional[int], broker_type: str = "land") -> Optional[dict]:
    """Map one WP REST record to the normalized raw-dict shape.

    broker_type controls type-specific extraction + coastal filter:
      - 'land'  → existing flow, no built-area / bedroom extraction
      - 'house' → regex-extract bedrooms + bathrooms from content_text;
                  apply coastal filter (drop unless coastal zone or
                  beachfront keyword in title/description)
      - 'condo' → same as house
    """
    title = _strip(rec["title"]["rendered"])
    if not title:
        return None

    # Land path: gate on the land term ID. Built path: caller already
    # filtered to known built-type term IDs, so no further check.
    if broker_type == "land":
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
    #
    # Phase-3 zone note (2026-05-02): class_list slugs are DEPARTMENT-level
    # (la-libertad / san-miguel / sonsonate), not zone-level. Migrating to
    # class_list-primary zone detection would downgrade 24 listings from
    # specific zones (el-tunco, el-zonte) to the generic 'la-libertad'.
    # The current flow already correctly uses class_list:
    #   class_list → loc_slugs → location_text → normalize() → detect_zone()
    # detect_zone() scans (location_text + title + description) so it resolves
    # el-tunco / el-zonte from the listing title even when location_text only
    # says "La Libertad". No migration needed.
    loc_slugs = [
        c[len("location-"):].replace("-", " ").title()
        for c in (rec.get("class_list") or [])
        if c.startswith("location-") and c != "location-el-salvador"
    ]
    if not loc_slugs:
        # Defensive: class_list should always have a location-* entry for
        # rental-details; log and fall back to title.
        print(f"[oceanside] WARNING: no location-* in class_list for id={rec.get('id')}")
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

    photo_urls = _extract_photo_urls(rec)
    description = content_text[:1500]

    rec_out: dict = {
        "source_id":       str(rec["id"]),
        "url":             rec["link"],
        "scraped_at":      datetime.now(timezone.utc).isoformat(),
        "title":           title,
        "description":     description,
        "raw_price_text":  raw_price_text,
        "raw_size_text":   raw_size_text,
        "location_text":   location_text,
        "property_type":   broker_type,
        "photo_urls":      photo_urls,
        "photos_count":    1 if rec.get("featured_media") else 0,
        "days_listed":     days_listed,
        "is_repriced":     False,
        "is_beachfront":   is_beachfront,
        "has_paved_access":has_paved_access,
        "has_water":       has_water,
        "has_power":       has_power,
    }

    # Type-specific fields for house/condo. Oceanside content_text is
    # unstructured prose (no ACF blob) so we regex out bedrooms +
    # bathrooms only — built area is too easy to confuse with lot area
    # in this format ("3 bedroom house on 1500 m² lot"). The per-type
    # ranker falls back to lot area when built_area_m2 is None.
    if broker_type in ("house", "condo"):
        bm = _BEDROOMS_RE.search(content_text)
        if bm:
            try:
                rec_out["bedrooms"] = int(bm.group(1))
            except ValueError:
                pass
        bath = _BATHROOMS_RE.search(content_text)
        if bath:
            try:
                rec_out["bathrooms"] = float(bath.group(1))
            except ValueError:
                pass

        # Vacation-zone filter — drop unless location matches a known
        # vacation zone (ocean coast or lake) OR title/description carries
        # a waterfront keyword. Most oceanside listings ARE coastal (the
        # brand is "Oceanside"), so this filter should be lenient in
        # practice — but documenting the gate keeps parity with the
        # other Phase-C scrapers (bienesraices/remax/c21/goodlife).
        loc_blob = location_text.lower().replace(" ", "-")
        zone_is_vacation = any(z in loc_blob for z in VACATION_ZONES)
        text_blob = f"{title}\n{description}"
        has_waterfront_kw = bool(_WATERFRONT_RE.search(text_blob))
        if not zone_is_vacation and not has_waterfront_kw:
            return None

    # Multi-signal classifier — confirms broker_type, surfaces signals
    # for the shadow log, FLAGS the listing if classifier disagrees.
    ptype, signals, confidence, total = classify_property_type({
        "broker_type_field": broker_type,
        "url":               rec_out["url"],
        "photo_urls":        photo_urls,
        "title":             title,
        "description":       description,
    }, fallback_type=broker_type)
    rec_out["_type_signals"]    = [s.to_dict() for s in signals]
    rec_out["_type_confidence"] = confidence
    rec_out["_type_total"]      = total
    if ptype != broker_type:
        rec_out["validation_status"] = "flagged"
        rec_out.setdefault("validation_warnings", []).append("type_classifier_disagree")

    return rec_out


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
            r = with_retries(lambda: client.get(f"{API_BASE}/rental-details", params=params))
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
        # Phase C — also resolve the built-type term IDs for the
        # /home-details branch.
        built_id_to_type = _find_built_term_ids(client)

        out: list[dict] = []
        max_pages_hit = False
        limit_hit = False

        # ── Pass 1: land via /rental-details (existing flow) ──────────
        params: dict = {"per_page": PER_PAGE, "_embed": "wp:featuredmedia"}
        if land_id:
            params["property-type"] = land_id

        for page in range(1, MAX_PAGES + 1):
            params["page"] = page
            time.sleep(REQUEST_DELAY)
            try:
                r = with_retries(lambda: client.get(f"{API_BASE}/rental-details", params=params))
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
                mapped = _map(rec, land_id, broker_type="land")
                if mapped:
                    out.append(mapped)

            if limit_hit:
                break

            if page >= total_pages:
                break

            if page >= MAX_PAGES:
                max_pages_hit = True
                break

        # ── Pass 2: house/condo via /home-details (Phase C) ───────────
        # Crawl all home-details, classify each via the term IDs we
        # resolved above. Multi-term records (e.g. [8, 21]) prefer
        # condo over house in the priority order.
        if not limit_hit and built_id_to_type:
            for page in range(1, MAX_PAGES + 1):
                if len(out) >= limit:
                    limit_hit = True
                    break
                time.sleep(REQUEST_DELAY)
                try:
                    home_r = with_retries(lambda: client.get(
                        f"{API_BASE}/home-details",
                        params={"per_page": PER_PAGE, "page": page,
                                "_embed": "wp:featuredmedia"}))
                    home_r.raise_for_status()
                except Exception as e:
                    print(f"[oceanside] /home-details page {page} failed: {e}")
                    break

                home_recs = home_r.json()
                home_total_pages = int(home_r.headers.get("X-WP-TotalPages") or 1)
                if not home_recs:
                    break

                for rec in home_recs:
                    if len(out) >= limit:
                        limit_hit = True
                        break
                    rec_term_ids = rec.get("property-type") or []
                    # Priority: condo > house. Pick the first matching type.
                    matched_type: Optional[str] = None
                    for tid in rec_term_ids:
                        t = built_id_to_type.get(tid)
                        if t == "condo":
                            matched_type = "condo"
                            break
                        if t == "house" and matched_type is None:
                            matched_type = "house"
                    if not matched_type:
                        continue  # not a house or condo we want
                    mapped = _map(rec, land_id, broker_type=matched_type)
                    if mapped:
                        out.append(mapped)

                if page >= home_total_pages:
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
