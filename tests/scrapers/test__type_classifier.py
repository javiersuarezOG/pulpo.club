"""Tests for the multi-signal property-type classifier.

Mirrors a subset of the cases in tests/test_property_types.py focused
specifically on the _type_classifier module's behaviour. The broader
config + JS-parity tests live in tests/test_property_types.py since
they cover automation/property_types.py and web/assets/index.js too.

CI's check_tests_added.py expects a per-module test file alongside any
new pulpo/scrapers/*.py — that's why the classifier-focused subset lives
here rather than only in the broader file.
"""
from __future__ import annotations

from pulpo.scrapers._type_classifier import (
    classify_property_type,
    _detect_type_in_text,
    _strip_exclusions,
    _map_broker_label_to_type,
    TypeSignal,
)


# ── Single-signal cases ─────────────────────────────────────────────────

def test_url_slug_signal_classifies_at_medium_boundary():
    """URL slug carries weight 2.5 — exactly on the low/medium boundary."""
    out = classify_property_type({
        "url": "https://x.com/casas/villa-bonita",
        "title": "", "description": "", "photo_urls": [],
    })
    ptype, _, conf, total = out
    assert ptype == "house"
    assert total == 2.5
    assert conf == "medium"


def test_broker_field_alone_reaches_medium():
    out = classify_property_type({"broker_type_field": "lote_residencial"})
    assert out[0] == "land"
    assert out[2] == "medium"


def test_unknown_broker_label_returns_none():
    """Conservative mapping — unknown label means 'I don't know', not 'guess'."""
    assert _map_broker_label_to_type("estate_xyz") is None
    assert _map_broker_label_to_type("") is None


def test_no_signals_returns_uncertain_with_fallback():
    out = classify_property_type({"title": "Oportunidad de inversión"})
    ptype, _, conf, total = out
    assert conf == "uncertain"
    assert total == 0.0
    assert ptype == "land"


def test_no_signals_respects_explicit_fallback():
    out = classify_property_type({"title": ""}, fallback_type="condo")
    assert out[0] == "condo"
    assert out[2] == "uncertain"


# ── Multi-signal aggregation ────────────────────────────────────────────

def test_two_agreeing_weak_signals_reach_medium():
    out = classify_property_type({
        "title": "Casa hermosa con vista",
        "description": "Esta casa de tres habitaciones.",
        "url": "", "photo_urls": [],
    })
    assert out[0] == "house"
    assert out[3] == 2.5  # title_first_5 (1.5) + description (1.0)
    assert out[2] == "medium"


def test_three_signals_reach_high():
    out = classify_property_type({
        "url": "https://x.com/lote-en-el-tunco",
        "title": "Lote en El Tunco 500m2",
        "description": "Terreno plano frente al mar.",
        "photo_urls": [],
    })
    assert out[0] == "land"
    assert out[3] == 5.0  # url (2.5) + title (1.5) + desc (1.0)
    assert out[2] == "high"


def test_photo_filenames_require_min_2_matches():
    """Single noisy filename must NOT tip classification — need ≥2 hits."""
    one = classify_property_type({
        "title": "", "url": "", "description": "",
        "photo_urls": ["https://cdn.example.com/villa-1.jpg",
                       "https://cdn.example.com/IMG_0042.jpg"],
    })
    assert one[2] == "uncertain"

    two = classify_property_type({
        "title": "", "url": "", "description": "",
        "photo_urls": ["https://cdn.example.com/villa-1.jpg",
                       "https://cdn.example.com/villa-2.jpg",
                       "https://cdn.example.com/villa-3.jpg"],
    })
    assert two[0] == "house"
    assert two[3] == 2.0


def test_title_anywhere_only_fires_when_no_other_signal():
    out = classify_property_type({
        "url": "https://x.com/terreno-1",
        "title": "Terreno en una colonia bonita y tranquila",
    })
    sources = {s.source for s in out[1]}
    assert "title_anywhere" not in sources


# ── Place-name exclusion ────────────────────────────────────────────────

def test_strip_exclusions_villa_bosque():
    cleaned = _strip_exclusions("terreno en villa bosque")
    assert "villa bosque" not in cleaned
    assert "terreno" in cleaned


def test_strip_exclusions_villanueva():
    cleaned = _strip_exclusions("lote en san josé villanueva 1000 v2")
    assert "villanueva" not in cleaned


def test_terreno_en_villa_bosque_classifies_as_land():
    """Real false-positive case — lot in 'Villa Bosque' development must
    NOT classify as house just because 'villa' is in the title."""
    out = classify_property_type({
        "title": "TERRENO en Villa Bosque, $60,000",
        "url": "https://example.com/lote-villa-bosque",
        "description": "", "photo_urls": [],
    })
    assert out[0] == "land"


# ── Real-world goodlife villa case ──────────────────────────────────────

def test_goodlife_villa_complex_classifies_as_house_high():
    """The motivating real listing: hardcoded as land pre-PR, ranked #651,
    canonicalized as 'Raw Land · Costa Del Sol'. With the multi-signal
    classifier all three primary signals (URL, photos, title) agree on
    house, total weight 6.0 → high confidence."""
    out = classify_property_type({
        "url": "https://goodlifeelsalvador.com/property/beautiful-new-modern-house-in-costa-del-sol/",
        "photo_urls": [f"https://cdn.example.com/villa-{i}.avif" for i in range(1, 28)],
        "title": "3 Villas Complex in Costa del Sol, $1,200,000",
        "description": "Three brand-new homes in a coastal community. Each villa has 4 bedrooms.",
    })
    ptype, signals, conf, total = out
    assert ptype == "house"
    assert conf == "high"
    sources = {s.source for s in signals}
    assert "url_slug" in sources
    assert "photo_filenames" in sources
    assert "title_first_5" in sources


# ── Lower-level helper ──────────────────────────────────────────────────

def test_detect_type_in_text_empty_returns_none():
    assert _detect_type_in_text("", weight=1.0, source="x") is None


def test_detect_type_in_text_word_boundary_not_substring():
    """Substring matching forbidden — 'lotionland' must not match \\blot\\b."""
    assert _detect_type_in_text("lotionland sales", weight=1.0, source="x") is None


def test_type_signal_to_dict_round_trips():
    """to_dict() output is what's serialized into type_classifier_log.jsonl
    — its shape is part of the log schema."""
    s = TypeSignal("house", 2.5, "url_slug")
    d = s.to_dict()
    assert d == {"type": "house", "weight": 2.5, "source": "url_slug"}
