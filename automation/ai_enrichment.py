"""
PRD §FR-6 — production AI enrichment.

Generates title_canonical, short_description_canonical, and reasons_to_buy
for every listing using GPT-4o-mini. Idempotent: regenerates only when
description_raw md5 changes (PRD §FR-6.3).

Cache shape (web/data/ai_enrichment_cache.json):
    {
      "<source>|<source_id>": {
        "description_md5": "...",
        "title_canonical": "...",
        "short_description_canonical": "...",
        "reasons_to_buy": ["...", "...", "..."],
        "content_quality": "high|medium|low",
        "tokens_in": 387,
        "tokens_out": 152,
        "cost_usd": 0.000234,
        "model": "gpt-4o-mini",
        "ts": "2026-05-04T..."
      }
    }

Graceful degradation:
- OPENAI_API_KEY missing → skip entirely, listings keep AI fields as None.
- `openai` package missing → skip entirely (the dryrun harness imports
  it lazily; production does the same).
- Per-listing API error → log and skip that listing; don't kill the run.

Reuses the prompts from automation.ai_enrichment_dryrun (§8.1/§8.2/§8.3).
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from automation.ai_enrichment_dryrun import (   # type: ignore  # noqa: E402
    SYSTEM_TITLE,
    SYSTEM_DESCRIPTION,
    SYSTEM_USPS,
    PRICE_INPUT_PER_M_TOKENS,
    PRICE_OUTPUT_PER_M_TOKENS,
    _build_input as _build_dryrun_input,
)


CACHE_FILE = REPO / "web" / "data" / "ai_enrichment_cache.json"
DEFAULT_MODEL = "gpt-4o-mini"
TASKS = ("title_canonical", "short_description_canonical", "reasons_to_buy")


def _description_md5(li: Any) -> str:
    """Hash of description_raw, used as the cache invalidation key per FR-6.3."""
    desc = (li.get("description") if isinstance(li, dict) else getattr(li, "description", "")) or ""
    return hashlib.md5(desc.encode("utf-8")).hexdigest()


def _user_prompt(task: str, populated_json: str) -> str:
    if task == "title_canonical":
        return f"Generate the title for this listing. Input fields (null fields omitted): {populated_json}"
    return f"Input fields (null fields omitted): {populated_json}"


def _system_prompt(task: str) -> str:
    return {
        "title_canonical":              SYSTEM_TITLE,
        "short_description_canonical":  SYSTEM_DESCRIPTION,
        "reasons_to_buy":                SYSTEM_USPS,
    }[task]


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")


def _enrich_one(li: Any, client, model: str) -> dict:
    """Run all three tasks for one listing. Returns the cache entry."""
    inp = _build_dryrun_input(li if isinstance(li, dict) else _to_dict(li))
    populated_json = json.dumps(inp.populated, ensure_ascii=False, default=str)
    entry: dict[str, Any] = {
        "description_md5":  _description_md5(li),
        "content_quality":  inp.content_quality,
        "model":            model,
        "ts":               datetime.now(timezone.utc).isoformat(),
        "tokens_in":        0,
        "tokens_out":       0,
        "cost_usd":         0.0,
    }
    for task in TASKS:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _system_prompt(task)},
                {"role": "user",   "content": _user_prompt(task, populated_json)},
            ],
            temperature=0.3,
        )
        choice = (resp.choices[0].message.content or "").strip()
        usage  = resp.usage
        ti = usage.prompt_tokens     if usage else 0
        to = usage.completion_tokens if usage else 0
        entry["tokens_in"]  += ti
        entry["tokens_out"] += to
        entry["cost_usd"]   += round(
            ti * PRICE_INPUT_PER_M_TOKENS  / 1_000_000
            + to * PRICE_OUTPUT_PER_M_TOKENS / 1_000_000,
            8,
        )
        # Parse output per task type
        if task == "reasons_to_buy":
            bullets = [ln.strip() for ln in choice.splitlines() if ln.strip()][:3]
            entry[task] = bullets
        else:
            entry[task] = choice
    entry["cost_usd"] = round(entry["cost_usd"], 8)
    return entry


def _to_dict(li: Any) -> dict:
    """Best-effort dataclass-or-dict → dict for the prompt builder."""
    if isinstance(li, dict):
        return li
    if hasattr(li, "to_dict"):
        return li.to_dict()
    return {k: getattr(li, k, None) for k in dir(li) if not k.startswith("_")}


# Errors that mean "every subsequent call will fail the same way" — stop
# the run rather than logging 800 identical errors. Detected by class name
# OR HTTP status code in the error message.
_GLOBAL_ERROR_SUBSTRINGS = (
    "AuthenticationError",
    "PermissionDeniedError",
    "InvalidAPIKeyError",
    " 401 ",
    " 402 ",
    "insufficient_quota",
    "billing_hard_limit_reached",
    "rate_limit_exceeded",
)


def _is_global_error(exc: BaseException) -> bool:
    """True if the error is a permanent/quota/auth issue — short-circuit."""
    blob = f"{type(exc).__name__} {exc!r}"
    return any(s in blob for s in _GLOBAL_ERROR_SUBSTRINGS)


def enrich_listings(listings: list[Any],
                    cache_path: Path = CACHE_FILE,
                    model: str = DEFAULT_MODEL,
                    max_listings: int | None = None,
                    apply_fallback: bool = True) -> dict:
    """Enrich a list of Listing objects (or dicts). Returns metrics dict.

    Path matrix:
      OPENAI_API_KEY missing     → fallback only (no API)
      openai package missing     → fallback only
      Auth/quota error mid-run   → short-circuit, fallback for remaining
      Per-listing transient err  → fallback for that listing, continue
      Cache hit                  → use cached AI output
      Cache miss + API ok        → live AI call

    The fallback module ships title_canonical and reasons_to_buy from
    deterministic templates (PRD §8.1 + §8.3 are fully spec'd rule sets).
    short_description_canonical needs natural-language flow and stays
    None when AI is unavailable.

    Set apply_fallback=False to opt out (e.g. tests that want to verify
    pure-AI behavior).
    """
    metrics: dict[str, Any] = {
        "skipped_no_api_key":  False,
        "skipped_no_package":  False,
        "global_error_seen":   None,
        "cache_hits":          0,
        "cache_misses":        0,
        "api_calls_succeeded": 0,
        "api_calls_failed":    0,
        "fallback_applied":    0,
        "total_cost_usd":      0.0,
        "content_quality":     {"high": 0, "medium": 0, "low": 0},
    }

    # Lazy-import the fallback so this module stays importable even if
    # something goes wrong in fallback land (very unlikely — pure stdlib).
    _fb_apply = None
    if apply_fallback:
        try:
            from automation.ai_enrichment_fallback import apply_fallbacks as _fb_apply  # type: ignore
        except Exception as e:
            print(f"[ai_enrich] fallback module import failed: {e!r}")

    api_path_alive = True

    if not os.environ.get("OPENAI_API_KEY"):
        metrics["skipped_no_api_key"] = True
        api_path_alive = False
    else:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            metrics["skipped_no_package"] = True
            api_path_alive = False

    client = OpenAI() if api_path_alive else None   # type: ignore[name-defined]
    cache  = _load_cache(cache_path)

    n_processed = 0
    for li in listings:
        if max_listings is not None and n_processed >= max_listings:
            break
        n_processed += 1
        key = f"{_g(li, 'source')}|{_g(li, 'source_id')}"
        current_md5 = _description_md5(li)
        cached = cache.get(key)
        entry: dict[str, Any] | None = None

        if cached and cached.get("description_md5") == current_md5:
            metrics["cache_hits"] += 1
            entry = cached
        elif api_path_alive and client is not None:
            metrics["cache_misses"] += 1
            try:
                entry = _enrich_one(li, client, model)
                cache[key] = entry
                metrics["api_calls_succeeded"] += 1
                metrics["total_cost_usd"] += entry.get("cost_usd", 0.0)
            except Exception as e:
                metrics["api_calls_failed"] += 1
                print(f"[ai_enrich] {key}: {e!r}")
                if _is_global_error(e):
                    # Auth / quota / billing — every subsequent call would
                    # fail the same way. Switch off the API path; remaining
                    # listings get fallback templates only.
                    metrics["global_error_seen"] = type(e).__name__
                    api_path_alive = False
                    print(f"[ai_enrich] global error detected — disabling "
                          f"API path for remaining {len(listings) - n_processed} listings")
                entry = None

        # Apply AI fields if available
        if entry:
            _set(li, "title_canonical",              entry.get("title_canonical"))
            _set(li, "short_description_canonical",  entry.get("short_description_canonical"))
            _set(li, "reasons_to_buy",               entry.get("reasons_to_buy") or [])
            cq = entry.get("content_quality") or "low"
            metrics["content_quality"][cq] = metrics["content_quality"].get(cq, 0) + 1

        # Fallback: fills title_canonical + reasons_to_buy from PRD-spec
        # templates whenever they're not already set (no overwrite if AI
        # succeeded). short_description_canonical stays None — needs AI.
        if _fb_apply is not None:
            written = _fb_apply(li)
            if written:
                metrics["fallback_applied"] += 1

    metrics["total_cost_usd"] = round(metrics["total_cost_usd"], 6)
    _save_cache(cache_path, cache)
    return metrics
