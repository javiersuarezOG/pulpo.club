"""Contract tests for automation/description_lint.py — plan 008.

The lint is observability, not a gate: it measures how often the v4
prompt's banned-phrase instruction is violated. The contract pinned
here:

  - clean text → []
  - banned phrases detected case-insensitively (EN + ES)
  - None / empty input → []
  - SUBSTRING match is the documented contract: "discovered" flags
    because the v4 prompt bans the stem "discover" on purpose — any
    inflection of the cliché counts as the cliché.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.description_lint import (   # noqa: E402
    BANNED_PHRASES,
    lint_description,
)


# ── clean inputs ───────────────────────────────────────────────────────

def test_clean_text_returns_empty_list():
    clean = (
        "Flat 850 m² residential lot in Barrio San Antonio, Santa Ana. "
        "Paved road access, water and power at the boundary, clear title."
    )
    assert lint_description(clean) == []


def test_clean_spanish_text_returns_empty_list():
    clean = (
        "Lote residencial plano de 850 m² en Barrio San Antonio, Santa Ana. "
        "Acceso pavimentado, agua y luz en el límite, escritura en regla."
    )
    assert lint_description(clean) == []


def test_none_input_is_clean():
    assert lint_description(None) == []


def test_empty_string_is_clean():
    assert lint_description("") == []


# ── detection, case-insensitive ────────────────────────────────────────

def test_detects_discover_case_insensitively():
    assert lint_description("Discover this amazing lot") == ["discover"]


def test_detects_paraiso_uppercase():
    assert lint_description("UN PARAÍSO EN LA COSTA") == ["paraíso"]


def test_detects_dont_miss():
    assert lint_description("A great lot — don't miss it!") == ["don't miss"]


def test_detects_multiple_phrases():
    text = "Discover this stunning lot in a tranquil paradise"
    found = lint_description(text)
    assert set(found) == {"discover", "stunning", "tranquil", "paradise"}


# ── substring semantics (documented contract) ──────────────────────────

def test_substring_match_flags_inflections():
    # "discovered" DOES flag — the v4 prompt bans the stem "discover" on
    # purpose; substring match is the documented contract, so inflections
    # of a cliché count as the cliché. No word-boundary special-casing.
    assert lint_description("We discovered a gem of a lot") == ["discover"]


# ── list hygiene ───────────────────────────────────────────────────────

def test_banned_phrases_are_lowercase_and_nonempty():
    # The matcher lowercases the input only; entries must already be
    # lowercase or they can never match.
    for phrase in BANNED_PHRASES:
        assert phrase == phrase.lower(), f"{phrase!r} is not lowercase"
        assert phrase.strip(), "empty/whitespace entry in BANNED_PHRASES"
