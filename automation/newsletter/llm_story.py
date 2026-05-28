"""Per-pick warm story paragraph via DeepSeek (PR-NL-6).

A focused companion to llm_commentary.py — instead of asking the model
for the whole Commentary object, this module asks for ONE paragraph at
a time, scoped to a single pick. The voice rules live in
`voice_guide.md` (operator-editable, no code changes needed); this
module's job is to load that file, format a fact-limited prompt, call
DeepSeek, and return either a paragraph string or an error.

Architectural notes:

* The voice guide is the **system prompt**. We want DeepSeek's prefix
  cache to amortize its cost across the ~10 picks in one issue, so the
  voice guide stays constant and the per-pick facts go in the user
  message. Same trick llm_commentary.py uses.

* Strict fact subset. Every field in the prompt comes from the listing
  record on disk. No invented features, no derived rumors. If the data
  doesn't have it, the prompt doesn't mention it. This is the
  "factuality guardrail" from the voice guide enforced at the data
  layer too.

* Every error path returns an `LlmStoryResult` with `paragraph=None`
  and an `error` string — never raises. The caller in build_issue.py
  falls back to `commentary.deterministic_story_for_pick` when
  paragraph is None.

* Cost: priced under llm_commentary.py's existing cap
  (PULPO_NEWSLETTER_LLM_MAX_COMMENTARIES) — each story counts the same
  as a commentary toward the runaway-billing guard.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .llm_commentary import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    cost_usd,
)
from .types import Locale

# Sized to fit a paragraph that runs up to ~5 short paragraphs (the voice
# guide explicitly removes the length cap). 800 tokens ≈ 600 words —
# plenty for the longest hero-pick story, and well below DeepSeek's
# default ceiling.
MAX_TOKENS = 800

# Slightly higher than llm_commentary.py's temperature because the
# voice guide explicitly invites creativity within the rules. Still
# low enough that the output stays grounded in the facts.
TEMPERATURE = 0.6

VOICE_GUIDE_PATH = Path(__file__).parent / "voice_guide.md"


def _load_voice_guide() -> str:
    """Read voice_guide.md from disk at call time.

    Not cached — we want operator edits to take effect on the next
    Generate-test click without a redeploy of this module. The file is
    small (~5 KB) and we call this at most ~10 times per issue, so the
    read cost is negligible.

    Falls back to a minimal hard-coded directive if the file is missing
    so we don't take the entire newsletter pipeline down over an
    operator delete-by-mistake. CI's voice-guide-load test catches the
    missing-file case before any of this gets to production."""
    try:
        return VOICE_GUIDE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (
            "You are Pulpo, an editorial voice for an El Salvador real-"
            "estate newsletter. Speak warmly to the reader as 'you'. "
            "Use only the facts provided. Wrap the single emotional-"
            "center sentence in <em>...</em>. Never use real-estate "
            "clichés (stunning, breathtaking, paradise, don't miss out)."
        )


def _facts_for_pick(listing: dict, locale: Locale) -> dict:
    """Build the structured listing facts the prompt is allowed to use.

    Mirrors the same anti-fabrication design as llm_commentary._facts_for_prompt:
    strict subset, every field grounded in the listing record. The
    prompt instruction tells the LLM to use ONLY these fields — and the
    voice guide reinforces that as a hard rule. The intersection of
    the two enforces honesty.
    """
    tc = listing.get("title_canonical") or {}
    title = (tc.get(locale) if isinstance(tc, dict) else None) \
        or (tc.get("en") if isinstance(tc, dict) else None) \
        or listing.get("title")
    return {
        "title": title,
        "zone": listing.get("zone"),
        "municipality": listing.get("municipality"),
        "department": listing.get("department"),
        "property_type": listing.get("property_type"),
        "price_usd": listing.get("price_usd"),
        "previous_price": listing.get("previous_price"),
        "is_repriced": bool(listing.get("is_repriced")),
        "price_per_m2": listing.get("price_per_m2"),
        "price_vs_zone_pct": listing.get("price_vs_zone_pct"),
        "area_m2": listing.get("area_m2"),
        "built_area_m2": listing.get("built_area_m2"),
        "bedrooms": listing.get("bedrooms"),
        "bathrooms": listing.get("bathrooms"),
        "days_listed": listing.get("days_listed"),
        "is_beachfront": bool(listing.get("is_beachfront")),
        "is_walk_to_beach": bool(listing.get("is_walk_to_beach")),
        "dist_beach_km": listing.get("dist_beach_km"),
        "nearest_beach": listing.get("nearest_beach") or listing.get("named_beach_nearest"),
        "has_power": bool(listing.get("has_power")),
        "has_water": bool(listing.get("has_water")),
        "has_paved_access": bool(listing.get("has_paved_access")),
        "readiness_score": listing.get("readiness_score"),
        "has_ocean_view": bool(listing.get("has_ocean_view")),
        "has_water_body": bool(listing.get("has_water_body")),
        # The source description is included so the model can ground in
        # any feature the structured fields don't capture — but the
        # voice guide says: don't invent. If a feature isn't in this
        # description either, the model has no source to invent from.
        "source_description": (listing.get("short_description_canonical") or {}).get(locale, "")
            or (listing.get("short_description_canonical") or {}).get("en", "")
            or listing.get("description", ""),
    }


def _render_user_prompt(facts: dict, locale: Locale) -> str:
    """Single-shot user prompt: the facts as JSON + an explicit directive."""
    return (
        "Write the warm editorial paragraph for ONE listing for the Pulpo "
        f"newsletter. Locale: {locale}.\n"
        "\n"
        "Use ONLY the structured facts below — never invent a fact that "
        "isn't there. Follow the voice guide in the system prompt "
        "exactly. Wrap the single emotional-center sentence in "
        "<em>...</em>.\n"
        "\n"
        "Output the paragraph only — no headers, no markdown, no extra "
        "commentary, no JSON. Plain HTML with optional <em> tags is "
        "fine; nothing else.\n"
        "\n"
        "FACTS:\n" + json.dumps(facts, ensure_ascii=False, indent=2)
    )


@dataclass
class LlmStoryResult:
    paragraph: Optional[str]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    finish_reason: str
    error: Optional[str]


def _build_client():
    """Lazy-import the OpenAI SDK pointed at DeepSeek.

    Mirrors llm_commentary._build_client; returns (client, error_kind).
    Kept separate so this module has no top-level OpenAI import — the
    deterministic test suite must be able to import this module without
    pulling in the LLM SDK.
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


def _sanitize_paragraph(text: str) -> str:
    """Strip leading/trailing whitespace + remove any JSON wrapper the
    LLM accidentally emitted despite the instruction.

    Defensive — DeepSeek usually respects the "no JSON" instruction,
    but every now and then we get '{"paragraph": "..."}'. Detect that
    shape and unwrap before returning.
    """
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                for key in ("paragraph", "story", "text", "content"):
                    if isinstance(parsed.get(key), str):
                        return parsed[key].strip()
        except json.JSONDecodeError:
            pass
    # Remove a leading "Paragraph:" / "Story:" label if the model added one.
    for prefix in ("Paragraph:", "Story:", "Output:", "HTML:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def llm_story_for_pick(
    *,
    listing: dict,
    locale: Locale = "en",
    client_override: Any = None,
) -> LlmStoryResult:
    """Call DeepSeek for one warm paragraph; return LlmStoryResult.

    `client_override` is a test seam — pass a stub with a
    `.chat.completions.create(...)` method to bypass the OpenAI SDK
    entirely. Failure modes are surfaced through `error` rather than
    raised, so the caller can fall back to deterministic copy without
    try/except. This mirrors llm_commentary.llm_commentary's contract.
    """
    if client_override is not None:
        client, build_err = client_override, None
    else:
        client, build_err = _build_client()
    if client is None:
        return LlmStoryResult(
            paragraph=None, tokens_in=0, tokens_out=0, cost_usd=0.0,
            latency_ms=0, finish_reason="skipped", error=build_err,
        )

    voice_guide = _load_voice_guide()
    facts = _facts_for_pick(listing, locale)
    user_prompt = _render_user_prompt(facts, locale)

    t0 = time.monotonic()
    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": voice_guide},
                {"role": "user", "content": user_prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
    except Exception as e:                              # noqa: BLE001 — graceful degrade
        return LlmStoryResult(
            paragraph=None, tokens_in=0, tokens_out=0, cost_usd=0.0,
            latency_ms=round((time.monotonic() - t0) * 1000),
            finish_reason="error", error=type(e).__name__,
        )
    latency_ms = round((time.monotonic() - t0) * 1000)

    choice = resp.choices[0]
    finish_reason = getattr(choice, "finish_reason", None) or "stop"
    usage = getattr(resp, "usage", None)
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    c_usd = cost_usd(tokens_in, tokens_out)

    if finish_reason == "length":
        # Truncated mid-sentence; safer to fall back than ship a partial
        # paragraph. Mirror llm_commentary's same-decision branch.
        return LlmStoryResult(
            paragraph=None, tokens_in=tokens_in, tokens_out=tokens_out,
            cost_usd=c_usd, latency_ms=latency_ms,
            finish_reason=finish_reason, error="finish_reason_length",
        )

    raw = (choice.message.content or "").strip()
    if not raw:
        return LlmStoryResult(
            paragraph=None, tokens_in=tokens_in, tokens_out=tokens_out,
            cost_usd=c_usd, latency_ms=latency_ms,
            finish_reason=finish_reason, error="empty_response",
        )

    paragraph = _sanitize_paragraph(raw)
    if not paragraph:
        return LlmStoryResult(
            paragraph=None, tokens_in=tokens_in, tokens_out=tokens_out,
            cost_usd=c_usd, latency_ms=latency_ms,
            finish_reason=finish_reason, error="empty_after_sanitize",
        )

    return LlmStoryResult(
        paragraph=paragraph, tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=c_usd, latency_ms=latency_ms,
        finish_reason=finish_reason, error=None,
    )
