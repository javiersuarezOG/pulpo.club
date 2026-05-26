"""ig_caption_lint.py — guard against listing-speak in IG captions.

The founder brief is explicit about the smells we never want shipped:

  > Cosas que NO quiero ver
  >   Captions con "premium", "oportunidad", "joya", "exclusivo",
  >   "no se repite", "única en su clase". Ningún listing-speak.
  >   Pandering de diáspora forzado ("etiquetá a tu primo", "el hermano
  >   lejano que…"). Si aparece, lo borrás.

This module turns that rule into a pure-function check.  Every caption
the pipeline produces (template-built OR DeepSeek-generated) flows
through ``check()`` before it reaches the queue.  A non-empty violations
list blocks the caption — the caller either regenerates (DeepSeek)
or falls back to the safe template (queue builder).

Returns a list of Violation dataclasses-as-dicts so the queue builder
can surface them in ``/admin/ig-review`` for the human reviewer:

    [{"code": "BANNED_WORD",   "matched": "premium", "span": (12, 19)},
     {"code": "EXCLAMATION",   "matched": "!!!",     "span": (44, 47)},
     {"code": "ALL_CAPS_RUN",  "matched": "OPORTUNIDAD", "span": (...)},
     ...]

Pure function — no I/O, no LLM calls.  Tests cover the gold-rule list +
each smell category.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Tuple

# Violation codes — stable; queue builder + admin widget switch on these.
BANNED_WORD       = "BANNED_WORD"
BANNED_PHRASE     = "BANNED_PHRASE"
EXCLAMATION       = "EXCLAMATION"
ALL_CAPS_RUN      = "ALL_CAPS_RUN"
EMOJI_SPAM        = "EMOJI_SPAM"


# ── word + phrase lists ────────────────────────────────────────────────

# Single-word banned tokens.  Matched case-insensitively as whole words
# (a "premium-finca" article wouldn't trip the regex; we want the
# stand-alone marketing adjective).  Spanish accent variants included
# explicitly because the corpus mixes "única" / "unica".
BANNED_WORDS: Tuple[str, ...] = (
    "premium",
    "oportunidad",
    "joya",
    "exclusivo", "exclusiva", "exclusivos", "exclusivas",
    "única", "unica", "únicas", "unicas", "único", "unico",
    "imperdible", "imperdibles",
    "inversionistas",            # listing-speak; "para inversionistas" is the giveaway
)

# Multi-word banned phrases.  Matched as substrings (after collapsing
# whitespace) — the diaspora-pandering smells are recognisable even when
# the surrounding sentence reshuffles.
BANNED_PHRASES: Tuple[str, ...] = (
    "no se repite",
    "única en su clase",
    "unica en su clase",
    "oferta única",
    "oferta unica",
    "etiquetá a tu primo",
    "etiqueta a tu primo",
    "el hermano lejano",
    "tu hermano lejano",
    "para los hermanos lejanos",
    "no pierda esta",             # urgency theatre
    "no te lo pierdas",
    "última oportunidad",
    "ultima oportunidad",
)


# Three or more consecutive ! characters = urgency theatre, blocked.
_EXCLAMATION_RE = re.compile(r"!{2,}")

# ALL-CAPS runs of 4+ Latin letters (so "USD", "OK", "PIN" survive but
# "OPORTUNIDAD" / "INVERSION" / "PRECIO" trip).  Brand tokens like
# "PULPO" / "EL ZONTE" are allowlisted below.
_ALL_CAPS_RUN_RE = re.compile(r"\b([A-ZÁÉÍÓÚÑ]{4,})\b")
_CAPS_ALLOWLIST = frozenset({
    "PULPO", "PULPO.CLUB",
    "LISTING", "RANK", "TOP",
    "SURF", "CITY", "BITCOIN", "BEACH",
    "EL", "ZONTE", "TUNCO", "SUNZAL", "CUCO",
    "LA", "LIBERTAD", "UNION", "UNIÓN", "MIGUEL", "SALVADOR",
    "ORIENTE", "CONCHAGUA", "USULUTÁN", "USULUTAN",
    "AIRBNB",
})


# Emoji spam: 3+ emoji code points in a row (back-to-back, no
# intervening alphanum/whitespace).  Single emoji is fine; "🌴🌴🌴" or
# "🐙🐙🐙🐙" is the smell.
def _is_emoji(ch: str) -> bool:
    """Heuristic: any character in the Unicode "So" (Symbol-Other) or
    "Sk" categories with code point ≥ U+1F000 counts as an emoji for
    our smell check.  Far from perfect but catches the spam patterns
    (🔥💎🏝️🎉) without false-flagging accents."""
    cp = ord(ch)
    if cp < 0x2600:                          # ascii + Latin block — never an emoji
        return False
    cat = unicodedata.category(ch)
    return cat in {"So", "Sk"} and cp >= 0x2600


_DEFAULT_EMOJI_SPAM_THRESHOLD = 3


# ── public API ─────────────────────────────────────────────────────────

def check(
    text: str,
    *,
    extra_banned_words: Iterable[str] = (),
    extra_banned_phrases: Iterable[str] = (),
    emoji_spam_threshold: int = _DEFAULT_EMOJI_SPAM_THRESHOLD,
    caps_allowlist: Iterable[str] = (),
) -> List[dict]:
    """Return the list of violations in `text` (empty = caption is clean).

    `extra_*` lets the queue builder pile on per-batch additions (e.g. a
    seasonal banned phrase) without re-deploying this module.

    `caps_allowlist` is merged with the built-in brand allowlist — used
    by tests to allow a fixture-specific token.
    """
    if not text:
        return []
    violations: List[dict] = []

    # Banned single words — case-insensitive whole-word match.
    lower = text.lower()
    for word in BANNED_WORDS + tuple(w.lower() for w in extra_banned_words):
        for m in re.finditer(rf"\b{re.escape(word)}\b", lower):
            violations.append({
                "code":    BANNED_WORD,
                "matched": text[m.start():m.end()],
                "span":    (m.start(), m.end()),
            })

    # Banned phrases — case-insensitive substring after whitespace squash.
    squashed = re.sub(r"\s+", " ", lower)
    for phrase in BANNED_PHRASES + tuple(p.lower() for p in extra_banned_phrases):
        idx = squashed.find(phrase)
        if idx >= 0:
            violations.append({
                "code":    BANNED_PHRASE,
                "matched": phrase,
                "span":    (idx, idx + len(phrase)),
            })

    # Exclamation runs.
    for m in _EXCLAMATION_RE.finditer(text):
        violations.append({
            "code":    EXCLAMATION,
            "matched": m.group(0),
            "span":    (m.start(), m.end()),
        })

    # ALL-CAPS runs (post-allowlist).
    allow = set(_CAPS_ALLOWLIST) | {tok.upper() for tok in caps_allowlist}
    for m in _ALL_CAPS_RUN_RE.finditer(text):
        token = m.group(1)
        if token in allow:
            continue
        violations.append({
            "code":    ALL_CAPS_RUN,
            "matched": token,
            "span":    (m.start(), m.end()),
        })

    # Emoji spam — sliding window over runs of emoji chars.
    run = 0
    for i, ch in enumerate(text):
        if _is_emoji(ch):
            run += 1
            if run == emoji_spam_threshold:
                violations.append({
                    "code":    EMOJI_SPAM,
                    "matched": text[i - run + 1 : i + 1],
                    "span":    (i - run + 1, i + 1),
                })
        else:
            run = 0

    return violations


def is_clean(text: str, **kwargs) -> bool:
    """Convenience predicate.  Returns False if any violation found."""
    return not check(text, **kwargs)
