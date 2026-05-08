"""
Encuentra24 SV real-estate scraper — adds the dominant CA classifieds
aggregator as a pulpo source.

Site:  https://www.encuentra24.com/el-salvador-es/bienes-raices
Stack: Next.js App Router (no `__NEXT_DATA__` blob — listings are
       rendered server-side via React Server Components, with the data
       on the page only after JS hydration). Cloudflare-fronted, but
       not blocking GitHub Actions runner IPs (verified live by the
       scout in PR pre-work, 2026-05-08).

Why a different approach than the other 6 scrapers
--------------------------------------------------
Pulpo's existing scrapers either (a) hit a structured API (bienesraices,
century21) or (b) parse server-rendered HTML with selectolax (oceanside,
goodlife). encuentra24 does neither — the static HTML returns an empty
SPA shell, and the only documented JSON endpoints (`/api.php/`,
`/ajax/`) are explicitly Disallowed by their robots.txt.

So the only ToS-compatible path is **rendering the page in a real
browser** and reading data from the rendered HTML. This module uses
Playwright + headless Chromium for the fetch step, then parses the
returned HTML with selectolax (same parser the rest of the project
uses). Three things make this less painful than it sounds:

1. **JSON-LD is canonical.** Every detail page carries one
   `<script type="application/ld+json">` block with an `@type=Product`
   schema covering name, description, price, currency, location, and
   broker. We don't need DOM scraping for the basics.
2. **Per-type fields live in a single Tailwind grid.** Bedrooms /
   bathrooms / built area / parking sit in adjacent child divs of
   `<div class="flex flex-wrap gap-x-4">`. One regex per child gets
   each field cleanly.
3. **The fetcher and the parser are split.** Playwright is lazy-imported
   in the live crawl path; the parse functions operate on HTML strings
   only, so offline tests use saved calibration fixtures and never
   touch Playwright. Means our existing `PULPO_OFFLINE=1 pytest -q`
   path keeps working without a 500MB Chromium dep.

Detail-page render time on a runner: ~7s. PULPO_E24_LIMIT caps the
nightly's exposure (PR-E2 will wire that env var into the workflow).
"""
from __future__ import annotations
import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

from pulpo.agents.html_crawler import SELECTOLAX_OK, is_offline, load_fixtures
from pulpo.agents import SOURCES, register
from pulpo.scrapers._type_classifier import classify_property_type
from automation.property_types import VACATION_ZONES, WATERFRONT_KEYWORDS

if SELECTOLAX_OK:
    from selectolax.parser import HTMLParser  # noqa: F401


# ── Site constants ────────────────────────────────────────────────────


BASE = "https://www.encuentra24.com"
INDEX_URL = f"{BASE}/el-salvador-es/bienes-raices"

# Sub-category landing URLs. encuentra24's sale section is split by
# property type (apartments/houses/lots), each at a stable URL. No
# pagination has been found at the category-URL level (infinite scroll
# is disabled, no `?page=N` query, no "next page" link); inventory size
# per render appears to cap at ~20 listings per category. Geographic
# sub-paths (`/apartamentos/la-libertad`, `/apartamentos/colonia-escalon`)
# could multiply coverage — left for v2 once we have a baseline of how
# many unique listings v1 actually surfaces.
CATEGORY_URLS: list[str] = [
    f"{BASE}/el-salvador-es/bienes-raices-venta-de-propiedades-apartamentos",
    f"{BASE}/el-salvador-es/bienes-raices-venta-de-propiedades-casas",
    f"{BASE}/el-salvador-es/bienes-raices-venta-de-propiedades-terrenos",
]

FIXTURE_FILE = "sample_listings.json"


# ── Compiled regexes ──────────────────────────────────────────────────


# Listing-detail URL pattern: any path ending in /<numeric-ID> where
# the ID is 7-9 digits. All current encuentra24 ad IDs fall in that range.
_NUMERIC_ID_RE = re.compile(r"/(\d{7,9})(?:[/?#]|$)")

# encuentra24's photo CDN. URL shape:
#   https://photos.encuentra24.com/<size>/<encoding>/v1/sv/<id-prefix>/<id>_<hash>-<variant>
# We filter to URLs containing the listing's numeric ID so related-
# listing thumbnails on the same page don't bleed into our gallery.
_PHOTO_RE = re.compile(r"https://photos\.encuentra24\.com/[^\"\s)\\]+")

# Tailwind grid carrying bedrooms / bathrooms / built_area / parking.
# Each child <div> has a label+value text concatenation:
#   "recámaras4"  → 4 bedrooms
#   "baños3"      → 3 bathrooms
#   "área construida97 m²"  → 97 m² built area
#   "área del lote500 m²"   → 500 m² lot (rare on apartments)
#   "parking2"    → 2 parking spaces
_FACT_PATTERNS: list[tuple[re.Pattern, str, type]] = [
    (re.compile(r"^rec[áa]maras?\s*(\d+)$",                 re.IGNORECASE), "bedrooms",       int),
    (re.compile(r"^ba[ñn]os?\s*(\d+(?:\.\d+)?)$",           re.IGNORECASE), "bathrooms",      float),
    (re.compile(r"^[áa]rea\s+construida\s*([\d,]+(?:\.\d+)?)\s*m²?$", re.IGNORECASE), "built_area_m2",  float),
    (re.compile(r"^[áa]rea\s+(?:del\s+lote|terreno)\s*([\d,]+(?:\.\d+)?)\s*m²?$", re.IGNORECASE), "area_m2", float),
    (re.compile(r"^parking\s*(\d+)$",                       re.IGNORECASE), "parking_spaces", int),
]

# Compiled waterfront-keyword regex — same pattern as the other Phase-C
# scrapers (vacation-zone filter for house/condo).
_WATERFRONT_RE = re.compile("|".join(WATERFRONT_KEYWORDS), re.IGNORECASE)


# Map the encuentra24 sub-category URL fragment to the pulpo property
# type. Sale-only — rentals (`alquiler`) aren't in pulpo's scope today.
_CATEGORY_TYPE: list[tuple[str, str]] = [
    ("-apartamentos", "condo"),
    ("-casas",        "house"),
    ("-terrenos",     "land"),
    ("-fincas",       "land"),
]


def _category_from_url(url: str) -> Optional[str]:
    """Pull pulpo property_type from an encuentra24 listing URL.

    Returns None for out-of-scope categories (commercial offices,
    rentals, parking, etc.) — caller drops the listing.
    """
    if "/bienes-raices-venta" not in url:
        return None  # Rental listing — drop
    for kw, ptype in _CATEGORY_TYPE:
        if kw in url:
            return ptype
    return None


# ── Pure parsers (HTML in, dict out) ──────────────────────────────────


def _strip_html(s: str) -> str:
    """Strip the `<br />` salad encuentra24 puts inside JSON-LD
    `description`. Keeps the line-break semantics by replacing each
    tag with a space."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def parse_index_html(html: str) -> list[str]:
    """Pull all distinct sale-listing detail URLs from an index/category
    render. Filters out rentals and non-real-estate categories."""
    if not SELECTOLAX_OK:
        return []
    tree = HTMLParser(html)
    out: list[str] = []
    seen: set[str] = set()
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href:
            continue
        if not _NUMERIC_ID_RE.search(href):
            continue
        if "/bienes-raices-venta" not in href:
            continue
        url = href if href.startswith("http") else BASE + href
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _parse_jsonld(tree) -> Optional[dict]:
    """Return the first `<script type="application/ld+json">` block as
    parsed JSON, or None if absent or malformed."""
    blk = tree.css_first('script[type="application/ld+json"]')
    if not blk:
        return None
    try:
        return json.loads(blk.text())
    except json.JSONDecodeError:
        return None


def _parse_facts_grid(tree) -> dict:
    """Read bedrooms / bathrooms / built_area_m2 / area_m2 / parking
    from the Tailwind facts grid. Missing fields are simply absent
    from the returned dict."""
    container = tree.css_first("div.flex.flex-wrap.gap-x-4")
    if container is None:
        return {}
    facts: dict = {}
    for child in container.css("div"):
        txt = (child.text(strip=True) or "")
        if not txt or len(txt) > 60:
            continue
        for rx, name, cast in _FACT_PATTERNS:
            m = rx.match(txt)
            if not m:
                continue
            try:
                facts[name] = cast(m.group(1).replace(",", ""))
            except (TypeError, ValueError):
                pass
            break
    return facts


def _parse_photos(html: str, listing_id: str) -> list[str]:
    """Extract gallery URLs filtered to this listing's ID. encuentra24
    pages render related-listing thumbnails too; the listing-ID prefix
    in the CDN URL (`/sv/<id-prefix>/<id>_...`) is the only reliable
    way to separate ours from theirs."""
    matches = _PHOTO_RE.findall(html)
    out: list[str] = []
    seen: set[str] = set()
    for u in matches:
        if listing_id not in u:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _build_raw_record(html: str, url: str) -> Optional[dict]:
    """Parse a rendered detail page into a pulpo raw record. NO filter
    logic — this only does the structural extraction. `parse_detail`
    layers the vacation-zone filter + classifier on top.

    Split out so tests can verify the parser's correctness on inland
    fixtures (which the production parse_detail correctly drops via
    the vacation-zone filter).

    Returns None when the page itself isn't parseable (no JSON-LD,
    out-of-scope URL, missing title).
    """
    if not SELECTOLAX_OK:
        return None

    m = _NUMERIC_ID_RE.search(url)
    if not m:
        return None
    listing_id = m.group(1)

    broker_type = _category_from_url(url)
    if broker_type is None:
        return None  # rental / commercial / other — drop

    tree = HTMLParser(html)
    ld = _parse_jsonld(tree)
    if not ld:
        return None

    title = (ld.get("name") or "").strip()
    if not title:
        return None
    description = _strip_html(ld.get("description") or "")[:1500]

    # Price — only USD listings count (encuentra24 lists in USD for SV)
    offers = ld.get("offers") or {}
    price_usd: Optional[float] = None
    if (offers.get("priceCurrency") or "").upper() == "USD":
        try:
            price_usd = float(offers.get("price") or 0) or None
        except (TypeError, ValueError):
            pass

    # Location: street + locality from JSON-LD's PostalAddress
    avail = (offers.get("availableAtOrFrom") or {})
    addr = avail.get("address") or {}
    location_parts = [
        p for p in (addr.get("streetAddress"), addr.get("addressLocality"))
        if p
    ]
    location_text = ", ".join(location_parts) or "El Salvador"

    # Broker — encuentra24 carries a seller Organization; some listings
    # are owner-direct (no broker), in which case the field is absent
    seller = offers.get("seller") or {}
    broker_name = seller.get("name") if isinstance(seller, dict) else None

    # Per-type fields from the Tailwind facts grid
    facts = _parse_facts_grid(tree)

    rec: dict = {
        "source_id":      listing_id,
        "url":            url,
        "title":          title,
        "description":    description,
        "location_text":  location_text,
        "raw_size_text":  "",
        "price_usd":      price_usd,
        "raw_price_text": f"USD {price_usd:.0f}" if price_usd else "",
        "property_type":  broker_type,
        "broker_name":    broker_name or "",
        "scraped_at":     datetime.now(timezone.utc).isoformat(),
        "photo_urls":     _parse_photos(html, listing_id),
    }

    # Type-specific fields. House/condo: built area is the unit interior;
    # area_m2 (lot) is rare on encuentra24 apartments (often absent).
    # Land: encuentra24's grid uses "área construida" inconsistently for
    # raw lots — fall back to it for area_m2 when the explicit "área del
    # lote" key is absent.
    if broker_type in ("house", "condo"):
        for k in ("bedrooms", "bathrooms", "built_area_m2",
                  "parking_spaces", "area_m2"):
            if k in facts:
                rec[k] = facts[k]
    elif broker_type == "land":
        if "area_m2" in facts:
            rec["area_m2"] = facts["area_m2"]
        elif "built_area_m2" in facts:
            # encuentra24's grid sometimes labels the lot as "construida"
            # for land listings (parser quirk on their side). Treat it
            # as the lot area rather than dropping the size field.
            rec["area_m2"] = facts["built_area_m2"]

    return rec


def parse_detail(html: str, url: str) -> Optional[dict]:
    """Map a fully-rendered detail page HTML to the pulpo raw-record
    schema, applying the vacation-zone filter and multi-signal
    classifier.

    Returns None when:
    - The HTML can't be parsed (no JSON-LD, missing title)
    - The URL is out-of-scope (rental, commercial, unknown sub-category)
    - It's an inland house/condo (vacation-zone filter drops it)

    The pure parse step is in `_build_raw_record` — split out so tests
    can verify parsing correctness on inland fixtures separately from
    the filter behaviour.
    """
    rec = _build_raw_record(html, url)
    if rec is None:
        return None

    broker_type = rec["property_type"]

    # Vacation-zone filter (house/condo only — same as Phase-C scrapers).
    # Land is exempt — inland lots are valid pulpo inventory.
    if broker_type in ("house", "condo"):
        loc_blob = rec["location_text"].lower().replace(" ", "-")
        zone_is_vacation = any(z in loc_blob for z in VACATION_ZONES)
        text_blob = f"{rec['title']}\n{rec['description']}"
        has_waterfront_kw = bool(_WATERFRONT_RE.search(text_blob))
        if not zone_is_vacation and not has_waterfront_kw:
            return None

    # Multi-signal classifier — confirms broker_type, surfaces signals
    # for the shadow log, FLAGS the listing if classifier disagrees.
    ptype, signals, confidence, total = classify_property_type({
        "broker_type_field": broker_type,
        "url":               url,
        "photo_urls":        rec["photo_urls"],
        "title":             rec["title"],
        "description":       rec["description"],
    }, fallback_type=broker_type)
    rec["_type_signals"]    = [s.to_dict() for s in signals]
    rec["_type_confidence"] = confidence
    rec["_type_total"]      = total
    if ptype != broker_type:
        rec["validation_status"] = "flagged"
        rec["validation_warnings"] = ["type_uncertain"]

    return rec


# ── Crawl orchestrator ────────────────────────────────────────────────


class Encuentra24Scraper:
    """Pulpo source adapter for encuentra24.com SV real estate.

    `crawl(limit, offline)` is the only method called by the rest of
    the pipeline. Offline mode loads from `tests/fixtures/sample_listings.json`
    (filtered to source=encuentra24). Live mode lazy-imports Playwright
    and renders every category + detail page sequentially.

    Polite-throttling is REQUEST_DELAY=2.0 between fetches — encuentra24
    doesn't surface rate-limit headers but Cloudflare is in front and
    the per-page render is already slow, so 2s/page is fine.
    """
    slug = "encuentra24"
    REQUEST_DELAY = 2.0
    PAGE_TIMEOUT_MS = 45_000   # 45s — encuentra24 detail pages take ~7s
                                # plus JSON-LD must hydrate; 45s is safe

    def __init__(self, offline: Optional[bool] = None):
        self.offline = offline

    def crawl(self, limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
        if is_offline(offline if offline is not None else self.offline):
            return load_fixtures(self.slug, FIXTURE_FILE, limit)
        return self._crawl_live(limit)

    def crawl_with_meta(
        self,
        limit: int = 30,
        offline: Optional[bool] = None,
        max_pages: Optional[int] = None,  # noqa: ARG002
    ) -> dict:
        records = self.crawl(limit, offline)
        return {
            "records":        records,
            "max_pages_hit":  False,
            "limit_hit":      len(records) >= limit,
        }

    # ------- Live crawl (Playwright) -------

    def _crawl_live(self, limit: int) -> list[dict]:
        """Render category landings → harvest URLs → render each detail.
        Lazy-imports playwright so the offline test path doesn't need it.
        """
        try:
            from playwright.sync_api import sync_playwright   # type: ignore
        except ImportError:
            print("[encuentra24] playwright not installed — skipping live crawl")
            return []

        UA = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        )
        out: list[dict] = []
        seen_urls: set[str] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 800},
                locale="es-SV",
            )
            # Cheap stealth — encuentra24 doesn't appear to do aggressive
            # bot detection, but `navigator.webdriver === true` is the
            # easy giveaway and trivial to suppress.
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', "
                "{get: () => undefined});"
            )
            page = context.new_page()

            try:
                # ── Phase 1: harvest listing URLs from each category ──
                listing_urls: list[str] = []
                for cat_url in CATEGORY_URLS:
                    if len(listing_urls) >= limit:
                        break
                    time.sleep(self.REQUEST_DELAY)
                    try:
                        page.goto(cat_url, wait_until="networkidle",
                                  timeout=self.PAGE_TIMEOUT_MS)
                        page.wait_for_timeout(2500)
                    except Exception as e:
                        print(f"[encuentra24] category fetch failed "
                              f"{cat_url}: {type(e).__name__}: {e}")
                        continue
                    cat_html = page.content()
                    for url in parse_index_html(cat_html):
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        listing_urls.append(url)
                        if len(listing_urls) >= limit:
                            break

                print(f"[encuentra24] harvested {len(listing_urls)} "
                      f"listing URLs across {len(CATEGORY_URLS)} categories")

                # ── Phase 2: render each detail page ──
                for url in listing_urls:
                    if len(out) >= limit:
                        break
                    time.sleep(self.REQUEST_DELAY)
                    try:
                        page.goto(url, wait_until="networkidle",
                                  timeout=self.PAGE_TIMEOUT_MS)
                        page.wait_for_timeout(1500)
                    except Exception as e:
                        print(f"[encuentra24] detail fetch failed "
                              f"{url}: {type(e).__name__}: {e}")
                        continue
                    html = page.content()
                    rec = parse_detail(html, url)
                    if rec is None:
                        continue
                    rec["source"] = self.slug
                    out.append(rec)

            finally:
                browser.close()

        return out


# Module-level entry points (parity with the other scrapers' contracts).
_scraper = Encuentra24Scraper()
register(SOURCES, "encuentra24", _scraper)


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return Encuentra24Scraper(offline=offline).crawl(limit)
