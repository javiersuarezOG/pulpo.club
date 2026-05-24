"""
CityMax El Salvador scraper.

Site: https://www.citymax-sv.com/
Stack: Next.js 14 SPA (App Router) backed by the O'Brien CRM
(api.obriencrm.com/v1/Website2/). Office id 1600.

Why SSR-parse and not the API
-----------------------------
The page at ``/inmuebles/venta?page=N`` is server-rendered: the React
Server Components payload embedded in ``self.__next_f.push([1, "..."])``
script tags contains the FULL listing array, 12 per page, with every
field we need (title, slug, price, area, lat/lng, photos, broker,
group label, type id). No API discovery, no auth, no SPA execution
required — just GET the page and parse the embedded JSON. This is the
same pattern bienesraices uses for AlterEstate-backed sites.

The chunk-bundle reconnaissance found ``/latestProperties``,
``/listPropertyTypes``, ``/listProjectTypes``, ``/listSimilarProperties``,
``/suggestSearchAddress`` on api.obriencrm.com — but no public
``/searchProperties`` endpoint. Going SSR-side avoids reverse-engineering
a private API.

Niche filter
------------
Per the new-sources brief, CityMax is filtered to the Pacific coast +
Lake Coatepeque + Lake Ilopango for ALL property types, not just
house/condo. The 25-page reconnaissance found:

  total 300 listings  → ~20 in-niche (7%): ilopango, coatepeque,
                         tunco, sunzal, zonte, costa-del-sol,
                         conchagua, san-blas

Without the force-gate on land, the scraper would flood ranked.json
with San Salvador / Cojutepeque parcels that are off-scope. Hence
``force_vacation_gate=True`` in the finalize_record call.

Type ID map (parm_tipoInmueble)
-------------------------------
Sampled across pages 1-25 (2026-05-25):

  4  → land   (Terreno Residencial, n=100)
  9  → land   (Terreno Comercial, n=28)
  17 → land   (Terreno Vacacional, n=12)
  19 → land   (Finca, n=11)  — agricultural purge handles downstream
  2  → condo  (Apartamento Residencial, n=38)
  1  → house  (Casa Sola Residencial, n=30)
  5  → house  (Casa en Condominio Residencial, n=34)
  10 → house  (Casa con Uso de Suelo Comercial, n=21)
  16 → house  (Villa y Quinta Amueblada, n=1)

Skipped (out-of-scope commercial/industrial):
  7 Edificio Comercial, 12 Bodegas, 6 Local Comercial, 8 Oficina,
  13 Terreno en Parque Industrial
"""
from __future__ import annotations
import codecs
import json
import re
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import HTTPX_OK, make_client
from pulpo.agents import SOURCES, register
from pulpo.scrapers._base import OfflineFixtureMixin, finalize_record, polite_get_for

if HTTPX_OK:
    import httpx  # noqa: F401

BASE_URL    = "https://www.citymax-sv.com"
LIST_PATH   = "/inmuebles/venta"
DETAIL_PATH = "/inmuebles"   # detail URL: /inmuebles/<slug>
MAX_PAGES   = 50              # 50 × 12 = 600 listings worst-case
FIXTURE_FILE = "sample_listings.json"

# parm_tipoInmueble → canonical Pulpo property_type. Types not listed
# (commercial / industrial / offices) are dropped at parse time.
_TYPE_ID_TO_PULPO: dict[int, str] = {
    1:  "house",
    2:  "condo",
    4:  "land",
    5:  "house",
    9:  "land",
    10: "house",
    16: "house",
    17: "land",
    19: "land",  # finca — downstream is_agricultural purge handles it
}

# Flight-payload tag the SSR data is embedded in.
_FLIGHT_RE = re.compile(r'self\.__next_f\.push\(\[1,"([\s\S]*?)"\]\)')


def _extract_listings(html: str) -> list[dict]:
    """Parse the SSR Flight payload and return the listings array.

    The /inmuebles/venta page emits ~17 ``self.__next_f.push`` script
    tags; the listing data lives in the largest one as a JSON-encoded
    React Server Components blob. We decode the unicode escapes, find
    the ``"properties":[...]`` array, then return each element parsed
    via brace-matching (the inner JSON includes nested arrays that
    would defeat a naive split).
    """
    chunks = _FLIGHT_RE.findall(html)
    if not chunks:
        return []
    big = max(chunks, key=len)
    try:
        s = codecs.decode(big, "unicode_escape")
    except UnicodeDecodeError:
        return []

    out: list[dict] = []
    for m in re.finditer(r'"idInmueble":(\d+)', s):
        p = m.start()
        # Walk backwards to the enclosing '{'
        depth = 0
        start = p
        for i in range(p, max(0, p - 6000), -1):
            if s[i] == '}':
                depth += 1
            elif s[i] == '{':
                if depth == 0:
                    start = i
                    break
                depth -= 1
        # Walk forwards to the matching '}'
        depth = 1
        end = p
        for j in range(start + 1, min(len(s), start + 12000)):
            if s[j] == '{':
                depth += 1
            elif s[j] == '}':
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        try:
            rec = json.loads(s[start:end])
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("idInmueble"):
            out.append(rec)
    return out


def _parse_latlng(s: str) -> tuple[Optional[float], Optional[float]]:
    """ubicacionMaps is "lat,lng" with possible whitespace."""
    if not s:
        return (None, None)
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 2:
        return (None, None)
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return (None, None)


def _map(rec: dict) -> Optional[dict]:
    """Map one CityMax listing record to the Pulpo raw-dict shape.

    Returns None if the listing's type is out-of-scope, or if the niche
    filter (applied in finalize_record with force_vacation_gate=True)
    drops it.
    """
    tid = rec.get("parm_tipoinmueble_idparm_tipoInmueble")
    broker_type = _TYPE_ID_TO_PULPO.get(int(tid) if tid is not None else -1)
    if broker_type is None:
        return None

    # operation=1 is sale (operation=2 would be rent — drop rentals).
    if rec.get("parm_tipooperacion_idparm_tipoOperacion") != 1:
        return None

    title = (rec.get("nombreInmueble") or "").strip()
    if not title:
        return None

    slug = (rec.get("slug") or "").strip()
    url  = f"{BASE_URL}{DETAIL_PATH}/{slug}" if slug else f"{BASE_URL}{LIST_PATH}"

    price = rec.get("precioVenta") or 0
    raw_price_text = f"{rec.get('monedaVenta', 'USD')} {price}" if price else ""

    area_terr = rec.get("areaTerreno") or 0
    unit_terr = (rec.get("unidadTerreno") or "m2").lower()
    raw_size_text = f"{area_terr} {unit_terr}" if area_terr else ""

    # Location: localidad > municipio > provincia. Append El Salvador for
    # downstream zone detection.
    loc_parts = [p for p in [
        rec.get("localidad") or "",
        rec.get("municipio") or "",
        rec.get("provincia") or "",
        "El Salvador",
    ] if p]
    location_text = ", ".join(loc_parts)

    # Photos: imagenPortada is the hero; imagenesGaleria is the full set
    # (and usually already includes the portada as the first element).
    photo_urls: list[str] = []
    seen: set[str] = set()
    for u in [rec.get("imagenPortada") or ""] + list(rec.get("imagenesGaleria") or []):
        if isinstance(u, str) and u.startswith("http") and u not in seen:
            seen.add(u)
            photo_urls.append(u)

    lat, lng = _parse_latlng(rec.get("ubicacionMaps") or "")

    record: dict = {
        "source":         "citymax",
        "source_id":      str(rec.get("idInmueble") or rec.get("claveInterna") or ""),
        "url":            url,
        "title":          title,
        "price_usd":      float(price) if price else None,
        "raw_price_text": raw_price_text,
        "raw_size_text":  raw_size_text,
        "location_text":  location_text,
        "description":    "",  # not in list payload; detail-page fetch is a follow-up
        "property_type":  broker_type,
        "photo_urls":     photo_urls,
        "broker_name":    (rec.get("ejecutivoAsociadoNombre") or "").strip(),
        "scraped_at":     datetime.now(timezone.utc).isoformat(),
    }
    if lat is not None and lng is not None:
        record["lat"] = lat
        record["lng"] = lng

    # Type-specific fields for house / condo.
    if broker_type in ("house", "condo"):
        if rec.get("areaConstruccion"):
            try:
                v = float(rec["areaConstruccion"])
                if v > 0:
                    record["built_area_m2"] = v
            except (TypeError, ValueError):
                pass
        if rec.get("nroHabitaciones"):
            try:
                n = int(rec["nroHabitaciones"])
                if n > 0:
                    record["bedrooms"] = n
            except (TypeError, ValueError):
                pass
        full_baths = int(rec.get("nroBanios") or 0)
        half_baths = int(rec.get("nroMediobanios") or 0)
        if full_baths or half_baths:
            record["bathrooms"] = float(full_baths) + 0.5 * float(half_baths)
        if rec.get("nroEstacionamientos"):
            try:
                n = int(rec["nroEstacionamientos"])
                if n > 0:
                    record["parking_spaces"] = n
            except (TypeError, ValueError):
                pass

    # Apply finalize_record with force_vacation_gate=True so the niche
    # filter (Pacific coast + Coatepeque + Ilopango) applies to LAND as
    # well as house/condo. CityMax is inland-dominant; without the
    # force-gate we'd ship hundreds of San Salvador terrenos.
    return finalize_record(
        record, slug="citymax",
        broker_type=broker_type,
        broker_type_field=rec.get("grupoInmueble") or "",
        force_vacation_gate=True,
    )


class CityMaxScraper(OfflineFixtureMixin):
    slug = "citymax"

    def __init__(self, offline: bool | None = None):
        self.offline = offline

    def report_total(self, client) -> Optional[int]:
        """No total-count signal in the SSR payload. Skip."""
        return None

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        return self.crawl_with_meta(limit, offline)["records"]

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None,
    ) -> dict:
        fix = self._offline_or_fixtures(limit, override_offline=offline)
        if fix is not None:
            return {"records": fix, "max_pages_hit": False, "limit_hit": len(fix) >= limit}

        client = make_client()
        get = polite_get_for(self.slug)
        page_cap = max_pages if max_pages is not None else MAX_PAGES
        out: list[dict] = []
        seen_ids: set[str] = set()
        max_pages_hit = False
        limit_hit = False
        try:
            for page in range(1, page_cap + 1):
                if len(out) >= limit:
                    limit_hit = True
                    break
                url = f"{BASE_URL}{LIST_PATH}?page={page}"
                try:
                    resp = get(client, url)
                    resp.raise_for_status()
                except Exception as e:
                    print(f"[{self.slug}] page {page} fetch failed: {e}")
                    break

                raw = _extract_listings(resp.text)
                if not raw:
                    break

                new_this_page = False
                for rec in raw:
                    if len(out) >= limit:
                        limit_hit = True
                        break
                    sid = str(rec.get("idInmueble") or "")
                    if not sid or sid in seen_ids:
                        continue
                    seen_ids.add(sid)
                    mapped = _map(rec)
                    if mapped is not None:
                        out.append(mapped)
                        new_this_page = True

                if not new_this_page and limit_hit is False:
                    # Page fetched fine but every record was either dupe or
                    # filtered. Keep paging — niche listings are sparse
                    # (~7% of total) so a single empty page is not the end.
                    continue

                if page >= page_cap:
                    max_pages_hit = True
        finally:
            client.close()
        return {"records": out, "max_pages_hit": max_pages_hit, "limit_hit": limit_hit}

    # Kept for calibration harness compatibility.
    def parse_index_page(self, html: str) -> list[dict]:
        return _extract_listings(html)

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:  # noqa: ARG002
        return None


_scraper = CityMaxScraper()
register(SOURCES, "citymax", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return CityMaxScraper(offline=offline).crawl(limit)
