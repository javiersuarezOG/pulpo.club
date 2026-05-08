"""
Generates `web/data/ranked.schema.json` from `pulpo.models.Listing`.

The Python `Listing` dataclass is the single source of truth for the shape
of `ranked.json`. The frontend consumes that JSON; we don't want field
renames/additions on either side to silently break the other. This module
turns the dataclass into a JSON Schema document so:

  - `tests/test_ranked_schema.py` can validate any `ranked.json` against it
  - Editors (VS Code) can validate JSON edits via the `$schema` link
  - `web/assets/types.d.ts` (hand-mirrored — see test_ranked_schema.py for
    the field-parity check) gives the JS frontend type-checked field access

Workflow when adding/removing a Listing field:
  1. Update `pulpo/models.py`.
  2. Run `python -m automation.generate_ranked_schema` to refresh the
     committed JSON Schema.
  3. Update `web/assets/types.d.ts` to mirror the new field.
  4. Tests will fail loudly if any of the three is out of sync.

Conscious decisions:
  - Every Listing field is `required` in the schema. The dataclass uses
    `asdict()` for serialization, which always emits every field — so a
    real `ranked.json` always carries all of them, even if many are null.
  - Optional[T] is rendered as `{"type": ["T", "null"]}`. JSON Schema
    `nullable: true` (OpenAPI flavour) doesn't apply in vanilla draft-07.
  - A handful of fields (property_type, zone_confidence, etc.) get an
    enum constraint pulled from the docstring on the dataclass. These
    are explicit overrides; the generator never invents them.
"""
from __future__ import annotations
import dataclasses
import json
import sys
import typing
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.models import Listing  # noqa: E402


# Per-field overrides. The generator can derive type from the dataclass
# annotation, but discrete-value constraints (enums) and ranges live here
# explicitly. Keeping them in code means a drifting docstring won't
# silently invalidate the schema.
_OVERRIDES: dict[str, dict[str, Any]] = {
    "country":              {"const": "SV"},
    "property_type":        {"enum": ["land", "house", "condo"]},
    "zone_confidence":      {"enum": ["specific", "municipality",
                                      "department", "unresolved", None]},
    "geocoding_confidence": {"enum": ["high", "medium", "low", None]},
    "geocoding_source":     {"enum": ["extracted", "estimated", None]},
    "validation_status":    {"enum": ["flagged", None]},
    "investment_signal":    {"enum": ["deal", "hot", "stale", "new", None]},
    # 0..100 composite scores
    "rank_score":           {"minimum": 0, "maximum": 100},
    "value_score":          {"minimum": 0, "maximum": 100},
    "location_score":       {"minimum": 0, "maximum": 100},
    "momentum_score":       {"minimum": 0, "maximum": 100},
    "zone_percentile":      {"minimum": 0, "maximum": 100},
    "data_quality_score":   {"minimum": 0, "maximum": 1},
    "readiness_score":      {"minimum": 0, "maximum": 3},
    # Non-negative quantities
    "bedrooms":             {"minimum": 0},
    "bathrooms":            {"minimum": 0},
    "parking_spaces":       {"minimum": 0},
    "floor":                {"minimum": 0},
    "year_built":           {"minimum": 1800, "maximum": 2100},
    "rank":                 {"minimum": 1},
    "price_usd":            {"minimum": 0},
    "price_per_m2":         {"minimum": 0},
    "price_per_built_m2":   {"minimum": 0},
    "area_m2":              {"minimum": 0},
    "built_area_m2":        {"minimum": 0},
    "hoa_fee_usd_monthly":  {"minimum": 0},
    "days_listed":          {"minimum": 0},
    "photos_count":         {"minimum": 0},
    "dist_airport_km":      {"minimum": 0},
    "dist_beach_km":        {"minimum": 0},
    "dist_highway_km":      {"minimum": 0},
    "dist_nearest_town_km": {"minimum": 0},
    "lat":                  {"minimum": -90,  "maximum": 90},
    "lng":                  {"minimum": -180, "maximum": 180},
    # Schema v3 — bilingual canonical fields. Type is permissive:
    # `object` is the DeepSeek-enriched shape ({en, es} dict), `string` is
    # the fallback-template shape (single-language). The FE adapter
    # (`localizedFromAny` in web/app/data/listings.ts) handles both.
    "title_canonical": {
        "type": ["object", "string", "null"],
        "properties": {"en": {"type": "string"}, "es": {"type": "string"}},
    },
    "short_description_canonical": {
        # No fallback writes this — only DeepSeek does — so it's strictly
        # dict-or-null. (The fallback template explicitly skips this field.)
        "type": ["object", "null"],
        "properties": {"en": {"type": "string"}, "es": {"type": "string"}},
        "required": ["en", "es"],
    },
    "reasons_to_buy": {
        "type": "array",
        "items": {
            "type": ["object", "string"],
            "properties": {"en": {"type": "string"}, "es": {"type": "string"}},
        },
    },
    "url_language": {"enum": ["en", "es", "mixed", None]},
    # PR-8 — NLP enum derives.
    "beachfront_tier":      {"enum": ["on_beach", "walk_to_beach", "near_beach", None]},
    "land_type":            {"enum": ["agricultural", "commercial", "tourist", "residential", None]},
}


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    """True iff annotation is `Optional[X]` / `X | None`. Returns the inner type."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return (len(args) < len(typing.get_args(annotation)), args[0] if args else Any)
    # PEP 604 `X | None` syntax — origin is types.UnionType in 3.10+
    try:
        import types as _types
        if isinstance(annotation, _types.UnionType):  # type: ignore[attr-defined]
            args = [a for a in typing.get_args(annotation) if a is not type(None)]
            return (len(args) < len(typing.get_args(annotation)), args[0] if args else Any)
    except Exception:
        pass
    return (False, annotation)


def _python_type_to_json_type(annotation: Any) -> str | None:
    """Map a primitive Python annotation to a JSON Schema `type` value."""
    # bool BEFORE int — bool is a subclass of int in Python.
    if annotation is str:
        return "string"
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    return None


def _field_to_schema(name: str, annotation: Any) -> dict:
    """Derive the per-field JSON Schema fragment from a dataclass annotation."""
    is_opt, inner = _is_optional(annotation)
    origin = typing.get_origin(inner)

    # list[X]
    if origin is list:
        # If an override is registered for this field, prefer it whole — the
        # override knows the item shape (e.g. {en, es} dicts for
        # reasons_to_buy) better than the generic primitive mapper.
        if name in _OVERRIDES:
            return dict(_OVERRIDES[name])
        item_t = typing.get_args(inner)[0]
        item_json_t = _python_type_to_json_type(item_t)
        if item_json_t is None:
            item_schema: dict = {}    # untyped list — only used for
            # validation_warnings: list[?] which is empty in practice
        else:
            item_schema = {"type": item_json_t}
        return {"type": "array", "items": item_schema}

    primitive = _python_type_to_json_type(inner)
    if primitive is None:
        # Fall back to `any` for fields the generator can't model from the
        # annotation alone (e.g., Optional[Any] for the bilingual canonical
        # fields whose JSON shape lives in _OVERRIDES). The override below
        # supplies the real schema; only fall through to `{}` (any) when
        # no override is present.
        return dict(_OVERRIDES[name]) if name in _OVERRIDES else {}

    schema: dict = {"type": [primitive, "null"] if is_opt else primitive}

    # Apply per-field overrides last so they always win.
    if name in _OVERRIDES:
        ov = dict(_OVERRIDES[name])
        # If override is just a const/enum, keep our type narrowing too
        # (JSON Schema permits both; validators apply both constraints).
        schema.update(ov)
    return schema


def build_schema() -> dict:
    """Return the complete JSON Schema document for an array of Listings."""
    # `Listing` uses `from __future__ import annotations`, so f.type comes
    # back as a string. Resolve via typing.get_type_hints() so we get real
    # type objects to inspect.
    hints = typing.get_type_hints(Listing)
    properties: dict[str, dict] = {}
    field_names: list[str] = []
    for f in dataclasses.fields(Listing):
        properties[f.name] = _field_to_schema(f.name, hints[f.name])
        field_names.append(f.name)

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id":     "https://pulpo.club/schemas/ranked.schema.json",
        "title":   "Pulpo ranked.json (array of Listings)",
        "description": (
            "Auto-generated from pulpo.models.Listing. Do not edit by hand — "
            "run `python -m automation.generate_ranked_schema` after changing "
            "the dataclass. Mirror any field changes in web/assets/types.d.ts."
        ),
        "type":  "array",
        "items": {
            "type":                 "object",
            "additionalProperties": False,
            "required":             field_names,
            "properties":           properties,
        },
    }


def main() -> None:
    schema = build_schema()
    out = REPO / "web" / "data" / "ranked.schema.json"
    out.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(schema['items']['properties'])} fields)")


if __name__ == "__main__":
    main()
