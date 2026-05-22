"""
Tests for automation/ai_enrichment_dryrun.py — pins prompt construction,
content_quality classification, and cost projection math so future
prompt edits or pricing changes are visible.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ai_enrichment_dryrun import (   # noqa: E402
    _build_input,
    _content_quality,
    _est_tokens,
    _project_costs,
    _system_prompt,
    _user_prompt,
    SYSTEM_TITLE,
    SYSTEM_DESCRIPTION,
    SYSTEM_USPS,
    PRICE_INPUT_PER_M_TOKENS,
    PRICE_OUTPUT_PER_M_TOKENS,
    OUTPUT_TOKEN_BUDGET,
    LAND_TYPE_LABELS,
)


def _li(**kwargs) -> dict:
    base = {
        "source":         "goodlife",
        "source_id":      "GL-001",
        "title":          "5,000 m² lot near El Tunco",
        "description":    "x" * 200,
        "area_m2":        5000.0,
        "price_usd":      300000.0,
        "price_per_m2":   60.0,
        "zone":           "el-tunco",
        "department":     "La Libertad",
        "property_type":  "land",
        "is_beachfront":  False,
        "first_seen_at":  "2026-04-01T12:00:00+00:00",
    }
    base.update(kwargs)
    return base


# ── _content_quality ───────────────────────────────────────────────────

def test_content_quality_high():
    assert _content_quality(_li(description="x" * 500)) == "high"


def test_content_quality_medium():
    assert _content_quality(_li(description="x" * 50)) == "medium"


def test_content_quality_low_when_short():
    assert _content_quality(_li(description="too short")) == "low"


def test_content_quality_low_when_empty():
    assert _content_quality(_li(description="")) == "low"


def test_content_quality_low_when_none():
    assert _content_quality(_li(description=None)) == "low"


# ── _build_input — populated/omitted classification ───────────────────

def test_build_input_omits_nulls():
    inp = _build_input(_li(broker_name=None, is_beachfront=False, days_listed=None))
    assert "broker_name"  in inp.omitted_keys
    assert "is_beachfront" in inp.omitted_keys   # bool False is treated as null
    assert "days_listed" in inp.omitted_keys
    # description was set, so it's populated
    assert "description_raw" in inp.populated


def test_build_input_keeps_land_type_label_even_when_input_missing():
    """LAND_TYPE_LABELS lookup falls back to 'Raw Land' for unknown property_type."""
    inp = _build_input(_li(property_type="weird"))
    assert inp.populated["land_type_label"] == "Raw Land"


def test_land_type_label_lookup():
    """Map land_type → user-facing label per PRD §8.1.
    'agricultural' was removed alongside the agricultural-listing purge."""
    assert LAND_TYPE_LABELS["residential"]  == "Residential Lot"
    assert LAND_TYPE_LABELS["commercial"]   == "Commercial Land"
    assert LAND_TYPE_LABELS["raw"]          == "Raw Land"
    assert "agricultural" not in LAND_TYPE_LABELS


# ── Prompts — system messages from PRD §8 ─────────────────────────────

def test_system_prompt_per_task():
    assert _system_prompt("title_canonical")             == SYSTEM_TITLE
    assert _system_prompt("short_description_canonical") == SYSTEM_DESCRIPTION
    assert _system_prompt("reasons_to_buy")              == SYSTEM_USPS


def test_user_prompt_includes_populated_json():
    inp = _build_input(_li())
    msg = _user_prompt("title_canonical", inp)
    assert "Generate the title" in msg
    assert '"land_type": "land"' in msg or '"land_type":"land"' in msg
    assert '"price_usd"' in msg


# ── _est_tokens — chars/4 estimate ────────────────────────────────────

def test_est_tokens_simple():
    # ~3.8 chars per token, so 38 chars → 10 tokens
    assert _est_tokens("a" * 38) == 10


def test_est_tokens_minimum_one():
    assert _est_tokens("") == 1
    assert _est_tokens("a") == 1


# ── _project_costs — per-task projection ───────────────────────────────

def test_project_costs_three_tasks_match_budget():
    inp = _build_input(_li())
    proj = _project_costs(inp)
    tasks = {t.task: t for t in proj.tasks}
    assert set(tasks.keys()) == {
        "title_canonical", "short_description_canonical", "reasons_to_buy"
    }
    for task, expected_out in OUTPUT_TOKEN_BUDGET.items():
        assert tasks[task].out_tokens == expected_out


def test_project_costs_reasonable_total():
    """Sanity: per-listing cost stays in the 0.0001-0.001 USD band per PRD §FR-6.2."""
    inp = _build_input(_li(description="x" * 800))
    proj = _project_costs(inp)
    assert 0.0001 <= proj.total_cost <= 0.0010


def test_project_costs_uses_correct_pricing():
    """Verify the cost math against the constants."""
    inp = _build_input(_li())
    proj = _project_costs(inp)
    for t in proj.tasks:
        expected = (t.in_tokens  * PRICE_INPUT_PER_M_TOKENS  / 1_000_000
                    + t.out_tokens * PRICE_OUTPUT_PER_M_TOKENS / 1_000_000)
        assert abs(t.cost_usd - expected) < 1e-9
