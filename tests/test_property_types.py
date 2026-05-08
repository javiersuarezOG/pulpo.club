"""Tests for the property-type config + multi-signal classifier.

Covers:
  - PROPERTY_TYPES config shape (fields every consumer expects)
  - Single-signal cases (broker field, URL slug, title, description)
  - Multi-signal aggregation (sums + confidence buckets)
  - Place-name exclusions (Villa Bosque, Villanueva — real false-positive
    cases observed in current data)
  - Real-world goodlife villa case (the one listing this whole feature was
    motivated by)
  - JS/Python config parity (PROPERTY_TYPES mirrored in index.js)
"""
from __future__ import annotations
import re
from pathlib import Path

import pytest

from automation.property_types import (
    PROPERTY_TYPES, VACATION_ZONES, TYPE_KEYWORDS, PLACE_NAME_EXCLUSIONS,
    WATERFRONT_KEYWORDS, label_for, is_known_type,
)
from pulpo.scrapers._type_classifier import (
    classify_property_type, _detect_type_in_text, _strip_exclusions,
    _map_broker_label_to_type,
)

REPO = Path(__file__).resolve().parent.parent


# ── Config shape ────────────────────────────────────────────────────────

def test_property_types_has_all_three_canonical_types():
    assert set(PROPERTY_TYPES) == {"land", "house", "condo"}


@pytest.mark.parametrize("ptype", ["land", "house", "condo"])
def test_property_type_config_has_required_fields(ptype):
    cfg = PROPERTY_TYPES[ptype]
    for field in ("label", "label_es", "vacation_only", "pill_bg",
                  "pill_text", "title_canonical_template"):
        assert field in cfg, f"{ptype} missing {field}"


def test_pill_colours_are_hex():
    for ptype, cfg in PROPERTY_TYPES.items():
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", cfg["pill_bg"]), ptype
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", cfg["pill_text"]), ptype


def test_label_for_falls_back_to_land_for_unknown():
    assert label_for("nonsense") == PROPERTY_TYPES["land"]["label"]
    assert label_for("nonsense", lang="es") == PROPERTY_TYPES["land"]["label_es"]


def test_is_known_type():
    assert is_known_type("land")
    assert is_known_type("house")
    assert is_known_type("condo")
    assert not is_known_type("villa")  # not a canonical type, even if a keyword


def test_vacation_only_flag_only_land_is_non_vacation():
    """house and condo are vacation_only; land is not. The flag is the
    documented contract that drives the scraper-side vacation-zone
    filter — if it ever flips for land we lose all inland lots, so this
    test makes the regression loud."""
    assert PROPERTY_TYPES["land"]["vacation_only"] is False
    assert PROPERTY_TYPES["house"]["vacation_only"] is True
    assert PROPERTY_TYPES["condo"]["vacation_only"] is True


def test_vacation_zones_includes_known_surf_corridor():
    for z in ("el-tunco", "el-sunzal", "el-zonte", "costa-del-sol"):
        assert z in VACATION_ZONES


def test_vacation_zones_includes_lake_zones():
    """Coatepeque + Ilopango lakes joined the vacation set in PR #161
    (2026-05-08). Recon found ~4 unique house/condo + ~14 land lake-area
    listings across bienesraices/remax/c21 — this test pins the
    inclusion so a future cleanup doesn't accidentally drop them."""
    assert "lago-coatepeque" in VACATION_ZONES
    assert "lago-ilopango" in VACATION_ZONES


# ── Place-name exclusion ────────────────────────────────────────────────

def test_strip_exclusions_removes_villa_bosque():
    """7 of 8 word-boundary `\\bvillas?\\b` matches in current goodlife
    data are place names, not villa structures. Strip them BEFORE keyword
    scoring so 'TERRENO en Villa Bosque' classifies as land, not house."""
    cleaned = _strip_exclusions("terreno en villa bosque, $60,000")
    assert "villa bosque" not in cleaned, "villa bosque must be stripped"
    # Remaining text still has 'terreno' → land classifier wins
    assert "terreno" in cleaned


def test_strip_exclusions_removes_san_jose_villanueva():
    cleaned = _strip_exclusions("lote en san josé villanueva 1000 v2")
    assert "villanueva" not in cleaned


def test_strip_exclusions_handles_villa_de_anything():
    """Generic 'Villas de X' pattern catches development names we haven't
    individually enumerated yet (Villas de Apaneca, Villas de Luxe, etc.)."""
    for s in ("villas de apaneca", "villas de luxe", "villa de algo"):
        assert "villa" not in _strip_exclusions(s).lower(), s


# ── Single-signal classification ────────────────────────────────────────

def test_url_slug_signal_alone_classifies_at_low_or_medium_boundary():
    """URL slug carries weight 2.5 — exactly on the low/medium boundary
    (low: <2.5, medium: 2.5–<4.0). Document the bucketing in the test
    so future weight tweaks surface here."""
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
    ptype, _, conf, total = out
    assert ptype == "land"
    assert total == 3.0
    assert conf == "medium"


def test_unknown_broker_label_yields_no_signal():
    """Conservative mapping — unknown label returns None rather than
    guessing, so caller still gets to run text signals."""
    assert _map_broker_label_to_type("estate_xyz") is None
    assert _map_broker_label_to_type("") is None


def test_no_signals_returns_uncertain_with_fallback():
    out = classify_property_type({"title": "Oportunidad de inversión"})
    ptype, _, conf, total = out
    assert conf == "uncertain"
    assert total == 0.0
    assert ptype == "land"  # fallback


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
    ptype, _, conf, total = out
    assert ptype == "house"
    # title_first_5 (1.5) + description (1.0) = 2.5 → medium boundary
    assert total == 2.5
    assert conf == "medium"


def test_high_confidence_requires_multiple_signals():
    out = classify_property_type({
        "url": "https://x.com/lote-en-el-tunco",
        "title": "Lote en El Tunco 500m2",
        "description": "Terreno plano frente al mar.",
        "photo_urls": [],
    })
    ptype, _, conf, total = out
    assert ptype == "land"
    # url (2.5) + title_first_5 (1.5) + desc (1.0) = 5.0 → high
    assert total == 5.0
    assert conf == "high"


def test_photo_filenames_require_min_2_matches():
    """A single noisy photo filename shouldn't tip the classification.
    Two or more filenames sharing a keyword IS a real signal."""
    one = classify_property_type({
        "title": "", "url": "", "description": "",
        "photo_urls": ["https://cdn.example.com/villa-1.jpg",
                       "https://cdn.example.com/IMG_0042.jpg"],
    })
    assert one[2] == "uncertain"  # only 1 villa-* photo

    two = classify_property_type({
        "title": "", "url": "", "description": "",
        "photo_urls": ["https://cdn.example.com/villa-1.jpg",
                       "https://cdn.example.com/villa-2.jpg",
                       "https://cdn.example.com/villa-3.jpg"],
    })
    assert two[0] == "house"
    assert two[3] == 2.0


def test_title_anywhere_only_fires_when_no_other_signal():
    """The 0.5-weight title-anywhere fallback is for last-resort matches.
    When stronger signals exist they take precedence and the fallback
    must NOT add its weight on top."""
    out = classify_property_type({
        "url": "https://x.com/terreno-1",
        "title": "Terreno en una colonia bonita y tranquila",
    })
    sources = {s.source for s in out[1]}
    assert "title_anywhere" not in sources, (
        "title_anywhere must NOT fire when stronger signals exist"
    )


# ── Real-world cases ────────────────────────────────────────────────────

def test_goodlife_villa_complex_classifies_as_house_high_confidence():
    """The motivating case for this whole feature.
    URL slug, 27 photo files named villa-*, title with 'Villas Complex',
    description with 'three brand-new homes' — every signal points to house.
    Pre-classifier: hardcoded as land, ranked #651, named 'Raw Land · Costa Del Sol'."""
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


def test_terreno_en_villa_bosque_stays_land_despite_villa_keyword():
    """Real false-positive case from current data — 'TERRENO en Villa Bosque'
    is a lot in a residential development named 'Villa Bosque', not a villa
    structure. The exclusion list strips 'villa bosque' before keyword scoring."""
    out = classify_property_type({
        "title": "TERRENO en Villa Bosque, $60,000",
        "url": "https://example.com/lote-villa-bosque",
        "description": "",
        "photo_urls": [],
    })
    assert out[0] == "land"


def test_san_jose_villanueva_lot_stays_land():
    """Villanueva is a municipality. The trailing -nueva strip keeps the
    'villa' keyword from contaminating land lots in this municipality."""
    out = classify_property_type({
        "title": "Lote en San José Villanueva 1000 v²",
        "url": "", "description": "", "photo_urls": [],
    })
    assert out[0] == "land"


def test_apartment_in_costa_del_sol_classifies_as_condo():
    out = classify_property_type({
        "title": "Apartamento frente al mar Costa del Sol",
        "url": "https://x.com/condominio-mar-azul",
        "description": "",
        "photo_urls": [],
    })
    assert out[0] == "condo"
    assert out[2] in ("medium", "high")


# ── Lower-level _detect_type_in_text helper ─────────────────────────────

def test_detect_type_in_text_returns_none_for_empty():
    assert _detect_type_in_text("", weight=1.0, source="x") is None


def test_detect_type_in_text_word_boundary_not_substring():
    """Substring matching is forbidden — 'lotionland' must not match \\blot\\b."""
    out = _detect_type_in_text("lotionland sales", weight=1.0, source="x")
    assert out is None, "substring match leaked through"


# ── JS / Python config parity ───────────────────────────────────────────

def test_property_types_mirror_python():
    """The PROPERTY_TYPES JS object in web/assets/index.js must include the
    same canonical types as the Python config. Drift produces silent UI
    bugs (pill colour wrong, label missing). The label/colour values are
    duplicated by design — this test checks the keys + colours match."""
    js = (REPO / "web/assets/index.js").read_text()
    js_block = js.split("const PROPERTY_TYPES")[1].split("};")[0]
    for ptype in PROPERTY_TYPES:
        assert f"{ptype}:" in js_block, f"JS PROPERTY_TYPES missing {ptype}"
    for ptype, cfg in PROPERTY_TYPES.items():
        assert cfg["pill_bg"] in js_block, (
            f"JS pill_bg drift for {ptype}: {cfg['pill_bg']}"
        )
        assert cfg["pill_text"] in js_block, (
            f"JS pill_text drift for {ptype}: {cfg['pill_text']}"
        )


def test_type_keywords_have_no_substring_traps():
    """Every keyword must be a regex with word boundaries. Bare strings
    would substring-match (e.g. 'lot' in 'lotion'); reject anything missing
    \\b on at least one side."""
    for ptype, patterns in TYPE_KEYWORDS.items():
        for p in patterns:
            assert "\\b" in p, f"{ptype} keyword {p!r} missing word boundary"


def test_waterfront_keywords_compile():
    """Cheap smoke test — every entry must be a valid regex; otherwise the
    vacation-zone fallback breaks at scrape time."""
    for p in WATERFRONT_KEYWORDS:
        re.compile(p)


def test_waterfront_keywords_match_lake_phrases():
    """Lake terms ('frente al lago', 'vista al lago', etc.) must produce
    matches — pins the fix for the geographic gate that previously only
    accepted ocean-coast text."""
    rx = re.compile("|".join(WATERFRONT_KEYWORDS), re.IGNORECASE)
    for phrase in (
        "casa con frente al lago",
        "vista al lago de coatepeque",
        "orillas del lago",
        "lakefront cabin",
    ):
        assert rx.search(phrase), f"WATERFRONT_KEYWORDS missed {phrase!r}"


def test_place_name_exclusions_compile():
    for p in PLACE_NAME_EXCLUSIONS:
        re.compile(p)
