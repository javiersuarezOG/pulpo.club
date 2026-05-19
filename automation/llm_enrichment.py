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
import concurrent.futures
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Bounded-concurrency default for the LLM enrichment fan-out. DeepSeek's
# documented chat-completions rate is comfortable above 8 concurrent
# in-flight requests; staying conservative leaves headroom for retries
# and keeps logs ordered enough to debug. Override via PULPO_LLM_CONCURRENCY.
DEFAULT_LLM_CONCURRENCY = 8

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
    """Load the enrichment sidecar; return an empty dict and LOG LOUDLY
    on corruption.

    The sidecar is the cache that prevents the LLM enrichment leg from
    re-spending DeepSeek credit on already-enriched listings. The legacy
    `except Exception: return {}` swallowed corruption silently — a
    half-written sidecar (e.g. from a crash before PR-1's atomic-write
    landed) would cause the next nightly to re-enrich every entry
    (~$1-$3 wasted) with zero operator signal.

    Now: missing file → empty dict (the normal first-run case, quiet).
    Bad JSON / wrong root type → empty dict but with a `[llm_enrich]`
    stderr line so the operator sees it in the nightly log + can
    follow up. Behavior is unchanged from the caller's POV — only the
    silence is broken.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(
            f"[llm_enrich] sidecar corrupt at {path} ({type(e).__name__}: "
            f"{e}); proceeding with empty cache — next run will re-enrich "
            "every listing. Inspect the file and restore from git if needed.",
            file=sys.stderr,
        )
        return {}
    if not isinstance(data, dict):
        print(
            f"[llm_enrich] sidecar at {path} has unexpected root type "
            f"{type(data).__name__} (expected dict); ignoring.",
            file=sys.stderr,
        )
        return {}
    return data


def _save_sidecar(path: Path, sidecar: dict) -> None:
    # Atomic write: the sidecar is the source of truth for "this listing
    # was already enriched"; a crash mid-write corrupts it and the next
    # run re-spends DeepSeek credit on every entry.
    from automation._atomic import atomic_write_json
    atomic_write_json(path, sidecar, indent=2, default=str)


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
        # Schema v3 — url_language must be persisted so rehydration can
        # re-validate it under the current schema (sidecar re-validation
        # in _hydrate_from_sidecar would silently skip the apply otherwise).
        "url_language":                _g(li, "url_language"),
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


# Bounded retry around the HTTP call. Network blips against DeepSeek
# happen ~1% of the time in nightly logs; without retry, that's a
# permanently-skipped listing that the next run re-spends $0.001-$0.003
# of credit on. Retry only on raised exceptions — validation/JSON/length
# failures are already returned as a structured ("failed", …) triple
# from _enrich_one, and retrying them would be deterministic-loss.
# Global errors (auth, quota, billing) skip retry and fail fast: every
# attempt would identically fail.
from automation._config import env_int as _env_int  # noqa: E402

_RETRY_MAX_ATTEMPTS = max(1, _env_int("PULPO_LLM_RETRY_MAX_ATTEMPTS", 3))
_RETRY_BASE_DELAYS = (0.5, 1.5)  # seconds before attempt 2, 3
_RETRY_JITTER_RATIO = 0.4         # ±20% around the base


def _retry_delay(attempt: int, *, rand: Callable[[], float] = random.random) -> float:
    """Delay before retry `attempt` (1-indexed; attempt=1 is the FIRST retry
    after the initial failure). Returns 0 if no retry is scheduled."""
    if attempt < 1 or attempt > len(_RETRY_BASE_DELAYS):
        return 0.0
    base = _RETRY_BASE_DELAYS[attempt - 1]
    return base * (1.0 - _RETRY_JITTER_RATIO / 2 + _RETRY_JITTER_RATIO * rand())


def _call_with_retry(
    fn: Callable[[], Any],
    *,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> Any:
    """Run `fn` with bounded retry on raised exceptions. Re-raises the
    final exception after exhaustion. Caller decides what to do (today:
    convert to a structured failure event)."""
    last_exc: BaseException | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if _is_global_error(e):
                raise
            remaining = _RETRY_MAX_ATTEMPTS - 1 - attempt
            if remaining <= 0:
                raise
            sleep(_retry_delay(attempt + 1, rand=rand))
    # Unreachable — loop body either returns or raises. Keeps type checkers happy.
    assert last_exc is not None
    raise last_exc


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
    user_prompt = render_user_prompt(
        _g(li, "description"),
        location_text = _g(li, "location_text"),
        municipality  = _g(li, "municipality"),
        department    = _g(li, "department"),
        country       = _g(li, "country"),
    )

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
                    client: Any | None = None,
                    max_workers: int | None = None,
                    deadline: float | None = None) -> dict:
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
        max_workers:  Bounded concurrency for the API fan-out. None →
                      reads PULPO_LLM_CONCURRENCY env var (default
                      DEFAULT_LLM_CONCURRENCY=8). Pass 1 to force the
                      sequential code path (handy for tests asserting
                      ordering or for debugging a single-threaded run).
        deadline:     Optional `time.monotonic()` deadline. Once it's
                      reached, no NEW API calls start; in-flight ones
                      are awaited to completion. Listings not yet
                      submitted are simply not enriched this run and
                      will be picked up next nightly. The point is
                      that the pipeline always SHIPS — better to commit
                      partially-enriched data than to time out the
                      whole nightly job and lose all of today's scrape.

    Returns:
      Metrics dict with these keys:
        eligible:           int   # listings that passed the eligibility check
        cache_hits:         int   # rehydrated from sidecar, no API call
        enriched:           int   # NEW enrichments via API call
        skipped:            int   # ineligible (one of 4 fields already set)
        failed:             int   # API/parse/schema failure
        deadline_skipped:   int   # eligible but deadline cut us off
        skipped_no_token:   bool  # DEEPSEEK_API_TOKEN missing
        skipped_no_package: bool  # openai package not installed
        global_error_seen:  str|None
        cost_usd:           float
        skip_reasons:       dict[str, int]    # counter per skip reason
        failure_reasons:    dict[str, int]    # counter per failure reason
        latency_ms:         list[int]         # per-call latencies (for p50/p95)
    """
    if max_workers is None:
        max_workers = max(1, _env_int("PULPO_LLM_CONCURRENCY",
                                      DEFAULT_LLM_CONCURRENCY))

    metrics: dict[str, Any] = {
        "eligible":           0,
        "cache_hits":         0,
        "enriched":           0,
        "skipped":            0,
        "failed":             0,
        "deadline_skipped":   0,
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

    # ── Phase 1 (sequential): classify each listing into one of
    # {cache_hit, ineligible, api_unavailable, max_reached, to_enrich}.
    # Apply non-API decisions immediately. Build a work list for Phase 2.
    work: list[tuple[Any, str]] = []   # (listing, key) for API calls
    for li in listings:
        key = _key(li)

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

        if not api_path_alive:
            if log_path is not None:
                _append_log(log_path, {
                    "ts":       _now_iso(),
                    "key":      key,
                    "decision": "skipped",
                    "reason":   f"api_unavailable:{api_build_error}",
                })
            continue

        if max_listings is not None and len(work) >= max_listings:
            if log_path is not None:
                _append_log(log_path, {
                    "ts":       _now_iso(),
                    "key":      key,
                    "decision": "skipped",
                    "reason":   "max_listings_reached",
                })
            continue

        work.append((li, key))

    # ── Phase 2 (parallel or sequential): fire the API calls.
    # Sequential when max_workers <= 1 (preserves the legacy code path
    # for tests asserting strict call ordering); parallel otherwise.

    def _record(li: Any, key: str, decision: str,
                entry: dict | None, event: dict) -> None:
        """Apply outcome to metrics + sidecar + log. Single-threaded
        callsite — runs from the main loop only."""
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

    def _safe_call(li: Any, key: str) -> tuple[str, dict | None, dict]:
        """_enrich_one wrapped with bounded retry + a final try/except so
        HTTP / network errors become a structured 'failed' event rather
        than crashing the run. Global errors (auth/quota) fail fast — see
        _call_with_retry."""
        try:
            return _call_with_retry(lambda: _enrich_one(api_client, li, schema))
        except Exception as e:
            event = {
                "ts":       _now_iso(),
                "key":      key,
                "decision": "failed",
                "reason":   f"http_error:{type(e).__name__}",
                "model":    schema.model,
            }
            if _is_global_error(e):
                event["_global_error"] = type(e).__name__
            return ("failed", None, event)

    if max_workers <= 1:
        # ── Sequential path: identical ordering to the legacy loop.
        for li, key in work:
            if not api_path_alive:
                break
            if deadline is not None and time.monotonic() >= deadline:
                metrics["deadline_skipped"] += 1
                continue
            decision, entry, event = _safe_call(li, key)
            global_err = event.pop("_global_error", None)
            if global_err:
                metrics["global_error_seen"] = global_err
                api_path_alive = False
                print(f"[llm_enrich] global error detected ({global_err}) "
                      f"— disabling API path for remaining listings")
            _record(li, key, decision, entry, event)
    else:
        # ── Parallel path: bounded ThreadPool fan-out, deadline-aware.
        # We submit lazily so the deadline cuts in BEFORE the next batch
        # of work is dispatched, not just before result collection. That
        # lets the pipeline ship with a fraction enriched rather than
        # paying for hundreds of in-flight calls we'll never use.
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            inflight: dict = {}
            iterator = iter(work)
            stopped = False

            def _submit_next() -> bool:
                """Pull one work item and submit it. Return False if
                the iterator's exhausted, the deadline's been hit, or
                the API path's gone dead."""
                nonlocal stopped
                if stopped or not api_path_alive:
                    return False
                if deadline is not None and time.monotonic() >= deadline:
                    stopped = True
                    return False
                try:
                    li, key = next(iterator)
                except StopIteration:
                    return False
                fut = ex.submit(_safe_call, li, key)
                inflight[fut] = (li, key)
                return True

            # Prime the pool
            for _ in range(max_workers):
                if not _submit_next():
                    break

            while inflight:
                done, _ = concurrent.futures.wait(
                    inflight.keys(),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for fut in done:
                    li, key = inflight.pop(fut)
                    decision, entry, event = fut.result()
                    global_err = event.pop("_global_error", None)
                    if global_err:
                        metrics["global_error_seen"] = global_err
                        api_path_alive = False
                        stopped = True
                        print(f"[llm_enrich] global error detected ({global_err}) "
                              f"— disabling API path for remaining listings")
                    _record(li, key, decision, entry, event)
                    # Top up the pool
                    _submit_next()

            # Anything left in the iterator after we stopped early is
            # counted as deadline-skipped so the metric reflects how
            # many listings we deferred to the next nightly.
            for _ in iterator:
                metrics["deadline_skipped"] += 1

    metrics["cost_usd"] = round(metrics["cost_usd"], 6)
    _save_sidecar(sidecar_path, sidecar)
    return metrics
