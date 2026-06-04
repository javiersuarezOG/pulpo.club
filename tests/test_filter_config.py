"""Tests for pulpo.filter_config — the visibility strictness slider.

PR A2 of the inventory-expansion workstream. Three named strictness
levels (strict | moderate | lenient) live in
``pulpo/filter_config.py``; one config flip
(``PULPO_FILTER_STRICTNESS=...``) changes which listings the FE renders
on shelves, with no code deploy.

Every level requires the immutable floor (price_usd + url +
property_type). Beyond that:

- strict: + zone + area_m2 + ≥1 photo
- moderate: + zone (PRD default)
- lenient: (nothing else above the floor)
"""
from __future__ import annotations

import pytest

from pulpo.filter_config import (
    DEFAULT_LEVEL,
    FLOOR_REQUIRED,
    STRICTNESS_LEVELS,
    active_level,
    derive_incomplete_reasons,
    derive_is_incomplete,
    derive_is_incomplete_for_level,
)


def _li(**fields):
    base = {
        "url": "https://example.test/x",
        "price_usd": 100_000,
        "area_m2": 500,
        "property_type": "land",
        "zone": "el-zonte",
        "photos_count": 3,
    }
    base.update(fields)
    return base


@pytest.fixture
def reset_env(monkeypatch):
    monkeypatch.delenv("PULPO_FILTER_STRICTNESS", raising=False)


# ── Active-level resolution ────────────────────────────────────────────


def test_active_level_defaults_to_moderate(reset_env):
    assert active_level() == "moderate"
    assert active_level() == DEFAULT_LEVEL


def test_active_level_reads_env_var(reset_env, monkeypatch):
    monkeypatch.setenv("PULPO_FILTER_STRICTNESS", "strict")
    assert active_level() == "strict"
    monkeypatch.setenv("PULPO_FILTER_STRICTNESS", "lenient")
    assert active_level() == "lenient"


def test_active_level_falls_back_on_unknown(reset_env, monkeypatch):
    monkeypatch.setenv("PULPO_FILTER_STRICTNESS", "garbage")
    assert active_level() == "moderate"
    monkeypatch.setenv("PULPO_FILTER_STRICTNESS", "")
    assert active_level() == "moderate"


def test_active_level_is_case_insensitive(reset_env, monkeypatch):
    monkeypatch.setenv("PULPO_FILTER_STRICTNESS", "STRICT")
    assert active_level() == "strict"


# ── Immutable floor ────────────────────────────────────────────────────


def test_every_level_requires_the_floor():
    for name, spec in STRICTNESS_LEVELS.items():
        for floor in FLOOR_REQUIRED:
            assert floor in spec["required"], f"{name} dropped floor field {floor}"
        # Even lenient must require property_type — without it the
        # listing can't be assigned to any shelf.
        assert "property_type" in spec["required"], f"{name} dropped property_type"


def test_floor_required_includes_price_and_url():
    assert "price_usd" in FLOOR_REQUIRED
    assert "url" in FLOOR_REQUIRED


def test_agricultural_exclusion_is_on_at_every_level():
    """Agricultural is a category exclusion, not a quality filter.
    Even lenient keeps the FE filter on."""
    for name, spec in STRICTNESS_LEVELS.items():
        assert spec["exclude_agricultural"] is True, f"{name} disabled agricultural exclusion"


# ── derive_is_incomplete_for_level ─────────────────────────────────────


def test_complete_listing_passes_every_level():
    li = _li()
    for level in STRICTNESS_LEVELS:
        flag, reasons = derive_is_incomplete_for_level(li, level)
        assert flag is False, f"{level} flagged a complete listing"
        assert reasons == []


def test_missing_price_blocks_every_level():
    li = _li(price_usd=None)
    for level in STRICTNESS_LEVELS:
        flag, reasons = derive_is_incomplete_for_level(li, level)
        assert flag is True
        assert "no_price_usd" in reasons


def test_missing_url_blocks_every_level():
    li = _li(url=None)
    for level in STRICTNESS_LEVELS:
        flag, reasons = derive_is_incomplete_for_level(li, level)
        assert flag is True
        assert "no_url" in reasons


def test_missing_property_type_blocks_every_level():
    li = _li(property_type=None)
    for level in STRICTNESS_LEVELS:
        flag, reasons = derive_is_incomplete_for_level(li, level)
        assert flag is True
        assert "no_property_type" in reasons


def test_missing_zone_blocks_strict_and_moderate_but_not_lenient():
    li = _li(zone=None)
    assert derive_is_incomplete_for_level(li, "strict")[0] is True
    assert derive_is_incomplete_for_level(li, "moderate")[0] is True
    flag, reasons = derive_is_incomplete_for_level(li, "lenient")
    assert flag is False
    assert reasons == []


def test_missing_area_blocks_strict_only():
    """The PRD-defined moderate gate requires type+zone+price, NOT area.
    A missing-area listing is the litmus test for the slider's lift."""
    li = _li(area_m2=None)
    assert derive_is_incomplete_for_level(li, "strict")[0] is True
    assert derive_is_incomplete_for_level(li, "moderate")[0] is False
    assert derive_is_incomplete_for_level(li, "lenient")[0] is False


def test_no_photos_blocks_strict_only():
    li = _li(photos_count=0)
    assert derive_is_incomplete_for_level(li, "strict")[0] is True
    assert derive_is_incomplete_for_level(li, "moderate")[0] is False
    assert derive_is_incomplete_for_level(li, "lenient")[0] is False


def test_unknown_level_falls_back_to_default():
    li = _li()
    flag, _ = derive_is_incomplete_for_level(li, "garbage")
    # garbage falls back to moderate which the complete listing passes
    assert flag is False


def test_reasons_capture_every_failing_gate_not_just_first():
    """Diagnostic completeness: a listing missing multiple fields
    reports ALL of them so the audit can do per-reason fan-out."""
    li = _li(price_usd=None, zone=None, property_type=None)
    _, reasons = derive_is_incomplete_for_level(li, "moderate")
    assert "no_price_usd" in reasons
    assert "no_zone" in reasons
    assert "no_property_type" in reasons
    assert len(reasons) == 3


# ── derive_is_incomplete (live entry) ──────────────────────────────────


def test_live_entry_honors_env_var(reset_env, monkeypatch):
    """A listing missing only area is visible under moderate (the new
    default) but hidden under strict — flipping the env var alone
    changes the live filter."""
    li_no_area = _li(area_m2=None)

    monkeypatch.setenv("PULPO_FILTER_STRICTNESS", "moderate")
    assert derive_is_incomplete(li_no_area) is False

    monkeypatch.setenv("PULPO_FILTER_STRICTNESS", "strict")
    assert derive_is_incomplete(li_no_area) is True

    monkeypatch.setenv("PULPO_FILTER_STRICTNESS", "lenient")
    assert derive_is_incomplete(li_no_area) is False


def test_derive_incomplete_reasons_returns_empty_when_complete(reset_env):
    li = _li()
    assert derive_incomplete_reasons(li) == []


def test_derive_incomplete_reasons_under_strict(reset_env, monkeypatch):
    monkeypatch.setenv("PULPO_FILTER_STRICTNESS", "strict")
    li = _li(area_m2=None, photos_count=0)
    reasons = derive_incomplete_reasons(li)
    assert "no_area_m2" in reasons
    assert "no_photos" in reasons


# ── Backward-compat: pulpo.derived_rules.derive_is_incomplete ──────────


def test_derived_rules_re_export_still_works(reset_env):
    """Existing callers (ranker hard-floor, automation/run.py) import
    from pulpo.derived_rules. PR A2 keeps that import path working by
    delegating to filter_config."""
    from pulpo.derived_rules import derive_is_incomplete as _dr_derive

    # Complete listing passes
    assert _dr_derive(_li()) is False
    # Missing price fails (every level)
    assert _dr_derive(_li(price_usd=None)) is True


# ── Empty / non-string photo handling ──────────────────────────────────


def test_photo_count_reads_from_photos_field_when_count_missing():
    li = _li()
    del li["photos_count"]
    li["photos"] = ["a", "b", "c"]
    flag, _ = derive_is_incomplete_for_level(li, "strict")
    assert flag is False  # 3 photos > 0


def test_empty_string_url_is_missing():
    li = _li(url="   ")
    flag, reasons = derive_is_incomplete_for_level(li, "lenient")
    assert flag is True
    assert "no_url" in reasons
