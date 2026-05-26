"""
Pins parity between the backend MACRO_ZONE table (single source of truth
for zone → macro-region mapping, lives in pulpo/ranker_legs/value.py)
and the frontend ZONE_TO_MACRO_REGION constant in web/app/pages.jsx.

Why this matters: when a zone qualifies for the macro tier but not the
zone tier, the FE substitutes a {scope} label resolved via
ZONE_TO_MACRO_REGION → i18n key zone.macro.<macro>. If the FE map is
missing an entry the backend has, the FE silently falls back to the
pretty zone name — turning an honest "the central Pacific region" label
into a misleading "El Tunco" one (the comparison pool is actually
broader than the user is told).

The two maps must stay in lockstep. This test parses the FE constant
out of pages.jsx text and asserts key-by-key equality with MACRO_ZONE.

If this test fails:
  - Backend added a zone slug to MACRO_ZONE? Mirror it in
    web/app/pages.jsx's ZONE_TO_MACRO_REGION literal.
  - Removed a zone? Remove from both.
  - The FE map should not have entries the backend lacks (otherwise the
    FE would label a macro tier the backend would never actually pick).
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pulpo.ranker_legs.value import MACRO_ZONE  # noqa: E402

PAGES_JSX = REPO / "web" / "app" / "pages.jsx"


def _extract_fe_map() -> dict[str, str]:
    """Parse ZONE_TO_MACRO_REGION out of pages.jsx as a dict.

    Tolerant of whitespace + trailing commas. Aborts loudly if the const
    can't be located (rename refactors would otherwise silently bypass
    this test).
    """
    text = PAGES_JSX.read_text(encoding="utf-8")
    block_match = re.search(
        r"const\s+ZONE_TO_MACRO_REGION\s*=\s*\{([^}]+)\}",
        text,
        re.DOTALL,
    )
    if not block_match:
        raise AssertionError(
            "Could not locate `const ZONE_TO_MACRO_REGION = { ... }` in "
            f"{PAGES_JSX}. If you renamed or moved the constant, update "
            "this test's regex (or the constant name) so parity stays "
            "enforced."
        )
    body = block_match.group(1)
    pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', body)
    return dict(pairs)


def test_fe_macro_map_can_be_parsed():
    fe = _extract_fe_map()
    assert fe, "ZONE_TO_MACRO_REGION parsed as empty — regex needs an update"


def test_fe_macro_map_matches_backend():
    """Every (zone, macro) pair must be identical on both sides."""
    fe = _extract_fe_map()
    py = dict(MACRO_ZONE)
    only_be = set(py) - set(fe)
    only_fe = set(fe) - set(py)
    mismatched = {k for k in set(py) & set(fe) if py[k] != fe[k]}
    msg = []
    if only_be:
        msg.append(
            f"backend has zones the FE map is missing: {sorted(only_be)}. "
            "Add them to ZONE_TO_MACRO_REGION in web/app/pages.jsx so the "
            "PriceContextBlock can resolve the macro-tier label."
        )
    if only_fe:
        msg.append(
            f"FE has zones the backend MACRO_ZONE doesn't: {sorted(only_fe)}. "
            "Either add them to pulpo/ranker_legs/value.py:MACRO_ZONE or "
            "drop them from the FE map — the FE shouldn't label a tier "
            "the backend would never pick."
        )
    if mismatched:
        rows = ", ".join(f"{k}: BE={py[k]} / FE={fe[k]}" for k in sorted(mismatched))
        msg.append(f"value mismatches: {rows}")
    assert not msg, "\n".join(msg)


def test_fe_macro_targets_are_known_macros():
    """Every macro slug used on the FE must exist as a value in the BE
    table. Catches a typo in the FE that would silently produce an
    untranslated i18n key (e.g. `zone.macro.central-pacifico`)."""
    fe = _extract_fe_map()
    valid_macros = set(MACRO_ZONE.values())
    unknown = {v for v in fe.values() if v not in valid_macros}
    assert not unknown, (
        f"FE map references macro slug(s) the backend doesn't define: "
        f"{sorted(unknown)}. Fix the FE typo or add the macro on the BE."
    )
