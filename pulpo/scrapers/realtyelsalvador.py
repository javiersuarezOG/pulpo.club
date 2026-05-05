"""
Realty El Salvador scraper — realtyelsalvador.com

El Salvador-focused English-language real estate broker.
Stack: WordPress + RealHomes theme. All listing data is accessible via
the WP REST API at /wp-json/wp/v2/propiedades with _embed for media.

Strategy:
  1. Fetch pages of /wp-json/wp/v2/propiedades?per_page=100&_embed
  2. Filter to land / lot property types via the tipo-de-propiedad taxonomy
  3. Extract price, area, location from property_meta (REAL_HOMES_* fields)
  4. Hero photo from _embedded.wp:featuredmedia; gallery from
     property_meta.REAL_HOMES_property_images (list of image dicts)

Photo CDN: realtyelsalvador.com/wp-content/uploads/

Note: there is no /wp-json/wp/v2/property CPT — the registered type is
`propiedades` (non-standard slug). The namespaces include crm/v1 and
elementor/v1 but no real-estate plugin namespace; all structured data
lives in property_meta.
"""
from __future__ import annotations
import re
import time
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import HTTPX_OK, is_offline, load_fixtures, make_client, with_retries
from pulpo.agents.html_crawler import DEFAULT_REQUEST_DELAY as REQUEST_DELAY
from pulpo.agents import SOURCES, register

BASE         = "https://realtyelsalvador.com"
API_BASE     = f"{BASE}/wp-json/wp/v2/propiedades"
PER_PAGE     = 100
MAX_PAGES    = 20
FIXTURE_FILE = "sample_listings.json"

# tipo-de-propiedad taxonomy: terms we treat as land
# Discovered by inspecting live records — expand as new terms appear.
_LAND_KEYWORDS = {"terreno", "terrenos", "lote", "lotes", "land", "lot", "finca", "parcela"}


def _is_land(rec: dict) -> bool:
    """Return True if the listing type is land / lot / finca."""
    # Check taxonomy term names from embedded wp:term
    for term_group in (rec.get("_embedded") or {}).get("wp:term", []):
        for term in term_group:
            slug = (term.get("slug") or "").lower()
            name = (term.get("name") or "").lower()
            if any(k in slug or k in name for k in _LAND_KEYWORDS):
                return True
    # Fallback: check the URL slug
    link = rec.get("link", "").lower()
    return any(k in link for k in _LAND_KEYWORDS)


def _extract_photo_urls(rec: dict) -> list[str]:
    """Collect hero + gallery photo URLs from the WP REST record."""
    urls: list[str] = []
    seen: set[str] = set()

    def _add(u: str) -> None:
        u = u.strip()
        if u.startswith("http") and u not in seen:
            seen.add(u)
            urls.append(u)

    # Hero from embedded featured media
    emb = (rec.get("_embedded") or {})
    for fm in emb.get("wp:featuredmedia", []):
        src = fm.get("source_url", "")
        if src:
            _add(src)

    # Gallery from property_meta.REAL_HOMES_property_images
    meta = rec.get("property_meta") or {}
    for img in meta.get("REAL_HOMES_property_images") or []:
        if isinstance(img, dict):
            # Prefer the highest-res size available
            sizes = img.get("sizes") or {}
            best = (
                sizes.get("large", {}).get("source_url")
                or sizes.get("medium_large", {}).get("source_url")
                or sizes.get("medium", {}).get("source_url")
            )
            src = best or img.get("source_url") or ""
            if not src and img.get("file"):
                src = f"{BASE}/wp-content/uploads/{img['file']}"
            if src:
                _add(src)

    return urls


def _map(rec: dict) -> Optional[dict]:
    """Map one WP REST record to our raw dict schema."""
    if rec.get("status") != "publish":
        return None
    if not _is_land(rec):
        return None

    title = rec.get("title", {}).get("rendered", "").strip()
    if not title:
        return None
    # Strip HTML entities
    title = re.sub(r"<[^>]+>", "", title).strip()

    meta = rec.get("property_meta") or {}

    # Price
    raw_price = meta.get("REAL_HOMES_property_price", "")
    price_usd: Optional[float] = None
    if raw_price:
        try:
            price_usd = float(str(raw_price).replace(",", ""))
        except (ValueError, TypeError):
            pass

    # Area (prefer size in m², fall back to lot_size)
    raw_size_str = meta.get("REAL_HOMES_property_size", "") or ""
    size_unit = meta.get("REAL_HOMES_property_size_postfix", "") or ""
    lot_str   = meta.get("REAL_HOMES_property_lot_size", "") or ""
    lot_unit  = meta.get("REAL_HOMES_property_lot_size_postfix", "") or ""
    raw_size_text = ""
    if raw_size_str:
        raw_size_text = f"{raw_size_str} {size_unit}".strip()
    elif lot_str:
        raw_size_text = f"{lot_str} {lot_unit}".strip()

    # Location from taxonomy terms
    location_parts: list[str] = []
    for term_group in (rec.get("_embedded") or {}).get("wp:term", []):
        for term in term_group:
            taxonomy = term.get("taxonomy", "")
            if taxonomy == "ubicacion-de-propiedad":
                location_parts.append(term.get("name", "").strip())
    location_text = ", ".join(location_parts) if location_parts else "El Salvador"
    if "El Salvador" not in location_text:
        location_text += ", El Salvador"

    # Description from excerpt (cleaned) or content snippet
    desc_html = rec.get("excerpt", {}).get("rendered", "") or rec.get("content", {}).get("rendered", "")
    description = re.sub(r"<[^>]+>", " ", desc_html).strip()[:1500]

    # Days listed from modified date
    days_listed: Optional[int] = None
    modified = rec.get("modified_gmt") or rec.get("modified") or ""
    if modified:
        try:
            mod_dt = datetime.fromisoformat(modified.rstrip("Z")).replace(tzinfo=timezone.utc)
            days_listed = (datetime.now(timezone.utc) - mod_dt).days
        except Exception:
            pass

    return {
        "source_id":      str(rec["id"]),
        "url":            rec.get("link", ""),
        "title":          title,
        "description":    description,
        "location_text":  location_text,
        "price_usd":      price_usd,
        "raw_price_text": f"${raw_price}" if raw_price else "",
        "raw_size_text":  raw_size_text,
        "property_type":  "land",
        "photo_urls":     _extract_photo_urls(rec),
        "days_listed":    days_listed,
        "is_repriced":    bool(meta.get("REAL_HOMES_property_old_price")),
    }


class RealtyElSalvadorScraper:
    slug = "realtyelsalvador"

    def __init__(self, offline: bool | None = None):
        self.offline = offline

    def report_total(self, client) -> Optional[int]:
        try:
            r = client.get(f"{API_BASE}?per_page=1")
            r.raise_for_status()
            return int(r.headers.get("X-WP-Total", 0)) or None
        except Exception:
            return None

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        if not HTTPX_OK:
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        client = make_client()
        try:
            out: list[dict] = []
            for page in range(1, MAX_PAGES + 1):
                time.sleep(REQUEST_DELAY)
                try:
                    r = with_retries(lambda: client.get(API_BASE, params={
                        "per_page": PER_PAGE,
                        "page":     page,
                        "_embed":   "wp:featuredmedia,wp:term",
                    }))
                    r.raise_for_status()
                except Exception as e:
                    print(f"[realtyelsalvador] page {page} failed: {e}")
                    break

                recs = r.json()
                if not recs:
                    break
                total_pages = int(r.headers.get("X-WP-TotalPages", 1))

                for rec in recs:
                    if len(out) >= limit:
                        break
                    mapped = _map(rec)
                    if mapped:
                        mapped["source"] = self.slug
                        mapped["scraped_at"] = datetime.now(timezone.utc).isoformat()
                        out.append(mapped)

                if len(out) >= limit or page >= total_pages:
                    break

            return out
        finally:
            client.close()

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None  # noqa: ARG002
    ) -> dict:
        records = self.crawl(limit, offline)
        return {"records": records, "max_pages_hit": False, "limit_hit": len(records) >= limit}


_scraper = RealtyElSalvadorScraper()
register(SOURCES, "realtyelsalvador", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return RealtyElSalvadorScraper(offline=offline).crawl(limit)
