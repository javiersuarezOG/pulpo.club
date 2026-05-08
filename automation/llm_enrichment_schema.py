"""
Configurable schema for the single-call DeepSeek enrichment pass.

ONE declaration drives:
  - eligibility check (skip listing if any target field already populated)
  - validation of the parsed JSON response
  - atomic application of the validated response onto the listing
  - the JSON shape block in the prompt (rendered at call time)

Adding a 5th derived field later means appending one EnrichmentField to
DEFAULT_SCHEMA.fields — eligibility, validation, and persistence all
evolve together rather than being changed in three places.

Reads/writes are dict-or-dataclass tolerant via _g/_set, mirroring the
helper pattern in automation/price_history.py and automation/geocoding.py
so production Listing objects and test dicts go through the same path.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable


# ── dict / dataclass helpers (pattern shared with price_history.py) ────

def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


# ── presence predicates (eligibility check) ────────────────────────────
# Each returns True iff the listing already has that target field
# populated. The eligibility rule is `any(present)` → skip.

def _present_title(li: Any) -> bool:
    v = _g(li, "title_canonical")
    return isinstance(v, str) and bool(v.strip())


def _present_description(li: Any) -> bool:
    v = _g(li, "short_description_canonical")
    return isinstance(v, str) and bool(v.strip())


def _present_usps(li: Any) -> bool:
    v = _g(li, "reasons_to_buy")
    return isinstance(v, list) and len(v) > 0


def _present_latlong(li: Any) -> bool:
    """Either lat or lng already set counts as 'latlong populated'.

    Per user-confirmed spec: this is intentional. A listing already
    geocoded by a prior Mapbox run (web/data/geocoding_cache.json carries
    coords from before WS2-Phase-2) is grandfathered out of the LLM
    enrichment until partial regeneration is added.
    """
    return _g(li, "lat") is not None or _g(li, "lng") is not None


# ── validators (run on parsed JSON before any persistence) ─────────────
# Fail-closed: any False here → the entire enrichment for this listing
# is rejected. Partial saves are forbidden.

# El Salvador bounding box — same constants as automation/geocoding.py
# (kept duplicated rather than imported to avoid coupling the schema
# module to the legacy Mapbox path).
_SV_BBOX_LAT = (13.0, 14.6)
_SV_BBOX_LNG = (-90.6, -87.6)
_VALID_CONFIDENCES = {"high", "medium", "low"}
_VALID_LATLONG_SOURCES = {"extracted", "estimated"}


def _valid_localized(v: Any, max_chars: int) -> bool:
    """Bilingual {en, es} dict shape.

    Both keys present, both non-empty strings, each ≤ max_chars. Any
    other shape (str, list, missing keys) fails. The prompt asks the
    LLM for both translations; partial translations get rejected so we
    never end up with EN-only or ES-only fields in production.
    """
    if not isinstance(v, dict):
        return False
    en = v.get("en")
    es = v.get("es")
    if not (isinstance(en, str) and 1 <= len(en.strip()) <= max_chars):
        return False
    if not (isinstance(es, str) and 1 <= len(es.strip()) <= max_chars):
        return False
    return True


def _valid_title(v: Any) -> bool:
    """Bilingual title — each language ≤ 200 chars (prompt asks for ≤10 words)."""
    return _valid_localized(v, 200)


def _valid_description(v: Any) -> bool:
    """Bilingual description — each language ≤ 2000 chars (prompt asks for ≤150 words)."""
    return _valid_localized(v, 2000)


def _valid_usps(v: Any) -> bool:
    """List of 3–5 bilingual {en, es} dicts."""
    if not isinstance(v, list):
        return False
    if not (3 <= len(v) <= 5):
        return False
    return all(_valid_localized(x, 200) for x in v)


_VALID_URL_LANGUAGES = {"en", "es", "mixed"}


def _valid_url_language(v: Any) -> bool:
    return v in _VALID_URL_LANGUAGES


def _valid_latlong(v: Any) -> bool:
    """Dict with lat (number, in SV bbox), lng (number, in SV bbox),
    source ∈ {extracted, estimated}, confidence ∈ {high, medium, low},
    reference (string, may be empty)."""
    if not isinstance(v, dict):
        return False
    lat, lng = v.get("lat"), v.get("lng")
    if not (isinstance(lat, (int, float)) and not isinstance(lat, bool)):
        return False
    if not (isinstance(lng, (int, float)) and not isinstance(lng, bool)):
        return False
    if not (_SV_BBOX_LAT[0] <= float(lat) <= _SV_BBOX_LAT[1]):
        return False
    if not (_SV_BBOX_LNG[0] <= float(lng) <= _SV_BBOX_LNG[1]):
        return False
    if v.get("source") not in _VALID_LATLONG_SOURCES:
        return False
    if v.get("confidence") not in _VALID_CONFIDENCES:
        return False
    ref = v.get("reference")
    if ref is not None and not isinstance(ref, str):
        return False
    return True


# ── applicators (mutate listing on validated response) ─────────────────
# Run AFTER all validators pass — partial application is impossible.

def _normalize_localized(v: dict) -> dict:
    """Strip whitespace from both languages and return a fresh dict.

    Defensive: validators already ensured the shape; we just normalize
    so applied data is consistent regardless of LLM response noise.
    """
    return {"en": v["en"].strip(), "es": v["es"].strip()}


def _apply_title(li: Any, v: Any) -> None:
    _set(li, "title_canonical", _normalize_localized(v))


def _apply_description(li: Any, v: Any) -> None:
    _set(li, "short_description_canonical", _normalize_localized(v))


def _apply_usps(li: Any, v: Any) -> None:
    _set(li, "reasons_to_buy", [_normalize_localized(x) for x in v])


def _apply_url_language(li: Any, v: Any) -> None:
    _set(li, "url_language", v)


def _present_url_language(li: Any) -> bool:
    return _g(li, "url_language") in _VALID_URL_LANGUAGES


def _apply_latlong(li: Any, v: Any) -> None:
    _set(li, "lat",                   round(float(v["lat"]), 6))
    _set(li, "lng",                   round(float(v["lng"]), 6))
    _set(li, "geocoding_confidence",  v["confidence"])
    _set(li, "geocoding_source",      v["source"])
    ref = v.get("reference")
    _set(li, "geocoding_reference",   ref.strip() if isinstance(ref, str) else None)


# ── schema definition ──────────────────────────────────────────────────

@dataclass(frozen=True)
class EnrichmentField:
    """One derived field in the enrichment batch.

    Attributes:
        json_key:     key name expected in the LLM's JSON response
        target_attrs: tuple of attributes that get written on the listing
                      when this field is applied (latlong fans out to 5)
        is_present:   eligibility predicate — True iff already populated
        validate:     shape/type validator on the parsed JSON value
        apply:        mutates the listing with the validated value
        skip_reason:  string emitted in telemetry when this field
                      triggers an eligibility skip
    """
    json_key:     str
    target_attrs: tuple[str, ...]
    is_present:   Callable[[Any], bool]
    validate:     Callable[[Any], bool]
    apply:        Callable[[Any, Any], None]
    skip_reason:  str


@dataclass(frozen=True)
class EnrichmentSchema:
    """All knobs the enrichment pass needs. Pass a custom one to
    enrich_listings(...) to extend the field set or swap models."""
    fields:      tuple[EnrichmentField, ...]
    model:       str = "deepseek-chat"
    # Bilingual {en, es} output approximately doubles text volume on title/
    # description/usps. 1024 was tight enough that long descriptions could
    # truncate latlong (which sits at the bottom of the JSON template),
    # surfacing as `schema_invalid:invalid:latlong` in telemetry. 1600
    # gives ~60% headroom for Spanish-side density without a per-call cost
    # bump (DeepSeek charges by tokens used, not max_tokens budget).
    max_tokens:  int = 1600
    temperature: float = 0.3
    base_url:    str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_TOKEN"
    # Schema version 3: bilingual {en, es} dicts on title/description/usps
    # + url_language. Bumped from 1 (post-#149 monolingual revert) so any
    # on-disk sidecar entries written under v1 fail re-validation in
    # _hydrate_from_sidecar and trigger a fresh DeepSeek call.
    schema_version: int = 3


DEFAULT_SCHEMA = EnrichmentSchema(
    fields=(
        EnrichmentField(
            json_key     = "title",
            target_attrs = ("title_canonical",),
            is_present   = _present_title,
            validate     = _valid_title,
            apply        = _apply_title,
            skip_reason  = "already_has_title_canonical",
        ),
        EnrichmentField(
            json_key     = "description",
            target_attrs = ("short_description_canonical",),
            is_present   = _present_description,
            validate     = _valid_description,
            apply        = _apply_description,
            skip_reason  = "already_has_short_description_canonical",
        ),
        EnrichmentField(
            json_key     = "usps",
            target_attrs = ("reasons_to_buy",),
            is_present   = _present_usps,
            validate     = _valid_usps,
            apply        = _apply_usps,
            skip_reason  = "already_has_reasons_to_buy",
        ),
        EnrichmentField(
            json_key     = "latlong",
            target_attrs = ("lat", "lng", "geocoding_confidence",
                            "geocoding_source", "geocoding_reference"),
            is_present   = _present_latlong,
            validate     = _valid_latlong,
            apply        = _apply_latlong,
            skip_reason  = "already_has_latlong",
        ),
        # url_language: detected dominant language of the source listing.
        # Persisted alongside the bilingual canonical fields so the FE can
        # gate the "View on source" link (only show when url_language
        # matches the user's locale OR is "mixed"). Frontend wiring is a
        # follow-up — backend produces the field today.
        EnrichmentField(
            json_key     = "url_language",
            target_attrs = ("url_language",),
            is_present   = _present_url_language,
            validate     = _valid_url_language,
            apply        = _apply_url_language,
            skip_reason  = "already_has_url_language",
        ),
    ),
)


# ── public helpers ─────────────────────────────────────────────────────

def is_eligible(li: Any, schema: EnrichmentSchema = DEFAULT_SCHEMA
                ) -> tuple[bool, str | None]:
    """True iff none of the target enrichment fields is populated.

    Returns (eligible, skip_reason). When eligible, skip_reason is None.
    When not eligible, skip_reason is the first failing field's
    `skip_reason` string — used directly in telemetry.
    """
    for field in schema.fields:
        if field.is_present(li):
            return (False, field.skip_reason)
    return (True, None)


def validate_response(parsed: Any, schema: EnrichmentSchema = DEFAULT_SCHEMA
                      ) -> tuple[bool, str | None]:
    """True iff every required key is present and its value validates.

    Returns (ok, failure_reason). Failure reasons are stable strings
    suitable for telemetry counters:
      - 'not_a_dict'
      - 'missing:<json_key>'
      - 'invalid:<json_key>'
    """
    if not isinstance(parsed, dict):
        return (False, "not_a_dict")
    for field in schema.fields:
        if field.json_key not in parsed:
            return (False, f"missing:{field.json_key}")
        if not field.validate(parsed[field.json_key]):
            return (False, f"invalid:{field.json_key}")
    return (True, None)


def apply_response(li: Any, parsed: dict,
                   schema: EnrichmentSchema = DEFAULT_SCHEMA) -> None:
    """Write the validated response onto the listing.

    Pre-condition: validate_response(parsed, schema) returned (True, None).
    The caller is responsible for that — this function does NOT re-
    validate, so it can be reused to hydrate from a sidecar where the
    payload was validated when first written.
    """
    for field in schema.fields:
        field.apply(li, parsed[field.json_key])
