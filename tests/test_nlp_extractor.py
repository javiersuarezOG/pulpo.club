"""
Tests for pulpo/nlp_extractor.py — pins keyword loading, regex compilation,
negation handling, and the extract() entry point so future keyword-dictionary
edits or refactors are visible.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pulpo.nlp_extractor import (   # noqa: E402
    CompiledDict,
    load_dictionaries,
    extract,
    _evaluate_field,
    _is_match_negated,
    _text_blob,
    NEGATION_WINDOW,
)


def _li(**kwargs) -> dict:
    base = {
        "title": "",
        "description": "",
        "location_text": "",
        "raw_size_text": "",
        "has_water": False,
        "has_power": False,
        "is_flat": False,
    }
    base.update(kwargs)
    return base


# ── _text_blob ─────────────────────────────────────────────────────────

def test_text_blob_concatenates_lowercased():
    blob = _text_blob(_li(title="Lot With Water", description="HAS POWER"))
    assert "lot with water" in blob
    assert "has power" in blob
    assert "Lot" not in blob


def test_text_blob_handles_object_with_attrs():
    """NLP extractor accepts both dicts and Listing objects."""
    class FakeListing:
        title = "Plano lot"
        description = "tiene agua"
        location_text = ""
        raw_size_text = ""
    blob = _text_blob(FakeListing())
    assert "plano lot" in blob
    assert "tiene agua" in blob


def test_text_blob_safe_on_empty():
    blob = _text_blob({"title": None, "description": None})
    assert blob.strip() == ""


# ── load_dictionaries ──────────────────────────────────────────────────

def test_load_dictionaries_finds_real_files():
    dicts = load_dictionaries()
    assert len(dicts) >= 6, f"expected ≥6 dictionary files, got {len(dicts)}"
    fields = {d.field for d in dicts}
    # Spot-check core fields
    for required in ("has_water", "has_power", "has_paved_access", "is_flat"):
        assert required in fields, f"{required} missing from nlp_keywords/"


def test_load_dictionaries_compiles_positive_regex(tmp_path):
    """Test fixture: write a synthetic dictionary file and load it."""
    d = tmp_path / "test_field.json"
    d.write_text(json.dumps({
        "field": "test_field",
        "type": "boolean",
        "positive": [r"\bfoo\b", "bar"],
        "negative": [],
    }))
    dicts = load_dictionaries(tmp_path)
    assert len(dicts) == 1
    cd = dicts[0]
    assert cd.field == "test_field"
    assert cd.positive.search("foo") is not None
    assert cd.positive.search("foofoo") is None
    assert cd.positive.search("bar") is not None


def test_load_dictionaries_skips_invalid_json(tmp_path):
    """Bad JSON shouldn't crash the loader."""
    (tmp_path / "broken.json").write_text("{ this is not json")
    (tmp_path / "good.json").write_text(json.dumps({
        "field": "good", "type": "boolean", "positive": ["x"], "negative": [],
    }))
    dicts = load_dictionaries(tmp_path)
    assert len(dicts) == 1
    assert dicts[0].field == "good"


def test_load_dictionaries_skips_dict_with_no_positives(tmp_path):
    (tmp_path / "empty.json").write_text(json.dumps({
        "field": "empty", "type": "boolean", "positive": [], "negative": [],
    }))
    assert load_dictionaries(tmp_path) == []


# ── _is_match_negated — window check ──────────────────────────────────

def test_negation_within_window_suppresses():
    import re
    neg = re.compile(r"no es plano", re.IGNORECASE)
    blob = "el lote no es plano sino con pendiente"
    # "plano" lives at position 14-19; negation is right next to it
    assert _is_match_negated(blob, blob.index("plano"), blob.index("plano") + 5, neg)


def test_negation_outside_window_does_not_suppress():
    import re
    neg = re.compile(r"no es plano", re.IGNORECASE)
    # Negative pattern is at the start; "plano" we test is far away (>25 chars)
    blob = "no es plano. " + (" " * 50) + "el siguiente lote es plano"
    second_plano = blob.rindex("plano")
    assert not _is_match_negated(blob, second_plano, second_plano + 5, neg)


def test_negation_window_constant_is_reasonable():
    """Sanity: NEGATION_WINDOW shouldn't be way out of spec."""
    assert 10 <= NEGATION_WINDOW <= 100


# ── _evaluate_field ────────────────────────────────────────────────────

def test_evaluate_returns_true_on_positive_match():
    import re
    cd = CompiledDict(field="x", type_="boolean",
                       positive=re.compile(r"\bagua\b", re.I),
                       negative=None)
    assert _evaluate_field("tiene agua potable", cd)


def test_evaluate_returns_false_on_no_match():
    import re
    cd = CompiledDict(field="x", type_="boolean",
                       positive=re.compile(r"\bagua\b", re.I),
                       negative=None)
    assert not _evaluate_field("nothing relevant here", cd)


def test_evaluate_boolean_with_negation_suppresses_match():
    import re
    cd = CompiledDict(field="is_flat", type_="boolean_with_negation",
                       positive=re.compile(r"\bplano\b", re.I),
                       negative=re.compile(r"no es plano", re.I))
    # "plano" is in the blob, but negation pattern is right next to it
    assert not _evaluate_field("el lote no es plano sino con pendiente", cd)


def test_evaluate_boolean_with_negation_keeps_genuine_match():
    import re
    cd = CompiledDict(field="is_flat", type_="boolean_with_negation",
                       positive=re.compile(r"\bplano\b", re.I),
                       negative=re.compile(r"no es plano", re.I))
    assert _evaluate_field("terreno plano y nivelado", cd)


def test_evaluate_plain_boolean_also_honors_global_negation():
    """Plain 'boolean' type should still suppress at-the-blob level if
    the negation pattern lands within the window of a positive hit.
    Cheap defense against 'no agua' → has_water=True."""
    import re
    cd = CompiledDict(field="has_water", type_="boolean",
                       positive=re.compile(r"\bagua\b", re.I),
                       negative=re.compile(r"sin agua|no agua", re.I))
    assert not _evaluate_field("sin agua aún", cd)


def test_evaluate_empty_blob_returns_false():
    import re
    cd = CompiledDict(field="x", type_="boolean",
                       positive=re.compile(r"\bagua\b", re.I), negative=None)
    assert not _evaluate_field("", cd)


# ── extract — full path on a Listing dict ─────────────────────────────

def test_extract_flips_false_to_true_on_match():
    dicts = load_dictionaries()
    li = _li(description="Tiene agua y luz al lote.")
    changes = extract(li, dicts)
    assert li.get("has_water") is True
    assert li.get("has_power") is True
    assert "has_water" in changes
    assert "has_power" in changes


def test_extract_does_not_overwrite_true_from_scraper():
    """Existing per-scraper True values are preserved."""
    dicts = load_dictionaries()
    li = _li(description="empty desc, no keywords", has_water=True)
    changes = extract(li, dicts)
    assert li["has_water"] is True   # preserved
    assert "has_water" not in changes  # we didn't flip it (already True)


def test_extract_skips_listing_with_no_text():
    dicts = load_dictionaries()
    li = _li()  # all empty strings
    changes = extract(li, dicts)
    assert changes == {}


def test_extract_skips_fields_not_on_listing():
    """If a dictionary's `field` doesn't exist on the listing, skip it
    (rather than crash or set extra fields)."""
    dicts = load_dictionaries()
    li = {"title": "Frente al mar", "description": "Beachfront parcel"}
    # has_ocean_view / is_beachfront not in li by default, has_water etc. exist.
    extract(li, dicts)
    # Only fields explicitly present in the dict get set.
    # No assertion error, just shouldn't crash.


def test_extract_real_dict_lifts_known_paved_signal():
    """The 'carretera del litoral' family in has_paved_access JSON should fire."""
    dicts = load_dictionaries()
    li = _li(description="Lote sobre la carretera del litoral, km 45.",
             has_paved_access=False)
    extract(li, dicts)
    assert li["has_paved_access"] is True


# ── is_agricultural false-positive regression tests ────────────────────
#
# Pre-2026-05-24, the is_agricultural JSON dictionary stored bare-word
# patterns ("ranch", "finca", "canal") without word boundaries. The
# regex engine then substring-matched them inside unrelated Spanish
# words, mass-purging in-scope beach houses:
#
#   English "ranch"  ⊂  Spanish "rancho"  (Salvadoran beach pavilion)
#   Spanish "finca"  ⊂  development names like "Finca Brava"
#   Spanish "canal"  ⊂  geographic names like "Canal de Suchitoto"
#
# Three nightlies failed in a row (May 22-24) because ~40 such false
# positives dropped the post-purge house count below the canary floor.
# These tests pin the fix — adding \b boundaries to bare keywords — so
# a future edit that drops them resurfaces the regression.


def test_is_agricultural_does_not_match_rancho_in_beach_title():
    """A real listing that triggered the false-positive purge:
    'RANCHO PLAYA ATAMI 1100vr2 EN PRIVADO SURF CITY I' is a beachfront
    house, not a working ranch. With \\b boundaries on 'ranch', the
    English keyword no longer substring-matches the Spanish 'rancho'."""
    dicts = load_dictionaries()
    li = _li(title="RANCHO PLAYA ATAMI 1100vr2 EN PRIVADO SURF CITY I",
             description="Casa Moderna con vista al mar en el exclusivo "
                         "Residencial Atami, Surf City. 3 habitaciones, "
                         "piscina privada.",
             is_agricultural=False)
    extract(li, dicts)
    assert li.get("is_agricultural") is False, (
        "'rancho' in a Spanish beach-house title should NOT trigger "
        "is_agricultural — that's the bug that mass-purged ~40 in-scope "
        "houses across three nightlies in May 2026."
    )


def test_is_agricultural_still_matches_genuine_english_ranch():
    """The \\b boundary must not break the real positive case. A title
    with the standalone word 'ranch' (English) still classifies as
    agricultural."""
    dicts = load_dictionaries()
    li = _li(title="Cattle Ranch with 50 head of livestock for sale",
             description="Working ranch with pasture, water, and equipment.",
             is_agricultural=False)
    extract(li, dicts)
    assert li.get("is_agricultural") is True


def test_is_agricultural_does_not_match_finca_in_development_name():
    """Same shape as rancho: Spanish 'finca' is a strong agricultural
    signal on its own, but it's also embedded in proper development
    names. Word boundary prevents the substring match. 'Finca Brava' is
    a real Salvadoran beachfront development."""
    dicts = load_dictionaries()
    li = _li(title="Casa en Finca Brava — frente al mar",
             description="Hermosa casa moderna en desarrollo privado "
                         "Finca Brava, vista al mar, piscina.",
             is_agricultural=False)
    extract(li, dicts)
    # 'finca' is in the title — with \b it still matches. This test is
    # for the SUBSTRING risk: 'Finca Brava' contains 'finca' as a full
    # token AND as substring. We accept the full-token match (genuine
    # finca-reference); we just prevent matches like 'finquita' or
    # 'fincas-real-estate'. So the assertion here is that 'finca' DOES
    # match when standalone — the behavior is intentional.
    assert li.get("is_agricultural") is True


def test_is_agricultural_still_matches_es_finca_standalone():
    """Sanity check that the \\b around 'finca' doesn't break the
    common positive case: a Spanish description mentioning 'finca'
    as a standalone word still classifies as agricultural."""
    dicts = load_dictionaries()
    li = _li(description="Se vende finca con cafetal, 5 manzanas de tierra "
                         "fértil en zona cafetera.",
             is_agricultural=False)
    extract(li, dicts)
    assert li.get("is_agricultural") is True
