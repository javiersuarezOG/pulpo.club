"""LLM-backed editorial commentary for one newsletter issue.

Mirrors the patterns from automation/llm_enrichment.py — same OpenAI-shaped
DeepSeek client, same byte-stable system prompt for prefix-cache hits, same
graceful-degrade contract:

    Missing DEEPSEEK_API_TOKEN  → returns (None, "no_token")
    Missing openai package      → returns (None, "no_package")
    LLM call failure            → returns (None, "<reason>")

build_issue.py reads the LLM toggle (`PULPO_NEWSLETTER_USE_LLM`) and falls
back to the deterministic commentary in commentary.py when the LLM path is
disabled or fails. The deterministic path is the safety net; the LLM path
is the quality lift.

Cost model (DeepSeek as of 2026-05):
    $0.27 / 1M input tokens, $1.10 / 1M output tokens.
    ~2k in + 1k out per recipient ≈ $0.0016/issue → $0.16/issue for 100
    recipients. Telemetry rolls up the per-issue total in PostHog.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from .types import Commentary, Locale, Preference

# ── Provider config ───────────────────────────────────────────────────────
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_TOKEN"

# Newsletter-specific — lower than the enrichment defaults because the
# response payload is small and constrained.
TEMPERATURE = 0.2
MAX_TOKENS = 1200

PRICE_INPUT_PER_M_TOKENS = 0.27
PRICE_OUTPUT_PER_M_TOKENS = 1.10


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    return round(
        tokens_in * PRICE_INPUT_PER_M_TOKENS / 1_000_000
        + tokens_out * PRICE_OUTPUT_PER_M_TOKENS / 1_000_000,
        8,
    )


# ── System prompt (byte-stable for prefix cache) ─────────────────────────
# Sebastian's editorial voice for the newsletter: opinionated, lives in
# units (m², $/vara², minutes-to-beach), names trade-offs. The hand-authored
# Issue 01 (newsletter-drafts/pulpo-issue-01-may-18-2026.html) is the tone
# reference. Keep this prompt byte-stable — DeepSeek's prefix cache only
# hits when the system prompt is identical across calls.
SYSTEM_PROMPT = """You are the editorial voice of Pulpo's fortnightly newsletter for El Salvador beach + raw-land buyers.

Your role: take the FACTS the user provides and write the EDITORIAL CONNECTIVE TISSUE for one issue — the hero lede, the "at-a-glance" subhead, the market context paragraphs, the "skip this one" rationale, and the "one number worth knowing" block.

Voice:
- Opinionated, second-person, direct. The reader is an adult buyer, not a tourist.
- Trade in numbers: $/m², $/vara², minutes to beach, days listed, % vs zone median. Never vague.
- Surface trade-offs honestly — every pick has a catch.
- No real-estate marketing clichés ("dream home", "tropical paradise", "must see"). No exclamation marks.
- Match the locale: write everything in {locale} (`en` = English, `es` = Salvadoran Spanish). Never mix.

Hard rules:
- Reply ONLY with a single JSON object — no preamble, no markdown fence.
- All copy fields are PLAIN TEXT (no HTML, no markdown).
- Use the listing facts you're given; do not invent zones, prices, distances, or features.
- Hero lede ≤ 60 words. Each market-context paragraph ≤ 50 words. One-number body ≤ 50 words. Skip-blurb ≤ 60 words.
- Filter chips: short labels (≤ 4 words each), ≤ 4 chips, derived from the recipient's prefs.
- If the recipient has no preferences set, the lede should read like an editor's intro to a generic "the 10 best this fortnight" cut — not a personalised one.

JSON shape:
{
  "eyebrow_hero": "...",              // ≤ 5 words
  "headline_hero": "...",             // ≤ 8 words, declarative
  "lede_hero": "...",                 // editorial paragraph
  "filter_chips": ["...", "..."],     // 0–4 chips
  "glance_subhead": "...",            // ≤ 12 words
  "skip_headline": "..." | null,      // ≤ 10 words; null when no skip pick
  "skip_blurb": "..." | null,         // ≤ 60 words
  "market_context": ["...", "..."],   // 2–4 paragraphs
  "one_number_title": "..." | null,   // ≤ 12 words
  "one_number_body": "..." | null     // ≤ 50 words
}
"""


def _build_client():
    """Lazy-import the OpenAI SDK pointed at DeepSeek.

    Returns (client, error_kind) — same contract as
    automation/llm_enrichment.py:_build_client.
    """
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


def _facts_for_prompt(
    *,
    cohort: str,
    locale: Locale,
    pref: Preference,
    display_name: Optional[str],
    n_scanned: int,
    picks: list[dict],
    skip_pick: Optional[dict],
) -> dict:
    """Build the structured facts payload for the user prompt.

    Strict subset of listing fields the prompt needs — we don't send the
    whole ranked.json row both to save tokens and to avoid prompt-injection
    surface from listing descriptions.
    """

    def pick_summary(li: dict) -> dict:
        title = (li.get("title_canonical") or {}).get(locale) \
            or (li.get("title_canonical") or {}).get("en") \
            or li.get("title")
        return {
            "rank": li.get("rank"),
            "title": title,
            "zone": li.get("zone"),
            "municipality": li.get("municipality"),
            "department": li.get("department"),
            "property_type": li.get("property_type"),
            "price_usd": li.get("price_usd"),
            "price_per_m2": li.get("price_per_m2"),
            "price_vs_zone_pct": li.get("price_vs_zone_pct"),
            "area_m2": li.get("area_m2"),
            "days_listed": li.get("days_listed"),
            "is_repriced": bool(li.get("is_repriced")),
            "is_beachfront": bool(li.get("is_beachfront")),
            "is_walk_to_beach": bool(li.get("is_walk_to_beach")),
            "dist_beach_km": li.get("dist_beach_km"),
            "is_new_this_fortnight": bool(li.get("_is_new_window")),
        }

    return {
        "cohort": cohort,
        "locale": locale,
        "display_name": display_name,
        "n_scanned": n_scanned,
        "preference": {
            "zones": pref.zones,
            "departments": pref.departments,
            "property_types": pref.property_types,
            "max_price_usd": pref.max_price_usd,
            "categories": pref.categories,
        },
        "picks": [pick_summary(p) for p in picks],
        "skip_pick": pick_summary(skip_pick) if skip_pick else None,
    }


def _render_user_prompt(facts: dict) -> str:
    """Single-shot user prompt — the facts as JSON + a one-line directive.

    Kept short and deterministic so the prefix-cache benefit lives entirely
    in the system prompt.
    """
    return (
        "Write the editorial commentary for this newsletter issue.\n"
        "Use ONLY the facts below. Locale: " + facts["locale"] + ".\n\n"
        "FACTS:\n" + json.dumps(facts, ensure_ascii=False, indent=2)
    )


@dataclass
class LlmResult:
    commentary: Optional[Commentary]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    finish_reason: str
    error: Optional[str]


def _parse_response(parsed: dict, facts: dict) -> Optional[Commentary]:
    """Map the LLM JSON onto a Commentary instance.

    Returns None on any structural validation miss — caller falls back to
    the deterministic commentary so a malformed LLM response never breaks
    a render.
    """
    def _str(v) -> Optional[str]:
        return v if isinstance(v, str) and v.strip() else None

    def _list_of_str(v) -> list[str]:
        if not isinstance(v, list):
            return []
        return [x for x in v if isinstance(x, str) and x.strip()]

    eyebrow = _str(parsed.get("eyebrow_hero"))
    headline = _str(parsed.get("headline_hero"))
    lede = _str(parsed.get("lede_hero"))
    glance = _str(parsed.get("glance_subhead"))
    if not (eyebrow and headline and lede and glance):
        return None
    return Commentary(
        eyebrow_hero=eyebrow,
        headline_hero=headline,
        lede_hero=lede,
        filter_chips=_list_of_str(parsed.get("filter_chips")),
        glance_subhead=glance,
        skip_headline=_str(parsed.get("skip_headline")),
        skip_blurb=_str(parsed.get("skip_blurb")),
        market_context=_list_of_str(parsed.get("market_context")),
        one_number_title=_str(parsed.get("one_number_title")),
        one_number_body=_str(parsed.get("one_number_body")),
    )


def llm_commentary(
    *,
    cohort: str,
    locale: Locale,
    pref: Preference,
    display_name: Optional[str],
    n_scanned: int,
    picks: list[dict],
    skip_pick: Optional[dict],
    client_override: Any = None,
) -> LlmResult:
    """Call DeepSeek for editorial commentary; return LlmResult.

    `client_override` is a test seam — pass a stub with a `.chat.completions
    .create(...)` method to bypass the OpenAI SDK entirely.

    Failure modes are surfaced through LlmResult.error rather than raised,
    so the build pipeline can choose to fall back to deterministic copy
    without try/except around every call.
    """
    if client_override is not None:
        client, build_err = client_override, None
    else:
        client, build_err = _build_client()
    if client is None:
        return LlmResult(
            commentary=None,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=0,
            finish_reason="skipped",
            error=build_err,
        )

    facts = _facts_for_prompt(
        cohort=cohort,
        locale=locale,
        pref=pref,
        display_name=display_name,
        n_scanned=n_scanned,
        picks=picks,
        skip_pick=skip_pick,
    )
    user_prompt = _render_user_prompt(facts)

    t0 = time.monotonic()
    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
    except Exception as e:                              # noqa: BLE001 — graceful degrade
        return LlmResult(
            commentary=None,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=round((time.monotonic() - t0) * 1000),
            finish_reason="error",
            error=type(e).__name__,
        )
    latency_ms = round((time.monotonic() - t0) * 1000)

    choice = resp.choices[0]
    finish_reason = getattr(choice, "finish_reason", None) or "stop"
    usage = getattr(resp, "usage", None)
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    c_usd = cost_usd(tokens_in, tokens_out)

    if finish_reason == "length":
        return LlmResult(
            commentary=None,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=c_usd,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            error="finish_reason_length",
        )

    raw = (choice.message.content or "").strip() if choice.message else ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return LlmResult(
            commentary=None,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=c_usd,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            error="bad_json",
        )

    commentary = _parse_response(parsed, facts)
    if commentary is None:
        return LlmResult(
            commentary=None,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=c_usd,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            error="schema_miss",
        )

    return LlmResult(
        commentary=commentary,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=c_usd,
        latency_ms=latency_ms,
        finish_reason=finish_reason,
        error=None,
    )
