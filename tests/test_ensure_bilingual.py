"""
Tests for automation/ensure_bilingual.py — the bilingual translate-fill
pass that guarantees every served listing carries BOTH en + es copy.

Offline: a fake `translate_fn` stands in for the DeepSeek client, so no
network / no openai package / no token is needed. It records every call
and returns a deterministic uppercased-marker "translation" so tests can
assert direction and idempotency without a real LLM.

Coverage:
- ES-only broker title/description → EN side filled (leak to EN users closed)
- EN-only broker title → ES side filled (leak to ES users closed)
- one-sided canonical {en} → es filled
- already-bilingual listing → no call, not counted as needed
- reusable cache: second run = zero API calls (source-hash replay)
- source text change → cache invalidated, re-translate
- usps opportunistic fill (one-sided → both sides), never fabricated
- soft-fail: translate error leaves the single-language string in place
- language heuristic: detect_lang direction
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ensure_bilingual import (  # noqa: E402
    ensure_bilingual,
    needs_fill,
    detect_lang,
)


# ── fake translator ────────────────────────────────────────────────────

class FakeTranslator:
    """Records calls; returns a deterministic marker translation.

    A translation of "Casa" from es→en becomes "[en]Casa" — enough to
    assert which side was produced and that the source was preserved.
    """

    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, str, dict]] = []
        self.fail = fail

    def __call__(self, client, src, tgt, payload):
        self.calls.append((src, tgt, payload))
        if self.fail:
            raise RuntimeError("simulated translate failure")
        out: dict = {}
        for k, v in payload.items():
            if k == "usps":
                out["usps"] = [f"[{tgt}]{s}" for s in v]
            else:
                out[k] = f"[{tgt}]{v}"
        return out


def _cache(tmp_path) -> Path:
    return tmp_path / "bilingual_fill.json"


# ── the leak: single-language broker copy ──────────────────────────────

def test_es_only_title_fills_english(tmp_path):
    li = {"source": "goodlife", "source_id": "zonte-lot",
          "title": "Terreno con vista al mar en El Zonte", "description": None}
    tx = FakeTranslator()
    m = ensure_bilingual([li], _cache(tmp_path), translate_fn=tx)
    assert m["needed"] == 1 and m["filled"] == 1
    tc = li["title_canonical"]
    assert tc["es"] == "Terreno con vista al mar en El Zonte"
    assert tc["en"].startswith("[en]")
    # source detected as Spanish → translated es→en
    assert tx.calls and tx.calls[0][0] == "es" and tx.calls[0][1] == "en"


def test_en_only_title_fills_spanish(tmp_path):
    li = {"source": "remax", "source_id": "sunzal-home",
          "title": "Beachfront Home El Sunzal", "description": None}
    tx = FakeTranslator()
    ensure_bilingual([li], _cache(tmp_path), translate_fn=tx)
    tc = li["title_canonical"]
    assert tc["en"] == "Beachfront Home El Sunzal"
    assert tc["es"].startswith("[es]")
    assert tx.calls[0][0] == "en" and tx.calls[0][1] == "es"


def test_one_sided_canonical_gets_completed(tmp_path):
    li = {"source": "nexo", "source_id": "x1",
          "title_canonical": {"en": "Ocean-view lot"},
          "short_description_canonical": {"es": "Terreno plano de 500 m²."}}
    tx = FakeTranslator()
    ensure_bilingual([li], _cache(tmp_path), translate_fn=tx)
    assert li["title_canonical"]["en"] == "Ocean-view lot"
    assert li["title_canonical"]["es"].startswith("[es]")
    assert li["short_description_canonical"]["es"] == "Terreno plano de 500 m²."
    assert li["short_description_canonical"]["en"].startswith("[en]")


def test_already_bilingual_no_call(tmp_path):
    li = {"source": "s", "source_id": "b",
          "title_canonical": {"en": "Lot", "es": "Terreno"},
          "short_description_canonical": {"en": "Flat lot.", "es": "Terreno plano."}}
    assert needs_fill(li) is False
    tx = FakeTranslator()
    m = ensure_bilingual([li], _cache(tmp_path), translate_fn=tx)
    assert m["needed"] == 0 and not tx.calls


# ── reusable cache ─────────────────────────────────────────────────────

def test_cache_reuse_zero_calls_second_run(tmp_path):
    cache = _cache(tmp_path)
    li1 = {"source": "s", "source_id": "id1", "title": "Casa frente al mar"}
    tx1 = FakeTranslator()
    ensure_bilingual([li1], cache, translate_fn=tx1)
    assert len(tx1.calls) == 1
    # Fresh listing object, same key + same source text → cache replay.
    li2 = {"source": "s", "source_id": "id1", "title": "Casa frente al mar"}
    tx2 = FakeTranslator()
    m2 = ensure_bilingual([li2], cache, translate_fn=tx2)
    assert m2["cache_hits"] == 1 and not tx2.calls
    assert li2["title_canonical"]["en"].startswith("[en]")


def test_source_change_invalidates_cache(tmp_path):
    cache = _cache(tmp_path)
    li1 = {"source": "s", "source_id": "id1", "title": "Casa vieja"}
    ensure_bilingual([li1], cache, translate_fn=FakeTranslator())
    li2 = {"source": "s", "source_id": "id1", "title": "Casa nueva remodelada"}
    tx = FakeTranslator()
    m = ensure_bilingual([li2], cache, translate_fn=tx)
    assert m["cache_hits"] == 0 and len(tx.calls) == 1
    assert "nueva" in li2["title_canonical"]["es"]


# ── usps ───────────────────────────────────────────────────────────────

def test_usps_one_sided_filled(tmp_path):
    li = {"source": "s", "source_id": "u1",
          "title_canonical": {"en": "Lot", "es": "Terreno"},
          "short_description_canonical": {"en": "Flat.", "es": "Plano."},
          "reasons_to_buy": [{"es": "Vista al mar"}, {"es": "A pasos de la playa"}]}
    tx = FakeTranslator()
    ensure_bilingual([li], _cache(tmp_path), translate_fn=tx)
    rtb = li["reasons_to_buy"]
    assert rtb[0]["es"] == "Vista al mar" and rtb[0]["en"].startswith("[en]")
    assert rtb[1]["en"].startswith("[en]")


def test_usps_never_fabricated_when_absent(tmp_path):
    li = {"source": "s", "source_id": "u2",
          "title_canonical": {"en": "Lot", "es": "Terreno"},
          "short_description_canonical": {"en": "Flat.", "es": "Plano."}}
    # fully bilingual title+desc, no usps → nothing to do
    assert needs_fill(li) is False
    tx = FakeTranslator()
    m = ensure_bilingual([li], _cache(tmp_path), translate_fn=tx)
    assert m["needed"] == 0 and not tx.calls


# ── soft-fail ──────────────────────────────────────────────────────────

def test_translate_failure_leaves_string_and_counts(tmp_path):
    li = {"source": "s", "source_id": "f1", "title": "Casa frente al mar"}
    tx = FakeTranslator(fail=True)
    m = ensure_bilingual([li], _cache(tmp_path), translate_fn=tx)
    assert m["failed"] == 1 and m["filled"] == 0
    # listing left untouched — no half-written canonical
    assert "title_canonical" not in li or li.get("title_canonical") is None


# ── language heuristic ─────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Terreno con vista al mar", "es"),
    ("Beachfront Home for Sale", "en"),
    ("Apartamento de lujo frente al mar", "es"),
    ("El Zonte Land", "en"),
    ("Casa", "es"),
    ("", "es"),
])
def test_detect_lang(text, expected):
    assert detect_lang(text) == expected
