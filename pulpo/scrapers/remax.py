"""
RE/MAX El Salvador scraper.

Site: https://www.remax-elsalvador.com/
Stack: Server-rendered HTML with POST-based AJAX pagination. The search
endpoint returns JSON {"ModelString": "<html>…</html>"} with 52 listing
cards per page. Pagination requires a session CSRF token obtained from the
index page GET, so we open one session per crawl.

Filters: propertyTypeID maps to property type, ContractTypeID=1 (For sale).
PROP_TYPE_IDS_TO_FETCH covers land, houses, and condos.

Data locations:
  index card  → title, price_usd, detail URL
  detail page → area (li "Tamaño de lote:" > span.det), description, type
                fields (bedrooms, bathrooms, built area, parking) for
                house/condo via labelled <li> entries.
"""
from __future__ import annotations
import re
import time
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import (
    HTTPX_OK, SELECTOLAX_OK, is_offline, load_fixtures, make_client,
    DEFAULT_REQUEST_DELAY as REQUEST_DELAY,
)
from pulpo.agents import SOURCES, register
from pulpo.scrapers._type_classifier import classify_property_type
from automation.property_types import VACATION_ZONES, WATERFRONT_KEYWORDS

if HTTPX_OK:
    import httpx  # noqa: F401
if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser

BASE_URL   = "https://www.remax-elsalvador.com"
LIST_PATH  = "/showing-properties-in/el-salvador/for-sale/newest-listings"
CONTRACT   = "1"   # For sale
MAX_PAGES  = 50
FIXTURE_FILE = "sample_listings.json"

# RE/MAX propertyTypeID → canonical property_type. Audited live 2026-05-06:
#   1 = Casa/Villa     (~150-300 listings, mostly inland; coastal filter
#                       drops most)
#   2 = Apto/Condominio(~18 listings, almost all in San Salvador / Santa
#                       Tecla towers; very few coastal)
#   3 = Lote/Terreno   (~313 listings, current scraper, unchanged)
#   4 = Mixed (Rancho/Quinta/Casa/Bodega) — heterogeneous, SKIPPED for now
#   5 = empty
PROP_TYPE_IDS_TO_FETCH: list[tuple[str, str]] = [
    ("3", "land"),
    ("1", "house"),
    ("2", "condo"),
]
# Backwards-compat alias — the existing offline tests + calibration scripts
# still import PROP_TYPE expecting the land ID.
PROP_TYPE = "3"

# Compiled waterfront-keyword fallback for the vacation-zone filter on
# house/condo. "Waterfront" covers ocean coast + lake (PR #161, 2026-05-08).
_WATERFRONT_RE = re.compile("|".join(WATERFRONT_KEYWORDS), re.IGNORECASE)

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


def _post_page(client, tokens: dict, page: int, property_type_id: str = PROP_TYPE) -> str:
    """Return ModelString HTML for one page of listings of the given type.

    property_type_id defaults to PROP_TYPE (land) for backwards compat with
    callers that don't pass it explicitly.
    """
    r = client.post(
        BASE_URL + LIST_PATH,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
        },
        data={
            **tokens,
            "page": str(page),
            "propertyTypeID": property_type_id,
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


def _li_dets(tree) -> dict:
    """Map labelled <li> entries to their <span class="det"> values.

    The detail page exposes structured fields as <li>{Label}: <span
    class="det">{Value}</span></li>. Returns {label: value} dict with
    labels normalised (no trailing colon, stripped). Used by
    _parse_detail to look up bedrooms / bathrooms / built area / etc.
    in one pass.
    """
    out: dict[str, str] = {}
    for li in tree.css("li"):
        det = li.css_first("span.det")
        if det:
            value = det.text(strip=True)
            # Strip the value substring + colon to recover the label
            label = li.text(strip=True).replace(value, "").strip(" :")
            if label:
                out[label] = value
    return out


def _parse_area_value_unit(s: str) -> tuple[Optional[float], str]:
    """Parse '290.50 Sq. Mt.' or '66.96 Sq. Vr.' → (value, 'm2'|'v2').

    Returns (None, '') if no parseable number, OR if the value parses to 0.
    Many remax listings have placeholder '0.00 Sq. Vr.' which is the broker's
    way of saying 'unknown' — treat as missing rather than 'zero size'.
    """
    if not s:
        return (None, "")
    m = _AREA_RE.search(s)
    if not m:
        return (None, "")
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return (None, "")
    if v == 0:
        return (None, "")
    unit = "v2" if m.group(2).lower().startswith("vr") else "m2"
    return (v, unit)


def _parse_detail(html: str, partial: dict) -> Optional[dict]:
    """Extract area, description, and type-specific fields from a detail page."""
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

    # One pass over <li><span class="det"></span></li> for all structured fields
    dets = _li_dets(tree)

    # Lot area (the area_m2 field for land + house). Prefer the structured
    # value over the legacy `for li in tree.css("li")` walk — same data
    # source, terser code path.
    raw_size = ""
    lot_str = dets.get("Tamaño de lote") or dets.get("Lot size") or ""
    lot_val, lot_unit = _parse_area_value_unit(lot_str)
    if lot_val:
        raw_size = f"{lot_val} {lot_unit}"

    # Description — multi-tier extraction. The original `section p` selector
    # works on a minority of pages (~26% in 2026-05-03 prod); the remaining
    # listings hide the description elsewhere. Tier order is:
    #   1. embedded `"description":"..."` JSON property (~74% of pages)
    #   2. og:description meta tag (cleaned of HTML entities)
    #   3. `section p` legacy selector (kept for backward compat)
    description = ""
    json_desc_match = re.search(
        r'"description"\s*:\s*"((?:[^"\\]|\\.){40,4000})"', html
    )
    if json_desc_match:
        import json as _json
        try:
            description = _json.loads(f'"{json_desc_match.group(1)}"')
            description = description.replace("\r", " ").replace("\n", " ").strip()[:1500]
        except _json.JSONDecodeError:
            description = json_desc_match.group(1).strip()[:1500]
    if not description:
        og_match = re.search(
            r'<meta\s+[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']{40,2000})["\']',
            html, re.IGNORECASE,
        )
        if og_match:
            description = (og_match.group(1)
                           .replace("&quot;", '"').replace("&#039;", "'")
                           .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                           .strip()[:1500])
    if not description:
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

    # Property type — preferred source is the explicit list-page POST tag
    # (partial['_source_property_type']). If absent (e.g. calibration call)
    # fall back to inferring from the "Tipo de Propiedad" detail field.
    explicit_type = partial.get("_source_property_type")
    if explicit_type in ("land", "house", "condo"):
        broker_type = explicit_type
    else:
        tipo = (dets.get("Tipo de Propiedad") or "").strip().lower()
        if tipo.startswith(("casa", "villa", "house")):
            broker_type = "house"
        elif tipo.startswith(("apto", "apartamento", "condominio", "condo")):
            broker_type = "condo"
        else:
            broker_type = "land"  # default for terreno/lote

    rec: dict = {
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
        "property_type": broker_type,
        "photo_urls": photo_urls,
    }

    # Type-specific fields — house + condo only. Same Optional treatment
    # as bienesraices: missing fields silently absent rather than 0/None
    # values that would falsely tip validation. The "0.00 Sq. Vr." placeholder
    # is filtered to None by _parse_area_value_unit.
    if broker_type in ("house", "condo"):
        # Bedrooms / bathrooms / parking
        try:
            beds = dets.get("Habitaciones") or dets.get("Bedrooms") or ""
            if beds.strip():
                rec["bedrooms"] = int(re.sub(r"\D", "", beds) or 0) or None
                if rec["bedrooms"] is None:
                    rec.pop("bedrooms", None)
        except (ValueError, TypeError):
            pass
        try:
            baths = dets.get("Baños") or dets.get("Bathrooms") or ""
            if baths.strip():
                # Some listings show "2.5" — preserve halves
                rec["bathrooms"] = float(re.search(r"[\d.]+", baths).group(0))
        except (AttributeError, ValueError, TypeError):
            pass
        try:
            park = dets.get("Espacios para vehículo") or dets.get("Parking") or ""
            if park.strip():
                rec["parking_spaces"] = int(re.sub(r"\D", "", park) or 0) or None
                if rec["parking_spaces"] is None:
                    rec.pop("parking_spaces", None)
        except (ValueError, TypeError):
            pass
        # Built area — use whichever unit parses out. Conversion to m² happens
        # downstream in normalize.py (parses raw_size_text via the units module).
        # We carry the m² value directly when it's m²; v² values get converted
        # here so built_area_m2 is always m² as the field name promises.
        built_str = dets.get("Tamaño de Construcción") or dets.get("Building size") or ""
        bv, bu = _parse_area_value_unit(built_str)
        if bv:
            # 1 v² = 0.6987 m² (standard El Salvador conversion).
            rec["built_area_m2"] = round(bv * 0.6987, 2) if bu == "v2" else bv

    # Vacation-zone filter — house/condo dropped unless its location string
    # matches VACATION_ZONES (ocean coast OR lake) OR title/description
    # carries a waterfront keyword. Land is exempt (inland lots stay).
    if broker_type in ("house", "condo"):
        loc_blob = (rec.get("location_text") or "").lower().replace(" ", "-")
        zone_is_vacation = any(z in loc_blob for z in VACATION_ZONES)
        text_blob = f"{title}\n{description}"
        has_waterfront_kw = bool(_WATERFRONT_RE.search(text_blob))
        if not zone_is_vacation and not has_waterfront_kw:
            return None

    # Multi-signal classifier — confirms broker_type, surfaces signals for
    # the shadow log, FLAGS the listing if classifier disagrees with the
    # broker's structured type field.
    ptype, signals, confidence, total = classify_property_type({
        "broker_type_field": dets.get("Tipo de Propiedad", ""),
        "url":               partial["url"],
        "photo_urls":        photo_urls,
        "title":             title,
        "description":       description,
    }, fallback_type=broker_type)
    rec["_type_signals"]    = [s.to_dict() for s in signals]
    rec["_type_confidence"] = confidence
    rec["_type_total"]      = total
    if ptype != broker_type:
        rec["validation_status"] = "flagged"
        rec.setdefault("validation_warnings", []).append("type_classifier_disagree")

    return rec


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

            # Iterate the property-type IDs in priority order. Land first
            # (largest pool, biggest single-source contributor); houses +
            # condos appended after. The seen set is shared across types
            # so an ID that appears in multiple categories (rare) doesn't
            # get duplicated.
            for type_id, ptype_label in PROP_TYPE_IDS_TO_FETCH:
                if len(out) >= limit:
                    break
                for page in range(1, MAX_PAGES + 1):
                    if len(out) >= limit:
                        break
                    time.sleep(REQUEST_DELAY)
                    try:
                        html = _post_page(client, tokens, page, type_id)
                    except Exception as e:
                        print(f"[remax] type={ptype_label} page {page} fetch failed: {e}")
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
                        # Tag the partial with the type the list-page POST
                        # was filtered by. _parse_detail prefers this over
                        # inferring from the detail page (more reliable).
                        p["_source_property_type"] = ptype_label

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

                    if not new_this_page:
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
