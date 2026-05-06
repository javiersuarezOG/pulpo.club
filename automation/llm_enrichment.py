"""
PRD WS2 — single-call DeepSeek enrichment per listing.

Replaces the legacy 3-call OpenAI enrichment in automation/ai_enrichment.py.
For each eligible listing, makes ONE chat-completion call to DeepSeek
(OpenAI-compatible endpoint) and gets back a JSON object containing
title + description + usps + latlong in one shot — no per-field re-send
of the long source description.

The eligibility rule, the JSON shape, and the apply-on-success step
are all driven by `automation/llm_enrichment_schema.py`'s
DEFAULT_SCHEMA. Adding a 5th derived field later is a one-line change
there; this orchestration module stays unchanged.

Idempotency is hard: a listing is enriched at most once under this
flow. The sidecar (web/data/llm_enrichment.json) is the source of
truth — if a listing has an entry there, it's rehydrated from it
without an API call. There is intentionally NO description-md5
invalidation. Re-running the job is a no-op for already-enriched
listings until partial regeneration is added later.

Failure modes (each treated as a clean failure — no partial save):
- DEEPSEEK_API_TOKEN missing       → skip the API path entirely
- openai package missing           → same
- finish_reason == "length"        → response may be truncated, fail
- response not parseable as JSON   → fail
- response fails schema validation → fail
- HTTP / network error             → fail this listing, continue

Public API:

    from automation.llm_enrichment import enrich_listings
    metrics = enrich_listings(listings, sidecar_path, log_path)
    # listings now have title_canonical / short_description_canonical /
    # reasons_to_buy / lat / lng / geocoding_* / enriched_at /
    # enrichment_model populated for newly-enriched ones; others
    # rehydrated from the sidecar.
"""
from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from automation.llm_enrichment_schema import (   # type: ignore  # noqa: E402
    DEFAULT_SCHEMA,
    EnrichmentSchema,
    apply_response,
    is_eligible,
    validate_response,
)
from automation.llm_enrichment_prompts import (   # type: ignore  # noqa: E402
    SYSTEM_PROMPT,
    render_user_prompt,
)


# DeepSeek pricing — public docs as of 2026-05. Used for cost telemetry
# only; never gates behavior. Update when DeepSeek revises the pricing
# page. (Numbers are USD per 1M tokens.)
PRICE_INPUT_PER_M_TOKENS  = 0.27
PRICE_OUTPUT_PER_M_TOKENS = 1.10


# Errors we treat as "every subsequent call will fail the same way" —
# stop the run rather than logging hundreds of identical errors. Mirrors
# the pattern in automation/ai_enrichment.py:_GLOBAL_ERROR_SUBSTRINGS.
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


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


def _key(li: Any) -> str:
    return f"{_g(li, 'source')}|{_g(li, 'source_id')}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_global_error(exc: BaseException) -> bool:
    blob = f"{type(exc).__name__} {exc!r}"
    return any(s in blob for s in _GLOBAL_ERROR_SUBSTRINGS)


def _load_sidecar(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_sidecar(path: Path, sidecar: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _append_log(path: Path, event: dict) -> None:
    """Append one JSONL event to the audit log. Best-effort — log I/O
    must never kill the enrichment run."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"[llm_enrich] audit log write failed: {e!r}")


def _cost_usd(tokens_in: int, tokens_out: int) -> float:
    return round(
        tokens_in  * PRICE_INPUT_PER_M_TOKENS  / 1_000_000
        + tokens_out * PRICE_OUTPUT_PER_M_TOKENS / 1_000_000,
        8,
    )


def _hydrate_from_sidecar(li: Any, entry: dict,
                          schema: EnrichmentSchema) -> None:
    """Replay a previously-saved enrichment onto the listing without an
    API call. The sidecar carries the same shape as the parsed LLM
    response (mapped to listing attrs at write time), so we can just
    re-apply each schema field's `apply` callable.

    The sidecar stores values in the listing's coordinate system (e.g.
    `title_canonical`, not `title`). We rebuild a parsed-shape dict by
    reading the first target_attr per field — except for latlong, which
    is reconstructed from its 5 fanned-out attrs.
    """
    parsed: dict[str, Any] = {}
    for f in schema.fields:
        if f.json_key == "latlong":
            parsed["latlong"] = {
                "lat":        entry.get("lat"),
                "lng":        entry.get("lng"),
                "source":     entry.get("geocoding_source"),
                "reference":  entry.get("geocoding_reference"),
                "confidence": entry.get("geocoding_confidence"),
            }
        else:
            parsed[f.json_key] = entry.get(f.target_attrs[0])

    # Re-validate before rehydrating — defends against a sidecar that
    # was written by an older, looser schema version. If it doesn't
    # validate now, treat as no-cache and let the eligibility check
    # decide whether to re-call the API.
    ok, _ = validate_response(parsed, schema)
    if ok:
        apply_response(li, parsed, schema)
        _set(li, "enriched_at",      entry.get("ts"))
        _set(li, "enrichment_model", entry.get("model"))


def _build_sidecar_entry(li: Any, schema: EnrichmentSchema,
                         model: str, ts: str, finish_reason: str,
                         usage: Any, latency_ms: int) -> dict:
    """Build the per-listing sidecar entry after a validated response
    has been applied to the listing.

    Pre-condition: `apply_response(li, parsed, schema)` already ran, so
    the listing carries the canonical attrs. The sidecar mirrors the
    listing shape (e.g. `title_canonical`, not `title`) so a future
    hydration pass can replay it without re-running schema callables.
    """
    tokens_in  = getattr(usage, "prompt_tokens",     0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    return {
        "ts":                          ts,
        "model":                       model,
        "schema_version":              schema.schema_version,
        "title_canonical":             _g(li, "title_canonical"),
        "short_description_canonical": _g(li, "short_description_canonical"),
        "reasons_to_buy":              list(_g(li, "reasons_to_buy") or []),
        "lat":                         _g(li, "lat"),
        "lng":                         _g(li, "lng"),
        "geocoding_confidence":        _g(li, "geocoding_confidence"),
        "geocoding_source":            _g(li, "geocoding_source"),
        "geocoding_reference":         _g(li, "geocoding_reference"),
        "tokens_in":                   tokens_in,
        "tokens_out":                  tokens_out,
        "cost_usd":                    _cost_usd(tokens_in, tokens_out),
        "finish_reason":               finish_reason,
        "latency_ms":                  latency_ms,
    }


def _build_client(schema: EnrichmentSchema):
    """Lazy-import the OpenAI SDK pointed at DeepSeek's base_url.

    Returns (client, error_kind):
      ("client", None)        — ready to call
      (None, "no_token")      — DEEPSEEK_API_TOKEN env var missing
      (None, "no_package")    — openai package not importable
    """
    if not os.environ.get(schema.api_key_env):
        return (None, "no_token")
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return (None, "no_package")
    return (OpenAI(
        base_url=schema.base_url,
        api_key=os.environ[schema.api_key_env],
    ), None)


def _enrich_one(client, li: Any, schema: EnrichmentSchema
                ) -> tuple[str, dict | None, dict]:
    """Make ONE DeepSeek call for one eligible listing.

    Returns a (decision, sidecar_entry, log_event) triple:
      decision      ∈ {"enriched", "failed"}
      sidecar_entry — populated only on success, None on failure
      log_event     — JSONL event with telemetry, always populated

    On success, the listing is mutated in-place via apply_response().
    On failure, the listing is left untouched (no partial save).
    """
    description = _g(li, "description") or ""
    user_prompt = render_user_prompt(description)

    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=schema.model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=schema.temperature,
        max_tokens=schema.max_tokens,
    )
    latency_ms = round((time.monotonic() - t0) * 1000)

    choice = resp.choices[0]
    finish_reason = getattr(choice, "finish_reason", None) or "stop"
    usage         = getattr(resp, "usage", None)
    tokens_in     = getattr(usage, "prompt_tokens",     0) or 0
    tokens_out    = getattr(usage, "completion_tokens", 0) or 0

    base_event = {
        "ts":            _now_iso(),
        "key":           _key(li),
        "model":         schema.model,
        "finish_reason": finish_reason,
        "tokens_in":     tokens_in,
        "tokens_out":    tokens_out,
        "cost_usd":      _cost_usd(tokens_in, tokens_out),
        "latency_ms":    latency_ms,
    }

    # Fail-closed gate 1: truncated response
    if finish_reason == "length":
        return ("failed", None,
                {**base_event, "decision": "failed",
                 "reason": "finish_reason_length"})

    # Fail-closed gate 2: malformed JSON
    raw = (choice.message.content or "").strip() if choice.message else ""
    try:
        parsed = json.loads(raw)
    except Exception:
        return ("failed", None,
                {**base_event, "decision": "failed",
                 "reason": "json_parse"})

    # Fail-closed gate 3: schema validation
    ok, val_reason = validate_response(parsed, schema)
    if not ok:
        return ("failed", None,
                {**base_event, "decision": "failed",
                 "reason": f"schema_invalid:{val_reason}"})

    # Atomic apply (only after all validators pass)
    ts = _now_iso()
    apply_response(li, parsed, schema)
    _set(li, "enriched_at",      ts)
    _set(li, "enrichment_model", schema.model)

    entry = _build_sidecar_entry(li, schema,
                                 model=schema.model, ts=ts,
                                 finish_reason=finish_reason,
                                 usage=usage, latency_ms=latency_ms)
    return ("enriched", entry,
            {**base_event, "decision": "enriched"})


def enrich_listings(listings: list[Any],
                    sidecar_path: Path,
                    log_path: Path | None = None,
                    *,
                    schema: EnrichmentSchema = DEFAULT_SCHEMA,
                    max_listings: int | None = None,
                    client: Any | None = None) -> dict:
    """Run single-call DeepSeek enrichment over a list of listings.

    Args:
        listings:     Listing objects or dicts. Mutated in-place when
                      enrichment succeeds OR when rehydrated from the
                      sidecar. Untouched on failure or skip.
        sidecar_path: Path to web/data/llm_enrichment.json (per-listing
                      cache used for idempotency).
        log_path:     Optional path to web/data/llm_enrichment_log.jsonl
                      (append-only audit log). When None, no file
                      logging happens — useful for tests.
        schema:       Defaults to DEFAULT_SCHEMA. Pass a custom one to
                      extend the field set or swap models.
        max_listings: Cap total API calls (cost control, dry runs).
        client:       Optional pre-built client (test injection). When
                      None, builds one from the schema's env var.

    Returns:
      Metrics dict with these keys:
        eligible:           int   # listings that passed the eligibility check
        cache_hits:         int   # rehydrated from sidecar, no API call
        enriched:           int   # NEW enrichments via API call
        skipped:            int   # ineligible (one of 4 fields already set)
        failed:             int   # API/parse/schema failure
        skipped_no_token:   bool  # DEEPSEEK_API_TOKEN missing
        skipped_no_package: bool  # openai package not installed
        global_error_seen:  str|None
        cost_usd:           float
        skip_reasons:       dict[str, int]    # counter per skip reason
        failure_reasons:    dict[str, int]    # counter per failure reason
        latency_ms:         list[int]         # per-call latencies (for p50/p95)
    """
    metrics: dict[str, Any] = {
        "eligible":           0,
        "cache_hits":         0,
        "enriched":           0,
        "skipped":            0,
        "failed":             0,
        "skipped_no_token":   False,
        "skipped_no_package": False,
        "global_error_seen":  None,
        "cost_usd":           0.0,
        "skip_reasons":       {},
        "failure_reasons":    {},
        "latency_ms":         [],
    }

    sidecar = _load_sidecar(sidecar_path)

    # Build the API client only if needed. Eligibility-only runs
    # (every listing already enriched) shouldn't require the env var.
    api_client = client
    api_path_alive = api_client is not None
    api_build_error: str | None = None
    if api_client is None:
        built, err = _build_client(schema)
        if built is not None:
            api_client = built
            api_path_alive = True
        else:
            api_build_error = err
            metrics[f"skipped_{err}"] = True   # skipped_no_token | skipped_no_package
            api_path_alive = False

    n_api_calls = 0

    for li in listings:
        key = _key(li)

        # ── 1. Sidecar hit → idempotent rehydration, no API call ──
        if key in sidecar:
            metrics["cache_hits"] += 1
            _hydrate_from_sidecar(li, sidecar[key], schema)
            if log_path is not None:
                _append_log(log_path, {
                    "ts":       _now_iso(),
                    "key":      key,
                    "decision": "cache_hit",
                    "model":    sidecar[key].get("model"),
                })
            continue

        # ── 2. Eligibility check (the hard rule) ──
        eligible, skip_reason = is_eligible(li, schema)
        if not eligible:
            metrics["skipped"] += 1
            metrics["skip_reasons"][skip_reason] = (
                metrics["skip_reasons"].get(skip_reason, 0) + 1)
            print(f"[llm_enrich] key={key} decision=skipped reason={skip_reason}")
            if log_path is not None:
                _append_log(log_path, {
                    "ts":       _now_iso(),
                    "key":      key,
                    "decision": "skipped",
                    "reason":   skip_reason,
                })
            continue

        metrics["eligible"] += 1

        # ── 3. API path closed (no token / no package / global error) ──
        if not api_path_alive:
            # We don't count this as "failed" — it's the API path being
            # unavailable, which is reported via skipped_no_* flags
            # and the run-level summary. Listing keeps no enrichment;
            # the fallback templates module can fill some fields later.
            if log_path is not None:
                _append_log(log_path, {
                    "ts":       _now_iso(),
                    "key":      key,
                    "decision": "skipped",
                    "reason":   f"api_unavailable:{api_build_error}",
                })
            continue

        # ── 4. API call cap (cost control) ──
        if max_listings is not None and n_api_calls >= max_listings:
            if log_path is not None:
                _append_log(log_path, {
                    "ts":       _now_iso(),
                    "key":      key,
                    "decision": "skipped",
                    "reason":   "max_listings_reached",
                })
            continue

        # ── 5. Make the call ──
        n_api_calls += 1
        try:
            decision, entry, event = _enrich_one(api_client, li, schema)
        except Exception as e:
            decision = "failed"
            entry    = None
            event    = {
                "ts":       _now_iso(),
                "key":      key,
                "decision": "failed",
                "reason":   f"http_error:{type(e).__name__}",
                "model":    schema.model,
            }
            if _is_global_error(e):
                metrics["global_error_seen"] = type(e).__name__
                api_path_alive = False
                print(f"[llm_enrich] global error detected ({type(e).__name__}) "
                      f"— disabling API path for remaining listings")

        # ── 6. Record outcome ──
        if log_path is not None:
            _append_log(log_path, event)

        if decision == "enriched" and entry is not None:
            metrics["enriched"] += 1
            metrics["cost_usd"] += float(event.get("cost_usd") or 0.0)
            if "latency_ms" in event:
                metrics["latency_ms"].append(int(event["latency_ms"]))
            sidecar[key] = entry
            print(f"[llm_enrich] key={key} decision=enriched "
                  f"model={schema.model} "
                  f"tokens_in={event.get('tokens_in')} "
                  f"tokens_out={event.get('tokens_out')} "
                  f"cost=${event.get('cost_usd', 0):.6f} "
                  f"latency_ms={event.get('latency_ms')}")
        else:
            metrics["failed"] += 1
            reason = event.get("reason") or "unknown"
            metrics["failure_reasons"][reason] = (
                metrics["failure_reasons"].get(reason, 0) + 1)
            print(f"[llm_enrich] key={key} decision=failed reason={reason}")

    metrics["cost_usd"] = round(metrics["cost_usd"], 6)
    _save_sidecar(sidecar_path, sidecar)
    return metrics
