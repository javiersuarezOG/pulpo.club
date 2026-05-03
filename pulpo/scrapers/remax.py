"""
RE/MAX El Salvador scraper.

Site: https://www.remax-elsalvador.com/
Stack: Server-rendered HTML with POST-based AJAX pagination. The search
endpoint returns JSON {"ModelString": "<html>…</html>"} with 52 listing
cards per page. Pagination requires a session CSRF token obtained from the
index page GET, so we open one session per crawl.

Filter: propertyTypeID=3 (Lot/Land), ContractTypeID=1 (For sale).
313 land listings total as of 2026-05-02.

Data locations:
  index card  → title, price_usd, detail URL
  detail page → area (li "Lot size:" > span.det), description, confirm title
"""
from __future__ import annotations
import re
import time
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import (
    HTTPX_OK, SELECTOLAX_OK, is_offline, load_fixtures, make_client,
)
from pulpo.agents import SOURCES, register

if HTTPX_OK:
    import httpx  # noqa: F401
if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser

BASE_URL   = "https://www.remax-elsalvador.com"
LIST_PATH  = "/showing-properties-in/el-salvador/for-sale/newest-listings"
PROP_TYPE  = "3"   # Lot/Land
CONTRACT   = "1"   # For sale
REQUEST_DELAY = 1.5
MAX_PAGES  = 50
FIXTURE_FILE = "sample_listings.json"

_TOKEN_FIELDS = ("__RequestVerificationToken", "ax", "bx", "cx", "dx")

# Area: "1,807.98 Sq. Vr." → "1807.98 v2" ; "246.00 Sq. Mt." → "246.00 m2"
_AREA_RE = re.compile(r"([\d,\.]+)\s*Sq\.?\s*(Vr|Mt)", re.I)
# Price: "USD $ 60,000.00" or "USD $60,000"
_PRICE_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def _get_tokens(client) -> dict:
    r = client.get(BASE_URL + LIST_PATH)
    r.raise_for_status()
    tree = HTMLParser(r.text)
    tokens = {}
    for k in _TOKEN_FIELDS:
        node = tree.css_first(f'input[name="{k}"]')
        if node:
            tokens[k] = node.attributes.get("value", "")
    return tokens


def _post_page(client, tokens: dict, page: int) -> str:
    """Return ModelString HTML for one page of land listings."""
    r = client.post(
        BASE_URL + LIST_PATH,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
        },
        data={
            **tokens,
            "page": str(page),
            "propertyTypeID": PROP_TYPE,
            "ContractTypeID": CONTRACT,
            "sortType": "1",
            "keyword": "",
            "minprice": "",
            "maxprice": "",
            "generalLocationID": "-1",
        },
    )
    r.raise_for_status()
    return r.json().get("ModelString", "")


def _parse_cards(html: str) -> list[dict]:
    """Extract partials from one page of index ModelString HTML."""
    if not SELECTOLAX_OK:
        return []
    tree = HTMLParser(html)
    out = []
    for card in tree.css("div.item"):
        link = card.css_first("a.recent-16")
        if not link:
            continue
        href = link.attributes.get("href", "").strip()
        if not href:
            continue
        # Title lives in recent-details before "USD $"
        det_el = card.css_first("div.recent-details")
        det_text = det_el.text(strip=True) if det_el else ""
        title = re.split(r"USD\s*\$|\$\s*\d", det_text)[0].strip()
        # Price from dedicated element
        price_el = card.css_first("div.recent-price")
        raw_price = price_el.text(strip=True) if price_el else ""
        price_usd: Optional[float] = None
        m = _PRICE_RE.search(raw_price.replace(",", ""))
        if m:
            try:
                price_usd = float(m.group(0))
            except ValueError:
                pass
        out.append({
            "url": BASE_URL + href,
            "source_id": href.strip("/"),
            "title": title,
            "price_usd": price_usd,
            "raw_price_text": raw_price,
        })
    return out


def _parse_detail(html: str, partial: dict) -> Optional[dict]:
    """Extract area and description from a detail page."""
    if not SELECTOLAX_OK:
        return None
    tree = HTMLParser(html)

    # Title: h3 ends with ".For Sale" (EN) or ".En Venta" (ES) — strip either
    title = partial.get("title", "")
    h3 = tree.css_first("h3")
    if h3:
        raw = re.sub(
            r"\.\s*(?:For\s+Sale|En\s+Venta|For\s+Lease|En\s+Renta)\s*$",
            "", h3.text(strip=True), flags=re.I,
        ).strip()
        if raw:
            title = raw

    # Area: li with "Lot size:" (EN) or "Tamaño de lote:" (ES) → span.det
    raw_size = ""
    for li in tree.css("li"):
        li_text = li.text(strip=True)
        if "Lot size:" in li_text or "Tamaño de lote:" in li_text:
            det = li.css_first("span.det")
            if det:
                m = _AREA_RE.search(det.text(strip=True))
                if m:
                    unit = "v2" if m.group(2).lower().startswith("vr") else "m2"
                    raw_size = f"{m.group(1).replace(',', '')} {unit}"
            break

    # Description: first <p> in main section
    desc_el = tree.css_first("section p")
    description = desc_el.text(strip=True)[:1500] if desc_el else ""

    # Photos — RE/MAX typically uses an image gallery with data-src lazy loading
    photo_urls: list[str] = []
    seen: set[str] = set()
    for img in tree.css(
        ".property-gallery img, .gallery img, .slider img, "
        "div[class*='gallery'] img, div[class*='photo'] img, "
        ".re-detail-gallery img"
    ):
        u = img.attributes.get("data-src") or img.attributes.get("src") or ""
        if u.startswith("http") and u not in seen:
            seen.add(u)
            photo_urls.append(u)
    if not photo_urls:
        og = tree.css_first('meta[property="og:image"]')
        if og:
            u = og.attributes.get("content") or ""
            if u.startswith("http"):
                photo_urls.append(u)

    if not title:
        return None

    return {
        "source": "remax",
        "source_id": partial["source_id"],
        "url": partial["url"],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "price_usd": partial.get("price_usd"),
        "raw_price_text": partial.get("raw_price_text", ""),
        "raw_size_text": raw_size,
        "location_text": title,   # title always contains location (zone / city)
        "description": description,
        "property_type": "land",
        "photo_urls": photo_urls,
    }


class RemaxScraper:
    slug = "remax"

    def __init__(self, offline: bool | None = None):
        self.offline = offline

    def report_total(self, client) -> Optional[int]:
        """Return total land-for-sale listings from the POST API count field."""
        try:
            tokens = _get_tokens(client)
            time.sleep(REQUEST_DELAY)
            html = _post_page(client, tokens, 1)
            m = re.search(r"Total properties:\s*(\d+)", html)
            return int(m.group(1)) if m else None
        except Exception:
            return None

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        client = make_client()
        try:
            # One GET to establish session and get CSRF tokens
            time.sleep(REQUEST_DELAY)
            tokens = _get_tokens(client)

            out: list[dict] = []
            seen: set[str] = set()

            for page in range(1, MAX_PAGES + 1):
                time.sleep(REQUEST_DELAY)
                try:
                    html = _post_page(client, tokens, page)
                except Exception as e:
                    print(f"[remax] page {page} fetch failed: {e}")
                    break

                partials = _parse_cards(html)
                if not partials:
                    break

                new_this_page = False
                for p in partials:
                    if len(out) >= limit:
                        break
                    sid = p["source_id"]
                    if sid in seen:
                        continue
                    seen.add(sid)
                    new_this_page = True

                    time.sleep(REQUEST_DELAY)
                    try:
                        dr = client.get(p["url"])
                        dr.raise_for_status()
                    except Exception as e:
                        print(f"[remax] detail failed {sid}: {e}")
                        continue

                    rec = _parse_detail(dr.text, p)
                    if rec:
                        out.append(rec)

                if not new_this_page or len(out) >= limit:
                    break

            return out
        finally:
            client.close()

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None  # noqa: ARG002
    ) -> dict:
        records = self.crawl(limit, offline)
        return {"records": records, "max_pages_hit": False, "limit_hit": len(records) >= limit}

    # Kept for calibration harness compatibility
    def parse_index_page(self, html: str) -> list[dict]:
        return _parse_cards(html)

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        return _parse_detail(html, partial)


_scraper = RemaxScraper()
register(SOURCES, "remax", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return RemaxScraper(offline=offline).crawl(limit)
