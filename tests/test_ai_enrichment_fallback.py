"""
Tests for automation/ai_enrichment_fallback.py — pins the deterministic
title and reasons_to_buy generators against PRD §8.1 / §8.3 specs.

These functions ship Phase 1 AI fields when OpenAI is unavailable
(no key, expired key, no credits, rate-limited), so they're load-bearing
for graceful degradation.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ai_enrichment_fallback import (   # noqa: E402
    _format_size,
    _top_feature,
    _zone_name,
    fallback_title,
    fallback_reasons_to_buy,
    apply_fallbacks,
)


def _li(**kwargs) -> dict:
    base = {
        "source":         "goodlife",
        "source_id":      "GL-001",
        "property_type":  "land",
        "area_m2":        5000.0,
        "zone":           "el-tunco",
        "department":     "La Libertad",
        "is_beachfront":  False,
        "has_ocean_view": False,
        "has_water_body": False,
        "is_repriced":    False,
        "is_flat":        False,
        "is_in_development": False,
        "has_paved_access": False,
        "readiness_score": 0,
        "days_listed":    None,
        "photos_count":   0,
        "zone_confidence":"specific",
    }
    base.update(kwargs)
    return base


# ── _format_size — PRD §8.1 size formatting ────────────────────────────

def test_format_size_hectares_at_threshold():
    assert _format_size(10_000) == "1 ha"


def test_format_size_hectares_above():
    assert _format_size(32_000) == "3.2 ha"


def test_format_size_meters_with_thousands_comma():
    assert _format_size(4_500) == "4,500 m²"


def test_format_size_small():
    assert _format_size(650) == "650 m²"


def test_format_size_zero_and_none():
    assert _format_size(0) is None
    assert _format_size(None) is None


# ── _top_feature — PRD §8.1 priority order ─────────────────────────────

def test_top_feature_beachfront_wins():
    out = _top_feature(_li(is_beachfront=True, has_ocean_view=True, is_flat=True))
    assert out == "Beachfront"


def test_top_feature_ocean_view_when_no_beachfront():
    out = _top_feature(_li(has_ocean_view=True, is_repriced=True))
    assert out == "Ocean View"


def test_top_feature_off_market():
    out = _li(source_type="off_market", is_repriced=True)
    assert _top_feature(out) == "Off-Market"


def test_top_feature_price_reduced():
    assert _top_feature(_li(is_repriced=True)) == "Price Reduced"


def test_top_feature_utilities_connected():
    assert _top_feature(_li(readiness_score=3)) == "Utilities Connected"


def test_top_feature_flat_terrain():
    assert _top_feature(_li(is_flat=True)) == "Flat Terrain"


def test_top_feature_none_when_nothing_qualifies():
    assert _top_feature(_li()) is None


# ── _zone_name ─────────────────────────────────────────────────────────

def test_zone_name_titlecases_slug():
    assert _zone_name(_li(zone="el-tunco")) == "El Tunco"


def test_zone_name_falls_back_to_municipality():
    assert _zone_name(_li(zone=None, municipality="La Libertad")) == "La Libertad"


def test_zone_name_falls_back_to_department():
    assert _zone_name(_li(zone=None, municipality=None, department="San Miguel")) == "San Miguel"


# ── fallback_title — full PRD §8.1 format ──────────────────────────────

def test_title_full_four_parts():
    title = fallback_title(_li(area_m2=12_000, zone="el-cuco", is_beachfront=True))
    assert title == "Raw Land · 1.2 ha · El Cuco · Beachfront"


def test_title_omits_missing_top_feature():
    title = fallback_title(_li(area_m2=4500, zone="el-zonte"))
    assert title == "Raw Land · 4,500 m² · El Zonte"


def test_title_caps_at_80_chars():
    long_zone = "x" * 100
    title = fallback_title(_li(area_m2=5000, zone=long_zone))
    assert len(title) <= 80


def test_title_uses_correct_land_type_label():
    title = fallback_title(_li(property_type="agricultural", area_m2=120_000))
    assert title.startswith("Farm / Agricultural Land")


# ── fallback_reasons_to_buy — PRD §8.3 trigger table ──────────────────

def test_reasons_picks_top_3_by_priority():
    li = _li(
        is_beachfront=True,    # priority 1
        is_repriced=True,      # priority 3
        readiness_score=3,     # priority 4
        is_flat=True,          # priority 8
        has_paved_access=True, # priority 10
    )
    reasons = fallback_reasons_to_buy(li, max_n=3)
    assert len(reasons) == 3
    assert reasons[0].startswith("🏖")
    assert reasons[1].startswith("📉")
    assert reasons[2].startswith("⚡")


def test_reasons_substitutes_zone_placeholder():
    li = _li(is_beachfront=True, zone="punta-mango")
    reasons = fallback_reasons_to_buy(li, max_n=3)
    assert any("Punta Mango" in r for r in reasons)


def test_reasons_empty_when_nothing_triggers():
    li = _li(zone_confidence="unresolved")   # zone_known would otherwise fire
    reasons = fallback_reasons_to_buy(li, max_n=3)
    assert reasons == []


def test_reasons_skips_development_when_name_absent():
    """Don't fire 'Inside {development_name}' when development_name is None."""
    li = _li(is_in_development=True, development_name=None, is_repriced=True)
    reasons = fallback_reasons_to_buy(li, max_n=3)
    # Should NOT contain a development bullet (predicate excludes nameless)
    assert not any("Inside" in r for r in reasons)
    # Should still contain the price-drop bullet
    assert any(r.startswith("📉") for r in reasons)


def test_reasons_truncates_long_bullets():
    """Defensive — any bullet >18 words gets cut."""
    # Hard to trigger naturally; verify the truncation logic doesn't crash
    reasons = fallback_reasons_to_buy(_li(is_beachfront=True))
    for r in reasons:
        assert len(r.split()) <= 18


# ── apply_fallbacks — orchestrator on a dict ──────────────────────────

def test_apply_fallbacks_sets_title_and_reasons_when_empty():
    li = _li(area_m2=5000, zone="el-tunco", is_repriced=True)
    written = apply_fallbacks(li)
    assert "title_canonical" in written
    assert "reasons_to_buy" in written
    assert li["title_canonical"] == "Raw Land · 5,000 m² · El Tunco · Price Reduced"
    assert len(li["reasons_to_buy"]) >= 1


def test_apply_fallbacks_does_not_overwrite_existing():
    """If AI succeeded, fallback must NOT overwrite the AI-generated value."""
    li = _li(
        is_beachfront=True,
        title_canonical="AI-generated title",
        reasons_to_buy=["AI bullet 1", "AI bullet 2"],
    )
    written = apply_fallbacks(li)
    assert written == {}
    assert li["title_canonical"] == "AI-generated title"
    assert li["reasons_to_buy"] == ["AI bullet 1", "AI bullet 2"]


def test_apply_fallbacks_does_not_set_short_description():
    """short_description_canonical needs natural-language flow; fallback skips."""
    li = _li()
    apply_fallbacks(li)
    assert "short_description_canonical" not in li or \
           li.get("short_description_canonical") is None
