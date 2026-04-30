"""
Century 21 El Salvador scraper.

Site: https://www.century21elsalvador.com/
Stack: WordPress + OmniMLS widget (mx.omnimls.com). The results page
embeds all listing data as JSON in window.REP_LOG_APP_PROPS.data.results,
so no per-listing detail requests are needed — all fields (price, area,
location, broker contact, URL) are present in a single fetch.

Land-type filter keeps: lote_residencial, finca, propiedad_de_desarrollo,
terreno, lote, tierra, rancho, hacienda, lote_comercial.
"""
from __future__ import annotations
import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

from .base import BaseScraper, HTTPX_OK

if HTTPX_OK:
    import httpx  # noqa: F401

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


class Century21Scraper(BaseScraper):
    SOURCE = "century21"
    BASE_URL = BASE
    LIST_URL = RESULTS_URL
    FIXTURE_FILE = "sample_listings.json"
    MAX_PAGES = 1  # all data is in a single embedded JSON blob

    def crawl(self, limit: int = 30) -> list[dict]:
        if self.offline:
            return self._load_fixtures(limit)
        time.sleep(self.REQUEST_DELAY)
        try:
            resp = self.client.get(RESULTS_URL)
            resp.raise_for_status()
        except Exception as e:
            print(f"[{self.SOURCE}] fetch failed: {e}")
            return []

        raw_results = _extract_results(resp.text)
        out = []
        for rec in raw_results:
            if rec.get("tipoPropiedad") not in LAND_TYPES:
                continue
            mapped = self._map(rec)
            if mapped:
                out.append(mapped)
            if len(out) >= limit:
                break
        return out

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

        return {
            "source": self.SOURCE,
            "source_id": str(rec.get("id") or ""),
            "url": url,
            "title": title.strip(),
            "raw_price_text": f"{price} {rec.get('moneda', 'USD')}" if price else "",
            "raw_size_text": f"{area_m2} m2" if area_m2 else "",
            "location_text": location_text,
            "description": "",
            "property_type": "land",
            "broker_name": broker_name.strip(),
            "broker_phone": broker_phone.strip(),
            "broker_email": broker_email.strip(),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def parse_index_page(self, html: str) -> list[dict]:
        return []

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        return None


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return Century21Scraper(offline=offline).crawl(limit)
