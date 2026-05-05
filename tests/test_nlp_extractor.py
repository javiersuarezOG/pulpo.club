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
