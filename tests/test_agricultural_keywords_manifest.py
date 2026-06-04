"""Tests for the manifest-driven is_agricultural keyword list (PR D2).

The canonical source for is_agricultural patterns is now per-country:
``pulpo/countries/<cc>.json`` under the ``agricultural_keywords`` key.
``pulpo.nlp_extractor.load_dictionaries`` prefers the manifest section
over the legacy ``nlp_keywords/is_agricultural.json`` file when the
active country carries the section. The legacy file remains as a
fallback during the migration window.

PRD acceptance criterion "Agricultural tag list editable via config"
is satisfied: editing ``sv.json`` deploys without a code change.
"""
from __future__ import annotations

from pulpo.countries import active as _active_country
from pulpo.nlp_extractor import (
    CompiledDict,
    _agricultural_keywords_from_manifest,
    load_dictionaries,
)


def test_active_manifest_carries_agricultural_keywords():
    """SV manifest carries the section (PR D2). Smoke-checks the
    accessor's contract — empty dict means consumers fall back."""
    m = _active_country()
    kw = m.agricultural_keywords()
    assert isinstance(kw, dict)
    assert kw, "SV manifest must carry agricultural_keywords"
    assert "positive_es" in kw
    assert any(
        "finca" in p.lower() for p in kw["positive_es"]
    ), "positive_es must include 'finca' (highest-signal SV keyword)"


def test_manifest_preserves_word_boundaries():
    """Word boundaries (\\b) on single-word patterns are load-bearing
    per CLAUDE.md / 2026-05-24 audit. The manifest move must NOT have
    transformed the patterns."""
    m = _active_country()
    kw = m.agricultural_keywords()
    assert any(
        r"\branch\b" == p for p in kw["positive_en"]
    ), "manifest must preserve \\branch\\b word-boundary"
    assert any(
        r"\bfinca\b" == p for p in kw["positive_es"]
    ), "manifest must preserve \\bfinca\\b word-boundary"


def test_extractor_loads_manifest_override():
    """The compiled CompiledDict returned for is_agricultural must come
    from the manifest, not from the legacy file (verified by the
    presence of an SV-specific keyword unique to the manifest's set)."""
    override = _agricultural_keywords_from_manifest()
    assert isinstance(override, CompiledDict)
    assert override.field == "is_agricultural"
    # The compiled pattern must match a positive SV cue.
    blob = "vendo bonita finca cafetalera con sembradío de café"
    assert override.positive.search(blob) is not None


def test_load_dictionaries_does_not_double_register_is_agricultural():
    """The extractor must NOT compile both the manifest copy AND the
    legacy file's copy for is_agricultural. Double-registration would
    fire patterns twice and could change negation-window semantics."""
    dicts = load_dictionaries()
    agri = [d for d in dicts if d.field == "is_agricultural"]
    assert len(agri) == 1, (
        f"Expected exactly one is_agricultural CompiledDict; got {len(agri)}. "
        f"Did the manifest override fail to suppress the legacy file?"
    )


def test_extractor_still_loads_other_legacy_dictionaries():
    """The legacy nlp_keywords/ directory still provides every OTHER
    boolean field (is_beachfront, has_water, etc.). Suppressing only
    is_agricultural must not affect them."""
    dicts = load_dictionaries()
    fields = {d.field for d in dicts}
    # Smoke-check: more than one field means non-agricultural dicts still
    # load. Exact set check would couple to nlp_keywords/ contents.
    assert len(fields) >= 5, (
        f"Expected legacy nlp_keywords/ to still load multiple fields; "
        f"got only {fields}"
    )


def test_manifest_keywords_negate_former_finca():
    """Negative patterns must continue to suppress 'antigua finca' /
    'former farm' false positives. PR-8 negation-window logic depends
    on these landing in the same CompiledDict.negative regex."""
    override = _agricultural_keywords_from_manifest()
    assert override is not None
    assert override.negative is not None
    blob = "antigua finca reconvertida a residencial"
    assert override.negative.search(blob) is not None


def test_legacy_file_marked_deprecated():
    """Defense against silent removal of the deprecation notice — the
    legacy nlp_keywords/is_agricultural.json header must explain that
    the canonical source is now the manifest."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    legacy = repo / "nlp_keywords" / "is_agricultural.json"
    text = legacy.read_text()
    assert "DEPRECATED" in text.upper() or "_deprecation_notice" in text or "PR D2" in text, (
        "Legacy file must carry a deprecation notice pointing at the manifest."
    )
