"""
Schema v1 validator — checks ranked.json records against
`pulpo/schemas/listing_v1.json`.

Stdlib only — no jsonschema dep. Implements the subset of JSON Schema
draft 2020-12 we actually need (type, required, enum, format=uri/date-time,
minimum/maximum, minLength/maxLength, items, additionalProperties=true).
That's enough to surface real conformance gaps without dragging in a 250 KB
package.

Public API:

    from pulpo.schema_validator import validate, ValidationResult, load_schema
    schema = load_schema()
    result = validate(record, schema)
    result.ok            # bool
    result.errors        # list[str]

CLI:

    python3 -m pulpo.schema_validator --check web/data/ranked.json
        Walks every record, prints a per-source conformance report:
        rows, conformance %, top error families, missing-field rates.
        Exits 0 even on conformance gaps — this is observability, not a
        hard gate (yet). Hard-gating moves to scrapers in a later PR per
        PRD §FR-1.4.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "pulpo" / "schemas" / "listing_v1.json"

# RFC 3339 / ISO 8601 — accept both with and without microseconds, with Z or offset.
_RX_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?$"
)
_RX_URI = re.compile(r"^[a-z][a-z0-9+.-]*:\S+$", re.IGNORECASE)


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _types_of(spec) -> tuple[str, ...]:
    """Resolve `type` to a tuple, since JSON Schema allows array-of-type."""
    t = spec.get("type")
    if t is None:
        return ()
    if isinstance(t, str):
        return (t,)
    return tuple(t)


_TYPE_CHECKS = {
    "string":  lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number":  lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array":   lambda v: isinstance(v, list),
    "object":  lambda v: isinstance(v, dict),
}


def _is_typed(value: Any, t: str) -> bool:
    if value is None:
        return t == "null"
    check = _TYPE_CHECKS.get(t)
    return bool(check and check(value))


def _check_field(name: str, value: Any, spec: dict) -> list[str]:
    """Return a list of error strings for one (field, value, spec) triple."""
    errors: list[str] = []

    # Type check
    types = _types_of(spec)
    if types and not any(_is_typed(value, t) for t in types):
        errors.append(f"{name}: expected {'|'.join(types)}, got {type(value).__name__}")
        return errors  # downstream checks pointless if type is wrong

    # Skip downstream checks on null
    if value is None:
        return errors

    # Enum
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"{name}: value {value!r} not in enum")

    # Numeric bounds
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            errors.append(f"{name}: {value} < minimum {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            errors.append(f"{name}: {value} > maximum {spec['maximum']}")

    # String constraints
    if isinstance(value, str):
        if "minLength" in spec and len(value) < spec["minLength"]:
            errors.append(f"{name}: length {len(value)} < minLength {spec['minLength']}")
        if "maxLength" in spec and len(value) > spec["maxLength"]:
            errors.append(f"{name}: length {len(value)} > maxLength {spec['maxLength']}")
        fmt = spec.get("format")
        if fmt == "uri" and not _RX_URI.match(value):
            errors.append(f"{name}: not a valid URI ({value[:60]!r})")
        if fmt == "date-time" and not _RX_DATETIME.match(value):
            errors.append(f"{name}: not a valid ISO date-time ({value[:60]!r})")

    # Array items
    if isinstance(value, list):
        if "minItems" in spec and len(value) < spec["minItems"]:
            errors.append(f"{name}: items {len(value)} < minItems {spec['minItems']}")
        if "maxItems" in spec and len(value) > spec["maxItems"]:
            errors.append(f"{name}: items {len(value)} > maxItems {spec['maxItems']}")
        items_spec = spec.get("items")
        if isinstance(items_spec, dict):
            for i, item in enumerate(value):
                errors.extend(
                    f"{name}[{i}]:{e.split(':', 1)[-1].strip()}"
                    for e in _check_field(f"{name}[{i}]", item, items_spec)
                )

    return errors


def validate(record: dict, schema: dict) -> ValidationResult:
    """Validate one record. Required fields + per-property checks."""
    result = ValidationResult()

    # Required
    for req in schema.get("required", []):
        if req not in record or record[req] is None or record[req] == "":
            result.errors.append(f"required: missing or empty `{req}`")

    # Per-property
    props: dict = schema.get("properties", {})
    for k, v in record.items():
        spec = props.get(k)
        if spec is None:
            # additionalProperties is True in our schema, so ignore unknowns
            continue
        result.errors.extend(_check_field(k, v, spec))

    result.ok = not result.errors
    return result


# ── CLI / report ────────────────────────────────────────────────────────

def _summarize_errors(errors: list[str]) -> Counter:
    """Group error strings into families by the leading `field: rule` shape."""
    fam: Counter = Counter()
    for e in errors:
        # Drop array indices like `photo_urls[3]` to coalesce
        head = re.sub(r"\[\d+\]", "[]", e.split(":", 1)[0]).strip()
        rule = e.split(":", 1)[1].strip().split(" ")[0] if ":" in e else ""
        fam[f"{head} :: {rule}"] += 1
    return fam


def cmd_check(input_path: Path, schema: dict) -> int:
    if not input_path.exists():
        print(f"ERROR: {input_path} not found", file=sys.stderr)
        return 1
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        print(f"ERROR: {input_path} is not a non-empty list", file=sys.stderr)
        return 1

    n = len(data)
    ok_count = 0
    per_source_total: Counter   = Counter()
    per_source_ok:    Counter   = Counter()
    error_families:   Counter   = Counter()
    missing_fields:   Counter   = Counter()
    per_source_errors: dict[str, Counter] = defaultdict(Counter)

    for r in data:
        src = r.get("source") or "?"
        per_source_total[src] += 1
        result = validate(r, schema)
        if result.ok:
            ok_count += 1
            per_source_ok[src] += 1
        else:
            for e in result.errors:
                error_families[e.split(":", 1)[0].strip()] += 1
                per_source_errors[src][e.split(":", 1)[0].strip()] += 1
                if e.startswith("required:"):
                    missing_fields[e.split("`")[1]] += 1
        for e in result.errors:
            pass

    fams = _summarize_errors(
        [e for r in data for e in validate(r, schema).errors]
    )

    try:
        rel = input_path.resolve().relative_to(REPO)
    except ValueError:
        rel = input_path
    print(f"\nschema: {schema.get('$id')} v{schema.get('version')}")
    print(f"input:  {rel}  ({n} records)\n")

    print(f"{'='*60}\nOverall conformance: {ok_count}/{n} ({100*ok_count/n:.1f}%)\n")

    print(f"Per-source conformance:\n{'-'*60}")
    print(f"{'source':<22} {'records':>9} {'conformant':>11} {'rate':>7}")
    for src in sorted(per_source_total):
        t = per_source_total[src]
        o = per_source_ok[src]
        rate = f"{100*o/t:.0f}%" if t else "-"
        print(f"{src:<22} {t:>9} {o:>11} {rate:>7}")

    if missing_fields:
        print(f"\nMissing required fields (most common):\n{'-'*60}")
        for k, c in missing_fields.most_common(15):
            print(f"  {c:>5}  `{k}`")

    print(f"\nTop error families:\n{'-'*60}")
    for k, c in fams.most_common(15):
        print(f"  {c:>5}  {k}")

    print()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Pulpo Listing Schema v1 validator")
    p.add_argument("--check", type=Path,
                   help="path to ranked.json (or any list of listing dicts) to validate")
    p.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    args = p.parse_args()

    schema = load_schema(args.schema)

    if args.check:
        return cmd_check(args.check, schema)

    # No subcommand: validate the default ranked.json
    return cmd_check(REPO / "web" / "data" / "ranked.json", schema)


if __name__ == "__main__":
    sys.exit(main())
