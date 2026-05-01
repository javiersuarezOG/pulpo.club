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
    (r"el\s*cuco|playa\s*el\s*cuco",            "el-cuco",        "Chirilagua",     "San Miguel"),
    (r"playa\s*las?\s*flores|las?\s*flores",    "las-flores",     "Intipucá",       "La Unión"),
    (r"punta\s*mango",                          "punta-mango",    "Intipucá",       "La Unión"),
    (r"el\s*espino|playa\s*espino",             "el-espino",      "Jucuarán",       "Usulután"),
    (r"el\s*tunco",                             "el-tunco",       "Tamanique",      "La Libertad"),
    (r"el\s*sunzal",                            "el-sunzal",      "Tamanique",      "La Libertad"),
    (r"el\s*zonte|zonte",                       "el-zonte",       "Chiltiupán",     "La Libertad"),
    (r"k\s*59|km\s*59|playa\s*san\s*diego",     "san-diego",      "La Libertad",    "La Libertad"),
    (r"mizata",                                 "mizata",         "Teotepeque",     "La Libertad"),
    (r"conchagua|playa\s*el\s*tamarindo",       "conchagua",      "Conchagua",      "La Unión"),
    (r"la\s*libertad\s*puerto",                 "puerto-la-libertad","La Libertad", "La Libertad"),
    (r"la\s*libertad",                          "la-libertad",    "La Libertad",    "La Libertad"),
    (r"la\s*uni[oó]n",                          "la-union",       "La Unión",       "La Unión"),
]

def detect_zone(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (zone_slug, municipality, department) or (None, None, None)."""
    if not text:
        return (None, None, None)
    t = text.lower()
    for pattern, slug, muni, dept in ZONE_PATTERNS:
        if re.search(pattern, t):
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

    # Zone snapping
    location_text = str(raw.get("location_text") or "")
    zone, muni, dept = detect_zone(location_text + " " + title + " " + description)

    # Property-type tagging. Honor any explicit value the scraper supplied;
    # otherwise classify from the text. Used by the ranker to segment comp
    # pools so houses don't drag the lot $/m² distribution.
    property_type = str(raw.get("property_type") or detect_property_type(title, description, location_text))

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
        is_beachfront=bool(raw.get("is_beachfront", False)),
        has_paved_access=bool(raw.get("has_paved_access", False)),
        has_water=bool(raw.get("has_water", False)),
        has_power=bool(raw.get("has_power", False)),
        is_repriced=bool(raw.get("is_repriced", False)),
        days_listed=raw.get("days_listed"),
        photos_count=int(raw.get("photos_count") or 0),
        broker_name=raw.get("broker_name"),
        broker_phone=raw.get("broker_phone"),
        broker_email=raw.get("broker_email"),
    )
