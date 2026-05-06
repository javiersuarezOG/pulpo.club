"""
Tests for automation/llm_enrichment_schema.py — pins the eligibility,
validation, and atomic-apply contract for the single-call DeepSeek
enrichment pass.

The schema module is the single source of truth for:
  - which fields gate the eligibility check
  - what shape the LLM JSON response must have
  - how a validated response is written onto a listing

These tests pin all three dimensions so future edits to the schema
fail loudly when they break the contract, rather than silently shipping
partial/malformed enrichment to production.

No network, no LLM client — pure data.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.llm_enrichment_schema import (   # noqa: E402
    DEFAULT_SCHEMA,
    EnrichmentField,
    EnrichmentSchema,
    apply_response,
    is_eligible,
    validate_response,
)


# ── helpers ────────────────────────────────────────────────────────────

def _li(**overrides) -> dict:
    """Listing dict with all enrichment-target fields unset by default."""
    base = {
        "source":    "goodlife",
        "source_id": "GL-001",
        "title":     "Raw scraped title",
        "description": "x" * 200,
        # Enrichment targets — all explicitly None/empty so eligibility passes
        "title_canonical":             None,
        "short_description_canonical": None,
        "reasons_to_buy":              [],
        "lat":                         None,
        "lng":                         None,
        "geocoding_confidence":        None,
        "geocoding_source":            None,
        "geocoding_reference":         None,
    }
    base.update(overrides)
    return base


def _ok_response() -> dict:
    """A response that passes every validator in DEFAULT_SCHEMA."""
    return {
        "title":       "Beachfront 5,000 m² lot in El Tunco",
        "description": "A flat, well-positioned parcel " * 5,
        "usps":        ["Direct beach access", "Flat terrain", "Paved road"],
        "latlong": {
            "lat":        13.4912,
            "lng":        -89.3818,
            "source":     "estimated",
            "reference":  "near El Tunco, La Libertad",
            "confidence": "medium",
        },
    }


# ── eligibility check ──────────────────────────────────────────────────

def test_eligibility_passes_when_all_fields_unset():
    eligible, reason = is_eligible(_li())
    assert eligible is True
    assert reason is None


def test_eligibility_skips_when_title_canonical_set():
    eligible, reason = is_eligible(_li(title_canonical="Some title"))
    assert eligible is False
    assert reason == "already_has_title_canonical"


def test_eligibility_skips_when_short_description_canonical_set():
    eligible, reason = is_eligible(_li(short_description_canonical="A description."))
    assert eligible is False
    assert reason == "already_has_short_description_canonical"


def test_eligibility_skips_when_reasons_to_buy_nonempty():
    eligible, reason = is_eligible(_li(reasons_to_buy=["one"]))
    assert eligible is False
    assert reason == "already_has_reasons_to_buy"


def test_eligibility_skips_when_lat_set():
    """Mapbox-grandfathered listings (lat already set) skip the LLM."""
    eligible, reason = is_eligible(_li(lat=13.5))
    assert eligible is False
    assert reason == "already_has_latlong"


def test_eligibility_skips_when_lng_set_only():
    """Either coord alone counts as 'latlong present'."""
    eligible, reason = is_eligible(_li(lng=-89.0))
    assert eligible is False
    assert reason == "already_has_latlong"


def test_eligibility_first_failing_field_wins():
    """When multiple fields are set, the eligibility skip_reason is the
    FIRST schema-order match — stable for telemetry counters."""
    li = _li(title_canonical="set", reasons_to_buy=["set"], lat=13.5)
    eligible, reason = is_eligible(li)
    assert eligible is False
    assert reason == "already_has_title_canonical"


def test_eligibility_blank_strings_count_as_unset():
    """Whitespace-only string is not 'populated'."""
    eligible, _ = is_eligible(_li(title_canonical="   "))
    assert eligible is True


def test_eligibility_works_with_dataclass_like_objects():
    class L:
        def __init__(self):
            self.title_canonical = None
            self.short_description_canonical = None
            self.reasons_to_buy = []
            self.lat = None
            self.lng = None
    eligible, _ = is_eligible(L())
    assert eligible is True

    class L2:
        title_canonical = "set"
        short_description_canonical = None
        reasons_to_buy = []
        lat = None
        lng = None
    eligible, reason = is_eligible(L2())
    assert eligible is False
    assert reason == "already_has_title_canonical"


# ── response validation ────────────────────────────────────────────────

def test_validate_accepts_correct_response():
    ok, reason = validate_response(_ok_response())
    assert ok is True
    assert reason is None


def test_validate_rejects_non_dict():
    ok, reason = validate_response(["not", "a", "dict"])
    assert ok is False
    assert reason == "not_a_dict"


def test_validate_rejects_missing_key():
    r = _ok_response()
    del r["usps"]
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "missing:usps"


def test_validate_rejects_usps_as_string():
    r = _ok_response()
    r["usps"] = "this should be a list"
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "invalid:usps"


def test_validate_rejects_usps_too_few():
    r = _ok_response()
    r["usps"] = ["only", "two"]
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "invalid:usps"


def test_validate_rejects_usps_too_many():
    r = _ok_response()
    r["usps"] = ["a", "b", "c", "d", "e", "f"]
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "invalid:usps"


def test_validate_rejects_lat_outside_sv_bbox():
    r = _ok_response()
    r["latlong"]["lat"] = 0.0   # equator, not El Salvador
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "invalid:latlong"


def test_validate_rejects_lat_as_string():
    r = _ok_response()
    r["latlong"]["lat"] = "13.5"
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "invalid:latlong"


def test_validate_rejects_unknown_confidence():
    r = _ok_response()
    r["latlong"]["confidence"] = "very high"
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "invalid:latlong"


def test_validate_rejects_unknown_source():
    r = _ok_response()
    r["latlong"]["source"] = "guessed"
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "invalid:latlong"


def test_validate_rejects_empty_title():
    r = _ok_response()
    r["title"] = "   "
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "invalid:title"


def test_validate_rejects_bool_as_lat():
    """isinstance(True, int) is True in Python — explicit bool guard."""
    r = _ok_response()
    r["latlong"]["lat"] = True
    ok, reason = validate_response(r)
    assert ok is False
    assert reason == "invalid:latlong"


# ── application (mutation) ─────────────────────────────────────────────

def test_apply_writes_all_target_attrs():
    li = _li()
    apply_response(li, _ok_response())
    assert li["title_canonical"] == "Beachfront 5,000 m² lot in El Tunco"
    assert "well-positioned" in li["short_description_canonical"]
    assert li["reasons_to_buy"] == ["Direct beach access", "Flat terrain", "Paved road"]
    assert li["lat"] == 13.4912
    assert li["lng"] == -89.3818
    assert li["geocoding_confidence"] == "medium"
    assert li["geocoding_source"] == "estimated"
    assert li["geocoding_reference"] == "near El Tunco, La Libertad"


def test_apply_strips_whitespace_on_strings():
    li = _li()
    r = _ok_response()
    r["title"] = "  Padded title  "
    apply_response(li, r)
    assert li["title_canonical"] == "Padded title"


def test_apply_rounds_coords_to_six_decimals():
    li = _li()
    r = _ok_response()
    r["latlong"]["lat"] = 13.123456789
    r["latlong"]["lng"] = -89.987654321
    apply_response(li, r)
    assert li["lat"] == 13.123457
    assert li["lng"] == -89.987654


# ── extensibility (the configurable-schema promise) ────────────────────

def test_custom_schema_can_omit_a_field():
    """A schema with only title + usps eligibility-checks just those."""
    custom = EnrichmentSchema(fields=tuple(
        f for f in DEFAULT_SCHEMA.fields if f.json_key in {"title", "usps"}
    ))
    # Listing has lat set, but lat is no longer in the custom schema
    li = _li(lat=13.5)
    eligible, _ = is_eligible(li, custom)
    assert eligible is True


def test_custom_schema_extends_eligibility_with_new_field():
    """Adding a field to the schema extends both eligibility AND
    validation in one place — that's the WHOLE point of the design."""
    def _present_marketing_tags(li):
        v = li.get("marketing_tags") if isinstance(li, dict) else getattr(li, "marketing_tags", None)
        return isinstance(v, list) and len(v) > 0

    def _valid_marketing_tags(v):
        return isinstance(v, list) and all(isinstance(x, str) for x in v)

    def _apply_marketing_tags(li, v):
        li["marketing_tags"] = list(v) if isinstance(li, dict) else None

    extended = EnrichmentSchema(fields=DEFAULT_SCHEMA.fields + (
        EnrichmentField(
            json_key     = "marketing_tags",
            target_attrs = ("marketing_tags",),
            is_present   = _present_marketing_tags,
            validate     = _valid_marketing_tags,
            apply        = _apply_marketing_tags,
            skip_reason  = "already_has_marketing_tags",
        ),
    ))

    # Eligibility now checks marketing_tags too
    li = _li()
    li["marketing_tags"] = ["one"]
    eligible, reason = is_eligible(li, extended)
    assert eligible is False
    assert reason == "already_has_marketing_tags"

    # Validation now requires marketing_tags in the response
    r = _ok_response()
    ok, reason = validate_response(r, extended)
    assert ok is False
    assert reason == "missing:marketing_tags"

    r["marketing_tags"] = ["beach", "investment"]
    ok, _ = validate_response(r, extended)
    assert ok is True


def test_default_schema_has_expected_fields_in_order():
    """Lock the field order — telemetry skip_reason depends on it."""
    keys = [f.json_key for f in DEFAULT_SCHEMA.fields]
    assert keys == ["title", "description", "usps", "latlong"]


def test_default_schema_uses_deepseek_model_and_env():
    assert DEFAULT_SCHEMA.model == "deepseek-chat"
    assert DEFAULT_SCHEMA.api_key_env == "DEEPSEEK_API_TOKEN"
    assert DEFAULT_SCHEMA.base_url == "https://api.deepseek.com"
    # Generous max_tokens so the JSON doesn't get truncated
    assert DEFAULT_SCHEMA.max_tokens >= 1024
