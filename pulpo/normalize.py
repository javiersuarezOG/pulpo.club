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
        property_type=str(raw.get("property_type") or "land"),
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
