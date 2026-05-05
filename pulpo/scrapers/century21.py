"""
Century 21 El Salvador scraper.

Site: https://www.century21elsalvador.com/
Stack: WordPress + OmniMLS widget (mx.omnimls.com). The results page
embeds most listing data as JSON in window.REP_LOG_APP_PROPS.data.results,
covering price, area, location, broker contact, URL — but NOT description.
Per-listing detail page fetches are required to populate `description`,
which downstream NLP and AI rely on (Phase 0 fix per PRD WS2 feasibility).

Land-type filter keeps: lote_residencial, finca, propiedad_de_desarrollo,
terreno, lote, tierra, rancho, hacienda, lote_comercial.
"""
from __future__ import annotations
import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import HTTPX_OK, is_offline, load_fixtures, make_client, with_retries, DEFAULT_REQUEST_DELAY
from pulpo.agents import SOURCES, register

if HTTPX_OK:
    import httpx  # noqa: F401


# Description extractors — tried in order, first hit wins.
# 1. og:description meta tag (HTML-decoded, present on every property page)
# 2. "descripcion": "..." JSON property in the embedded REP_LOG_APP_PROPS blob
_RX_OG_DESC      = re.compile(
    r'<meta\s+[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']{20,2000})["\']',
    re.IGNORECASE,
)
_RX_JSON_DESC    = re.compile(r'"descripcion"\s*:\s*"((?:[^"\\]|\\.){20,4000})"')


def _extract_description(html: str) -> str:
    """Pull a description out of a c21 detail page. Empty string if neither path hits."""
    m = _RX_OG_DESC.search(html)
    if m:
        # Decode common HTML entities that ride in og: meta tags
        text = (m.group(1)
                .replace("&quot;", '"').replace("&#039;", "'")
                .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
        return text.strip()[:2000]
    m = _RX_JSON_DESC.search(html)
    if m:
        # Decode JSON escapes (\\u00f3 → ó, \\r → space, \\n → space)
        try:
            return json.loads(f'"{m.group(1)}"').replace("\r", " ").replace("\n", " ").strip()[:2000]
        except json.JSONDecodeError:
            return m.group(1).strip()[:2000]
    return ""

BASE = "https://www.century21elsalvador.com"
RESULTS_URL = f"{BASE}/v/resultados/oficina_4942-century-21-el-salvador_local"

LAND_TYPES = {
    "lote_residencial", "lote_comercial", "lote",
    "terreno", "tierra",
    "finca", "rancho", "hacienda",
    "propiedad_de_desarrollo",
}


def _extract_results(html: str) -> list[dict]:
    """Pull the results array out of window.REP_LOG_APP_PROPS embedded JSON."""
    idx = html.find('"results"')
    if idx < 0:
        return []
    arr_start = html.find('[', idx)
    if arr_start < 0:
        return []
    depth = 0
    pos = arr_start
    while pos < len(html):
        c = html[pos]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                break
        pos += 1
    try:
        return json.loads(html[arr_start:pos + 1])
    except json.JSONDecodeError:
        return []


class Century21Scraper:
    slug = "century21"
    FIXTURE_FILE = "sample_listings.json"

    def __init__(self, offline: bool | None = None):
        self.offline = offline
        # PULPO_REQUEST_DELAY env var honoured by DEFAULT_REQUEST_DELAY (html_crawler).
        self.REQUEST_DELAY = DEFAULT_REQUEST_DELAY

    def report_total(self, client) -> Optional[int]:
        """Count land-type listings from the embedded OmniMLS JSON."""
        try:
            resp = with_retries(lambda: client.get(RESULTS_URL))
            resp.raise_for_status()
            raw = _extract_results(resp.text)
            return sum(1 for r in raw if r.get("tipoPropiedad") in LAND_TYPES)
        except Exception:
            return None

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, self.FIXTURE_FILE, limit)
        client = make_client()
        try:
            time.sleep(self.REQUEST_DELAY)
            try:
                resp = with_retries(lambda: client.get(RESULTS_URL))
                resp.raise_for_status()
            except Exception as e:
                print(f"[{self.slug}] fetch failed: {e}")
                return []

            raw_results = _extract_results(resp.text)
            out = []
            for rec in raw_results:
                if rec.get("tipoPropiedad") not in LAND_TYPES:
                    continue
                mapped = self._map(rec)
                if not mapped:
                    continue

                # Phase 0: fetch detail page to populate description.
                # The OmniMLS results blob has 91 fields but no description —
                # description lives on the property detail page only.
                # Cost: ~1 HTTP request per listing × ~15 listings × 1.5s = ~22s
                # overhead per nightly run. Worth it: c21 today ships 100% empty
                # descriptions which kills downstream NLP + AI quality.
                if mapped.get("url"):
                    try:
                        time.sleep(self.REQUEST_DELAY)
                        dresp = with_retries(lambda: client.get(mapped["url"]))
                        if dresp.status_code == 200:
                            mapped["description"] = _extract_description(dresp.text)
                        else:
                            print(f"[{self.slug}] detail {mapped['source_id']} "
                                  f"returned HTTP {dresp.status_code}")
                    except Exception as e:
                        # Non-fatal: keep the listing with empty description rather
                        # than dropping it entirely.
                        print(f"[{self.slug}] detail fetch failed "
                              f"{mapped['source_id']}: {e}")

                out.append(mapped)
                if len(out) >= limit:
                    break
            return out
        finally:
            client.close()

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None  # noqa: ARG002
    ) -> dict:
        """Single-fetch source — max_pages does not apply."""
        records = self.crawl(limit, offline)
        return {"records": records, "max_pages_hit": False, "limit_hit": len(records) >= limit}

    def _map(self, rec: dict) -> Optional[dict]:
        title = rec.get("encabezado") or ""
        if not title:
            return None

        price = rec.get("precio")
        area_m2 = rec.get("m2T") or None

        municipio = rec.get("municipio") or ""
        estado = rec.get("estado") or ""
        calle = rec.get("calle") or ""
        location_parts = [p for p in [calle, municipio, estado, "El Salvador"] if p]
        location_text = ", ".join(location_parts)

        url_path = rec.get("urlCorrectaPropiedad") or ""
        url = (BASE + url_path) if url_path else ""

        broker_name = rec.get("asesorNombre") or rec.get("nombreAfiliado") or ""
        broker_phone = rec.get("whatsapp") or rec.get("telefono") or ""
        broker_email = rec.get("email") or ""

        # Photos — OmniMLS typically stores them under 'fotos' (list of URL strings)
        photo_urls: list[str] = []
        for item in (rec.get("fotos") or rec.get("photos") or rec.get("imagenes") or []):
            if isinstance(item, str) and item.startswith("http"):
                photo_urls.append(item)
            elif isinstance(item, dict):
                u = item.get("url") or item.get("src") or ""
                if u.startswith("http"):
                    photo_urls.append(u)

        return {
            "source": self.slug,
            "source_id": str(rec.get("id") or ""),
            "url": url,
            "title": title.strip(),
            "price_usd": float(price) if price else None,
            "raw_price_text": f"{price} {rec.get('moneda', 'USD')}" if price else "",
            "raw_size_text": f"{area_m2} m2" if area_m2 else "",
            "location_text": location_text,
            "description": "",
            "property_type": "land",
            "photo_urls": photo_urls,
            "broker_name": broker_name.strip(),
            "broker_phone": broker_phone.strip(),
            "broker_email": broker_email.strip(),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def parse_index_page(self, html: str) -> list[dict]:
        return []

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        return None


_scraper = Century21Scraper(offline=None)
register(SOURCES, "century21", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return Century21Scraper(offline=offline).crawl(limit)
