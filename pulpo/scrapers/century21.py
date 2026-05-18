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
from pulpo.scrapers._type_classifier import classify_property_type
from pulpo.scrapers._photo_url_upgrade import upgrade_photo_urls
from automation.property_types import VACATION_ZONES, WATERFRONT_KEYWORDS

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
HOUSE_TYPES = {"casa", "villa", "residencia", "chalet"}
CONDO_TYPES = {"apartamento", "departamento", "condominio", "loft"}

# tipoPropiedad → canonical property_type. Audited live 2026-05-06: results
# spread on the office's listing endpoint includes 8× casa, 8× lote_residencial,
# 5× finca, 3× local (skip), 2× propiedad_de_desarrollo, 1× restaurante_bar (skip).
# No apartamento on the current page but condo branch is wired for when one
# appears.
def _broker_type_for(tipo: str) -> Optional[str]:
    if not tipo:
        return None
    t = tipo.lower()
    if t in LAND_TYPES:
        return "land"
    if t in HOUSE_TYPES:
        return "house"
    if t in CONDO_TYPES:
        return "condo"
    return None


# Compiled waterfront-keyword fallback for the vacation-zone filter on
# house/condo. "Waterfront" covers ocean coast + lake (PR #161, 2026-05-08).
_WATERFRONT_RE = re.compile("|".join(WATERFRONT_KEYWORDS), re.IGNORECASE)


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
        """Count relevant listings (land + house + condo) from the embedded OmniMLS JSON."""
        try:
            resp = with_retries(lambda: client.get(RESULTS_URL))
            resp.raise_for_status()
            raw = _extract_results(resp.text)
            return sum(1 for r in raw if _broker_type_for(r.get("tipoPropiedad")) is not None)
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
                broker_type = _broker_type_for(rec.get("tipoPropiedad"))
                if broker_type is None:
                    continue
                mapped = self._map(rec, broker_type=broker_type)
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

    def _map(self, rec: dict, broker_type: str = "land") -> Optional[dict]:
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

        # Photos — OmniMLS exposes them under fotos: a DICT (not a list) with
        # the schema: {totalFotos: int, propiedadThumbnail: [url, url, ...]}.
        # The list-of-strings shape was an early misread; iterating the dict
        # yielded its keys and silently produced zero photos.
        photo_urls: list[str] = []
        fotos = rec.get("fotos")
        if isinstance(fotos, dict):
            for u in fotos.get("propiedadThumbnail") or []:
                if isinstance(u, str) and u.startswith("http"):
                    photo_urls.append(u)
        elif isinstance(fotos, list):  # defensive: future schema change
            for item in fotos:
                if isinstance(item, str) and item.startswith("http"):
                    photo_urls.append(item)
                elif isinstance(item, dict):
                    u = item.get("url") or item.get("src") or ""
                    if u.startswith("http"):
                        photo_urls.append(u)
        photo_urls = upgrade_photo_urls("century21", photo_urls, payload=rec)

        rec_out: dict = {
            "source": self.slug,
            "source_id": str(rec.get("id") or ""),
            "url": url,
            "title": title.strip(),
            "price_usd": float(price) if price else None,
            "raw_price_text": f"{price} {rec.get('moneda', 'USD')}" if price else "",
            "raw_size_text": f"{area_m2} m2" if area_m2 else "",
            "location_text": location_text,
            "description": "",
            "property_type": broker_type,
            "photo_urls": photo_urls,
            "broker_name": broker_name.strip(),
            "broker_phone": broker_phone.strip(),
            "broker_email": broker_email.strip(),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

        # Type-specific fields — house/condo only. OmniMLS exposes these
        # consistently when present, in m² (the field comments confirm
        # m2T = total/lot, m2C = construction/built — both in metres²).
        if broker_type in ("house", "condo"):
            built = rec.get("m2C")
            if built and float(built) > 0:
                rec_out["built_area_m2"] = float(built)
            if rec.get("recamaras"):
                try:
                    rec_out["bedrooms"] = int(rec["recamaras"])
                except (TypeError, ValueError):
                    pass
            full_baths = rec.get("banos") or 0
            half_baths = rec.get("medioBanos") or 0
            if full_baths or half_baths:
                try:
                    rec_out["bathrooms"] = float(full_baths) + 0.5 * float(half_baths)
                except (TypeError, ValueError):
                    pass
            if rec.get("estacionamientos"):
                try:
                    rec_out["parking_spaces"] = int(rec["estacionamientos"])
                except (TypeError, ValueError):
                    pass
            if rec.get("antiguedad"):
                # antiguedad is years-old, not year-built. Skip — we'd need
                # current_year - antiguedad which can drift. Lock when the
                # field has a clearer semantic.
                pass
            # Mantenimiento string format observed: " + 210 mantenimiento".
            # Pull the first integer out.
            mant = rec.get("mantenimiento") or ""
            if isinstance(mant, str) and mant.strip():
                m = re.search(r"\d[\d,]*\.?\d*", mant)
                if m:
                    try:
                        rec_out["hoa_fee_usd_monthly"] = float(m.group(0).replace(",", ""))
                    except ValueError:
                        pass
            if broker_type == "condo" and rec.get("niveles"):
                try:
                    rec_out["floor"] = int(rec["niveles"])
                except (TypeError, ValueError):
                    pass

        # Vacation-zone filter for house/condo (land is exempt — inland
        # lots stay). Drops the listing unless its location matches a
        # known vacation zone (ocean coast or lake) or the title/desc
        # carries a waterfront keyword.
        if broker_type in ("house", "condo"):
            loc_blob = location_text.lower().replace(" ", "-")
            zone_is_vacation = any(z in loc_blob for z in VACATION_ZONES)
            text_blob = f"{title}\n{rec_out.get('description','')}"
            has_waterfront_kw = bool(_WATERFRONT_RE.search(text_blob))
            if not zone_is_vacation and not has_waterfront_kw:
                return None

        # Multi-signal classifier — confirms broker_type, surfaces signals
        # for the shadow log, FLAGS the listing if classifier disagrees.
        ptype, signals, confidence, total = classify_property_type({
            "broker_type_field": rec.get("tipoPropiedad", ""),
            "url":               url,
            "photo_urls":        photo_urls,
            "title":             title,
            "description":       rec_out.get("description", ""),
        }, fallback_type=broker_type)
        rec_out["_type_signals"]    = [s.to_dict() for s in signals]
        rec_out["_type_confidence"] = confidence
        rec_out["_type_total"]      = total
        if ptype != broker_type:
            rec_out["validation_status"] = "flagged"
            rec_out.setdefault("validation_warnings", []).append("type_classifier_disagree")

        return rec_out

    def parse_index_page(self, html: str) -> list[dict]:
        return []

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        return None


_scraper = Century21Scraper(offline=None)
register(SOURCES, "century21", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return Century21Scraper(offline=offline).crawl(limit)
