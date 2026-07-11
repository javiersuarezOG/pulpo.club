"""
Bilingual translate-fill — guarantee every served listing carries BOTH
English and Spanish copy on title / description / reasons-to-buy.

Why this exists
---------------
Bilingual listing copy is produced by the DeepSeek *enrichment* pass
(automation/llm_enrichment.py), which writes ``title_canonical`` /
``short_description_canonical`` / ``reasons_to_buy`` as ``{en, es}`` dicts.
But a tail of listings never reaches that pass:

  - a listing already geocoded by an old Mapbox run is INELIGIBLE for
    enrichment (``_present_latlong`` short-circuits eligibility in
    automation/llm_enrichment_schema.py) — so it keeps its raw broker
    ``title``/``description`` string and never gets bilingual copy;
  - the nightly's soft-fail deadline can cut enrichment off mid-run;
  - repeated API failures leave a listing un-enriched.

For those listings the frontend adapter falls back to the single raw
broker string, and ``tr()`` shows it in EVERY locale — a Spanish title
leaks to English users and vice-versa. That is the exact "copy mixed up
between English and Spanish" bug this module closes.

What it does
------------
Runs AFTER ``enrich_listings`` over the same in-memory listings. For any
listing still missing a language on title/description/usps, it makes ONE
faithful *translate-only* DeepSeek call to fill the missing side from the
side that exists, then persists the result to a dedicated, reusable cache
(``web/data/bilingual_fill.json``) keyed by ``source|source_id`` so it is
never recomputed once cached (compounds over nights, mirrors the
enrichment sidecar's idempotency).

Design choices
--------------
- **Separate cache file**, not the enrichment sidecar. The enrichment
  sidecar re-validates the FULL schema (title+description+usps+facts+
  latlong+url_language) on hydration; a partial translate-fill entry
  would fail that and silently skip. A dedicated store sidesteps the
  coupling and keeps the two passes independent.
- **Translate, don't enrich.** This is a faithful translation of copy
  that already exists — it preserves numbers/measurements/proper nouns
  and adds no information. It is NOT the marketing-rewrite the enrichment
  prompt does; a listing that later becomes enrichment-eligible gets the
  richer copy and this fill is superseded.
- **Source-hash guard.** Each cached field stores a hash of the source
  text it was translated from. If the broker text changes, the hash
  changes and we re-translate; otherwise we reuse.
- **Soft-fail per listing.** A translate error leaves the listing's
  existing single-language string in place (the frontend safety net in
  web/app/data/listings.ts renders it honestly). The pass never raises
  and never blocks the nightly.

Public API
----------
    from automation.ensure_bilingual import ensure_bilingual
    metrics = ensure_bilingual(listings, cache_path, log_path=...)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Reuse the enrichment module's dict/dataclass helpers, atomic sidecar I/O,
# key format, and DeepSeek client builder — one seam, one behavior.
from automation.llm_enrichment import (  # type: ignore  # noqa: E402
    _g,
    _key,
    _load_sidecar,
    _save_sidecar,
    _append_log,
)

# Bump when the translate contract changes (prompt, cached shape). A cache
# entry stamped with a lower version is ignored and re-translated.
TRANSLATE_VERSION = 1

# DeepSeek chat endpoint (same provider as enrichment). Kept local so this
# module has no import-time dependency on the enrichment schema object.
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEEPSEEK_MODEL = "deepseek-chat"
_API_KEY_ENV = "DEEPSEEK_API_TOKEN"

# Same fail-fast substrings as enrichment: auth/quota/billing errors will
# fail identically on every call, so stop rather than log hundreds.
_GLOBAL_ERROR_SUBSTRINGS = (
    "AuthenticationError", "PermissionDeniedError", "InvalidAPIKeyError",
    " 401 ", " 402 ", "insufficient_quota",
    "billing_hard_limit_reached", "rate_limit_exceeded",
)

# Char ceilings mirror the enrichment validators (llm_enrichment_schema.py)
# so a translate-fill entry is shaped like an enrichment entry downstream.
_MAX_TITLE_CHARS = 200
_MAX_DESC_CHARS = 700
_MAX_USP_CHARS = 200


# ── language heuristic ─────────────────────────────────────────────────
# Cheap, dependency-free source-language detection. Good enough to decide
# "which side do we have" for a short broker title/description; the actual
# translation is done by the LLM. Spanish diacritics + a stopword frequency
# comparison. Ties resolve to Spanish (LATAM broker source default).

_ES_DIACRITICS = re.compile(r"[áéíóúñ¿¡ü]", re.IGNORECASE)
_WORD = re.compile(r"[a-záéíóúñü]+", re.IGNORECASE)

# NOTE: the definite articles el/la/los/las are deliberately EXCLUDED. In
# this deployment nearly every place name starts with one ("El Zonte",
# "El Sunzal", "El Tunco", "La Libertad", "La Unión"), so they appear just
# as often inside English titles and carry no language signal here.
_ES_STOP = frozenset({
    "de", "en", "con", "para", "por", "del", "una", "un", "y", "se", "su",
    "al", "casa", "terreno", "playa", "mar", "vista", "venta", "frente",
    "cerca", "lote", "lujo", "apartamento", "sobre",
})
_EN_STOP = frozenset({
    "the", "for", "with", "and", "sale", "lot", "house", "home", "beach",
    "beachfront", "ocean", "oceanfront", "view", "near", "front", "land",
    "of", "in", "on", "to", "luxury", "apartment", "condo",
})


def detect_lang(text: str | None) -> str:
    """Return "en" or "es" for a short listing string. Ties → "es"."""
    if not text or not text.strip():
        return "es"
    if _ES_DIACRITICS.search(text):
        return "es"
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return "es"
    es = sum(1 for w in words if w in _ES_STOP)
    en = sum(1 for w in words if w in _EN_STOP)
    if en > es:
        return "en"
    return "es"


def other(lang: str) -> str:
    return "en" if lang == "es" else "es"


# ── field-state helpers ────────────────────────────────────────────────

def _localized_sides(v: Any) -> dict[str, str]:
    """Extract the non-empty {en, es} sides present on a canonical field.

    Accepts a ``{en, es}`` dict (enrichment shape) or ignores anything
    else. Returns only sides that are non-empty strings.
    """
    out: dict[str, str] = {}
    if isinstance(v, dict):
        for k in ("en", "es"):
            s = v.get(k)
            if isinstance(s, str) and s.strip():
                out[k] = s.strip()
    return out


def _src_hash(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_global_error(exc: BaseException) -> bool:
    blob = f"{type(exc).__name__} {exc!r}"
    return any(s in blob for s in _GLOBAL_ERROR_SUBSTRINGS)


# ── what needs filling ─────────────────────────────────────────────────

class _FieldPlan:
    """One field's translate plan: the side we have, the side we need, and
    the source text + language to translate from."""

    __slots__ = ("name", "src_lang", "tgt_lang", "src_text")

    def __init__(self, name: str, src_lang: str, tgt_lang: str, src_text: str):
        self.name = name
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.src_text = src_text


def _plan_title(li: Any) -> _FieldPlan | None:
    canonical = _localized_sides(_g(li, "title_canonical"))
    if len(canonical) == 2:
        return None  # already bilingual
    if len(canonical) == 1:
        have = next(iter(canonical))
        return _FieldPlan("title", have, other(have), canonical[have])
    # No canonical — fall back to the raw broker title string.
    legacy = _g(li, "title")
    if isinstance(legacy, str) and legacy.strip():
        lang = detect_lang(legacy)
        return _FieldPlan("title", lang, other(lang), legacy.strip())
    return None


def _plan_description(li: Any) -> _FieldPlan | None:
    canonical = _localized_sides(_g(li, "short_description_canonical"))
    if len(canonical) == 2:
        return None
    if len(canonical) == 1:
        have = next(iter(canonical))
        return _FieldPlan("description", have, other(have), canonical[have])
    legacy = _g(li, "description")
    if isinstance(legacy, str) and legacy.strip():
        lang = detect_lang(legacy)
        return _FieldPlan("description", lang, other(lang), legacy.strip())
    return None


def needs_fill(li: Any) -> bool:
    """True iff title OR description is missing a language and we have a
    source to translate from. USPs are opportunistic (only filled when a
    one-sided entry exists) and never force a call on their own."""
    return _plan_title(li) is not None or _plan_description(li) is not None


# ── DeepSeek translate call ────────────────────────────────────────────

_TRANSLATE_SYSTEM = (
    "You are a professional translator for real-estate listings. "
    "Translate the provided fields from {src} to {tgt} faithfully. "
    "Rules: preserve every number, price, measurement, and proper noun "
    "exactly; do not add, remove, or embellish information; keep the same "
    "register; return valid JSON only with the same keys you were given "
    "and the translated string values. For the 'usps' key, return an array "
    "of translated strings in the same order."
)

_LANG_NAME = {"en": "English", "es": "Spanish"}


def _build_client():
    """(client, err) — err ∈ {None, 'no_token', 'no_package'}."""
    if not os.environ.get(_API_KEY_ENV):
        return (None, "no_token")
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return (None, "no_package")
    return (OpenAI(base_url=_DEEPSEEK_BASE_URL,
                   api_key=os.environ[_API_KEY_ENV]), None)


def _default_translate(client, src_lang: str, tgt_lang: str,
                       payload: dict[str, Any]) -> dict[str, Any]:
    """Translate ``payload`` (str values + optional usps list) from
    src_lang to tgt_lang via one DeepSeek call. Returns the parsed JSON
    dict. Raises on network/parse error — the caller converts to a
    soft failure."""
    system = _TRANSLATE_SYSTEM.format(
        src=_LANG_NAME[src_lang], tgt=_LANG_NAME[tgt_lang])
    resp = client.chat.completions.create(
        model=_DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=1200,
    )
    choice = resp.choices[0]
    if (getattr(choice, "finish_reason", None) or "stop") == "length":
        raise ValueError("translate response truncated (finish_reason=length)")
    raw = (choice.message.content or "").strip() if choice.message else ""
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("translate response is not a JSON object")
    return parsed


def _apply_translation(li: Any, plans: list[_FieldPlan],
                       have_sides: dict[str, dict[str, str]],
                       translated: dict[str, Any]) -> list[str]:
    """Write the completed {en, es} dicts back onto the listing. Returns
    the list of field names actually filled (both sides now present)."""
    filled: list[str] = []
    for plan in plans:
        tgt_val = translated.get(plan.name)
        if plan.name == "usps":
            continue  # usps handled separately below
        if not (isinstance(tgt_val, str) and tgt_val.strip()):
            continue
        cap = _MAX_TITLE_CHARS if plan.name == "title" else _MAX_DESC_CHARS
        merged = dict(have_sides.get(plan.name, {}))
        merged[plan.src_lang] = plan.src_text[:cap]
        merged[plan.tgt_lang] = tgt_val.strip()[:cap]
        attr = "title_canonical" if plan.name == "title" else "short_description_canonical"
        if merged.get("en") and merged.get("es"):
            _set_field(li, attr, {"en": merged["en"], "es": merged["es"]})
            filled.append(plan.name)
    return filled


def _set_field(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


# ── usps opportunistic fill ────────────────────────────────────────────

def _plan_usps(li: Any) -> tuple[str, str, list[str]] | None:
    """If reasons_to_buy has one-sided {en|es} entries, plan to fill the
    missing side. Returns (src_lang, tgt_lang, [src_texts]) or None.
    Never fabricates USPs — only translates ones that already exist."""
    arr = _g(li, "reasons_to_buy")
    if not isinstance(arr, list) or not arr:
        return None
    src_texts: list[str] = []
    src_lang: str | None = None
    for item in arr:
        sides = _localized_sides(item)
        if len(sides) != 1:
            return None  # already bilingual, or unusable → skip whole array
        lang = next(iter(sides))
        if src_lang is None:
            src_lang = lang
        elif src_lang != lang:
            return None  # mixed source langs across usps → skip
        src_texts.append(sides[lang])
    if src_lang is None:
        return None
    return (src_lang, other(src_lang), src_texts)


def _apply_usps(li: Any, src_lang: str, tgt_lang: str,
                src_texts: list[str], translated: dict[str, Any]) -> bool:
    out = translated.get("usps")
    if not (isinstance(out, list) and len(out) == len(src_texts)):
        return False
    src_count = len(src_texts)
    merged: list[dict[str, str]] = []
    for i in range(src_count):
        tgt = out[i]
        if not (isinstance(tgt, str) and tgt.strip()):
            return False
        merged.append({
            src_lang: src_texts[i][:_MAX_USP_CHARS],
            tgt_lang: tgt.strip()[:_MAX_USP_CHARS],
        })
    _set_field(li, "reasons_to_buy", [{"en": m["en"], "es": m["es"]} for m in merged])
    return True


# ── main pass ──────────────────────────────────────────────────────────

def ensure_bilingual(
    listings: list[Any],
    cache_path: Path,
    *,
    log_path: Path | None = None,
    client: Any | None = None,
    translate_fn: Callable[..., dict[str, Any]] | None = None,
    max_listings: int | None = None,
    deadline: float | None = None,
) -> dict:
    """Fill missing-language sides on title/description/usps for every
    listing that needs it, using a reusable per-listing cache.

    Args:
        listings:     listing dicts/objects, mutated in place on fill.
        cache_path:   web/data/bilingual_fill.json (reusable translate cache).
        log_path:     optional JSONL audit log.
        client:       optional pre-built DeepSeek client (test injection).
        translate_fn: optional callable(client, src, tgt, payload) → dict,
                      for offline tests. Defaults to _default_translate.
        max_listings: cap number of API calls (cost control / dry runs).
        deadline:     time.monotonic() deadline; no new calls after it.

    Returns a metrics dict (needed / cache_hits / filled / failed /
    skipped_no_token / skipped_no_package / global_error_seen / api_calls).
    """
    translate = translate_fn or _default_translate
    metrics: dict[str, Any] = {
        "needed": 0, "cache_hits": 0, "filled": 0, "failed": 0,
        "api_calls": 0, "deadline_skipped": 0,
        "skipped_no_token": False, "skipped_no_package": False,
        "global_error_seen": None, "failure_reasons": {},
    }

    cache = _load_sidecar(cache_path)

    api_client = client
    api_alive = api_client is not None
    build_err: str | None = None
    if api_client is None and translate_fn is None:
        api_client, build_err = _build_client()
        api_alive = api_client is not None
        if build_err:
            metrics[f"skipped_{build_err}"] = True
    elif translate_fn is not None:
        api_alive = True  # test path: translate_fn stands in for the client

    dirty = False
    for li in listings:
        if not needs_fill(li) and _plan_usps(li) is None:
            continue
        metrics["needed"] += 1
        key = _key(li)

        title_plan = _plan_title(li)
        desc_plan = _plan_description(li)
        usps_plan = _plan_usps(li)

        # Build the source signature so a cache hit only applies when the
        # underlying broker text is unchanged.
        sig_parts = [f"v{TRANSLATE_VERSION}"]
        for p in (title_plan, desc_plan):
            if p is not None:
                sig_parts.append(f"{p.name}:{p.src_lang}:{p.src_text}")
        if usps_plan is not None:
            sig_parts.append("usps:" + usps_plan[0] + ":" + "|".join(usps_plan[2]))
        sig = _src_hash(*sig_parts)

        entry = cache.get(key)
        if isinstance(entry, dict) and entry.get("sig") == sig:
            # Reusable cache hit — replay stored translations onto the listing.
            _replay_cache(li, entry)
            metrics["cache_hits"] += 1
            continue

        if not api_alive:
            continue
        if max_listings is not None and metrics["api_calls"] >= max_listings:
            continue
        if deadline is not None and time.monotonic() >= deadline:
            metrics["deadline_skipped"] += 1
            continue

        # One call per source language present (title+description usually
        # share a language; usps may differ). Group by source language.
        try:
            filled_fields, cache_entry = _fill_one(
                li, title_plan, desc_plan, usps_plan, translate, api_client)
        except Exception as e:  # noqa: BLE001 — soft-fail per listing
            metrics["failed"] += 1
            reason = ("global" if _is_global_error(e)
                      else f"{type(e).__name__}")
            metrics["failure_reasons"][reason] = (
                metrics["failure_reasons"].get(reason, 0) + 1)
            if _is_global_error(e):
                metrics["global_error_seen"] = type(e).__name__
                api_alive = False
                print(f"[bilingual_fill] global error ({type(e).__name__}) "
                      "— disabling API path for remaining listings",
                      file=sys.stderr)
            if log_path is not None:
                _append_log(log_path, {"ts": _now_iso(), "key": key,
                                       "decision": "failed", "reason": reason})
            continue

        metrics["api_calls"] += cache_entry.get("_calls", 1)
        if filled_fields:
            cache_entry["sig"] = sig
            cache_entry["ts"] = _now_iso()
            cache_entry["translate_version"] = TRANSLATE_VERSION
            cache_entry.pop("_calls", None)
            cache[key] = cache_entry
            dirty = True
            metrics["filled"] += 1
            if log_path is not None:
                _append_log(log_path, {"ts": _now_iso(), "key": key,
                                       "decision": "filled",
                                       "fields": filled_fields})
        else:
            metrics["failed"] += 1

    if dirty:
        _save_sidecar(cache_path, cache)
    return metrics


def _fill_one(li, title_plan, desc_plan, usps_plan, translate, client
              ) -> tuple[list[str], dict]:
    """Do the translate calls for one listing and apply results. Returns
    (filled_field_names, cache_entry). cache_entry carries the completed
    {en,es} dicts under 'title'/'description'/'usps' for replay."""
    filled: list[str] = []
    entry: dict[str, Any] = {"_calls": 0}

    # Group title + description if they share a source language (one call).
    have_sides = {
        "title": _localized_sides(_g(li, "title_canonical")),
        "description": _localized_sides(_g(li, "short_description_canonical")),
    }
    text_plans = [p for p in (title_plan, desc_plan) if p is not None]
    by_lang: dict[tuple[str, str], list[_FieldPlan]] = {}
    for p in text_plans:
        by_lang.setdefault((p.src_lang, p.tgt_lang), []).append(p)

    for (src_lang, tgt_lang), plans in by_lang.items():
        payload = {p.name: p.src_text for p in plans}
        translated = translate(client, src_lang, tgt_lang, payload)
        entry["_calls"] += 1
        newly = _apply_translation(li, plans, have_sides, translated)
        for name in newly:
            attr = ("title_canonical" if name == "title"
                    else "short_description_canonical")
            entry[name] = _g(li, attr)
            filled.append(name)

    if usps_plan is not None:
        src_lang, tgt_lang, src_texts = usps_plan
        translated = translate(client, src_lang, tgt_lang, {"usps": src_texts})
        entry["_calls"] += 1
        if _apply_usps(li, src_lang, tgt_lang, src_texts, translated):
            entry["usps"] = _g(li, "reasons_to_buy")
            filled.append("usps")

    return filled, entry


def _replay_cache(li: Any, entry: dict) -> None:
    """Apply a cached translate-fill entry onto a listing without an API
    call. Only writes a field when the cached value is a complete {en,es}
    dict (or a list of them for usps)."""
    t = entry.get("title")
    if isinstance(t, dict) and t.get("en") and t.get("es"):
        _set_field(li, "title_canonical", {"en": t["en"], "es": t["es"]})
    d = entry.get("description")
    if isinstance(d, dict) and d.get("en") and d.get("es"):
        _set_field(li, "short_description_canonical", {"en": d["en"], "es": d["es"]})
    u = entry.get("usps")
    if isinstance(u, list) and u and all(
        isinstance(x, dict) and x.get("en") and x.get("es") for x in u
    ):
        _set_field(li, "reasons_to_buy",
                   [{"en": x["en"], "es": x["es"]} for x in u])
