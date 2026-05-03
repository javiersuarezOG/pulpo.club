"""
Raw site dict -> canonical Listing.

A "raw" record is whatever a scraper produced — keys vary per site. This
module is the choke point that turns that mess into a Listing object with
canonical units, derived $/m², and a snapped zone slug.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Optional

from .models import Listing
from .units import parse_area, parse_price_usd
from .developments import detect_development
from automation.localities import (
    parse_location_text as _parse_loc_text,
    lookup_locality     as _lookup_locality,
    DEPT_LOOKUP, MUNI_LOOKUP, TOURIST_LOOKUP, _norm,
)

# ---- Sold-listing detection ----
# Goodlife (and other SV brokers) leave properties indexed indefinitely with
# a "*SOLD*" / "VENDIDO" prefix instead of unpublishing. We drop those at the
# normalize step so they never reach the ranker.
#
# We require a leading boundary (start of string or non-word char such as `$`,
# space, or `*`) so we don't false-match words that contain "sold" as a
# substring (e.g. "household", "soldering") — the broker markers always sit
# at a word start. We deliberately do NOT require a trailing word boundary,
# because oceanside's `.post-content` blob arrives as tightly-concatenated
# DOM text like "$SOLDAvailable today" or "$UNDER CONTRACTAvailable today"
# where the marker runs straight into the next word with no whitespace —
# `\b` between two letters is no boundary, so a trailing `\b` silently
# misses these. Real-estate copy starting with "sold…" or "vendido…" is
# essentially never followed by a longer English/Spanish word that
# legitimately starts with those letters.
_SOLD_RE = re.compile(
    r"(?:^|[\s\W])(?:\*?\s*sold|vendido|vendida|under\s+contract|"
    r"en\s+proceso\s+de\s+venta|reservado|reservada|pending\s+sale)",
    re.IGNORECASE,
)

def is_sold(*texts: str) -> bool:
    """Return True if any of the given strings carries a sold/under-contract marker."""
    for t in texts:
        if t and _SOLD_RE.search(t):
            return True
    return False

# ---- Zone canonicalization ----
# Maps free-text location strings to a canonical slug. Order matters — most
# specific patterns first. Add zones here as we expand coverage.
ZONE_PATTERNS: list[tuple[str, str, str, str]] = [
    # (regex, zone_slug, municipality, department)
    # Most-specific patterns first — order matters.
    (r"el\s*cuco|playa\s*el\s*cuco",            "el-cuco",           "Chirilagua",     "San Miguel"),
    (r"playa\s*las?\s*flores|las?\s*flores",    "las-flores",        "Intipucá",       "La Unión"),
    (r"punta\s*mango",                          "punta-mango",       "Intipucá",       "La Unión"),
    (r"el\s*espino|playa\s*espino",             "el-espino",         "Jucuarán",       "Usulután"),
    (r"el\s*tunco",                             "el-tunco",          "Tamanique",      "La Libertad"),
    (r"el\s*sunzal",                            "el-sunzal",         "Tamanique",      "La Libertad"),
    (r"el\s*zonte|(?<!\w)zonte(?!\w)",          "el-zonte",          "Chiltiupán",     "La Libertad"),
    (r"k\s*59|km\s*59|playa\s*san\s*diego",     "san-diego",         "La Libertad",    "La Libertad"),
    (r"mizata",                                 "mizata",            "Teotepeque",     "La Libertad"),
    (r"conchagua|playa\s*el\s*tamarindo",       "conchagua",         "Conchagua",      "La Unión"),
    (r"jiquilisco",                             "jiquilisco",        "Jiquilisco",     "Usulután"),
    (r"la\s*libertad\s*puerto",                 "puerto-la-libertad","La Libertad",    "La Libertad"),
    (r"la\s*libertad",                          "la-libertad",       "La Libertad",    "La Libertad"),
    (r"la\s*uni[oó]n",                          "la-union",          "La Unión",       "La Unión"),
]

# Known El Salvador departments for structured-title validation
_SV_DEPARTMENTS = {
    "ahuachapán", "santa ana", "sonsonate", "chalatenango",
    "la libertad", "san salvador", "cuscatlán", "la paz", "cabañas",
    "san vicente", "usulután", "san miguel", "morazán", "la unión",
}
_DEPT_CANONICAL = {
    "ahuachapán": "Ahuachapán", "santa ana": "Santa Ana",
    "sonsonate": "Sonsonate",   "chalatenango": "Chalatenango",
    "la libertad": "La Libertad", "san salvador": "San Salvador",
    "cuscatlán": "Cuscatlán",   "la paz": "La Paz",
    "cabañas": "Cabañas",       "san vicente": "San Vicente",
    "usulután": "Usulután",     "san miguel": "San Miguel",
    "morazán": "Morazán",       "la unión": "La Unión",
}

# Structured-title pattern: "Locality, Department, El Salvador"
# Matches after a dash/preamble, not necessarily at string start.
_STRUCTURED_LOC_RE = re.compile(
    r'([A-ZÁÉÍÓÚÜÑa-záéíóúüñ][A-ZÁÉÍÓÚÜÑa-záéíóúüñ\s]+?)'
    r',\s*'
    r'([A-ZÁÉÍÓÚÜÑa-záéíóúüñ][A-ZÁÉÍÓÚÜÑa-záéíóúüñ\s]+?)'
    r',\s*El\s+Salvador\b',
    re.IGNORECASE,
)

def _detect_zone_structured(title: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract zone from 'Locality, Department, El Salvador' in title.

    Returns (zone_slug, municipality, department) when the department is a
    valid El Salvador department, else (None, None, None).
    """
    m = _STRUCTURED_LOC_RE.search(title)
    if not m:
        return (None, None, None)
    locality   = m.group(1).strip()
    department = m.group(2).strip()
    dept_lower = department.lower()
    if dept_lower not in _SV_DEPARTMENTS:
        return (None, None, None)
    dept_canon = _DEPT_CANONICAL[dept_lower]
    # Try to snap the locality to a known zone slug
    slug, muni, _ = detect_zone(locality)
    if slug:
        return (slug, muni, dept_canon)
    # No zone match: use locality as slug + department as region
    slug_gen = re.sub(r'[\s]+', '-', locality.strip().lower())
    slug_gen = re.sub(r'[^a-záéíóúüñ\-]', '', slug_gen)
    return (slug_gen or None, locality.strip().title(), dept_canon)


def detect_zone(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (zone_slug, municipality, department) or (None, None, None).

    Performs simple substring matching — reliable for title/location_text.
    Use _detect_zone_structured() first for titles with structured location info.
    """
    if not text:
        return (None, None, None)
    t = text.lower()
    for pattern, slug, muni, dept in ZONE_PATTERNS:
        if re.search(pattern, t):
            return (slug, muni, dept)
    return (None, None, None)


# Context-guarded zone matching for description text.
# Zone name must appear after "en/in/located/ubicado" or a comma, or at the
# start of a sentence — prevents "El Zonte" from matching when it appears in
# a comparative clause like "similar to what you find in El Zonte".
_ZONE_SLUG_PATTERNS = [
    (r"el\s*cuco|playa\s*el\s*cuco",          "el-cuco",           "Chirilagua",  "San Miguel"),
    (r"playa\s*las?\s*flores|las?\s*flores",  "las-flores",        "Intipucá",    "La Unión"),
    (r"punta\s*mango",                        "punta-mango",       "Intipucá",    "La Unión"),
    (r"el\s*espino|playa\s*espino",           "el-espino",         "Jucuarán",    "Usulután"),
    (r"el\s*tunco",                           "el-tunco",          "Tamanique",   "La Libertad"),
    (r"el\s*sunzal",                          "el-sunzal",         "Tamanique",   "La Libertad"),
    (r"el\s*zonte|(?<!\w)zonte(?!\w)",        "el-zonte",          "Chiltiupán",  "La Libertad"),
    (r"k\s*59|km\s*59|playa\s*san\s*diego",  "san-diego",         "La Libertad", "La Libertad"),
    (r"mizata",                               "mizata",            "Teotepeque",  "La Libertad"),
    (r"conchagua|playa\s*el\s*tamarindo",     "conchagua",         "Conchagua",   "La Unión"),
    (r"jiquilisco",                           "jiquilisco",        "Jiquilisco",  "Usulután"),
    (r"la\s*libertad",                        "la-libertad",       "La Libertad", "La Libertad"),
    (r"la\s*uni[oó]n",                        "la-union",          "La Unión",    "La Unión"),
]
_DESC_ZONE_CONTEXT_RE = re.compile(
    r'(?:(?:^|[.\n])\s*|[,]\s*|\b(?:en|in|located\s+in|ubicad[ao]\s+en)\s+)',
    re.IGNORECASE,
)

def _detect_zone_desc(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Zone extraction from description with context guard.

    Only matches zone names that appear after "en/in/ubicado" or a comma/newline
    — prevents comparative mentions ("similar to El Zonte") from registering.
    """
    if not text:
        return (None, None, None)
    # Build a single string to search with context prefix
    for pattern, slug, muni, dept in _ZONE_SLUG_PATTERNS:
        combined = rf'(?:(?:^|[.\n])\s*|[,]\s*|\b(?:en|in|located\s+in|ubicad[ao]\s+en)\s+)(?:{pattern})'
        if re.search(combined, text, re.IGNORECASE | re.MULTILINE):
            return (slug, muni, dept)
    return (None, None, None)

# ---- Property-type classification ----
# The scrapers pull every "real estate" listing — houses, condos, villas,
# mansions, lots, raw land — and the canonical schema defaults `property_type`
# to "land". Without this classifier, a 6-bedroom mansion in Surf City sits in
# the same comp pool as a raw 30-manzana parcel, and the $/m² distribution
# becomes meaningless. The ranker segments comp pools on `property_type`, so
# a wrong tag here propagates straight into the value score.
#
# We classify primarily on the TITLE because descriptions routinely talk about
# *future use* — "suitable for boutique hotel", "ideal para construir su casa
# de playa" — which would false-trigger built-structure keywords on what is
# actually raw land being marketed for development. Title is the curated, terse
# claim about what the listing is; description is sales copy about what it
# could become. We only consult the description when the title is missing or
# a placeholder like "Contact us" (which the oceanside scraper produces ~26%
# of the time), and even then we strip future-use phrases first.

# Built-structure keywords: explicit "this is a building" vocabulary. Plurals
# are required because broker headlines pluralize freely ("Cliffside apartments
# in El Zonte", "Two Lofts in Tuscania") and missing the trailing `s` silently
# drops them into the land pool.
_BUILT_RE = re.compile(
    r"\b("
    r"houses?|homes?|villas?|mansions?|cabins?|cottages?|bungalows?|"
    r"casas?|chalets?|residencias?|"
    r"apartments?|apartamentos?|condos?|condominiums?|condominios?|"
    r"lofts?|penthouses?|studios?|"
    r"hotels?|b&b|"
    r"\d+[\s-]*bed(?:room)?s?|"
    r"\d+[\s-]*dormitorios?|"
    r"\d+[\s-]*hab(?:itaciones)?\b"
    r")\b",
    re.IGNORECASE,
)

# Land vocabulary: explicit lot/land/finca words.
_LAND_RE = re.compile(
    r"\b("
    r"lot|lote|lots?|lotes?|lotificaci[oó]n|"
    r"land|terreno|terrenos|parcela|parcelas|plot|plots|"
    r"finca|fincas|hacienda|"
    r"acres?\s+of\s+land|manzanas?|hect[aá]reas?|hect[aá]rea"
    r")\b",
    re.IGNORECASE,
)

# Quantity-of-land patterns: "30 manzanas", "8 acres", "1.5 mz", "800 vrs²".
# When this fires in the title, the listing is land regardless of any incidental
# built-structure keyword (e.g. "30 manzanas beachfront El Cuco — suitable for
# boutique hotel" is a 30-manzana parcel, not a hotel).
_LAND_QTY_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*"
    r"(manzanas?|mz|acres?|hect[aá]reas?|hect[aá]rea|has?|"
    r"vrs?[²2]|varas?[\s-]*[²2]?)\b",
    re.IGNORECASE,
)

# Sales-copy phrases describing what the buyer could BUILD on the parcel. We
# strip these from the description before classifying so "suitable for a
# boutique hotel" stops triggering the hotel keyword on raw land.
_FUTURE_USE_RE = re.compile(
    r"(?:suitable\s+for|ideal\s+for|perfect\s+for|great\s+for|"
    r"build\s+(?:your|a|an)|could\s+be|might\s+be|develop\s+(?:into|as)|"
    r"ideal\s+para|perfecto\s+para|construir|"
    r"vacation\s+home|dream\s+home|family\s+compound|boutique\s+hotel)"
    r"[^.\n]{0,120}",
    re.IGNORECASE,
)

_PLACEHOLDER_TITLES = {"", "contact us", "contact", "(untitled)", "untitled"}

def _classify(text: str) -> Optional[str]:
    """Return 'house' / 'land' / None for a single piece of text."""
    if not text:
        return None
    # Quantity-of-land takes precedence over built keywords in the same string.
    if _LAND_QTY_RE.search(text):
        return "land"
    if _BUILT_RE.search(text):
        return "house"
    if _LAND_RE.search(text):
        return "land"
    return None

def detect_property_type(title: str = "", description: str = "", location_text: str = "") -> str:
    """Classify a listing as `house` (built structure) or `land` (lot/raw).

    Title-first: the title is a terse claim about what the listing IS.
    Description is consulted only when the title is empty / a placeholder,
    and future-use sales copy is stripped before classification so phrases
    like "suitable for boutique hotel" don't false-tag raw land as built.
    Defaults to `land` when nothing classifies — matches the dataclass
    default and keeps unclassifiable records in the lot comp pool.
    """
    title_norm = (title or "").strip().lower()
    if title_norm not in _PLACEHOLDER_TITLES:
        verdict = _classify(title)
        if verdict:
            return verdict
    # Title was empty or a placeholder — fall back to description with
    # future-use phrases stripped.
    blob = (description or "") + " " + (location_text or "")
    blob = _FUTURE_USE_RE.sub(" ", blob)
    return _classify(blob) or "land"

# ── Phase 1: property-type title filter ─────────────────────────────────────
# Applied only to HTML scraper sources that pull mixed inventory.
# oceanside: already API-filtered to property-type=lot. century21: clean.
_TITLE_FILTER_SOURCES = {"bienesraices", "remax", "goodlife"}

# Always drop these patterns in the title regardless of other keywords.
_ALWAYS_DROP_RE = re.compile(
    r"\b(bedroom|habitaci[oó]n|apartment|apartamento|departamento|depa|condo)\b",
    re.IGNORECASE,
)
# Drop "house" / "casa" UNLESS the title also carries explicit land vocabulary.
_HOUSE_RE = re.compile(r"\b(house|casa)\b", re.IGNORECASE)
_LAND_EXCEPTION_RE = re.compile(
    r"\b(land|terreno|lote|lots?|finca)\b", re.IGNORECASE
)


# ── Multi-tier zone resolver ──────────────────────────────────────────
# Returns (zone_slug, municipality, department, confidence).
# confidence: 'specific' | 'municipality' | 'department' | 'unresolved'

# Context guard for description text — zone must follow a location preposition
# or appear at the start of a sentence/after a comma.
_LOC_CTX = r'(?:(?:^|[.\n])\s*|[,;]\s*|\b(?:en|in|at|near|from|around|within|by|destination|located\s+in|ubicad[ao]\s+en|cerca\s+de|junto\s+a|frente\s+a)\s+)'


def _search_localities_in_text(text: str, use_context: bool = False) -> Optional[tuple[str, str, str, str]]:
    """Scan text for known tourist locality or municipality names.

    Returns (slug, municipality, department, confidence) or None.
    With use_context=True, tourist names must follow a location preposition
    (prevents comparative-mention false-positives).

    Matching uses accent-stripped normalized text so "AHUACHAPÁN" and
    "Ahuachapan" both resolve correctly.
    """
    if not text:
        return None
    # Accent-stripped lowercase for pattern matching against normalized lookup keys
    tl = _norm(text)

    # Tourist localities (specific)
    for variant, t in TOURIST_LOOKUP.items():
        if use_context:
            pattern = _LOC_CTX + re.escape(variant)
            if re.search(pattern, tl, re.IGNORECASE | re.MULTILINE):
                return (t["slug"], t["municipality"], t["department"], "specific")
        else:
            if re.search(r'\b' + re.escape(variant) + r'\b', tl):
                return (t["slug"], t["municipality"], t["department"], "specific")

    # Municipalities — longer names first to avoid partial matches
    for variant in sorted(MUNI_LOOKUP, key=len, reverse=True):
        if re.search(r'\b' + re.escape(variant) + r'\b', tl):
            name, dept = MUNI_LOOKUP[variant]
            slug = variant.replace(" ", "-")
            return (slug, name, dept, "municipality")

    # Department only
    for variant, dept_canon in DEPT_LOOKUP.items():
        if re.search(r'\b' + re.escape(variant) + r'\b', tl):
            return (None, None, dept_canon, "department")

    return None


def _slug_localities(url: str) -> Optional[tuple[str, str, str, str]]:
    """Extract location from URL slug (e.g. /terreno-en-tonacatepeque-cm045)."""
    try:
        from urllib.parse import urlparse
        path = urlparse(url).path.lower()
    except Exception:
        return None
    # Strip common non-location words from the slug tokens
    _STOPWORDS = {"terreno", "finca", "lote", "venta", "en", "de", "la", "el",
                  "propiedad", "property", "land", "sale", "playa", "beach", "for"}
    tokens = re.split(r'[-/]', path)
    for tok in tokens:
        tok = tok.strip()
        if len(tok) < 3 or tok in _STOPWORDS:
            continue
        result = _lookup_locality(tok)
        if result:
            return result
    return None


def _search_tourist_only(text: str) -> Optional[tuple[str, str, str, str]]:
    """Search for tourist localities ONLY (not municipalities or departments).

    Used on title/location_text where we want specific zones but NOT the
    municipality/dept fallback (which would prevent the description from
    providing a more precise zone like El Tunco for a La Libertad listing).
    """
    if not text:
        return None
    tl = _norm(text)
    for variant, t in TOURIST_LOOKUP.items():
        if re.search(r'\b' + re.escape(variant) + r'\b', tl):
            return (t["slug"], t["municipality"], t["department"], "specific")
    return None


def _search_muni_dept_only(text: str) -> Optional[tuple[str, str, str, str]]:
    """Search for municipality or department names (NOT tourist zones).

    Used as a fallback AFTER zone-specific search has already failed.
    """
    if not text:
        return None
    tl = _norm(text)
    # Municipality — longer names first to avoid partial matches
    for variant in sorted(MUNI_LOOKUP, key=len, reverse=True):
        if re.search(r'\b' + re.escape(variant) + r'\b', tl):
            name, dept = MUNI_LOOKUP[variant]
            slug = variant.replace(" ", "-")
            return (slug, name, dept, "municipality")
    # Department only
    for variant, dept_canon in DEPT_LOOKUP.items():
        if re.search(r'\b' + re.escape(variant) + r'\b', tl):
            return (None, None, dept_canon, "department")
    return None


def _resolve_zone(
    location_text: str,
    title: str,
    description: str,
    url: str,
) -> tuple[Optional[str], Optional[str], Optional[str], str]:
    """Multi-tier zone resolver.

    Specific-zone tiers run first (T1–T5), then municipality/dept fallback
    (T6–T8). This ensures a "La Libertad" in location_text doesn't shadow
    "El Tunco" found in the description.

      T1  Structured "Locality, Department, El Salvador" in title
      T2  Tourist/zone-specific in location_text + title
      T3  Legacy ZONE_PATTERNS on all text (backward compat for oceanside)
      T4  Tourist/zone in description WITH context guard
      T5  URL slug analysis
      T6  Structured parse of location_text CSV (municipality/dept)
      T7  Municipality/dept in title
      T8  Municipality/dept in description (context-guarded)

    Returns (zone_slug, municipality, department, confidence).
    """
    # T1 — structured title ("Jiquilisco, Usulután, El Salvador")
    z, m, d = _detect_zone_structured(title)
    if z or d:
        return (z, m, d, "specific" if z else "municipality")

    # T2 — tourist/zone-specific in location_text + title (no description yet)
    combined = (location_text + " " + title).strip()
    res = _search_tourist_only(combined)
    if res:
        return res

    # T3 — legacy ZONE_PATTERNS on full text including description (backward compat)
    z, m, d = detect_zone(location_text + " " + title + " " + description)
    if z:
        return (z, m, d, "specific")

    # T4 — tourist/zone in description WITH context guard (only if T3 missed)
    res = _search_localities_in_text(description, use_context=True)
    if res and res[3] == "specific":
        return res

    # T5 — URL slug analysis
    res = _slug_localities(url)
    if res:
        return res

    # T6 — parse location_text as structured CSV (municipality/dept fallback)
    res = _parse_loc_text(location_text)
    if res:
        return res

    # T7 — municipality/dept in title
    res = _search_muni_dept_only(title)
    if res:
        return res

    # T8 — municipality/dept in description (context-guarded via existing fn)
    res = _search_localities_in_text(description, use_context=True)
    if res:
        return res

    return (None, None, None, "unresolved")


def is_non_land_title(title: str, source: str) -> bool:
    """Return True if the title signals a non-raw-land listing that should be dropped.

    Only applied to sources that pull mixed inventory (see _TITLE_FILTER_SOURCES).
    Keeps 'Land With House' style titles; drops '3-Bedroom House' titles.
    """
    if source not in _TITLE_FILTER_SOURCES:
        return False
    if _ALWAYS_DROP_RE.search(title):
        return True
    if _HOUSE_RE.search(title) and not _LAND_EXCEPTION_RE.search(title):
        return True
    return False


def normalize(raw: dict, source: str) -> Optional[Listing]:
    """
    Convert a raw scraper dict into a canonical Listing.

    Required raw keys: source_id, url, title.
    Optional raw keys: description, location_text, lat, lng, area_m2,
        raw_size_text, price_usd, raw_price_text, photos_count, days_listed,
        is_beachfront, has_paved_access, is_repriced, broker_name, broker_phone.

    Returns None if the record can't be salvaged (missing both price and area).
    """
    # Required identity
    sid = str(raw.get("source_id") or "").strip()
    url = str(raw.get("url") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not sid or not url:
        return None

    # Drop sold / under-contract listings before we spend any work normalizing
    # them. Brokers commonly leave these indexed for SEO; they pollute the
    # ranker because their advertised prices no longer reflect the market.
    # Some sites (oceanside seen) keep the title clean and put the SOLD marker
    # only in the body blob that ends up in raw_price_text/raw_size_text — so
    # we check those too. Pulled forward of any parsing work.
    description = str(raw.get("description") or "")
    raw_size_text = str(raw.get("raw_size_text") or "")
    raw_price_text = str(raw.get("raw_price_text") or "")
    if is_sold(title, description, raw_price_text, raw_size_text):
        return None

    # Phase 1: drop non-land listings by title pattern (bienesraices/remax/goodlife only)
    if is_non_land_title(title, source):
        return None

    # Area: prefer pre-computed, else parse raw_size_text
    area_m2 = raw.get("area_m2")
    if area_m2 is None and raw_size_text:
        parsed = parse_area(raw_size_text)
        if parsed:
            area_m2 = parsed.area_m2

    # Price: prefer pre-computed, else parse raw_price_text
    price_usd = raw.get("price_usd")
    if price_usd is None and raw_price_text:
        price_usd = parse_price_usd(raw_price_text)

    # If neither area nor price, drop the record (can't rank it)
    if area_m2 is None and price_usd is None:
        return None

    # Zone snapping — multi-tier resolver (highest confidence first).
    # Each tier short-circuits on a hit.  Scraper-supplied zone (raw["zone"])
    # takes priority over all tiers at return time.
    location_text = str(raw.get("location_text") or "")

    zone, muni, dept, zone_confidence = _resolve_zone(
        location_text=location_text,
        title=title,
        description=description,
        url=url,
    )

    # Property-type tagging. Honor any explicit value the scraper supplied;
    # otherwise classify from the text. Used by the ranker to segment comp
    # pools so houses don't drag the lot $/m² distribution.
    property_type = str(raw.get("property_type") or detect_property_type(title, description, location_text))

    # Phase 3: development / gated-community tagging
    is_in_development, development_name = detect_development(title, description)

    # Derived $/m²
    price_per_m2 = None
    if area_m2 and price_usd and area_m2 > 0:
        price_per_m2 = round(price_usd / area_m2, 2)

    return Listing(
        source=source,
        source_id=sid,
        url=url,
        scraped_at=raw.get("scraped_at") or datetime.now(timezone.utc).isoformat(),
        title=title or "(untitled)",
        description=description,
        country="SV",
        department=raw.get("department") or dept,
        municipality=raw.get("municipality") or muni,
        zone=raw.get("zone") or zone,
        location_text=location_text,
        lat=raw.get("lat"),
        lng=raw.get("lng"),
        area_m2=round(area_m2, 2) if area_m2 else None,
        raw_size_text=raw_size_text,
        price_usd=round(price_usd, 2) if price_usd else None,
        raw_price_text=raw_price_text,
        price_per_m2=price_per_m2,
        property_type=property_type,
        is_in_development=is_in_development,
        development_name=development_name,
        is_beachfront=bool(raw.get("is_beachfront", False)),
        has_paved_access=bool(raw.get("has_paved_access", False)),
        has_water=bool(raw.get("has_water", False)),
        has_power=bool(raw.get("has_power", False)),
        is_repriced=bool(raw.get("is_repriced", False)),
        days_listed=raw.get("days_listed"),
        photos_count=int(raw.get("photos_count") or len(raw.get("photo_urls") or [])),
        photo_urls=list(raw.get("photo_urls") or []),
        broker_name=raw.get("broker_name"),
        broker_phone=raw.get("broker_phone"),
        broker_email=raw.get("broker_email"),
        zone_confidence=zone_confidence if not raw.get("zone") else "specific",
    )
