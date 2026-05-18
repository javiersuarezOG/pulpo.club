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

# Per-call dollar cost rough estimate. Qwen3-VL Flash via DashScope is
# ~$0.0006 per call for a single 1080×1080 image at the prompt size
# below (input ~700 tokens, output ~80 tokens). The number is
# deliberately a single conservative figure rather than a per-token
# breakdown — we don't have real-time pricing, and the goal is to
# protect against runaway spend, not bill-accurate accounting. Override
# via LLM_VISION_COST_PER_CALL_USD for other providers (Claude
# claude-haiku-4-5 is ~$0.001 per image at similar prompt size).
_DEFAULT_COST_PER_CALL_USD = 0.0006

_DEFAULT_BUDGET_USD = 1.0

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
    "Return STRICT JSON only (no prose) matching:\n"
    '{"visual_appeal": <0-10 number>, "issues": [<string>...], '
    '"rationale": "<one sentence>"}'
)

_USER_PROMPT_TEXT = "Score this hero photo for the listing."


def score_aesthetic(raw_bytes: bytes) -> Optional[float]:
    """Return a 0-10 visual-appeal score for the image, or None when the
    booster is disabled / no key configured / daily budget exhausted /
    the provider call fails.

    Never raises. Callers in automation/run.py treat None as "no
    aesthetic signal available, use technical score alone".
    """
    if not _is_enabled():
        return None
    provider = _resolve_provider()
    if provider is None:
        return None
    if _budget_exhausted():
        _log_budget_event("llm_vision_budget_exceeded", provider=provider)
        return None

    score = None
    try:
        if provider == "qwen":
            score = _call_qwen(raw_bytes)
        elif provider == "openai":
            score = _call_openai(raw_bytes)
        elif provider == "anthropic":
            score = _call_anthropic(raw_bytes)
    except Exception as exc:  # noqa: BLE001 — booster is fail-soft
        _log_budget_event("llm_vision_call_failed", provider=provider,
                          error=str(exc)[:200])
        return None

    if score is None:
        return None

    # Record the spend even when the score parsing succeeds — keeps the
    # budget honest in the face of a 200 response we couldn't parse.
    _record_spend(provider=provider, score=score)
    return score


def _is_enabled() -> bool:
    val = os.environ.get("LLM_VISION_ENABLED", "false").strip().lower()
    return val in ("1", "true", "yes", "on")


def _resolve_provider() -> Optional[str]:
    """Return the active provider name when its API key is configured,
    else None. Priority: explicit env override → qwen → openai →
    anthropic. No silent fallback across providers when the operator
    explicitly named one — surfaces config errors loudly."""
    explicit = os.environ.get("LLM_VISION_PROVIDER", "").strip().lower()
    if explicit == "qwen":
        return "qwen" if os.environ.get("QWEN_API_KEY") else None
    if explicit == "openai":
        return "openai" if os.environ.get("OPENAI_API_KEY") else None
    if explicit == "anthropic" or explicit == "claude":
        return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else None

    # No explicit pick — auto-detect the first configured key.
    if os.environ.get("QWEN_API_KEY"):
        return "qwen"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


# ── Provider calls ────────────────────────────────────────────────────────

def _call_qwen(raw_bytes: bytes) -> Optional[float]:
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
    return _parse_score(content)


def _call_openai(raw_bytes: bytes) -> Optional[float]:
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
    return _parse_score(content)


def _call_anthropic(raw_bytes: bytes) -> Optional[float]:
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
    return _parse_score("\n".join(text_parts))


def _data_url(raw_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(raw_bytes).decode("ascii")


def _parse_score(content: str) -> Optional[float]:
    """Extract the visual_appeal number from the LLM's JSON response.
    Tolerates ```json fences and surrounding prose."""
    cleaned = content.replace("```json", "").replace("```", "").strip()
    # Some providers wrap the JSON inside a prose envelope; pull out the
    # first {...} block.
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    raw = data.get("visual_appeal")
    if isinstance(raw, (int, float)):
        return max(0.0, min(10.0, float(raw)))
    return None


# ── Budget tracking ────────────────────────────────────────────────────────

def _budget_log_path() -> Path:
    return _REPO_ROOT / "web" / "data" / "llm_vision_budget.jsonl"


def _today_iso() -> str:
    return date.today().isoformat()


def _cost_per_call() -> float:
    raw = os.environ.get("LLM_VISION_COST_PER_CALL_USD")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _DEFAULT_COST_PER_CALL_USD


def _daily_budget_usd() -> float:
    raw = os.environ.get("LLM_VISION_DAILY_BUDGET_USD")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _DEFAULT_BUDGET_USD


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


def _budget_exhausted() -> bool:
    return _spent_today() + _cost_per_call() > _daily_budget_usd()


def _record_spend(provider: str, score: float) -> None:
    path = _budget_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "event": "llm_vision_call",
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": _today_iso(),
        "provider": provider,
        "cost_usd": _cost_per_call(),
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
