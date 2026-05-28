"""ig_caption.py — generate IG captions for batch 1 posts.

Composition:

    {HOOK_LINE}                  ← per-poster-type opener (template)
    {DESCRIPTIVE_LINE}           ← one sensory line, DeepSeek-personalised
                                   (falls back to a template line on no API
                                    key / lint failure / timeout)
    {FACTS_LINE}                 ← area · price · zone, gold-rule formatted
    {CTA}                        ← pulpo.club · listing N° XXX

Voice rules:
  - Spanish, declarative, no exclamation cascades.
  - Gold rule on units (m² · USD · km/m) via ig_units formatters.
  - Banned vocabulary enforced by ig_caption_lint.check() before any
    DeepSeek output is allowed through.  A flagged sentence triggers
    one regeneration retry; a second failure pins to the template-only
    baseline (safe, less interesting, never broken).

Public API:

    generate_caption(candidate, listing, *, poster_type=TYPO_MAX,
                     overrides=None) → str

    generate_descriptive_line(candidate, listing, *, client=None) → str
        Pure-ish: skips the LLM call if `client` is None.  Used by the
        queue builder to test prompt iterations without committing to
        a full caption.

CLI:

    python3 -m automation.ig_caption \\
        --candidate-id remax__001461165132 [--poster-type sticker]

Reads web/data/ig_candidates.json + web/data/ranked.json, prints the
caption to stdout.  No file writes — the queue builder (PR-3) owns
persisting captions to ig_queue.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from automation._config import env_float, env_int
from automation.ig_caption_lint import check as lint_check, is_clean
from pulpo.countries import active as _active_country
from automation.ig_poster import (
    BIG_NUMBER, MAP_MARK, POSTER_TYPES, POST_IT, RECEIPT, STICKER, TYPO_MAX,
)
from automation.ig_units import (
    format_area_m2,
    format_distance,
    format_price_per_m2,
    format_price_usd,
    format_zone_delta_pct,
)


# ── DeepSeek client config ─────────────────────────────────────────────

DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_TOKEN"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"


def _build_client():
    """Returns (client, error_kind).  Mirrors automation/llm_enrichment.
    py's _build_client so the caption path uses the same client config
    as the nightly enrichment.

      ("client", None)          ready
      (None, "no_token")        DEEPSEEK_API_TOKEN env unset
      (None, "no_package")      openai package not importable
    """
    if not os.environ.get(DEEPSEEK_API_KEY_ENV):
        return None, "no_token"
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return None, "no_package"
    return OpenAI(
        base_url=DEEPSEEK_BASE_URL,
        api_key=os.environ[DEEPSEEK_API_KEY_ENV],
    ), None


# ── prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Escribes para Pulpo, un marketplace de propiedades de El Salvador. Tu voz es \
declarativa, sensorial, breve.

REGLAS DURAS — viola cualquiera y la salida será descartada:
- Una sola oración. Máximo 25 palabras.
- Solo en español neutro, sin regionalismos forzados.
- Sin exclamaciones (¡! prohibido).
- Sin palabras prohibidas: premium, oportunidad, joya, exclusivo, único, \
  imperdible, inversionistas, no se repite, "etiqueta a tu primo", \
  "el hermano lejano".
- Sin mayúsculas decorativas, sin emojis.
- Sin precio explícito (eso va aparte). Sin call-to-action ("contacta", \
  "visita"). Sin URL.
- Detalle sensorial: vista, escala, paisaje, ubicación concreta. No vendas — \
  describe.

EJEMPLO BUENO:
"Diecinueve mil metros de tierra cruda con vista al océano, a diez minutos \
caminando de Bitcoin Beach."

EJEMPLO MALO:
"¡Una premium oportunidad única en El Zonte para inversionistas exclusivos!"
"""


def _build_user_prompt(candidate: dict, listing: dict) -> str:
    """Compact summary of the listing facts the model will turn into
    one sensory line.  No instructions here — those live in the system
    prompt; user prompt is data only so future prompt iterations don't
    drift into mixing data with directives."""
    facts = [
        f"zona: {candidate.get('zone') or listing.get('zone') or '?'}",
        f"departamento: {candidate.get('department') or listing.get('department') or '?'}",
        f"area_m2: {candidate.get('area_m2') or listing.get('area_m2')}",
        f"price_usd: {candidate.get('price_usd') or listing.get('price_usd')}",
        f"price_per_m2: {candidate.get('price_per_m2') or listing.get('price_per_m2')}",
        f"dist_beach_km: {candidate.get('dist_beach_km') or listing.get('dist_beach_km')}",
        f"has_ocean_view: {listing.get('has_ocean_view')}",
        f"has_water: {listing.get('has_water')}",
        f"has_power: {listing.get('has_power')}",
        f"has_paved_access: {listing.get('has_paved_access')}",
        f"property_type: {candidate.get('property_type') or listing.get('property_type')}",
    ]
    title = listing.get("title") or ""
    if title:
        facts.append(f"título original: {title[:140]}")
    return "Datos del listing:\n" + "\n".join(f"  - {f}" for f in facts)


# ── descriptive-line generator ────────────────────────────────────────

# Fallback templates by poster type.  Used when DeepSeek is unavailable
# or returns lint-flagged text twice.  Each template references a few
# computed fields and stays safely on-voice (no banned vocabulary).
def _fallback_descriptive_line(candidate: dict, listing: dict, poster_type: str) -> str:
    area = format_area_m2(candidate.get("area_m2"))
    zone = (candidate.get("zone") or listing.get("zone") or _active_country().name_en).replace("-", " ").title()
    has_view = listing.get("has_ocean_view") or listing.get("has_water_body")
    feature = "con vista al océano" if listing.get("has_ocean_view") else (
        "frente al agua" if has_view else "sin construir"
    )
    return f"{area} en {zone}, {feature}."


def generate_descriptive_line(
    candidate: dict,
    listing: dict,
    *,
    client: Optional[Any] = None,
    poster_type: str = TYPO_MAX,
    max_retries: int = 1,
) -> str:
    """Returns a clean (lint-passing) descriptive sentence.

    If `client` is None or the API errors out, returns the fallback
    template line.  If the LLM emits a lint-flagged sentence, retries
    once; second failure also falls back."""
    if client is None:
        return _fallback_descriptive_line(candidate, listing, poster_type)

    user_prompt = _build_user_prompt(candidate, listing)
    last_attempt: Optional[str] = None

    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=env_int("IG_CAPTION_MAX_TOKENS", 120),
                temperature=env_float("IG_CAPTION_TEMPERATURE", 0.45),
            )
            text = (resp.choices[0].message.content or "").strip().strip('"')
        except Exception as e:
            print(f"[ig_caption] DeepSeek call failed (attempt {attempt+1}): {e!r}",
                  file=sys.stderr)
            break
        last_attempt = text
        if is_clean(text):
            return text
        violations = lint_check(text)
        print(
            f"[ig_caption] DeepSeek output lint-rejected "
            f"(attempt {attempt+1}): {[v['code'] for v in violations]}",
            file=sys.stderr,
        )

    if last_attempt:
        print(f"[ig_caption] using fallback after lint reject; LLM emitted: {last_attempt!r}",
              file=sys.stderr)
    return _fallback_descriptive_line(candidate, listing, poster_type)


# ── full caption composition ──────────────────────────────────────────

def _hook_line(candidate: dict, listing: dict, poster_type: str) -> str:
    """Bold-faced opener.  Wrapped in ``**...**`` so IG renders the
    first line emphasised when copied through ig_queue → IG paste flow."""
    zone = (candidate.get("zone") or _active_country().name_en).replace("-", " ").title()
    area = format_area_m2(candidate.get("area_m2"))
    pct = candidate.get("price_vs_zone_pct")
    if poster_type == POST_IT and pct is not None and pct <= -20:
        return f"**El tentáculo de {zone} encontró esto. {format_zone_delta_pct(pct)} vs su zona.**"
    if poster_type == BIG_NUMBER:
        ppm = format_price_per_m2(candidate.get("price_per_m2"))
        return f"**{ppm} por metro cuadrado en {zone}.**"
    if poster_type == RECEIPT:
        return "**Cinco terrenos. Los cinco mejor rankeados de su banda esta semana.**"
    if poster_type == MAP_MARK:
        return f"**El tentáculo de {zone} esta semana.**"
    if poster_type == STICKER:
        return f"**{area} en {zone}.**"
    # default = TYPO_MAX
    return f"**{area} en {zone}.**"


def _facts_line(candidate: dict, listing: dict, poster_type: str) -> str:
    """Compact fact strip that closes the caption.  Receipt + map_mark
    skip the facts line because they're carousel covers — the actual
    listings live in slides 2-N, not in the cover caption."""
    if poster_type in (RECEIPT, MAP_MARK):
        return ""
    parts = [format_price_usd(candidate.get("price_usd"))]
    dist = format_distance(candidate.get("dist_beach_km"))
    if dist != "—":
        parts.append(f"a {dist} del mar")
    return " · ".join(p for p in parts if p and p != "—")


def _cta(candidate: dict, poster_type: str) -> str:
    rank = candidate.get("rank")
    if poster_type in (RECEIPT, MAP_MARK):
        return "pulpo.club · link en bio"
    if rank is not None:
        return f"pulpo.club · listing N° {int(rank):03d}"
    return "pulpo.club"


def generate_caption(
    candidate: dict,
    listing: Optional[dict] = None,
    *,
    poster_type: str = TYPO_MAX,
    client: Optional[Any] = None,
    overrides: Optional[dict] = None,
) -> str:
    """Build the full caption.  `client` is the OpenAI-compatible
    DeepSeek client (passing None forces template-only mode).

    `overrides` lets the queue builder slot in a hand-edited line:
      {"hook": "...", "descriptive": "...", "facts": "...", "cta": "..."}
    Empty strings disable a section entirely."""
    if poster_type not in POSTER_TYPES:
        raise ValueError(f"unknown poster_type {poster_type!r}")
    listing = listing or {}
    overrides = overrides or {}

    hook = overrides.get("hook")
    if hook is None:
        hook = _hook_line(candidate, listing, poster_type)
    descriptive = overrides.get("descriptive")
    if descriptive is None:
        descriptive = generate_descriptive_line(
            candidate, listing, client=client, poster_type=poster_type,
        )
    facts = overrides.get("facts")
    if facts is None:
        facts = _facts_line(candidate, listing, poster_type)
    cta = overrides.get("cta")
    if cta is None:
        cta = _cta(candidate, poster_type)

    sections = [s for s in (hook, descriptive, facts, cta) if s]
    return "\n\n".join(sections)


# ── CLI ────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate one IG caption (template + optional DeepSeek)."
    )
    parser.add_argument(
        "--candidates", type=Path, default=Path("web/data/ig_candidates.json"),
    )
    parser.add_argument(
        "--ranked", type=Path, default=Path("web/data/ranked.json"),
    )
    parser.add_argument("--candidate-id", required=True, help="e.g. remax__001461165132")
    parser.add_argument(
        "--poster-type", default=TYPO_MAX, choices=POSTER_TYPES,
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip the DeepSeek call (template-only).  Useful for offline runs.",
    )
    args = parser.parse_args(argv)

    payload = json.loads(args.candidates.read_text(encoding="utf-8"))
    candidate = next(
        (c for c in payload.get("candidates", []) if c.get("listing_id") == args.candidate_id),
        None,
    )
    if candidate is None:
        print(f"candidate {args.candidate_id!r} not found", file=sys.stderr)
        return 2

    rows = json.loads(args.ranked.read_text(encoding="utf-8"))
    listing = next(
        (li for li in rows
         if li.get("source") == candidate.get("source")
         and li.get("source_id") == candidate.get("source_id")),
        {},
    )

    client = None
    if not args.no_llm:
        client, err = _build_client()
        if err:
            print(f"[ig_caption] LLM client unavailable ({err}) — template only",
                  file=sys.stderr)

    caption = generate_caption(
        candidate, listing,
        poster_type=args.poster_type, client=client,
    )
    print(caption)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
