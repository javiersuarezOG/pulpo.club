"""
Nexo Inmobiliario scraper — nexo.com.sv

El Salvador-only real estate directory. Land listings at:
  https://nexo.com.sv/terrenos-en-venta-el-salvador/{page}

Stack: 2017 Dreamweaver static HTML, ISO-8859-1, Schema.org microdata.
No JS rendering, no bot protection. Server-rendered listing cards
with itemprop attributes (Product / Offer / PostalAddress).

Photo CDN: https://nexo.com.sv/nexocrm/imagenes/fotos_inmuebles/terrenos/
Hero: fotoGeneral_{listing_id}.jpg  Thumb: fotoGeneral_{id}_thumbnail.jpg

Pagination: single-page at the time of writing (≈9 listings).
Scraper walks pages 1..MAX_PAGES and stops when a page returns 0 cards.
"""
from __future__ import annotations
import re
import time
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import SELECTOLAX_OK, HTTPX_OK, is_offline, load_fixtures, make_client
from pulpo.agents import SOURCES, register

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser

BASE = "https://nexo.com.sv"
LIST_URL = BASE + "/terrenos-en-venta-el-salvador/{page}"
MAX_PAGES = 20
REQUEST_DELAY = 1.5
FIXTURE_FILE = "sample_listings.json"


def _abs(path: str) -> str:
    """Resolve a relative URL against the nexo.com.sv base."""
    if not path:
        return ""
    if path.startswith("http"):
        return path
    # Strip leading "../" chains — all relative URLs on this site are
    # relative to the page root, not the current path.
    clean = re.sub(r"^(\.\./)+", "", path)
    return f"{BASE}/{clean}"


def _parse_listing_page(html: str) -> list[dict]:
    """Extract listing stubs from a /terrenos-en-venta-el-salvador/{page} page."""
    if not SELECTOLAX_OK:
        return []
    tree = HTMLParser(html)
    out = []
    for card in tree.css("div.dresultado"):
        name_node = card.css_first("[itemprop='name']")
        title = name_node.text(strip=True) if name_node else ""
        if not title:
            continue

        # URL from VER DETALLES link (or itemprop="url")
        link_node = card.css_first("[itemprop='url'], a[href*='/']")
        href = link_node.attributes.get("href", "") if link_node else ""
        url = _abs(href) if href else ""
        if not url:
            continue

        # Extract source_id from URL pattern: /6/42/Slug → "6_42"
        m = re.search(r"/(\d+)/(\d+)/", url)
        source_id = f"{m.group(1)}_{m.group(2)}" if m else re.search(r"/(\d+)/", url).group(1) if re.search(r"/(\d+)/", url) else url

        # Price from itemprop="price" span
        price_node = card.css_first("[itemprop='price']")
        raw_price = price_node.text(strip=True) if price_node else ""

        # Area from <li class="terreno">
        area_node = card.css_first("li.terreno")
        raw_size = area_node.text(strip=True) if area_node else ""

        # Location
        locality = card.css_first("[itemprop='addressLocality']")
        region = card.css_first("[itemprop='addressRegion']")
        loc_parts = [n.text(strip=True) for n in [locality, region] if n and n.text(strip=True)]
        location_text = ", ".join(loc_parts + ["El Salvador"]) if loc_parts else "El Salvador"

        # Thumbnail image → derive full-size URL
        img_node = card.css_first("[itemprop='image']")
        thumb_src = img_node.attributes.get("src", "") if img_node else ""
        # Full-size: replace _thumbnail.jpg with .jpg
        full_src = re.sub(r"_thumbnail(\.[a-z]+)$", r"\1", thumb_src)
        photo_urls = [_abs(full_src)] if full_src else []

        out.append({
            "source_id":    source_id,
            "url":          url,
            "title":        title,
            "raw_price_text": raw_price,
            "raw_size_text":  raw_size,
            "location_text":  location_text,
            "description":    "",
            "property_type":  "land",
            "photo_urls":     photo_urls,
        })
    return out


def _parse_detail_page(html: str, partial: dict) -> Optional[dict]:
    """Enrich with description and full photo gallery from the detail page."""
    if not SELECTOLAX_OK:
        return partial
    tree = HTMLParser(html)

    # Description from the first long text block
    desc_node = tree.css_first("div.content, div.descripcion, div.details, [itemprop='description']")
    description = desc_node.text(strip=True)[:1500] if desc_node else ""

    # All full-size property photos (exclude logo, thumbnail, user avatars)
    all_imgs = [
        _abs(n.attributes.get("src") or n.attributes.get("data-src", ""))
        for n in tree.css("img[src], img[data-src]")
    ]
    photo_urls = [
        u for u in all_imgs
        if u.startswith(BASE + "/nexocrm/imagenes/fotos_inmuebles")
        and "thumbnail" not in u
        and "fotoUsuario" not in u
    ]
    # Keep hero first, dedup
    seen: set[str] = set()
    unique_photos: list[str] = []
    for u in (partial.get("photo_urls", []) + photo_urls):
        if u and u not in seen:
            seen.add(u)
            unique_photos.append(u)

    return {
        **partial,
        "description": description,
        "photo_urls":  unique_photos,
    }


class NexoScraper:
    slug = "nexo"

    def __init__(self, offline: bool | None = None):
        self.offline = offline

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        if not HTTPX_OK:
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        client = make_client()
        try:
            out: list[dict] = []
            seen: set[str] = set()
            for page in range(1, MAX_PAGES + 1):
                time.sleep(REQUEST_DELAY)
                try:
                    resp = client.get(LIST_URL.format(page=page))
                    resp.raise_for_status()
                    # Site uses ISO-8859-1 — encode response bytes explicitly
                    html = resp.content.decode("iso-8859-1", errors="replace")
                except Exception as e:
                    print(f"[nexo] page {page} failed: {e}")
                    break

                stubs = _parse_listing_page(html)
                if not stubs:
                    break

                for stub in stubs:
                    if len(out) >= limit:
                        break
                    sid = stub["source_id"]
                    if sid in seen:
                        continue
                    seen.add(sid)

                    # Fetch detail page
                    time.sleep(REQUEST_DELAY)
                    try:
                        dr = client.get(stub["url"])
                        dr.raise_for_status()
                        detail_html = dr.content.decode("iso-8859-1", errors="replace")
                        rec = _parse_detail_page(detail_html, stub)
                    except Exception as e:
                        print(f"[nexo] detail failed {sid}: {e}")
                        rec = stub

                    if rec:
                        rec["source"] = self.slug
                        rec["scraped_at"] = datetime.now(timezone.utc).isoformat()
                        out.append(rec)

                if len(out) >= limit:
                    break

            return out
        finally:
            client.close()

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None  # noqa: ARG002
    ) -> dict:
        records = self.crawl(limit, offline)
        return {"records": records, "max_pages_hit": False, "limit_hit": len(records) >= limit}


_scraper = NexoScraper()
register(SOURCES, "nexo", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return NexoScraper(offline=offline).crawl(limit)
