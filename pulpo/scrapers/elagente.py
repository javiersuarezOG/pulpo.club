"""
El Agente Inmobiliario scraper.

Site: https://www.elagenteinmobiliario.com/
Stack: Server-rendered WordPress + Houzez theme (3.x). Listings have
the URL pattern /propiedad/<slug>/. The /estado/for-sale/ archive lists
only for-sale taxonomies (~55 active listings across 5 pages × 11) and
acts as the index for this scraper.

Why /estado/for-sale/ and not /casas/ / /apartamentos/ / /terrenos/
-------------------------------------------------------------------
The type archives mix sale + rent: a single property URL can appear in
/casas/ regardless of whether it's listed for sale or rent. The
/estado/for-sale/ archive filters by Houzez's status taxonomy, which is
the authoritative for-sale-vs-rent signal upstream. Detail pages still
get a defense-in-depth status check (anchor link to /estado/for-rent/
present → drop) before mapping.

Niche filter
------------
Per the new-sources brief, elagente is filtered to Pacific coast +
Lake Coatepeque + Lake Ilopango for ALL property types via
finalize_record(force_vacation_gate=True). The agency's catalog is
mixed — San Salvador residential + Chalatenango fincas + a few
genuinely-in-niche Lake Coatepeque and La Libertad coastal lots — and
without the force-gate ranked.json would absorb dozens of inland
homes that aren't Pulpo's audience.

Type inference
--------------
The Houzez "Tipo de propiedad" field on the property-overview block
maps to:
  Casas / Residencias / Chalets             → house
  Apartamentos / Condominios                → condo
  Terrenos / Lotes / Fincas / Quintas       → land
The breadcrumb is a secondary signal; URL slug also helps for the
multi-signal classifier.
"""
from __future__ import annotations
import html as _html
import re
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import HTTPX_OK, SELECTOLAX_OK, make_client
from pulpo.agents import SOURCES, register
from pulpo.scrapers._base import OfflineFixtureMixin, finalize_record, polite_get_for
from pulpo.scrapers._policy import get_policy

if HTTPX_OK:
    import httpx  # noqa: F401

BASE_URL    = "https://www.elagenteinmobiliario.com"
INDEX_PATH  = "/estado/for-sale"   # the for-sale taxonomy archive
MAX_PAGES   = 20                    # 20 × 11 = 220 listings worst-case
FIXTURE_FILE = "sample_listings.json"

# Browser-realistic headers — defense against Wordfence / generic
# bot-detection plugins. First nightly (2026-05-25) returned HTTP 403
# from the GitHub Actions runner with only a User-Agent header set.
# Local curl with full Chrome headers returned 200, so the missing
# piece is the Sec-Fetch-* / Accept-* fingerprint that real browsers
# always send. If the host is also doing IP-class filtering on Azure
# (GitHub Actions runners) these headers won't help — see
# auto_repair=False in _policy.py, which documents the fallback.
_BROWSER_HEADERS: dict[str, str] = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "es-SV,es;q=0.9,en;q=0.8",
    # Brotli ("br") intentionally omitted — httpx doesn't decode it
    # without the `brotli` package, so claiming br gets us a
    # gibberish response body from any host that prefers it.
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# Houzez "Tipo de propiedad" → Pulpo type. Unknown labels are dropped at
# parse time (commercial / industrial taxonomies don't ship to Pulpo).
_HOUZEZ_TYPE_TO_PULPO: dict[str, str] = {
    "casas":         "house",
    "casa":          "house",
    "residencia":    "house",
    "residencias":   "house",
    "chalet":        "house",
    "chalets":       "house",
    "villa":         "house",
    "villas":        "house",
    # "Ranchos de playa" is elagente's custom Houzez category for beach
    # cabins — built structures with beds + baths, NOT agricultural
    # ranches. The Pulpo type classifier sees "rancho" as a land keyword
    # so it will flag the disagreement, but PR #444 already taught the
    # `is_agricultural` filter that beach ranchos aren't agricultural,
    # so downstream they ship as house without getting purged.
    "ranchos":       "house",
    "rancho":        "house",
    "apartamentos":  "condo",
    "apartamento":   "condo",
    "condominios":   "condo",
    "condominio":    "condo",
    "terrenos":      "land",
    "terreno":       "land",
    "lotes":         "land",
    "lote":          "land",
    "fincas":        "land",
    "finca":         "land",
    "quintas":       "land",
}

_PRICE_RE          = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
# Site name appears as both "Inmobiliario" (correct Spanish) and
# "Immobiliario" (typo with double-m) in different parts of the site.
# Strip either form, plus any optional trailing punctuation (".", ",")
# some titles drop in before the suffix.
_TITLE_SUFFIX_RE   = re.compile(
    r"[\s.,]*-\s*El\s+Agente\s+(?:Inmobiliario|Immobiliario)\s*$", re.IGNORECASE,
)
# Houzez "Tipo de propiedad: <Label>" — the label can sit behind one or
# more intervening tags (the live DOM wraps it in <a href="/casas/">
# inside a <dd> inside a <dl>). Allow up to ~200 chars of intervening
# markup before picking the first alphabetic word as the label.
_HOUZEZ_TYPE_RE    = re.compile(
    r"Tipo de propiedad[\s\S]{0,200}?>\s*([A-Za-zÁ-úñ]+)",
    re.IGNORECASE,
)
# Alternate Houzez 3.x form: the type label sits as a link text inside
# the property-overview-data <ul>, before "Tipo de propiedad".
_HOUZEZ_TYPE_LINK_RE = re.compile(
    r'href="https://www\.elagenteinmobiliario\.com/(casas|apartamentos|terrenos|residencias|chalets|villas|condominios|lotes|fincas|quintas)[^"]*"',
    re.IGNORECASE,
)
_BEDS_RE  = re.compile(r"(\d+)\s+(?:Habitacion(?:es)?|Cuartos|Recámaras|Bedrooms)", re.IGNORECASE)
_BATHS_RE = re.compile(r"(\d+(?:\.\d+)?)\s+(?:Baños|Bathrooms)", re.IGNORECASE)
# Lot/built area: "1,200 m²" near the area icon
_AREA_RE  = re.compile(r"([\d,]+(?:\.\d+)?)\s*m[2²]")

# Status anchors — Houzez emits both the property's status link AND
# global nav links to both taxonomies. The property's OWN status link
# appears INSIDE the .property-labels-wrap or near the price block.
# Heuristic: if the URL appears in the for-sale archive that fed us
# the URL, treat it as for-sale unless the body contains an explicit
# "/etiqueta-de-propiedad/en-alquiler/" or "alquiler" in the URL slug.
_RENT_SLUG_RE = re.compile(r"\b(alquiler|rent|renta)\b", re.IGNORECASE)


def _meta_content(html: str, prop: str) -> str:
    m = re.search(
        rf'<meta\s+[^>]*property=["\']({re.escape(prop)})["\'][^>]*content=["\']([^"\']*)["\']',
        html, re.IGNORECASE,
    )
    return _html.unescape(m.group(2)) if m else ""


def _parse_index(html: str) -> list[dict]:
    """Extract /propiedad/<slug>/ URLs from a for-sale archive page."""
    urls = set(re.findall(
        r'href="(https://www\.elagenteinmobiliario\.com/propiedad/[a-z0-9-]+/?)"',
        html,
    ))
    return [{"url": u.rstrip("/")} for u in sorted(urls)]


def _infer_property_type(html: str, url: str) -> Optional[str]:
    """Pick the Pulpo property_type from Houzez signals.

    Priority:
      1. Explicit "Tipo de propiedad: <Label>" — the label is captured
         from the overview block's <a> tag text right after the
         "Tipo de propiedad" label.
      2. A /casas|/apartamentos|/terrenos/ taxonomy link, but ONLY when
         it appears within ~600 chars of the "Tipo de propiedad" label
         (which scopes the search to the property-overview-data block
         and avoids matching the global nav's category links).
      3. URL slug (casa/apartamento/terreno/finca/lote tokens).
    Returns None if none of the above resolve.

    Why the proximity check on #2: every elagente page has BOTH the
    global nav links (Casas, Apartamentos, Terrenos) AND the per-listing
    taxonomy link. Without scoping, the first match was always the nav
    link, which produced wrong types like "rancho de playa" being
    classified as condo via the /apartamentos/ nav link.
    """
    m = _HOUZEZ_TYPE_RE.search(html)
    if m:
        label = m.group(1).strip().lower().rstrip("s")
        if label + "s" in _HOUZEZ_TYPE_TO_PULPO:
            return _HOUZEZ_TYPE_TO_PULPO[label + "s"]
        if label in _HOUZEZ_TYPE_TO_PULPO:
            return _HOUZEZ_TYPE_TO_PULPO[label]

    # Scoped taxonomy-link search: the property-overview block always
    # places its taxonomy link within a few hundred chars of the
    # "Tipo de propiedad" label. The global nav links are far above
    # (header) so the proximity check excludes them.
    label_pos = html.lower().find("tipo de propiedad")
    if label_pos >= 0:
        window = html[label_pos:label_pos + 600]
        link_m = _HOUZEZ_TYPE_LINK_RE.search(window)
        if link_m:
            slug = link_m.group(1).lower()
            if slug in _HOUZEZ_TYPE_TO_PULPO:
                return _HOUZEZ_TYPE_TO_PULPO[slug]

    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    for tok in slug.split("-"):
        if tok in _HOUZEZ_TYPE_TO_PULPO:
            return _HOUZEZ_TYPE_TO_PULPO[tok]
    return None


def _extract_photo_urls(html: str) -> list[str]:
    """Pull photo URLs from the schema.org/ImageGallery block.

    Falls back to all wp-content/uploads/<year>/<month>/ image URLs in
    the page if the gallery block is missing or thin. Filters out
    logos, favicons, and avatar gravatars.
    """
    urls: list[str] = []
    seen: set[str] = set()
    # Primary: gallery section
    m = re.search(
        r'itemtype="http://schema\.org/ImageGallery"([\s\S]{0,8000}?)</div>\s*</div>',
        html,
    )
    blob = m.group(1) if m else html
    for u in re.findall(
        r'https://www\.elagenteinmobiliario\.com/wp-content/uploads/\d+/\d+/[^"\'\\s)]+',
        blob,
    ):
        if not u.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        if any(skip in u.lower() for skip in ("logo", "favicon", "avatar", "icon")):
            continue
        if u in seen:
            continue
        seen.add(u)
        urls.append(u)
    return urls


def _extract_price(html: str) -> tuple[Optional[float], str]:
    """Pull the listing price from the Houzez .item-price element.

    Two Houzez shapes observed live (2026-05-25):
      direct:   <li class="item-price ...">$295,000</li>
      wrapped:  <li class="item-price ..."><span class="price">$650,000</span>...</li>

    We grab the whole element interior (tags + text), strip the inner
    tags, then run the price regex over the cleaned text. Returns
    (price_usd, raw_text). raw_text preserves the cleaned string so the
    downstream units module gets the same input shape it does for
    other scrapers.
    """
    m = re.search(
        r'class="item-price[^"]*"[^>]*>([\s\S]{0,400}?)</li>',
        html,
    )
    if not m:
        return (None, "")
    raw_inner = re.sub(r"<[^>]+>", " ", m.group(1))
    raw_inner = re.sub(r"\s+", " ", raw_inner).strip()
    pm = _PRICE_RE.search(raw_inner)
    if not pm:
        return (None, raw_inner)
    try:
        return (float(pm.group(1).replace(",", "")), raw_inner)
    except ValueError:
        return (None, raw_inner)


def _extract_address(html: str) -> str:
    """Pull the listing's <address> tag contents."""
    m = re.search(r"<address[^>]*>([\s\S]*?)</address>", html, re.IGNORECASE)
    if not m:
        return ""
    txt = re.sub(r"<[^>]+>", " ", m.group(1))
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _is_rental(html: str, url: str) -> bool:
    """Heuristic: this listing is a rental, not a sale.

    Signals (any True → drop):
      - URL slug contains 'alquiler' / 'rent' / 'renta' as a word
      - explicit /etiqueta-de-propiedad/en-alquiler/ link in body
        (this is the per-listing taxonomy link, not the global nav)
    The for-sale archive already pre-filters most rentals out, so
    this is defense in depth.
    """
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    if _RENT_SLUG_RE.search(slug):
        return True
    if re.search(
        r'href="https://www\.elagenteinmobiliario\.com/etiqueta-de-propiedad/(en-alquiler|alquiler|en-renta)/',
        html, re.IGNORECASE,
    ):
        return True
    return False


def _parse_detail(html: str, url: str) -> Optional[dict]:
    """Map one elagente detail page to the Pulpo raw-dict shape."""
    if _is_rental(html, url):
        return None
    broker_type = _infer_property_type(html, url)
    if broker_type is None:
        return None

    title = (_meta_content(html, "og:title") or "").strip()
    title = _TITLE_SUFFIX_RE.sub("", title).strip()
    if not title:
        return None

    description = (_meta_content(html, "og:description") or "").strip()[:1500]
    og_image    = _meta_content(html, "og:image")

    price_usd, price_raw = _extract_price(html)

    photo_urls = _extract_photo_urls(html)
    if og_image and og_image.startswith("http") and og_image not in photo_urls:
        photo_urls.insert(0, og_image)

    address = _extract_address(html)
    location_text = address or title
    if "El Salvador" not in location_text:
        location_text = f"{location_text}, El Salvador" if location_text else "El Salvador"

    area_m = _AREA_RE.search(html)
    raw_size_text = f"{area_m.group(1).replace(',', '')} m2" if area_m else ""

    slug = url.rstrip("/").rsplit("/", 1)[-1]

    record: dict = {
        "source":         "elagente",
        "source_id":      slug,
        "url":            url,
        "title":          title,
        "price_usd":      price_usd,
        "raw_price_text": price_raw,
        "raw_size_text":  raw_size_text,
        "location_text":  location_text,
        "description":    description,
        "property_type":  broker_type,
        "photo_urls":     photo_urls,
        "scraped_at":     datetime.now(timezone.utc).isoformat(),
    }

    if broker_type in ("house", "condo"):
        beds_m = _BEDS_RE.search(html)
        if beds_m:
            try:
                record["bedrooms"] = int(beds_m.group(1))
            except ValueError:
                pass
        baths_m = _BATHS_RE.search(html)
        if baths_m:
            try:
                record["bathrooms"] = float(baths_m.group(1))
            except ValueError:
                pass

    return finalize_record(
        record, slug="elagente",
        broker_type=broker_type,
        broker_type_field=_HOUZEZ_TYPE_RE.search(html).group(1) if _HOUZEZ_TYPE_RE.search(html) else "",
        force_vacation_gate=True,
    )


class ElAgenteScraper(OfflineFixtureMixin):
    slug = "elagente"
    country = "SV"

    def __init__(self, offline: bool | None = None):
        self.offline = offline

    def report_total(self, client) -> Optional[int]:
        """No clean total signal in the archive header. Return None
        rather than guessing — the audit will show '?' for elagente
        instead of a misleading percentage."""
        return None

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        return self.crawl_with_meta(limit, offline)["records"]

    def crawl_with_meta(
        self, limit: int = 30, offline: bool | None = None, max_pages: int | None = None,
    ) -> dict:
        fix = self._offline_or_fixtures(limit, override_offline=offline)
        if fix is not None:
            return {"records": fix, "max_pages_hit": False, "limit_hit": len(fix) >= limit}

        if not SELECTOLAX_OK:
            print(f"[{self.slug}] selectolax not installed, skipping")
            return {"records": [], "max_pages_hit": False, "limit_hit": False}

        page_cap = max_pages if max_pages is not None else MAX_PAGES
        # Transport-conditional client allocation. httpx wants a shared
        # Client (cookies, connection pool); curl_cffi opens its own
        # connection per call and ignores the client argument. The
        # polite_get_for callable handles the dispatch — see _base.py.
        policy = get_policy(self.slug)
        client = make_client() if policy.transport == "httpx" else None
        get = polite_get_for(self.slug)
        out: list[dict] = []
        seen_urls: set[str] = set()
        max_pages_hit = False
        limit_hit = False
        try:
            # Warmup: hit the homepage first so any cookie-gated paths
            # (Wordfence challenges, session establishers) get their
            # cookies set on the shared httpx.Client before we start
            # paginating. Failure of the warmup is not fatal — the
            # paginated GETs below run regardless and will surface the
            # real error if the site is blocking us at the IP layer.
            #
            # On the curl_cffi transport the warmup is functionally a
            # no-op (each call opens a fresh connection), but the GET
            # still costs nothing meaningful and keeps the behaviour
            # symmetric across transports.
            try:
                _ = get(client, f"{BASE_URL}/", extra_headers=_BROWSER_HEADERS)
            except Exception as e:
                print(f"[{self.slug}] warmup GET / failed (continuing): {e}")

            for page in range(1, page_cap + 1):
                if len(out) >= limit:
                    limit_hit = True
                    break
                index_url = f"{BASE_URL}{INDEX_PATH}/" if page == 1 else f"{BASE_URL}{INDEX_PATH}/page/{page}/"
                try:
                    # Sec-Fetch-Site=same-origin once we have a referer
                    referer = (
                        f"{BASE_URL}/" if page == 1
                        else f"{BASE_URL}{INDEX_PATH}/page/{page - 1}/"
                    )
                    resp = get(client, index_url, extra_headers={
                        **_BROWSER_HEADERS,
                        "Sec-Fetch-Site": "same-origin",
                        "Referer": referer,
                    })
                    resp.raise_for_status()
                except Exception as e:
                    print(f"[{self.slug}] index page {page} failed: {e}")
                    break

                partials = _parse_index(resp.text)
                if not partials:
                    break

                new_this_page = False
                for p in partials:
                    if len(out) >= limit:
                        limit_hit = True
                        break
                    durl = p["url"]
                    if durl in seen_urls:
                        continue
                    seen_urls.add(durl)
                    try:
                        dresp = get(client, durl, extra_headers={
                            **_BROWSER_HEADERS,
                            "Sec-Fetch-Site": "same-origin",
                            "Referer": index_url,
                        })
                        dresp.raise_for_status()
                    except Exception as e:
                        print(f"[{self.slug}] detail {durl} failed: {e}")
                        continue
                    rec = _parse_detail(dresp.text, durl)
                    if rec is not None:
                        out.append(rec)
                        new_this_page = True

                if not new_this_page and page > 1:
                    # Pagination wrap (WordPress can serve the same page
                    # indefinitely past the last real page).
                    break
                if page >= page_cap:
                    max_pages_hit = True
        finally:
            if client is not None:
                client.close()
        return {"records": out, "max_pages_hit": max_pages_hit, "limit_hit": limit_hit}

    def parse_index_page(self, html: str) -> list[dict]:
        return _parse_index(html)

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        return _parse_detail(html, partial.get("url", ""))


_scraper = ElAgenteScraper()
register(SOURCES, "elagente", _scraper)


def crawl(limit: int = 30, offline: bool | None = None) -> list[dict]:
    return ElAgenteScraper(offline=offline).crawl(limit)
