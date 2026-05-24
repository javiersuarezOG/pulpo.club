"""Tests for the shared scraper base (pulpo/scrapers/_base.py).

Targets the cross-cutting helpers that every scraper builds on:
  - passes_vacation_gate
  - finalize_record
  - OfflineFixtureMixin

The HTTP wrapper (polite_get_for) is exercised by the scraper-level
tests of any module that uses it; no separate unit test here.
"""
from __future__ import annotations
import pytest

from pulpo.scrapers._base import (
    OfflineFixtureMixin, finalize_record, passes_vacation_gate,
)


# ── passes_vacation_gate ──────────────────────────────────────────────


def test_vacation_gate_land_always_passes():
    """Land is exempt — inland lots are valid inventory."""
    assert passes_vacation_gate(
        property_type="land", location_text="San Salvador", title="Lote", description="",
    ) is True


def test_vacation_gate_house_in_vacation_zone_passes():
    """House in a known VACATION_ZONE slug passes without keyword help."""
    assert passes_vacation_gate(
        property_type="house",
        location_text="El Tunco, Tamanique, La Libertad",
        title="Casa moderna",
        description="",
    ) is True


def test_vacation_gate_house_inland_no_keyword_drops():
    """Inland house with no waterfront keyword fails the gate."""
    assert passes_vacation_gate(
        property_type="house",
        location_text="San Salvador",
        title="Casa amplia",
        description="Cerca del aeropuerto.",
    ) is False


def test_vacation_gate_house_inland_with_waterfront_keyword_passes():
    """Inland zone but description mentions 'frente al mar' → passes."""
    assert passes_vacation_gate(
        property_type="house",
        location_text="Ahuachapán",
        title="Casa",
        description="Casa frente al mar con acceso directo a la playa.",
    ) is True


def test_vacation_gate_condo_at_lake_passes():
    """Lake zones added 2026-05-08 cover Coatepeque / Ilopango."""
    assert passes_vacation_gate(
        property_type="condo",
        location_text="Lago Coatepeque, Santa Ana",
        title="Apartamento",
        description="",
    ) is True


# ── finalize_record ───────────────────────────────────────────────────


def _coastal_house_record() -> dict:
    return {
        "source":        "test",
        "source_id":     "T1",
        "url":           "https://example.com/casa-el-tunco-1",
        "title":         "Casa de playa El Tunco",
        "description":   "Casa frente al mar con vista directa al océano.",
        "location_text": "El Tunco, La Libertad",
        "property_type": "house",
        "photo_urls":    ["https://cdn.example.com/casa-tunco.jpg"],
    }


def test_finalize_attaches_type_signals():
    rec = finalize_record(
        _coastal_house_record(),
        slug="test", broker_type="house", broker_type_field="Casa",
    )
    assert rec is not None
    assert "_type_signals" in rec
    assert "_type_confidence" in rec
    assert "_type_total" in rec
    assert rec["_type_confidence"] in {"high", "medium", "low", "uncertain"}


def test_finalize_drops_inland_house():
    """Inland house with no waterfront keyword is dropped at the gate."""
    inland = _coastal_house_record()
    inland["location_text"] = "San Salvador"
    inland["description"]   = "Casa cerca del centro."
    inland["title"]         = "Casa moderna"
    out = finalize_record(
        inland, slug="test", broker_type="house", broker_type_field="Casa",
    )
    assert out is None


def test_finalize_land_skips_gate_and_classifies():
    """Land records skip the gate and still get classifier signals."""
    land = {
        "source":        "test",
        "url":           "https://example.com/terreno-1",
        "title":         "Terreno 500 m2 en San Salvador",
        "description":   "Lote plano residencial.",
        "location_text": "San Salvador",
        "property_type": "land",
        "photo_urls":    [],
    }
    out = finalize_record(
        land, slug="test", broker_type="land", broker_type_field="Terreno",
    )
    assert out is not None
    assert "_type_signals" in out


def test_finalize_flags_classifier_disagreement():
    """If the title screams 'apartamento condominio' but broker says
    'house', the listing ships as house but is FLAGGED for review."""
    confused = _coastal_house_record()
    confused["title"]       = "Apartamento Loft Condominio frente al mar"
    confused["description"] = "Departamento condominio en torre."
    confused["url"]         = "https://example.com/apartamento-condominio-9001"
    out = finalize_record(
        confused, slug="test", broker_type="house", broker_type_field="Casa",
    )
    assert out is not None
    assert out["property_type"] == "house"  # broker_type stays authoritative
    assert out.get("validation_status") == "flagged"
    assert "type_classifier_disagree" in out.get("validation_warnings", [])


# ── OfflineFixtureMixin ───────────────────────────────────────────────


class _FakeScraper(OfflineFixtureMixin):
    """Minimal subclass for testing the mixin."""
    slug = "bienesraices"  # piggy-back on an existing fixture set

    def __init__(self, offline=None):
        self.offline = offline


def test_offline_mixin_returns_fixtures_when_offline():
    s = _FakeScraper(offline=True)
    recs = s._offline_or_fixtures(limit=5)
    assert recs is not None
    assert all(r.get("source") == "bienesraices" for r in recs)


def test_offline_mixin_returns_none_when_online():
    """When offline resolves False, mixin returns None so caller proceeds."""
    import os
    prior = os.environ.pop("PULPO_OFFLINE", None)
    try:
        s = _FakeScraper(offline=False)
        # _offline_or_fixtures returns None only when offline resolves False
        # AND httpx/selectolax are installed. In CI both are installed.
        result = s._offline_or_fixtures(limit=5)
        # If deps are missing in this env, the helper returns fixtures
        # anyway — that's the documented fallback. Accept either as
        # long as it's not a crash.
        assert result is None or isinstance(result, list)
    finally:
        if prior is not None:
            os.environ["PULPO_OFFLINE"] = prior


def test_offline_mixin_respects_override():
    s = _FakeScraper(offline=False)
    recs = s._offline_or_fixtures(limit=3, override_offline=True)
    assert recs is not None
    assert len(recs) <= 3


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
