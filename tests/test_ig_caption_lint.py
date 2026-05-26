"""Tests for automation/ig_caption_lint.py.

Every banned word in the founder brief gets its own assertion so the
list can never silently shrink without a failing test.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_caption_lint import (   # noqa: E402
    ALL_CAPS_RUN,
    BANNED_PHRASE,
    BANNED_WORD,
    BANNED_WORDS,
    BANNED_PHRASES,
    EMOJI_SPAM,
    EXCLAMATION,
    check,
    is_clean,
)


# ── clean baseline ─────────────────────────────────────────────────────

def test_clean_caption_passes():
    text = (
        "19,000 metros cuadrados en El Zonte con vista al océano. "
        "Sin construir. Bitcoin Beach a diez minutos caminando."
    )
    assert check(text) == []
    assert is_clean(text)


def test_empty_text_is_clean():
    assert check("") == []
    assert check(None) == []


# ── banned single words ────────────────────────────────────────────────

@pytest.mark.parametrize("word", [
    "premium", "oportunidad", "joya", "exclusivo", "exclusiva",
    "única", "unica", "imperdible", "inversionistas",
])
def test_each_banned_word_flagged(word):
    text = f"Una {word} propiedad en El Zonte."
    violations = check(text)
    codes = [v["code"] for v in violations]
    assert BANNED_WORD in codes, f"banned word {word!r} should trip BANNED_WORD"


def test_banned_word_is_case_insensitive():
    text = "PREMIUM propiedad."
    violations = check(text)
    # Hits BANNED_WORD ("premium") but might also hit ALL_CAPS_RUN.
    assert any(v["code"] == BANNED_WORD for v in violations)


def test_banned_word_must_be_whole_word():
    """'oportunidades' contains 'oportunidad' but isn't a whole word —
    historically this caused false flags.  Verify substring matching
    does NOT fire here."""
    # NOTE: 'oportunidades' contains the exact word boundary at end
    # because of the plural 's'.  Python \b matches positions.  Our
    # whole-word regex uses \b on both sides so the plural shouldn't
    # match — but a single occurrence of 'oportunidad' inside an URL
    # like /oportunidad-en-zonte/ would still match (the dashes are
    # word boundaries).  That's fine — we don't put URLs in captions.
    text = "Las oportunidades del catálogo son curadas."
    # The \b at the end of 'oportunidad' followed by 'es' wouldn't
    # be a word boundary, so this should NOT flag.
    violations = [v for v in check(text) if v["matched"] == "oportunidades"]
    assert violations == [], "plural form should not match singular"
    # But the whole-word singular DOES flag (sanity).
    assert any(v["matched"].lower() == "oportunidad"
               for v in check("Esta oportunidad."))


def test_banned_word_list_includes_brief_canon():
    """The brief enumerates the canon list.  Don't let it silently shrink."""
    canon = {"premium", "oportunidad", "joya", "exclusivo", "única"}
    listed = {w.lower() for w in BANNED_WORDS}
    missing = canon - listed
    assert not missing, f"BANNED_WORDS is missing canon brief words: {missing}"


# ── banned phrases ─────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "no se repite",
    "única en su clase",
    "etiquetá a tu primo",
    "etiqueta a tu primo",
    "el hermano lejano",
    "para los hermanos lejanos",
    "última oportunidad",
])
def test_each_banned_phrase_flagged(phrase):
    text = f"Mensaje con {phrase} dentro."
    violations = check(text)
    codes = [v["code"] for v in violations]
    assert BANNED_PHRASE in codes, f"phrase {phrase!r} should flag"


def test_banned_phrase_case_insensitive():
    assert any(v["code"] == BANNED_PHRASE
               for v in check("ETIQUETÁ A TU PRIMO en este post."))


def test_banned_phrase_handles_extra_whitespace():
    """A caption with weird spacing shouldn't smuggle the phrase past."""
    assert any(v["code"] == BANNED_PHRASE
               for v in check("etiquetá   a   tu primo en este post."))


def test_banned_phrases_includes_brief_canon():
    canon = {"no se repite", "etiquetá a tu primo", "el hermano lejano"}
    listed = {p.lower() for p in BANNED_PHRASES}
    missing = canon - listed
    assert not missing, f"BANNED_PHRASES is missing canon brief phrases: {missing}"


# ── exclamation cascades ───────────────────────────────────────────────

@pytest.mark.parametrize("text,should_flag", [
    ("Está acá!",         False),
    ("Está acá!!",        True),
    ("Está acá!!!",       True),
    ("Una !!!!",          True),
])
def test_exclamation_cascade(text, should_flag):
    flagged = any(v["code"] == EXCLAMATION for v in check(text))
    assert flagged is should_flag


# ── ALL CAPS runs ──────────────────────────────────────────────────────

def test_all_caps_long_word_flags():
    """'OPORTUNIDAD' is decorative caps — should flag."""
    assert any(v["code"] == ALL_CAPS_RUN
               for v in check("Esta OPORTUNIDAD es buena."))


def test_short_caps_words_pass():
    """'OK', 'PIN' under 4 chars — not flagged.  But 'USD' is allowed
    via the brand allowlist; 'TOP' too."""
    text = "USD 100 OK TOP."
    violations = [v for v in check(text) if v["code"] == ALL_CAPS_RUN]
    assert violations == []


def test_brand_caps_allowlist():
    """PULPO / EL ZONTE / SURF CITY should not flag."""
    text = "PULPO presenta EL ZONTE y SURF CITY."
    violations = [v for v in check(text) if v["code"] == ALL_CAPS_RUN]
    assert violations == []


def test_extra_caps_allowlist_param():
    """Caller can extend the allowlist for fixture-specific tokens."""
    text = "FIESTAS DE PULPO en SURF CITY."
    bad = [v for v in check(text) if v["code"] == ALL_CAPS_RUN]
    assert any(v["matched"] == "FIESTAS" for v in bad)
    no_bad = [v for v in check(text, caps_allowlist={"FIESTAS"})
              if v["code"] == ALL_CAPS_RUN]
    assert no_bad == []


# ── emoji spam ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,should_flag", [
    ("Vista al mar 🌊",                          False),
    ("Vista al mar 🌊🌴",                         False),
    ("Vista al mar 🌊🌴🌅",                       True),
    ("Mira esto 🔥🔥🔥",                          True),
    ("Mira 🔥 esto 🔥 acá 🔥",                    False),  # separated by text
])
def test_emoji_spam(text, should_flag):
    flagged = any(v["code"] == EMOJI_SPAM for v in check(text))
    assert flagged is should_flag


def test_custom_emoji_threshold():
    """A caller can soften the threshold if they really want."""
    text = "Mira 🔥🔥🔥"
    assert any(v["code"] == EMOJI_SPAM for v in check(text))
    assert not any(v["code"] == EMOJI_SPAM
                   for v in check(text, emoji_spam_threshold=4))


# ── extra_banned_words/phrases hooks ──────────────────────────────────

def test_extra_banned_words():
    text = "Una propiedad pleamarea en El Zonte."
    assert is_clean(text)
    assert not is_clean(text, extra_banned_words=("pleamarea",))


def test_extra_banned_phrases():
    text = "Compra ahora para ganar más."
    assert is_clean(text)
    assert not is_clean(text, extra_banned_phrases=("compra ahora",))


# ── violation report shape ─────────────────────────────────────────────

def test_violation_report_shape():
    """Queue builder + admin widget switch on these keys.  Pin shape."""
    v = check("Esta oportunidad premium es única.")[0]
    assert set(v.keys()) == {"code", "matched", "span"}
    assert isinstance(v["span"], tuple) and len(v["span"]) == 2
