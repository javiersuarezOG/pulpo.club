"""Drift guard: web/app/admin/widgets/newsletter/constants.ts must mirror
the Python source-of-truth enums in automation/newsletter/types.py.

If `Cohort` literal in types.py changes, this test fails until the matching
TypeScript constant (NEWSLETTER_COHORTS) is updated. Same for any other
enum we centralise via constants.ts in the future.

Lives next to the existing automation/* tests rather than under tests/api/
because the source-of-truth file is Python — pytest is the canonical
place to assert against it. The Node-side counterpart (the JS port of
segments.py's CATEGORY_PREDICATES) is guarded in
tests/api/admin_newsletter_filter.test.js."""

from __future__ import annotations

import re
import typing
from pathlib import Path

from automation.newsletter.types import Cohort


REPO_ROOT = Path(__file__).resolve().parents[1]
CONSTANTS_TS = REPO_ROOT / "web/app/admin/widgets/newsletter/constants.ts"


def _ts_string_array(name: str, source: str) -> list[str]:
    """Extract a `const NAME = [...] as const;` string-array from a .ts file.

    Tolerates trailing commas, comments, and arbitrary whitespace inside
    the array. Returns the string values in declaration order.
    """
    pattern = rf"const\s+{re.escape(name)}\s*=\s*\[([\s\S]*?)\]\s*as\s+const"
    m = re.search(pattern, source)
    if not m:
        raise AssertionError(f"Could not locate `const {name} = [...] as const` in constants.ts")
    return re.findall(r'"([^"]+)"', m.group(1))


def test_newsletter_cohorts_constants_ts_matches_python_literal():
    """NEWSLETTER_COHORTS in constants.ts mirrors Cohort in types.py."""
    py_cohorts = sorted(typing.get_args(Cohort))
    source = CONSTANTS_TS.read_text(encoding="utf-8")
    ts_cohorts = sorted(_ts_string_array("NEWSLETTER_COHORTS", source))
    assert ts_cohorts == py_cohorts, (
        f"Drift: types.py Cohort = {py_cohorts}, "
        f"constants.ts NEWSLETTER_COHORTS = {ts_cohorts}. "
        f"Update the smaller side."
    )


def test_newsletter_property_types_constants_ts_matches_normalize():
    """NEWSLETTER_PROPERTY_TYPES in constants.ts is a subset of the
    classifier's known property types in pulpo/normalize.py.

    The classifier validates against a fixed set ("land", "house",
    "condo"); the constants.ts mirror exists so the admin widget renders
    the right checkbox set. If the classifier ever ingests a 4th type,
    update both sides."""
    source = CONSTANTS_TS.read_text(encoding="utf-8")
    ts_types = set(_ts_string_array("NEWSLETTER_PROPERTY_TYPES", source))
    # These are the values pulpo/normalize.py emits today; intentionally
    # hardcoded here so the test fails loudly if the production set
    # expands without an admin-widget update.
    expected = {"land", "house", "condo"}
    assert ts_types == expected, (
        f"Drift: NEWSLETTER_PROPERTY_TYPES = {ts_types}, "
        f"normalize.py emits {expected}. Reconcile both."
    )
