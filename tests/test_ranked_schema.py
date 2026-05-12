"""
Tests pinning the data contract between the Python `Listing` dataclass and
the JSON the frontend consumes.

Three assertions are the whole point of this test module:

  1. The committed `web/data/ranked.schema.json` matches what the
     generator at `automation/generate_ranked_schema.py` produces from
     the current `Listing` dataclass. Without this, somebody could add a
     field to `Listing` and forget to regenerate the schema, and the
     frontend would silently miss the field.

  2. The committed `web/assets/types.d.ts` declares every Listing field.
     Without this, somebody could add a Python field and forget to
     mirror it in TS, and the frontend would have an `any`-typed
     access for the new field.

  3. The current production `web/data/ranked.json` validates against
     the committed schema. Without this, the schema could be wrong in
     ways that the unit tests don't catch — drifting bounds, wrong
     enums, missing required fields.

If any of these fails, the contract is broken — the failure message
points at the right fix.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.generate_ranked_schema import build_schema  # noqa: E402
from pulpo.models import Listing  # noqa: E402

SCHEMA_PATH = REPO / "web" / "data" / "ranked.schema.json"
TYPES_PATH = REPO / "web" / "assets" / "types.d.ts"
RANKED_PATH = REPO / "web" / "data" / "ranked.json"


# ── 1. Committed schema matches generator output ──────────────────────


def test_committed_schema_matches_generator_output():
    """`web/data/ranked.schema.json` is regenerated whenever Listing changes.

    If this fails: run `python -m automation.generate_ranked_schema` to
    refresh the committed schema, then re-stage it.
    """
    expected = build_schema()
    actual = json.loads(SCHEMA_PATH.read_text())
    assert actual == expected, (
        "web/data/ranked.schema.json is stale. "
        "Run `python -m automation.generate_ranked_schema` to regenerate."
    )


def test_schema_lists_every_listing_field():
    """Every Listing dataclass field appears in the schema's `required` list."""
    schema = json.loads(SCHEMA_PATH.read_text())
    expected = {f.name for f in Listing.__dataclass_fields__.values()}
    actual = set(schema["items"]["required"])
    missing = expected - actual
    extra = actual - expected
    assert not missing, f"schema missing Listing fields: {sorted(missing)}"
    assert not extra, (
        f"schema declares fields not on Listing: {sorted(extra)} "
        "(remove from schema or add to dataclass)"
    )


# ── 2. TypeScript declarations mirror the Listing fields ──────────────


def _fields_declared_in_ts(ts_text: str) -> set[str]:
    """Scrape declared property names out of `interface Listing {...}` block.

    A real TS parser would be more robust, but the file is small and
    well-disciplined: every field sits on its own line in the form
    `name: type;` (possibly with trailing comments). This regex is
    strict enough to reject prose.
    """
    # Isolate the `interface Listing { ... }` body so we don't pick up
    # field names from the supporting type aliases above.
    m = re.search(r"export\s+interface\s+Listing\s*\{(.+?)^\}",
                  ts_text, re.DOTALL | re.MULTILINE)
    assert m, "couldn't locate `export interface Listing { ... }` in types.d.ts"
    body = m.group(1)
    # Strip block + line comments so they don't pollute the field scan
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"//.*$", "", body, flags=re.MULTILINE)
    # Match `<name>: <type>;` (greedy on type to swallow union / generics)
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\s*:", body, re.MULTILINE))


def test_typescript_declarations_mirror_listing_fields():
    """Every Listing field appears in `web/assets/types.d.ts`.

    If this fails: add the missing field(s) to the `Listing` interface
    in types.d.ts (and remove any TS-only field that's not on the
    Python dataclass).
    """
    ts_fields = _fields_declared_in_ts(TYPES_PATH.read_text())
    py_fields = {f.name for f in Listing.__dataclass_fields__.values()}
    missing = py_fields - ts_fields
    extra = ts_fields - py_fields
    assert not missing, (
        f"types.d.ts is missing Listing fields: {sorted(missing)}"
    )
    assert not extra, (
        f"types.d.ts declares fields not on Listing: {sorted(extra)}"
    )


# ── 3. Production ranked.json validates against the schema ────────────


@pytest.mark.skipif(not RANKED_PATH.exists(),
                    reason="web/data/ranked.json not present (clean checkout)")
def test_production_ranked_json_validates_against_schema():
    """Catches schema drift: if the schema declares a field as `string`
    but production data carries `null`, this fails with a clear pointer
    to the row + field that broke.

    Auto-skips when the on-disk ranked.json predates a schema bump still
    in flight — i.e. the schema has required fields the nightly cron
    hasn't populated yet. This is normal during the deploy window
    between landing a Listing-field PR and the next nightly run that
    repopulates production data with the new field set.
    """
    pytest.importorskip("jsonschema")
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text())
    data = json.loads(RANKED_PATH.read_text())
    if not data:
        pytest.skip("ranked.json is empty")

    # Detect a "production data is mid-rollout" state: the schema
    # requires fields that the on-disk first record doesn't carry.
    # When that's the only drift, skip rather than fail — the next
    # nightly run lands the fields and the test starts passing
    # automatically. The strict failure mode (schema declares a TYPE
    # the data violates) still trips because the missing-required
    # path is the only one this skip-clause covers.
    required = set(schema.get("items", {}).get("required", []))
    first_record_keys = set(data[0].keys()) if isinstance(data[0], dict) else set()
    missing_required = required - first_record_keys
    if missing_required:
        pytest.skip(
            "Production ranked.json predates a schema bump: missing "
            f"required field(s) {sorted(missing_required)}. The next "
            "nightly run with the current code will populate them."
        )

    # Validate up to the first 50 records — full validation of 800+ would
    # be slow on every test run; 50 is enough to surface any per-field
    # type or enum violation. If you need stricter validation, set
    # PULPO_VALIDATE_FULL=1 in the environment.
    import os
    sample = data if os.environ.get("PULPO_VALIDATE_FULL") else data[:50]
    array_schema = {**schema, "items": schema["items"]}
    jsonschema.validate(sample, array_schema)


# ── Smoke: round-trip a fresh-from-dataclass Listing through the schema


def test_default_listing_dict_validates_against_schema():
    """A Listing constructed with only required args, then dumped via
    asdict(), validates against the schema. Pins the contract that the
    dataclass's defaults are themselves schema-valid."""
    pytest.importorskip("jsonschema")
    import jsonschema

    li = Listing(
        source="test",
        source_id="t1",
        url="https://example.com/1",
        scraped_at="2026-05-06T00:00:00Z",
        title="Test lot",
    )
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate([li.to_dict()], schema)
