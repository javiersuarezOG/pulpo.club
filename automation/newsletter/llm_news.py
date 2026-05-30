"""LLM ranker + summarizer for the Weekly News Spotlight.

Reads candidate articles from `news_search.fetch_candidates`, asks
DeepSeek to pick the ONE article most useful for a coastal-property
buyer in El Salvador and write an 80-word editorial summary in the
issue's locale. Returns a `NewsSpotlight` populated with the picked
article's source name, URL, and date — or `None` when no article was
useful (slow news week) / LLM unavailable / parse failure.

Mirrors the failure-mode contract from `llm_commentary.py`:
  • Missing DEEPSEEK_API_TOKEN  → returns None (no_token)
  • Missing `openai` package    → returns None (no_package)
  • Network / API error         → returns None (exception)
  • Bad JSON / schema-miss      → returns None (bad_json / schema_miss)

The renderer's deterministic fallback handles all None cases — the
newsletter ships either way, but never fabricates a citation.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Optional

from .news_search import CandidateArticle, fetch_candidates
from .types import NewsSpotlight

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_TOKEN"

# Approximate DeepSeek pricing as of 2026-05 ($/1M tokens, cache-miss).
# Used for telemetry only — the call is small enough that drift here
# doesn't affect billing reality.
_INPUT_USD_PER_M = 0.27
_OUTPUT_USD_PER_M = 1.10


_PROMPT_EN = """You are Pulpo's news editor. Pulpo is a curated weekly
newsletter for people buying coastal or lake property in El Salvador.

You will be given a JSON list of candidate news articles from the past 7
days — each with a source, URL, title, summary, and publication date.

Your job:
  1. Pick the ONE article that's most useful for a property buyer this week.
  2. Write a tight 80-word editorial summary explaining what changed,
     why it matters for someone buying coastal/lake property in El Salvador,
     and what they should know or do. Plain language, second-person ("you"),
     no real-estate jargon, no hype.
  3. If NO article in the list is genuinely useful (slow news week,
     all coverage is unrelated), return {"pick": null}.

Output STRICT JSON only, no markdown, no commentary:
{
  "pick": {
    "index": <int>,          // index into the candidate list
    "title": "<string>",     // ≤ 12 word H2 headline
    "summary": "<string>"    // ≤ 80 word editorial body
  }
}
or {"pick": null} for slow weeks.
"""

_PROMPT_ES = """Sos el editor de noticias de Pulpo. Pulpo es un boletín
semanal curado para personas que están comprando propiedad costera o de
lago en El Salvador.

Vas a recibir una lista JSON de artículos de noticias candidatos de los
últimos 7 días — cada uno con fuente, URL, título, resumen y fecha de
publicación.

Tu tarea:
  1. Escogé el ÚNICO artículo más útil para un comprador esta semana.
  2. Escribí un resumen editorial ajustado de 80 palabras explicando qué
     cambió, por qué importa para alguien comprando propiedad costera o
     de lago en El Salvador, y qué debería saber o hacer. Lenguaje claro,
     en segunda persona ("vos"/"tu"), sin jerga inmobiliaria, sin hype.
  3. Si NINGÚN artículo de la lista es genuinamente útil (semana
     tranquila, toda la cobertura es de otros temas), retorná {"pick": null}.

Salida JSON ESTRICTA, sin markdown, sin comentarios:
{
  "pick": {
    "index": <int>,
    "title": "<string>",
    "summary": "<string>"
  }
}
o {"pick": null} en semanas tranquilas.
"""


def pick_and_summarize(
    candidates: list[CandidateArticle],
    *,
    locale: str = "en",
    client_override=None,
) -> Optional[NewsSpotlight]:
    """LLM-pick the most useful article + write the editorial. Returns
    `None` on any failure / slow-week path.

    `client_override` lets tests inject a fake DeepSeek client; production
    builds one lazily via `_build_client`.
    """
    if not candidates:
        return None

    client, err = (client_override, None) if client_override else _build_client()
    if client is None:
        return None

    facts = _candidates_to_facts(candidates)
    user_msg = (
        f"Locale: {locale}\n\nCandidates (newest first):\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
        "Pick one and summarize. JSON only."
    )
    system_msg = _PROMPT_ES if locale == "es" else _PROMPT_EN

    t0 = time.monotonic()
    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            max_tokens=600,
        )
    except Exception:
        return None
    latency_ms = int((time.monotonic() - t0) * 1000)
    _ = latency_ms  # reserved for telemetry hook

    raw = (resp.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    pick = data.get("pick")
    if not isinstance(pick, dict):
        return None  # slow-week path returns {"pick": null}

    try:
        idx = int(pick.get("index", -1))
    except (TypeError, ValueError):
        return None
    if not (0 <= idx < len(candidates)):
        return None

    title = str(pick.get("title") or "").strip()
    summary = str(pick.get("summary") or "").strip()
    if not title or not summary:
        return None

    article = candidates[idx]
    cost_usd = _estimate_cost_usd(resp)

    return NewsSpotlight(
        title=title,
        paragraph=summary,
        source_name=article.source_name,
        source_url=article.source_url,
        source_date=_format_date(article.published_at, locale),
        candidates_seen=len(candidates),
        llm_cost_usd=cost_usd,
    )


def fetch_pick_and_summarize(
    *,
    locale: str = "en",
    client_override=None,
    fetcher=None,
    now: datetime | None = None,
) -> Optional[NewsSpotlight]:
    """End-to-end convenience for `build_issue`: fetch RSS → LLM pick →
    NewsSpotlight. Returns None on slow weeks / LLM unavailable / fetch
    failure. Dependency-inject `fetcher` for tests."""
    candidates = fetch_candidates(fetcher=fetcher, now=now)
    return pick_and_summarize(candidates, locale=locale, client_override=client_override)


# ── Internal helpers ─────────────────────────────────────────────────


def _build_client():
    """Lazy DeepSeek client. Returns (client, error_kind). Mirrors
    `llm_commentary._build_client` for failure-mode parity."""
    if not os.environ.get(DEEPSEEK_API_KEY_ENV):
        return (None, "no_token")
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return (None, "no_package")
    return (
        OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=os.environ[DEEPSEEK_API_KEY_ENV]),
        None,
    )


def _candidates_to_facts(candidates: list[CandidateArticle]) -> list[dict]:
    """Compact prompt-friendly view of each candidate. Summary is
    capped at 300 chars so the prompt stays under ~3K tokens with 20
    candidates."""
    out: list[dict] = []
    for i, c in enumerate(candidates):
        out.append({
            "index": i,
            "source": c.source_name,
            "url": c.source_url,
            "title": c.title,
            "summary": c.summary[:300],
            "published": c.published_at.strftime("%Y-%m-%d"),
        })
    return out


_ES_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_EN_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _format_date(dt: datetime, locale: str) -> str:
    """Locale-aware short date string (e.g. '28 May 2026' / '28 may 2026')."""
    months = _ES_MONTHS if locale == "es" else _EN_MONTHS
    return f"{dt.day} {months[dt.month - 1]} {dt.year}"


def _estimate_cost_usd(resp) -> float:
    """Estimate the call's DeepSeek cost in USD. Pricing constants at
    the top of this file — drift here doesn't affect billing reality."""
    usage = getattr(resp, "usage", None)
    if not usage:
        return 0.0
    pt = getattr(usage, "prompt_tokens", 0) or 0
    ct = getattr(usage, "completion_tokens", 0) or 0
    return (pt * _INPUT_USD_PER_M + ct * _OUTPUT_USD_PER_M) / 1_000_000.0
