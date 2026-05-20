"""
Phase 4 U3 — LLM-vision aesthetic booster (default OFF).

Wires Qwen3-VL Flash (Alibaba DashScope OpenAI-compatible endpoint) and
optional Claude/OpenAI vision providers into hero re-escalation. The
booster is strictly additive:

  - With no LLM_VISION_ENABLED env var (or set to "false"), every call
    returns None and `_pick_best_photo_url` ignores it — picker falls
    back to the existing PR-7.6 compute_score + detect_text_overlay
    ordering. Production-safe default.

  - With LLM_VISION_ENABLED=true AND the configured provider's API key
    set (default provider: qwen → QWEN_API_KEY), each candidate gets a
    0-10 visual_appeal score that feeds the composite ranking in
    automation/run.py.

  - Daily USD budget cap (LLM_VISION_DAILY_BUDGET_USD, default $1) is
    tracked in web/data/llm_vision_budget.jsonl. Once exhausted, calls
    return None for the rest of the calendar day and selection falls
    back to technical-score-only.

Provider routing reuses the OpenAI SDK already in requirements.txt.
Qwen3-VL Flash is exposed by DashScope at
`https://dashscope.aliyuncs.com/compatible-mode/v1` in OpenAI-compat
mode, identical to pointing the SDK at DeepSeek.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

# Repo root resolved from this file's location — automation/ is a
# package directly under repo root. Matches the pattern used by
# automation/run.py for web/data writes.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Per-call dollar cost rough estimate. The numbers are deliberately
# conservative single figures rather than per-token breakdowns — we
# don't have real-time pricing, and the goal is to protect against
# runaway spend, not bill-accurate accounting. Override via
# LLM_VISION_COST_PER_CALL_USD if you need a different cap basis.
#
# Provider notes:
#   - qwen      DashScope Qwen3-VL Flash ~$0.0006/call for a 1080² image
#   - segmind   Segmind Qwen3-VL Flash ~$0.0008/call at the same prompt size
#   - openai    gpt-4o-mini vision ~$0.0008/image
#   - anthropic claude-haiku-4-5 vision ~$0.001/image
_DEFAULT_COSTS_BY_PROVIDER = {
    "qwen":      0.0006,
    "segmind":   0.0008,
    "openai":    0.0008,
    "anthropic": 0.001,
}
# Back-compat for callers/tests that referenced the old single constant.
_DEFAULT_COST_PER_CALL_USD = _DEFAULT_COSTS_BY_PROVIDER["qwen"]

_DEFAULT_BUDGET_USD = 1.0

# Aesthetic-score cache. Keyed on sha1(image_bytes)[:16] so identical
# images across runs reuse the prior score for free. The cache lives in
# web/data/ alongside the budget log; commit it (same policy as other
# generated web/data/*.json outputs) so CI / fresh clones don't cold-
# start with $-spend per candidate.
_CACHE_MAX_ROWS = 50_000

_SYSTEM_PROMPT = (
    "You are a real-estate marketing photo critic. Score the photo's "
    "appeal as a hero image for a real-estate listing on a property "
    "discovery site.\n\n"
    "Score 0-10:\n"
    "  10 = stunning, magazine-quality, would stop the scroll\n"
    "  7-9 = professional, clean, attractive\n"
    "  4-6 = acceptable, technically OK but uninspiring\n"
    "  1-3 = poor — bad composition, awkward angle, no focal point, "
    "cluttered\n"
    "  0 = unusable — heavily watermarked, dominated by text, broken\n\n"
    "Also detect whether the image carries ANY marketing overlay — text "
    "banners, watermarks, agency logos, price stamps, 'SOLD' / 'FOR SALE' "
    "/ 'PRICE REDUCTION' badges — even small, even partially transparent. "
    "If you see ANY non-photographic text or logo overlay, set "
    "has_marketing_overlay=true. A clean property photo with no stamps "
    "or banners is has_marketing_overlay=false.\n\n"
    "Return STRICT JSON only (no prose) matching:\n"
    '{"visual_appeal": <0-10 number>, '
    '"has_marketing_overlay": <true|false>, '
    '"rationale": "<one sentence>"}'
)

_USER_PROMPT_TEXT = "Score this hero photo for the listing."


def score_aesthetic(raw_bytes: bytes) -> Optional[dict]:
    """Return ``{"score": 0-10, "has_marketing_overlay": bool|None}`` for the
    image, or None when the booster is disabled / no key configured /
    daily budget exhausted / the provider call fails.

    Never raises. Callers in automation/run.py treat None as "no
    aesthetic signal available, use technical score alone".

    Cache rows written before the marketing-overlay field existed return
    ``has_marketing_overlay=None`` — the picker treats that as "no
    signal" (same null-tolerance as ``has_text_overlay``), so legacy
    cache rows don't false-reject. Rescore via repick-heroes.yml to
    repopulate.
    """
    if not _is_enabled():
        return None
    provider = _resolve_provider()
    if provider is None:
        return None
    # Cache hit — short-circuit the provider call. No spend recorded
    # because none was incurred. We still return the score for ranking.
    key = _cache_key(raw_bytes)
    cache = _load_cache()
    hit = cache.get(key)
    if hit is not None:
        cached_score = hit.get("score")
        if isinstance(cached_score, (int, float)):
            cached_overlay = hit.get("has_marketing_overlay")
            overlay = bool(cached_overlay) if isinstance(cached_overlay, bool) else None
            return {"score": float(cached_score), "has_marketing_overlay": overlay}

    if _budget_exhausted(provider=provider):
        _log_budget_event("llm_vision_budget_exceeded", provider=provider)
        return None

    result: Optional[tuple[Optional[float], Optional[bool]]] = None
    try:
        if provider == "qwen":
            result = _call_qwen(raw_bytes)
        elif provider == "segmind":
            result = _call_segmind(raw_bytes)
        elif provider == "openai":
            result = _call_openai(raw_bytes)
        elif provider == "anthropic":
            result = _call_anthropic(raw_bytes)
    except Exception as exc:  # noqa: BLE001 — booster is fail-soft
        _log_budget_event("llm_vision_call_failed", provider=provider,
                          error=str(exc)[:200])
        return None

    if result is None:
        return None
    score, has_overlay = result
    if score is None:
        return None

    # Record the spend even when the score parsing succeeds — keeps the
    # budget honest in the face of a 200 response we couldn't parse.
    _record_spend(provider=provider, score=score)
    _write_cache(cache, key, provider=provider, score=score,
                 has_marketing_overlay=has_overlay)
    return {"score": score, "has_marketing_overlay": has_overlay}


def _is_enabled() -> bool:
    from automation._config import env_bool
    return env_bool("LLM_VISION_ENABLED", False)


def _resolve_provider() -> Optional[str]:
    """Return the active provider name when its API key is configured,
    else None. Priority: explicit env override → qwen → segmind → openai
    → anthropic. No silent fallback across providers when the operator
    explicitly named one — surfaces config errors loudly."""
    explicit = os.environ.get("LLM_VISION_PROVIDER", "").strip().lower()
    if explicit == "qwen":
        return "qwen" if os.environ.get("QWEN_API_KEY") else None
    if explicit == "segmind":
        return "segmind" if os.environ.get("SEGMIND_API_KEY") else None
    if explicit == "openai":
        return "openai" if os.environ.get("OPENAI_API_KEY") else None
    if explicit == "anthropic" or explicit == "claude":
        return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else None

    # No explicit pick — auto-detect the first configured key. DashScope
    # stays first per .env.example's "recommended" guidance; Segmind is
    # opt-in but ranks ahead of openai/anthropic because it's a cheaper
    # peer of the same Qwen3-VL model rather than a different model
    # family.
    if os.environ.get("QWEN_API_KEY"):
        return "qwen"
    if os.environ.get("SEGMIND_API_KEY"):
        return "segmind"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


# ── Provider calls ────────────────────────────────────────────────────────

def _call_qwen(raw_bytes: bytes) -> Optional[tuple[Optional[float], Optional[bool]]]:
    """Qwen3-VL Flash via DashScope's OpenAI-compatible endpoint."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    base_url = os.environ.get(
        "QWEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model = os.environ.get("QWEN_VISION_MODEL", "qwen3-vl-flash")
    client = OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url=base_url)
    data_url = _data_url(raw_bytes)
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=256,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_PROMPT_TEXT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    )
    content = resp.choices[0].message.content or ""
    return _parse_response(content)


def _call_segmind(raw_bytes: bytes) -> Optional[tuple[Optional[float], Optional[bool]]]:
    """Qwen3-VL Flash via Segmind's model-specific endpoint.

    Segmind is NOT a standard OpenAI-compatible chat-completions
    endpoint — the URL embeds the model name, and auth is an
    ``x-api-key`` header instead of ``Authorization: Bearer``. So we
    bypass the OpenAI SDK and POST directly. Body shape mirrors the
    OpenAI vision spec (Segmind documents it as "OpenAI GPT (Standard
    Format)" but only on the request body, not the transport layer).
    """
    import httpx
    base_url = os.environ.get("SEGMIND_BASE_URL", "https://api.segmind.com/v1").rstrip("/")
    model = os.environ.get("SEGMIND_VISION_MODEL", "qwen3-vl-flash")
    url = f"{base_url}/{model}"
    headers = {
        "x-api-key": os.environ["SEGMIND_API_KEY"],
        "Content-Type": "application/json",
    }
    data_url = _data_url(raw_bytes)
    payload = {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_PROMPT_TEXT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "temperature": 0,
        "max_tokens": 256,
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=30.0)
    resp.raise_for_status()
    body = resp.json()
    try:
        content = body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return None
    return _parse_response(content)


def _call_openai(raw_bytes: bytes) -> Optional[tuple[Optional[float], Optional[bool]]]:
    try:
        from openai import OpenAI
    except ImportError:
        return None
    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    data_url = _data_url(raw_bytes)
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=256,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_PROMPT_TEXT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    )
    content = resp.choices[0].message.content or ""
    return _parse_response(content)


def _call_anthropic(raw_bytes: bytes) -> Optional[tuple[Optional[float], Optional[bool]]]:
    # Optional dependency — only imported when explicitly chosen. Keeps
    # `anthropic` out of the base requirements.txt while the booster
    # ships as off-by-default.
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError:
        return None
    model = os.environ.get("ANTHROPIC_VISION_MODEL", "claude-haiku-4-5-20251001")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    msg = client.messages.create(
        model=model,
        max_tokens=256,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_PROMPT_TEXT},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                ],
            }
        ],
    )
    text_parts: list[str] = []
    for b in msg.content:
        if getattr(b, "type", None) == "text":
            text_parts.append(getattr(b, "text", "") or "")
    return _parse_response("\n".join(text_parts))


def _data_url(raw_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(raw_bytes).decode("ascii")


def _parse_response(content: str) -> tuple[Optional[float], Optional[bool]]:
    """Extract (visual_appeal, has_marketing_overlay) from the LLM's JSON
    response. Tolerates ```json fences and surrounding prose. Either
    field can be None when the model omits it or the response is
    unparseable — callers treat None on either axis as "no signal."
    """
    cleaned = content.replace("```json", "").replace("```", "").strip()
    # Some providers wrap the JSON inside a prose envelope; pull out the
    # first {...} block.
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return (None, None)
    raw_score = data.get("visual_appeal")
    score = (max(0.0, min(10.0, float(raw_score)))
             if isinstance(raw_score, (int, float)) else None)
    raw_overlay = data.get("has_marketing_overlay")
    overlay = bool(raw_overlay) if isinstance(raw_overlay, bool) else None
    return (score, overlay)


# ── Budget tracking ────────────────────────────────────────────────────────

def _budget_log_path() -> Path:
    return _REPO_ROOT / "web" / "data" / "llm_vision_budget.jsonl"


def _today_iso() -> str:
    return date.today().isoformat()


def _cost_per_call(provider: Optional[str] = None) -> float:
    """Per-call cost estimate. Operator override via
    LLM_VISION_COST_PER_CALL_USD always wins; otherwise the provider's
    listed default is returned. When ``provider`` is None (legacy
    callsite), the qwen default holds — matches pre-refactor behavior.
    """
    from automation._config import env_float
    fallback = (_DEFAULT_COSTS_BY_PROVIDER.get(provider, _DEFAULT_COST_PER_CALL_USD)
                if provider else _DEFAULT_COST_PER_CALL_USD)
    return env_float("LLM_VISION_COST_PER_CALL_USD", fallback)


def _daily_budget_usd() -> float:
    from automation._config import env_float
    return env_float("LLM_VISION_DAILY_BUDGET_USD", _DEFAULT_BUDGET_USD)


def _spent_today() -> float:
    """Sum recorded spend for today from the rolling jsonl log. Reads
    the whole file each call — fine because the per-day row count is at
    most ~hundreds (5 candidates × ~200 listings)."""
    path = _budget_log_path()
    if not path.exists():
        return 0.0
    today = _today_iso()
    total = 0.0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("event") == "llm_vision_call" and row.get("date") == today:
                    total += float(row.get("cost_usd", 0.0))
    except OSError:
        return 0.0
    return total


def _budget_exhausted(provider: Optional[str] = None) -> bool:
    return _spent_today() + _cost_per_call(provider=provider) > _daily_budget_usd()


def _record_spend(provider: str, score: float) -> None:
    path = _budget_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "event": "llm_vision_call",
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": _today_iso(),
        "provider": provider,
        "cost_usd": _cost_per_call(provider=provider),
        "score": round(score, 2),
    }
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        # Budget log failure is non-fatal — the booster still ran, we
        # just can't enforce a tight cap until the next successful
        # write. Better than throwing in the hot path.
        pass


def _log_budget_event(event: str, **kwargs: object) -> None:
    path = _budget_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "event": event,
            "ts": datetime.now(timezone.utc).isoformat(),
            "date": _today_iso(),
            **kwargs,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


# ── Aesthetic-score cache ─────────────────────────────────────────────────

def _cache_path() -> Path:
    return _REPO_ROOT / "web" / "data" / "llm_vision_cache.json"


def _cache_key(raw_bytes: bytes) -> str:
    """SHA1 prefix of the image bytes. 16 hex chars = 64 bits of entropy
    which is comfortably below the birthday-collision threshold for the
    cache's 50k-row cap."""
    return hashlib.sha1(raw_bytes).hexdigest()[:16]


def _load_cache() -> dict:
    """Return the on-disk cache as a dict, or {} on any failure. The
    cache is fail-soft by design — a corrupt file just means the next
    call pays full price (and overwrites the corruption on the next
    successful write)."""
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(cache: dict, key: str, *, provider: str, score: float,
                 has_marketing_overlay: Optional[bool] = None) -> None:
    """Insert (key → {score, has_marketing_overlay, provider, model, ts}) and
    persist. Evicts the oldest rows when the cache grows past
    _CACHE_MAX_ROWS. Write is atomic (tmp file + rename) so a crash
    mid-write can't corrupt the cache."""
    cache[key] = {
        "score": round(float(score), 2),
        "has_marketing_overlay": has_marketing_overlay,
        "provider": provider,
        "model": _model_for_provider(provider),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if len(cache) > _CACHE_MAX_ROWS:
        # Sort by ts ascending and drop the oldest 10% in one pass —
        # cheaper than evicting one-at-a-time on subsequent writes.
        rows = sorted(cache.items(), key=lambda kv: kv[1].get("ts", ""))
        drop = max(1, len(cache) - _CACHE_MAX_ROWS) + (_CACHE_MAX_ROWS // 10)
        cache = dict(rows[drop:])
    path = _cache_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        # Mirrors the budget-log policy: a write failure doesn't bubble
        # up — the booster already scored this candidate, we just can't
        # cache it. Worst case is one extra paid call next run.
        pass


def _model_for_provider(provider: str) -> str:
    """The model name a provider was configured against — embedded in
    cache rows so an operator swapping the model env var doesn't get
    cross-model cache hits."""
    if provider == "qwen":
        return os.environ.get("QWEN_VISION_MODEL", "qwen3-vl-flash")
    if provider == "segmind":
        return os.environ.get("SEGMIND_VISION_MODEL", "qwen3-vl-flash")
    if provider == "openai":
        return os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_VISION_MODEL", "claude-haiku-4-5-20251001")
    return provider


def daily_summary() -> dict:
    """Operator-facing — used by /healthz extension to surface today's
    aesthetic-vision activity. Returns counts + spend without exposing
    individual rows."""
    path = _budget_log_path()
    if not path.exists():
        return _summary_zero()
    today = _today_iso()
    calls = 0
    spend = 0.0
    failures = 0
    budget_exceeded = 0
    by_provider: dict[str, int] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("date") != today:
                    continue
                event = row.get("event")
                if event == "llm_vision_call":
                    calls += 1
                    spend += float(row.get("cost_usd", 0.0))
                    p = row.get("provider", "unknown")
                    by_provider[p] = by_provider.get(p, 0) + 1
                elif event == "llm_vision_call_failed":
                    failures += 1
                elif event == "llm_vision_budget_exceeded":
                    budget_exceeded += 1
    except OSError:
        return _summary_zero()
    return {
        "enabled": _is_enabled(),
        "provider": _resolve_provider(),
        "calls": calls,
        "failures": failures,
        "budget_exceeded_count": budget_exceeded,
        "spend_usd": round(spend, 4),
        "budget_cap_usd": _daily_budget_usd(),
        "by_provider": by_provider,
    }


def _summary_zero() -> dict:
    return {
        "enabled": _is_enabled(),
        "provider": _resolve_provider(),
        "calls": 0,
        "failures": 0,
        "budget_exceeded_count": 0,
        "spend_usd": 0.0,
        "budget_cap_usd": _daily_budget_usd(),
        "by_provider": {},
    }
