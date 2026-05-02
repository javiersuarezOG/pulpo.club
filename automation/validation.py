"""
Listing validation layer — runs BETWEEN normalize() and rank().

Every listing gets a disposition:
  PASS  — clean, no changes
  FLAG  — suspicious; kept for ranking but gets validation_status/warnings fields
  DROP  — structural failure; excluded from ranked.json entirely

Public API:
    result = validate(listing_dict)   # dict from Listing.to_dict()
    result.disposition                # "PASS" | "FLAG" | "DROP"
    result.reasons                    # list[str] describing triggered rules

The pipeline adds validation_status / validation_warnings to flagged listings
and writes one line per listing to web/data/validation_log.jsonl.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional
from urllib.parse import urlparse

from automation.validation_bounds import (
    PRICE_DROP_MIN, PRICE_DROP_MAX, PRICE_FLAG_MIN, PRICE_FLAG_MAX,
    AREA_DROP_MIN, AREA_DROP_MAX, AREA_FLAG_MIN, AREA_FLAG_MAX,
    PPM_DROP_MIN, PPM_DROP_MAX, PPM_FLAG_MIN, PPM_FLAG_MAX,
    DAYS_DROP_MIN, DAYS_DROP_MAX, DAYS_FLAG_MAX,
    PHOTOS_DROP_MAX,
    PPM_CONSISTENCY_TOLERANCE, MANZANA_M2,
    COASTAL_ZONES, COASTAL_LARGE_AREA_M2,
    STALE_PHOTOLESS_DAYS,
)

Disposition = Literal["PASS", "FLAG", "DROP"]
RuleFn = Callable[[dict], tuple[Disposition, Optional[str]]]


@dataclass
class ValidationResult:
    disposition: Disposition
    reasons: list[str] = field(default_factory=list)


# ── Country exclusion patterns ─────────────────────────────────────────
# URL slug check: match country name as a word-segment in the URL path.
# Handles slugs like /en-guatemala-, /costa-rica/, /panama/.
_COUNTRY_SLUG_RE = re.compile(
    r'(?:^|[-/])'
    r'(guatemala|honduras|costa.?rica|nicaragua|panam[aá]|m[eé]xico|colombia)'
    r'(?:[-/]|$)',
    re.IGNORECASE,
)

# Title check: country name in first 5 words, OR after comma + en/in.
# "Fincas en Venta en Guatemala" → drops (in first 5 words)
# "Land for Sale, en Guatemala: ..." → drops (after comma + en)
# "Land in El Salvador, similar quality to Guatemala fincas" → PASS
_COUNTRY_IN_TITLE_RE = re.compile(
    r'(?:'
    r'^(?:\w+\s+){0,4}'           # in the first 5 words
    r'|'
    r',\s*(?:en|in)\s+'           # OR after comma + en/in
    r')'
    r'(guatemala|honduras|costa.?rica|nicaragua|panam[aá]|m[eé]xico|colombia)\b',
    re.IGNORECASE,
)

# Description check (first 200 chars): "located in / in [country]" pattern.
_COUNTRY_IN_DESC_RE = re.compile(
    r'(?:located\s+in|ubicad[ao]\s+en|situated\s+in|(?<!\bEl\sSalvador,\s)\bin\s)'
    r'(guatemala|honduras|costa.?rica|nicaragua|panam[aá]|m[eé]xico|colombia)\b',
    re.IGNORECASE,
)

# Manzana unit in title
_MANZANA_RE = re.compile(r'\b(\d+(?:[.,]\d+)?)\s*(?:manzanas?|mz)\b', re.IGNORECASE)

# "located/en/in" context guard for zone names in description
# (prevents false-positive zone extraction from comparative text)
_ZONE_LOCATION_CTX_RE = re.compile(
    r'(?:^|,|\b(?:en|in|located\s+in|ubicad[ao]\s+en)\s)',
    re.IGNORECASE,
)


# ── Rule functions ─────────────────────────────────────────────────────

def _rule_country_url(li: dict) -> tuple[Disposition, Optional[str]]:
    url = li.get("url") or ""
    try:
        path = urlparse(url).path
    except Exception:
        path = url
    m = _COUNTRY_SLUG_RE.search(path)
    if m:
        return ("DROP", f"country_exclusion: url slug contains '{m.group(1).lower()}'")
    return ("PASS", None)


def _rule_country_title(li: dict) -> tuple[Disposition, Optional[str]]:
    title = li.get("title") or ""
    m = _COUNTRY_IN_TITLE_RE.search(title)
    if m:
        return ("DROP", f"country_exclusion: title places listing in '{m.group(1).lower()}'")
    return ("PASS", None)


def _rule_country_desc(li: dict) -> tuple[Disposition, Optional[str]]:
    desc = (li.get("description") or "")[:200]
    m = _COUNTRY_IN_DESC_RE.search(desc)
    if m:
        return ("DROP", f"country_exclusion: description places listing in '{m.group(1).lower()}'")
    return ("PASS", None)


def _rule_price_bounds(li: dict) -> tuple[Disposition, Optional[str]]:
    price = li.get("price_usd")
    if price is None:
        return ("PASS", None)
    if price < PRICE_DROP_MIN or price > PRICE_DROP_MAX:
        return ("DROP", f"bound_violation: price_usd={price} outside drop range [{PRICE_DROP_MIN}, {PRICE_DROP_MAX}]")
    if price < PRICE_FLAG_MIN or price > PRICE_FLAG_MAX:
        return ("FLAG", f"bound_violation: price_usd={price} outside flag range [{PRICE_FLAG_MIN}, {PRICE_FLAG_MAX}]")
    return ("PASS", None)


def _rule_area_bounds(li: dict) -> tuple[Disposition, Optional[str]]:
    area = li.get("area_m2")
    if area is None:
        return ("PASS", None)
    if area < AREA_DROP_MIN or area > AREA_DROP_MAX:
        return ("DROP", f"bound_violation: area_m2={area} outside drop range [{AREA_DROP_MIN}, {AREA_DROP_MAX}]")
    if area < AREA_FLAG_MIN or area > AREA_FLAG_MAX:
        return ("FLAG", f"bound_violation: area_m2={area} outside flag range [{AREA_FLAG_MIN}, {AREA_FLAG_MAX}]")
    return ("PASS", None)


def _rule_ppm_bounds(li: dict) -> tuple[Disposition, Optional[str]]:
    ppm = li.get("price_per_m2")
    if ppm is None or ppm <= 0:
        return ("PASS", None)
    if ppm < PPM_DROP_MIN or ppm > PPM_DROP_MAX:
        return ("DROP", f"bound_violation: price_per_m2={ppm} outside drop range [{PPM_DROP_MIN}, {PPM_DROP_MAX}]")
    if ppm < PPM_FLAG_MIN or ppm > PPM_FLAG_MAX:
        return ("FLAG", f"bound_violation: price_per_m2={ppm} outside flag range [{PPM_FLAG_MIN}, {PPM_FLAG_MAX}]")
    return ("PASS", None)


def _rule_days_bounds(li: dict) -> tuple[Disposition, Optional[str]]:
    days = li.get("days_listed")
    if days is None:
        return ("PASS", None)
    if days < DAYS_DROP_MIN or days > DAYS_DROP_MAX:
        return ("DROP", f"bound_violation: days_listed={days} outside drop range [{DAYS_DROP_MIN}, {DAYS_DROP_MAX}]")
    if days > DAYS_FLAG_MAX:
        return ("FLAG", f"bound_violation: days_listed={days} exceeds flag threshold {DAYS_FLAG_MAX}")
    return ("PASS", None)


def _rule_photos_bounds(li: dict) -> tuple[Disposition, Optional[str]]:
    photos = li.get("photos_count")
    if photos is None:
        return ("PASS", None)
    if photos < 0 or photos > PHOTOS_DROP_MAX:
        return ("DROP", f"bound_violation: photos_count={photos} outside drop range [0, {PHOTOS_DROP_MAX}]")
    return ("PASS", None)


def _rule_ppm_consistency(li: dict) -> tuple[Disposition, Optional[str]]:
    price = li.get("price_usd")
    area  = li.get("area_m2")
    ppm   = li.get("price_per_m2")
    if price is None or area is None or ppm is None or area <= 0 or ppm <= 0:
        return ("PASS", None)
    computed = price / area
    if abs(computed - ppm) / max(ppm, 1e-9) > PPM_CONSISTENCY_TOLERANCE:
        return ("FLAG", (
            f"ppm_inconsistency: stored={ppm:.2f} computed={computed:.2f} "
            f"(price_usd={price}, area_m2={area})"
        ))
    return ("PASS", None)


def _rule_manzana_suspicion(li: dict) -> tuple[Disposition, Optional[str]]:
    title = li.get("title") or ""
    area  = li.get("area_m2")
    m = _MANZANA_RE.search(title)
    if m and area is not None:
        claimed_manzanas = float(m.group(1).replace(",", "."))
        expected_m2 = claimed_manzanas * MANZANA_M2
        # Flag if stored area is < 50% of the manzana-implied area
        if area < expected_m2 * 0.5:
            return ("FLAG", (
                f"unit_suspicion: title claims {claimed_manzanas} manzanas "
                f"(≈{expected_m2:.0f}m²) but area_m2={area}"
            ))
    return ("PASS", None)


def _rule_coastal_large_area(li: dict) -> tuple[Disposition, Optional[str]]:
    zone = li.get("zone") or ""
    area = li.get("area_m2")
    if zone in COASTAL_ZONES and area is not None and area > COASTAL_LARGE_AREA_M2:
        return ("FLAG", (
            f"coastal_large_area: zone={zone} area_m2={area} "
            f"exceeds coastal threshold {COASTAL_LARGE_AREA_M2}"
        ))
    return ("PASS", None)


def _rule_stale_no_photos(li: dict) -> tuple[Disposition, Optional[str]]:
    days   = li.get("days_listed")
    photos = li.get("photos_count", 0)
    if days is not None and days > STALE_PHOTOLESS_DAYS and photos == 0:
        return ("FLAG", f"stale_no_photos: days_listed={days} photos_count=0")
    return ("PASS", None)


def _rule_zero_ppm(li: dict) -> tuple[Disposition, Optional[str]]:
    ppm = li.get("price_per_m2")
    if ppm is not None and ppm == 0.0:
        return ("FLAG", "zero_ppm: price_per_m2 rounds to $0 (likely unit mismatch)")
    return ("PASS", None)


def _rule_zone_unresolved(li: dict) -> tuple[Disposition, Optional[str]]:
    if not li.get("zone"):
        title = (li.get("title") or "")[:80]
        return ("FLAG", f"zone_unresolved: title='{title}'")
    return ("PASS", None)


# ── Registry ───────────────────────────────────────────────────────────
_RULES: list[RuleFn] = [
    _rule_country_url,
    _rule_country_title,
    _rule_country_desc,
    _rule_price_bounds,
    _rule_area_bounds,
    _rule_ppm_bounds,
    _rule_days_bounds,
    _rule_photos_bounds,
    _rule_ppm_consistency,
    _rule_manzana_suspicion,
    _rule_coastal_large_area,
    _rule_stale_no_photos,
    _rule_zero_ppm,
    _rule_zone_unresolved,
]

_DISPOSITION_ORDER = {"DROP": 2, "FLAG": 1, "PASS": 0}


def validate(listing: dict) -> ValidationResult:
    """Run all validation rules. Return strictest disposition + all reasons."""
    worst: Disposition = "PASS"
    reasons: list[str] = []
    for rule in _RULES:
        disp, reason = rule(listing)
        if reason:
            reasons.append(reason)
        if _DISPOSITION_ORDER[disp] > _DISPOSITION_ORDER[worst]:
            worst = disp
    return ValidationResult(worst, reasons)
