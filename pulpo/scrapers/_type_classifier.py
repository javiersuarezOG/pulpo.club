"""Multi-signal property-type classifier.

Replaces single-keyword title checks. Each signal carries a weight; the
type with the highest cumulative weight wins, gated by a minimum-confidence
threshold below which the listing is reported as `uncertain` (caller may
choose to FLAG for review rather than blindly classify).

Signals, by weight (highest first):
  3.0  broker_field          Broker's own structured type (most authoritative)
  2.5  url_slug              URL contains a type keyword
  2.0  photo_filenames       ≥2 photo URLs share a type keyword
  1.5  title_first_5         First 5 words of title contain a type keyword
  1.0  description_first_sentence
  0.5  title_anywhere        Fallback only — used iff no other signal fired

Confidence buckets:
  total ≥ 4.0  → high
  total ≥ 2.5  → medium
  total ≥ 1.5  → low
  total < 1.5  → uncertain (caller should FLAG)

The scoring weights were chosen to make a single high-quality signal (broker
field, URL slug) sufficient on its own for `low` confidence, while two
agreeing weak signals (title + description) reach `medium`.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from typing import Literal, Optional

from automation.property_types import TYPE_KEYWORDS, PLACE_NAME_EXCLUSIONS

PropertyType = Literal["land", "house", "condo"]
Confidence = Literal["high", "medium", "low", "uncertain"]

# Pre-compile regex sets once. The keyword regexes are case-insensitive;
# place-name exclusions strip false-positive substrings before scoring.
_KW_PATTERNS: dict[str, list[re.Pattern]] = {
    ptype: [re.compile(p, re.IGNORECASE) for p in pats]
    for ptype, pats in TYPE_KEYWORDS.items()
}
_EXCLUSION_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in PLACE_NAME_EXCLUSIONS
]


@dataclass(frozen=True)
class TypeSignal:
    type: PropertyType
    weight: float
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


# Broker-side label → canonical type. Conservative: unknown labels return None
# rather than guessing, so the caller knows to fall through to text signals.
_BROKER_LABEL_MAP: dict[str, PropertyType] = {
    # land
    "land": "land", "lot": "land", "lote": "land", "lotes": "land",
    "terreno": "land", "terrenos": "land", "finca": "land", "fincas": "land",
    "lote_residencial": "land", "lote_comercial": "land",
    "propiedad_de_desarrollo": "land",
    "tierra": "land", "rancho": "land", "hacienda": "land",
    # house
    "house": "house", "casa": "house", "villa": "house", "villas": "house",
    "residencia": "house", "chalet": "house", "single_family": "house",
    # condo
    "apartment": "condo", "apartamento": "condo", "condo": "condo",
    "condominio": "condo", "departamento": "condo", "depa": "condo",
    "loft": "condo",
}


def _map_broker_label_to_type(raw: str) -> Optional[PropertyType]:
    if not raw:
        return None
    return _BROKER_LABEL_MAP.get(raw.strip().lower())


def _strip_exclusions(text: str) -> str:
    """Remove all PLACE_NAME_EXCLUSIONS substrings before keyword scoring."""
    out = text
    for rx in _EXCLUSION_PATTERNS:
        out = rx.sub(" ", out)
    return out


def _detect_type_in_text(
    text: str, weight: float, source: str, *, min_matches: int = 1
) -> Optional[TypeSignal]:
    """Score TYPE_KEYWORDS against text, returning the winning signal or None.

    `min_matches` lets the photo-filenames signal demand at least 2 hits before
    counting (a single noisy filename shouldn't tip a listing).
    """
    if not text:
        return None
    cleaned = _strip_exclusions(text.lower())

    counts = {"land": 0, "house": 0, "condo": 0}
    for ptype, patterns in _KW_PATTERNS.items():
        for rx in patterns:
            counts[ptype] += len(rx.findall(cleaned))

    best = max(counts, key=counts.get)
    if counts[best] >= min_matches and counts[best] > 0:
        return TypeSignal(best, weight, source)  # type: ignore[arg-type]
    return None


def classify_property_type(
    listing_data: dict, *, fallback_type: PropertyType = "land"
) -> tuple[PropertyType, list[TypeSignal], Confidence, float]:
    """Classify a listing from its raw scraped fields.

    `listing_data` is a partially-built raw dict (whatever the scraper has
    extracted): expects optional keys `broker_type_field`, `url`, `photo_urls`,
    `title`, `description`. Missing keys are tolerated.

    Returns (type, signals, confidence, total_weight).

    `fallback_type` is what's returned when confidence is `uncertain` —
    callers should typically ALSO mark such listings as flagged so a human
    can review, rather than treating the fallback as authoritative.
    """
    signals: list[TypeSignal] = []

    broker = listing_data.get("broker_type_field") or ""
    if mapped := _map_broker_label_to_type(broker):
        signals.append(TypeSignal(mapped, 3.0, "broker_field"))

    url = listing_data.get("url") or ""
    if s := _detect_type_in_text(url, weight=2.5, source="url_slug"):
        signals.append(s)

    photos = listing_data.get("photo_urls") or []
    if photos:
        photo_text = " ".join(p for p in photos if isinstance(p, str))
        if s := _detect_type_in_text(
            photo_text, weight=2.0, source="photo_filenames", min_matches=2
        ):
            signals.append(s)

    title = listing_data.get("title") or ""
    title_first_5 = " ".join(title.split()[:5])
    if s := _detect_type_in_text(title_first_5, weight=1.5, source="title_first_5"):
        signals.append(s)

    desc = listing_data.get("description") or ""
    first_sentence = desc.split(".")[0] if desc else ""
    if s := _detect_type_in_text(
        first_sentence, weight=1.0, source="description_first_sentence"
    ):
        signals.append(s)

    if not signals:
        if s := _detect_type_in_text(title, weight=0.5, source="title_anywhere"):
            signals.append(s)

    sums = {"land": 0.0, "house": 0.0, "condo": 0.0}
    for sig in signals:
        sums[sig.type] += sig.weight

    best_type = max(sums, key=sums.get)
    total = sums[best_type]

    if total < 1.5:
        return (fallback_type, signals, "uncertain", total)
    elif total < 2.5:
        return (best_type, signals, "low", total)  # type: ignore[return-value]
    elif total < 4.0:
        return (best_type, signals, "medium", total)  # type: ignore[return-value]
    else:
        return (best_type, signals, "high", total)  # type: ignore[return-value]
