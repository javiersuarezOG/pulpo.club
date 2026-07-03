"""
Retroactively re-generate cached LLM descriptions with prompt v4 — plan 011.

The enrichment sidecar (web/data/llm_enrichment.json) is a permanent
cache: `is_eligible` skips any listing whose short_description_canonical
is already set, so prompt v4 (plan 008) + extracted_facts (plan 009)
only ever reach NEW listings. This one-shot script re-calls DeepSeek for
every cached entry written under an older prompt
(`entry.get("prompt_version", 0) < PROMPT_VERSION`), replaces
title/description/usps/extracted-facts in BOTH the sidecar and
ranked.json, and prints a before/after quality report.

The mirror image of scripts/retrofit_geocoding.py: that one touched ONLY
the geocoding fields; this one touches everything EXCEPT them. The new
LLM response's `latlong` and `url_language` are validated (whole-response
fail-closed) and then DISCARDED — lat/lng/geocoding_*/url_language keep
their cached, already-approved values byte-for-byte.

Idempotent: rewritten entries are stamped prompt_version=4 and skipped on
re-run. The next prompt bump (v5) reuses this script unchanged.

Usage:
    python3 scripts/retrofit_descriptions.py --dry-run    # selection + cost estimate, zero writes, no token needed
    python3 scripts/retrofit_descriptions.py --limit 20   # staged run (plan 011 step 3)
    python3 scripts/retrofit_descriptions.py              # full backfill (step 4)
    python3 scripts/retrofit_descriptions.py --yes        # skip the interactive confirm
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Load .env if not already exported (same pattern as retrofit_geocoding.py)
if not os.environ.get("DEEPSEEK_API_TOKEN"):
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from automation._atomic import atomic_write_json  # type: ignore  # noqa: E402
from automation.description_lint import lint_description  # type: ignore  # noqa: E402
from automation.llm_cost_guard import check_budget, record_cost  # type: ignore  # noqa: E402
# Private imports are repo-internal tooling precedent (retrofit_geocoding
# imports the prompts module the same way).
from automation.llm_enrichment import DEFAULT_LLM_CONCURRENCY, _cost_usd  # type: ignore  # noqa: E402
from automation.llm_enrichment_prompts import (  # type: ignore  # noqa: E402
    PROMPT_VERSION, SYSTEM_PROMPT, render_user_prompt,
)
from automation.llm_enrichment_schema import (  # type: ignore  # noqa: E402
    DEFAULT_SCHEMA, _apply_extracted_facts, _FACT_KEYS,
    _normalize_localized,
)


RANKED  = REPO / "web" / "data" / "ranked.json"
SIDECAR = REPO / "web" / "data" / "llm_enrichment.json"
COST_HISTORY = REPO / "web" / "data" / "llm_cost_history.jsonl"
REPORT  = REPO / "samples" / "retrofit_descriptions_report.md"

# Estimate per plan 011 (observed sidecar mean cost_usd ≈ $0.00115).
EST_COST_PER_CALL_USD = 0.0012


def _sidecar_key(li: dict) -> str:
    """Match automation/llm_enrichment.py::_key()."""
    return f"{li.get('source')}|{li.get('source_id')}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── pure functions (unit-tested in tests/test_retrofit_descriptions.py) ─

def select_targets(
    sidecar: dict,
    ranked_by_key: dict,
    prompt_version: int = PROMPT_VERSION,
) -> tuple[list[str], dict]:
    """Pick the sidecar keys that need the v4 rewrite.

    A key is a target iff its entry's prompt_version is missing or below
    `prompt_version` (pre-008 entries have NO prompt_version key — that
    absence is the selector) AND the key still exists in ranked.json AND
    the ranked listing carries non-empty source `description` text.

    Returns (targets, counters). Targets preserve sidecar order so
    --limit N is a stable prefix. counters = {already_current, orphaned,
    no_source_text, malformed}.
    """
    targets: list[str] = []
    counters = {"already_current": 0, "orphaned": 0,
                "no_source_text": 0, "malformed": 0}
    for key, entry in sidecar.items():
        if not isinstance(entry, dict):
            counters["malformed"] += 1
            continue
        if entry.get("prompt_version", 0) >= prompt_version:
            counters["already_current"] += 1
            continue
        listing = ranked_by_key.get(key)
        if listing is None:
            # Listing left the catalog (sold/pruned) — nothing to render
            # the prompt from and nothing user-visible to fix.
            counters["orphaned"] += 1
            continue
        desc = listing.get("description")
        if not isinstance(desc, str) or not desc.strip():
            counters["no_source_text"] += 1
            continue
        targets.append(key)
    return targets, counters


def apply_result(entry: dict, listing: dict, parsed: dict,
                 usage: dict | None = None) -> None:
    """Write a validated v4 response onto the sidecar entry and mirror it
    onto the ranked listing. Mutates both dicts in place.

    Pre-condition: the consumed-fields validation in _rewrite_one passed.

    Replaces: title_canonical, short_description_canonical,
    reasons_to_buy, extracted_facts (sanitized; only-fill-nulls merge on
    the listing — scraper value wins). Stamps prompt_version /
    schema_version and, when `usage` is given, refreshes
    ts/model/tokens_in/tokens_out/cost_usd/finish_reason/latency_ms.

    NEVER touches lat/lng/geocoding_*/url_language — the response's
    `latlong` and `url_language` are discarded (geocoding was retrofitted
    by a dedicated approved workstream; see scripts/retrofit_geocoding.py).
    """
    title = _normalize_localized(parsed["title"])
    desc  = _normalize_localized(parsed["description"])
    usps  = [_normalize_localized(x) for x in parsed["usps"]]

    entry["title_canonical"]             = dict(title)
    entry["short_description_canonical"] = dict(desc)
    entry["reasons_to_buy"]              = [dict(x) for x in usps]

    listing["title_canonical"]             = dict(title)
    listing["short_description_canonical"] = dict(desc)
    listing["reasons_to_buy"]              = [dict(x) for x in usps]

    # extracted_facts: sanitize via the schema's bounds logic and merge
    # only-fill-nulls onto the listing (scraper value always wins). The
    # applicator also stores the sanitized raw dict on the listing; the
    # sidecar mirrors it for rebuild + audit, same as the nightly does.
    _apply_extracted_facts(listing, parsed.get("extracted_facts") or {})
    entry["extracted_facts"] = dict(listing.get("extracted_facts") or {})

    entry["prompt_version"] = PROMPT_VERSION
    entry["schema_version"] = DEFAULT_SCHEMA.schema_version
    if usage:
        for k in ("ts", "model", "tokens_in", "tokens_out",
                  "cost_usd", "finish_reason", "latency_ms"):
            if k in usage:
                entry[k] = usage[k]


# ── quality stats ───────────────────────────────────────────────────────

def _en_desc(entry: dict) -> str:
    v = entry.get("short_description_canonical")
    if isinstance(v, dict):
        return v.get("en") or ""
    return v if isinstance(v, str) else ""


def corpus_stats(entries: list[dict]) -> dict:
    """Word-count / lint / 'Discover'-opener stats over sidecar entries."""
    texts = [_en_desc(e) for e in entries]
    words = sorted(len(t.split()) for t in texts if t.strip())
    n = len(words)
    return {
        "n": len(entries),
        "with_text": n,
        "mean_words": round(sum(words) / n, 1) if n else 0.0,
        "p90_words": words[int(0.9 * (n - 1))] if n else 0,
        "lint_hit_pct": round(
            100.0 * sum(1 for t in texts if lint_description(t)) / max(len(entries), 1), 1),
        "discover_openers": sum(
            1 for t in texts if t.strip().lower().startswith("discover")),
    }


def _format_report(before: dict, after: dict | None, counts: dict,
                   counters: dict, facts_filled: dict, total_cost: float,
                   n_targets: int) -> str:
    lines = [
        "# Retrofit descriptions — prompt v4 backfill report (plan 011)",
        "",
        f"Generated: {_now_iso()}",
        "",
        f"- targets: {n_targets}",
        f"- rewritten: {counts.get('rewritten', 0)}",
        f"- failed (kept old entry): {counts.get('failed', 0)}",
        f"- orphaned (left catalog): {counters['orphaned']}",
        f"- no_source_text: {counters['no_source_text']}",
        f"- already_current (prompt_version >= {PROMPT_VERSION}): {counters['already_current']}",
        f"- actual cost: ${total_cost:.4f}",
        "",
        "| metric | before | after |",
        "|---|---|---|",
    ]
    after = after or {}
    for label, key in (
        ("mean EN words", "mean_words"),
        ("p90 EN words", "p90_words"),
        ("% entries with ≥1 lint hit", "lint_hit_pct"),
        ("EN descriptions starting 'Discover'", "discover_openers"),
    ):
        lines.append(f"| {label} | {before[key]} | {after.get(key, '—')} |")
    lines += ["", "## Extracted-facts fills (listing field was null, now set)", ""]
    for k in sorted(_FACT_KEYS):
        lines.append(f"- {k}: {facts_filled.get(k, 0)}")
    return "\n".join(lines) + "\n"


# ── DeepSeek call ───────────────────────────────────────────────────────

def _render_prompt(listing: dict) -> str:
    return render_user_prompt(
        listing.get("description"),
        location_text=listing.get("location_text"),
        municipality=listing.get("municipality"),
        department=listing.get("department"),
        country=listing.get("country"),
        property_type=listing.get("property_type"),
        area_m2=listing.get("area_m2"),
        built_area_m2=listing.get("built_area_m2"),
        bedrooms=listing.get("bedrooms"),
        bathrooms=listing.get("bathrooms"),
        year_built=listing.get("year_built"),
        parking_spaces=listing.get("parking_spaces"),
        floor=listing.get("floor"),
        price_usd=listing.get("price_usd"),
    )


def _call_deepseek(client, user_prompt: str):
    """One API call. Returns (parsed, usage_dict) or (None, reason)."""
    t0 = time.monotonic()
    try:
        resp = client.chat.completions.create(
            model=DEFAULT_SCHEMA.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=DEFAULT_SCHEMA.temperature,
            max_tokens=DEFAULT_SCHEMA.max_tokens,
        )
        parsed = json.loads((resp.choices[0].message.content or "").strip())
    except Exception as e:
        return None, f"api_error:{type(e).__name__}"
    latency_ms = round((time.monotonic() - t0) * 1000)
    u = getattr(resp, "usage", None)
    tokens_in  = getattr(u, "prompt_tokens",     0) or 0
    tokens_out = getattr(u, "completion_tokens", 0) or 0
    usage = {
        "ts":            _now_iso(),
        "model":         DEFAULT_SCHEMA.model,
        "tokens_in":     tokens_in,
        "tokens_out":    tokens_out,
        "cost_usd":      _cost_usd(tokens_in, tokens_out),
        "finish_reason": getattr(resp.choices[0], "finish_reason", None),
        "latency_ms":    latency_ms,
    }
    return parsed, usage


def _rewrite_one(client, key: str, listing: dict) -> dict:
    """Call + validate, one retry on invalid. No shared-state mutation —
    safe to run on a worker thread; apply happens on the main thread."""
    user_prompt = _render_prompt(listing)
    last_reason = "unknown"
    spent = 0.0
    for _attempt in (1, 2):
        parsed, usage_or_reason = _call_deepseek(client, user_prompt)
        if parsed is None:
            last_reason = usage_or_reason
            continue
        usage = usage_or_reason
        spent += usage["cost_usd"]
        # We discard the response's latlong (cached geocoding is preserved,
        # even when the cache has none), yet validate_response checks the
        # WHOLE schema — so a malformed latlong rejected entries whose copy
        # was perfectly good (37/1828 in the 2026-06-13 backfill, all
        # `invalid:latlong`; 26 of those have NO cached lat/lng either, so
        # substitution can't fix them). Validate exactly what we consume:
        # every schema field EXCEPT latlong.
        ok, reason = True, None
        if not isinstance(parsed, dict):
            ok, reason = False, "not_a_dict"
        else:
            for _f in DEFAULT_SCHEMA.fields:
                if _f.json_key == "latlong":
                    continue
                if _f.json_key not in parsed:
                    ok, reason = False, f"missing:{_f.json_key}"
                    break
                if not _f.validate(parsed[_f.json_key]):
                    ok, reason = False, f"invalid:{_f.json_key}"
                    break
        if ok:
            usage["cost_usd"] = round(spent, 8)  # charge retries to the entry
            return {"key": key, "ok": True, "parsed": parsed, "usage": usage}
        last_reason = f"invalid:{reason}"
    return {"key": key, "ok": False, "reason": last_reason,
            "cost_usd": round(spent, 8)}


# ── main ────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--dry-run", action="store_true",
                   help="selection + cost estimate only; zero writes, no API calls")
    p.add_argument("--limit", type=int, default=None,
                   help="only rewrite the first N targets")
    p.add_argument("--yes", action="store_true",
                   help="skip the interactive cost confirmation")
    p.add_argument("--concurrency", type=int, default=DEFAULT_LLM_CONCURRENCY,
                   help=f"parallel API calls (default {DEFAULT_LLM_CONCURRENCY}, max 8)")
    args = p.parse_args()

    listings: list[dict] = json.loads(RANKED.read_text(encoding="utf-8"))
    sidecar: dict = json.loads(SIDECAR.read_text(encoding="utf-8"))
    ranked_by_key = {_sidecar_key(li): li for li in listings}

    targets, counters = select_targets(sidecar, ranked_by_key)
    if args.limit:
        targets = targets[: args.limit]

    est_cost = len(targets) * EST_COST_PER_CALL_USD
    before = corpus_stats([sidecar[k] for k in targets])

    print(f"targets={len(targets)} est_cost=${est_cost:.2f} "
          f"({len(targets)} × ${EST_COST_PER_CALL_USD})", flush=True)
    print(f"skipped: already_current={counters['already_current']} "
          f"orphaned={counters['orphaned']} "
          f"no_source_text={counters['no_source_text']} "
          f"malformed={counters['malformed']}", flush=True)
    print(f"before: mean_words={before['mean_words']} "
          f"p90_words={before['p90_words']} "
          f"lint_hit_pct={before['lint_hit_pct']}% "
          f"discover_openers={before['discover_openers']}", flush=True)

    if args.dry_run:
        print("[dry-run] no files written, no API calls made.", flush=True)
        return

    # Budget visibility (informational — the operator confirm below is the
    # gate; record_cost() at the end keeps the nightly's budget view honest).
    snap = check_budget(history_path=COST_HISTORY)
    print(f"budget: verdict={snap.verdict} mtd=${snap.month_to_date_usd:.2f}"
          f"/{snap.monthly_cap_usd:.0f} today=${snap.today_usd:.2f}"
          f"/{snap.daily_cap_usd:.0f}", flush=True)
    if snap.today_usd + est_cost > snap.daily_cap_usd:
        print(f"  NOTE: estimated spend exceeds the daily cap "
              f"(LLM_DAILY_USD_CAP={snap.daily_cap_usd}); this one-shot "
              "backfill is operator-confirmed, proceeding past the cap is "
              "deliberate.", flush=True)

    if not args.yes:
        answer = input(f"Rewrite {len(targets)} cached descriptions "
                       f"(~${est_cost:.2f})? Type 'yes' to proceed: ").strip()
        if answer.lower() != "yes":
            print("aborted.", flush=True)
            return

    if not os.environ.get("DEEPSEEK_API_TOKEN"):
        print("ERROR: DEEPSEEK_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("pip install openai", file=sys.stderr)
        sys.exit(1)
    client = OpenAI(
        base_url=DEFAULT_SCHEMA.base_url,
        api_key=os.environ[DEFAULT_SCHEMA.api_key_env],
    )

    counts = {"rewritten": 0, "failed": 0}
    facts_filled: dict[str, int] = {}
    failure_reasons: dict[str, int] = {}
    total_cost = 0.0
    workers = max(1, min(args.concurrency, 8))
    t0 = time.monotonic()
    done = 0

    print(f"\nRewriting {len(targets)} entries with {workers} workers...",
          flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_rewrite_one, client, k, ranked_by_key[k])
                   for k in targets]
        for fut in as_completed(futures):
            res = fut.result()
            done += 1
            key = res["key"]
            if res["ok"]:
                listing = ranked_by_key[key]
                pre_facts = {k: listing.get(k) for k in _FACT_KEYS}
                apply_result(sidecar[key], listing, res["parsed"], res["usage"])
                for k in _FACT_KEYS:
                    if pre_facts[k] is None and listing.get(k) is not None:
                        facts_filled[k] = facts_filled.get(k, 0) + 1
                total_cost += res["usage"]["cost_usd"]
                counts["rewritten"] += 1
            else:
                total_cost += res.get("cost_usd", 0.0)
                counts["failed"] += 1
                reason = res.get("reason", "unknown")
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            if done % 50 == 0 or done == len(targets):
                elapsed = time.monotonic() - t0
                rate = done / max(elapsed, 0.1)
                eta = (len(targets) - done) / max(rate, 0.01)
                print(f"  [{done:4d}/{len(targets)}] "
                      f"rewritten={counts['rewritten']} "
                      f"failed={counts['failed']} "
                      f"cost=${total_cost:.4f} "
                      f"({elapsed:.0f}s, ~{eta:.0f}s left)", flush=True)

    after = corpus_stats([sidecar[k] for k in targets])

    print(flush=True)
    print("=" * 80, flush=True)
    print(f"Rewritten: {counts['rewritten']}", flush=True)
    print(f"Failed:    {counts['failed']} "
          f"(old entries kept) {failure_reasons or ''}", flush=True)
    print(f"Cost:      ${total_cost:.4f}", flush=True)
    print(f"after:  mean_words={after['mean_words']} "
          f"p90_words={after['p90_words']} "
          f"lint_hit_pct={after['lint_hit_pct']}% "
          f"discover_openers={after['discover_openers']}", flush=True)
    print("=" * 80, flush=True)

    # Persist (atomic; matches the nightly's writer and current file bytes:
    # indent=2, no trailing newline).
    atomic_write_json(RANKED, listings, indent=2, default=str)
    atomic_write_json(SIDECAR, sidecar, indent=2, default=str)
    print(f"wrote {RANKED.relative_to(REPO)} ({len(listings)} records)", flush=True)
    print(f"wrote {SIDECAR.relative_to(REPO)} ({len(sidecar)} sidecar entries)",
          flush=True)

    # Record the realized spend so the nightly's budget view stays truthful.
    if total_cost > 0:
        record_cost(cost_usd=total_cost, purpose="retrofit_descriptions_v4",
                    model=DEFAULT_SCHEMA.model, history_path=COST_HISTORY)
        print(f"recorded ${total_cost:.4f} to {COST_HISTORY.relative_to(REPO)}",
              flush=True)

    report = _format_report(before, after, counts, counters, facts_filled,
                            total_cost, len(targets))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(f"report written to {REPORT.relative_to(REPO)}", flush=True)
    print(report, flush=True)


if __name__ == "__main__":
    main()
