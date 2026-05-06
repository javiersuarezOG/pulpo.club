"""
Single-command pipeline runner for automation (cron, GitHub Actions, etc.).

Runs all configured scrapers, normalizes, ranks, and writes:
    samples/ranked.csv         (committed for human review)
    web/data/ranked.json       (consumed by web/index.html dashboard)
    web/data/last_updated.json (timestamp + counts for the dashboard header)

Exit code 0 on success, 1 on failure.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is on sys.path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.agents import SOURCES as REGISTRY  # noqa: E402
import pulpo.scrapers  # noqa: F401,E402 — triggers registration of all sources
from pulpo.agents.html_crawler import HTTPX_OK, SELECTOLAX_OK  # noqa: E402
from pulpo.ranker import rank  # noqa: E402
from automation.prd_feasibility import run_probe as run_feasibility_probe  # type: ignore  # noqa: E402
from automation.llm_enrichment import enrich_listings as _llm_enrich  # type: ignore  # noqa: E402
from automation.ai_enrichment_fallback import apply_fallbacks as _ai_fallback  # type: ignore  # noqa: E402
from pulpo.nlp_extractor import (  # type: ignore  # noqa: E402
    load_dictionaries as _load_nlp_dicts,
    extract as _nlp_extract,
)
from pulpo.derived_rules import apply_all as _apply_derived_rules  # type: ignore  # noqa: E402
from automation.pipeline_steps import (  # noqa: E402
    phase_normalize, phase_validate, phase_write_outputs, phase_print_summary,
)

import hashlib  # noqa: E402
import io      # noqa: E402
import time as _time  # noqa: E402


def _classify_error(exc: BaseException) -> str:
    """Map a scraper exception to a short, alert-friendly category.

    Used by source health telemetry so the watchdog can say "remax has had
    4 ParseError(NoListings) in 6 runs" rather than "remax errored."
    Categories are deliberately coarse — refine over time as alert rules
    mature.
    """
    name = type(exc).__name__
    msg  = (str(exc) or "").lower()
    # httpx, requests, urllib3 timeouts — all use these substrings
    if "timeout" in name.lower() or "timeout" in msg:
        return "NetworkTimeout"
    if "connect" in name.lower() or "connection" in msg or "dns" in msg:
        return "NetworkError"
    if "httpstatus" in name.lower() or "http" in name.lower():
        return "HTTPError"
    if name in ("JSONDecodeError",) or "json" in msg:
        return "JSONDecodeError"
    if name in ("KeyError", "IndexError", "AttributeError", "ValueError"):
        return "ParseError"
    return "Unknown"


def _download_hero_photos(listings, repo: Path) -> dict:
    """Download + resize the first photo_url for each listing with photos.

    Saves to web/photos/{source}_{source_id}.jpg (max 600×400, JPEG Q75).
    Uses a URL-hash sidecar (.hash file) to skip unchanged photos.
    Logs failures to web/data/photo_fetch_log.jsonl (non-fatal).
    Returns summary counts.
    """
    # Pillow is optional — skip the whole step if not installed
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("[photos] Pillow not installed — skipping hero download")
        return {"attempted": 0, "ok": 0, "skipped": 0, "failed": 0, "elapsed_s": 0.0}

    import httpx

    photos_dir = repo / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    log_path = repo / "web" / "data" / "photo_fetch_log.jsonl"

    attempted = ok = skipped = failed = 0
    budget_s = float(os.environ.get("PULPO_PHOTO_BUDGET_S", "600"))
    t0 = _time.monotonic()
    budget_hit = False

    for li in listings:
        if _time.monotonic() - t0 > budget_s:
            budget_hit = True
            break
        if not li.photo_urls:
            continue
        url = li.photo_urls[0]
        fname = f"{li.source}_{li.source_id}.jpg"
        fpath = photos_dir / fname
        hash_path = photos_dir / (fname + ".hash")

        # Skip if URL unchanged
        url_hash = hashlib.sha1(url.encode()).hexdigest()[:12]
        if fpath.exists() and hash_path.exists():
            if hash_path.read_text().strip() == url_hash:
                li.hero_photo_path = f"/photos/{fname}"
                skipped += 1
                continue

        attempted += 1
        try:
            r = httpx.get(url, timeout=5.0, follow_redirects=True)
            r.raise_for_status()
            from PIL import Image
            img = Image.open(io.BytesIO(r.content))
            img.thumbnail((600, 400), Image.LANCZOS)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=True)
            fpath.write_bytes(buf.getvalue())
            hash_path.write_text(url_hash)
            li.hero_photo_path = f"/photos/{fname}"
            ok += 1
        except Exception as e:
            failed += 1
            with log_path.open("a", encoding="utf-8") as lf:
                lf.write(json.dumps({
                    "source_id": li.source_id, "source": li.source,
                    "url": url, "error": str(e),
                    "ts": datetime.now(timezone.utc).isoformat(),
                }) + "\n")

    elapsed = _time.monotonic() - t0
    if budget_hit:
        print(f"[photos] WARNING: budget {budget_s:.0f}s exceeded — "
              f"stopped at {ok}/{attempted} downloads ({skipped} skipped, {failed} failed)")
    elif elapsed > 300:
        print(f"[photos] WARNING: download step took {elapsed:.0f}s (>5 min)")

    # Orphan pruning — photos with no matching listing move to _archive/
    _prune_orphan_photos(photos_dir, {f"{li.source}_{li.source_id}.jpg" for li in listings})

    return {"attempted": attempted, "ok": ok, "skipped": skipped, "failed": failed,
            "elapsed_s": elapsed, "budget_hit": budget_hit}


def _prune_orphan_photos(photos_dir: Path, live_filenames: set) -> None:
    """Move orphaned hero photos to _archive/<date>/, delete those older than 30d."""
    from datetime import timedelta
    archive_base = photos_dir / "_archive"
    today_dir = archive_base / datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for f in photos_dir.glob("*.jpg"):
        if f.name not in live_filenames:
            today_dir.mkdir(parents=True, exist_ok=True)
            f.rename(today_dir / f.name)
            # Remove matching .hash sidecar
            h = photos_dir / (f.name + ".hash")
            if h.exists():
                h.unlink()

    # Delete archives older than 30 days
    if not archive_base.exists():
        return
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
    for d in archive_base.iterdir():
        if d.is_dir():
            try:
                if datetime.strptime(d.name, "%Y-%m-%d").date() < cutoff:
                    import shutil
                    shutil.rmtree(d, ignore_errors=True)
            except ValueError:
                pass


def _print_per_type_score_distribution(ranked: list) -> None:
    """Stdout breakdown of rank_score quartiles per property_type.

    Empty {} for land-only datasets — kept silent so the existing log
    layout is unchanged for the historical state. As soon as a second
    type appears (houses/condos), surface their distribution alongside
    land's so a per-type regression is visible without parsing JSON.
    """
    from collections import defaultdict
    by_type: dict[str, list[float]] = defaultdict(list)
    for li in ranked:
        s = getattr(li, "rank_score", None)
        if s is not None:
            by_type[li.property_type or "land"].append(s)
    if len(by_type) <= 1:
        return
    print("[ranker] score distribution by_type:")
    for pt in sorted(by_type):
        scores = sorted(by_type[pt])
        n = len(scores)
        if n == 0:
            continue
        p10 = scores[max(0, n // 10)]
        p50 = scores[n // 2]
        p90 = scores[min(n - 1, (9 * n) // 10)]
        print(f"  {pt:6s} n={n:>4}  p10={p10:>5.1f}  median={p50:>5.1f}  p90={p90:>5.1f}  top={scores[-1]:>5.1f}")


def main() -> int:
    offline = os.environ.get("PULPO_OFFLINE") == "1"
    limit = int(os.environ.get("PULPO_LIMIT", "30"))
    sources = (os.environ.get("PULPO_SOURCES") or ",".join(REGISTRY.keys())).split(",")

    started = datetime.now(timezone.utc)
    raw: list[dict] = []
    per_source_count: dict[str, int] = {}
    errors: list[str] = []

    # Fixture-fallback guard. BaseScraper auto-flips to fixture mode when
    # httpx or selectolax aren't importable. That's fine when PULPO_OFFLINE=1
    # is explicit, but if we expected a live run and the deps are missing
    # we'd happily serve stale fixture data while reporting offline=false in
    # last_updated.json — invisible to monitoring. Surface it loudly instead.
    fixture_fallback_active = (not offline) and not (HTTPX_OK and SELECTOLAX_OK)
    if fixture_fallback_active:
        missing = []
        if not HTTPX_OK:
            missing.append("httpx")
        if not SELECTOLAX_OK:
            missing.append("selectolax")
        msg = (
            f"deps missing ({', '.join(missing)}); BaseScraper will fall back "
            f"to fixtures despite PULPO_OFFLINE=0. Live data will NOT be fetched. "
            f"Install with `pip install -r requirements.txt` (use httpx[socks] "
            f"behind a SOCKS proxy)."
        )
        print(f"WARNING: {msg}", file=sys.stderr)
        errors.append(msg)

    source_errors: dict[str, str] = {}     # src -> error message
    source_meta: dict[str, dict] = {}      # src -> {max_pages_hit, limit_hit}
    source_durations: dict[str, float] = {}  # src -> seconds in mod.crawl
    source_error_class: dict[str, str] = {}  # src -> short error category

    for src in sources:
        src = src.strip()
        mod = REGISTRY.get(src)
        if not mod:
            err = f"unknown source: {src}"
            errors.append(err)
            source_errors[src] = err
            source_error_class[src] = "UnknownSource"
            continue
        crawl_started = _time.monotonic()
        try:
            if hasattr(mod, "crawl_with_meta"):
                result = mod.crawl_with_meta(limit=limit, offline=offline or None)
                recs = result["records"]
                source_meta[src] = {
                    "max_pages_hit": result["max_pages_hit"],
                    "limit_hit": result["limit_hit"],
                }
            else:
                recs = mod.crawl(limit=limit, offline=offline or None)
                source_meta[src] = {"max_pages_hit": False, "limit_hit": False}
        except Exception as e:
            err = repr(e)
            errors.append(f"{src}: {err}")
            source_errors[src] = err
            source_error_class[src] = _classify_error(e)
            source_durations[src] = round(_time.monotonic() - crawl_started, 2)
            continue
        source_durations[src] = round(_time.monotonic() - crawl_started, 2)
        per_source_count[src] = len(recs)
        for r in recs:
            r.setdefault("source", src)
            raw.append(r)

    # ── Per-listing type-classifier shadow log ───────────────────────
    # Goodlife already runs the multi-signal classifier inline and writes
    # `_type_signals`, `_type_confidence`, `_type_total` onto its records.
    # Other sources still hardcode their type — for those we run the
    # classifier here in SHADOW mode (no behaviour change; we only log
    # whether the prediction agrees with the scraper's hardcode). This is
    # observability without risk: drives the next phase's decision on
    # which scrapers to broaden.
    type_log_path = REPO / "web" / "data" / "type_classifier_log.jsonl"
    type_log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from pulpo.scrapers._type_classifier import classify_property_type as _classify_t
        with type_log_path.open("a", encoding="utf-8") as _tf:
            for r in raw:
                if "_type_signals" in r:
                    pred_type, signals_payload = r["property_type"], r["_type_signals"]
                    confidence, total = r["_type_confidence"], r["_type_total"]
                    mode = "applied"
                else:
                    p, sigs, confidence, total = _classify_t({
                        "url":         r.get("url") or "",
                        "photo_urls":  r.get("photo_urls") or [],
                        "title":       r.get("title") or "",
                        "description": r.get("description") or "",
                    }, fallback_type=r.get("property_type") or "land")
                    pred_type = p
                    signals_payload = [s.to_dict() for s in sigs]
                    mode = "shadow"
                _tf.write(json.dumps({
                    "ts":           started.isoformat(),
                    "source":       r.get("source"),
                    "source_id":    r.get("source_id"),
                    "scraper_type": r.get("property_type"),
                    "predicted":    pred_type,
                    "confidence":   confidence,
                    "total_weight": round(total, 2),
                    "mode":         mode,
                    "signals":      signals_payload,
                }, ensure_ascii=False) + "\n")
                # Strip the piggyback fields before normalize sees the record.
                for k in ("_type_signals", "_type_confidence", "_type_total"):
                    r.pop(k, None)
    except Exception as e:
        # Telemetry must never block a run.
        print(f"[type_classifier] shadow log skipped: {e}")

    # ── Per-source health telemetry ──────────────────────────────────
    # Append one row per source per run to web/data/source_health_history.jsonl
    # so we can detect "scraper X went silent for 3 days" without staring at
    # the dashboard. Same idea as run_history.json but per-source granular,
    # and with error classification for the watchdog to alert on.
    health_path = REPO / "web" / "data" / "source_health_history.jsonl"
    health_path.parent.mkdir(parents=True, exist_ok=True)
    health_ts = started.isoformat()
    with health_path.open("a", encoding="utf-8") as _hf:
        for src in sources:
            src = src.strip()
            count = per_source_count.get(src, 0)
            had_error = src in source_errors
            if had_error:
                status = "red"
            elif count == 0:
                status = "red"
            else:
                status = "green"
            _hf.write(json.dumps({
                "ts":          health_ts,
                "source":      src,
                "status":      status,
                "count":       count,
                "duration_s":  source_durations.get(src, 0.0),
                "error_class": source_error_class.get(src),
                "error_msg":   (source_errors.get(src) or "")[:300],
                "max_pages_hit": source_meta.get(src, {}).get("max_pages_hit", False),
                "limit_hit":     source_meta.get(src, {}).get("limit_hit", False),
            }, ensure_ascii=False) + "\n")

    # Normalize
    listings, dropped = phase_normalize(raw)

    # PRD §FR-2 — shared NLP keyword extraction. Reads nlp_keywords/*.json
    # at startup, runs all dictionaries against title+description+location_text
    # for each listing, and fills False→True on the boolean fields. Existing
    # per-scraper True values are preserved.
    nlp_dicts = _load_nlp_dicts()
    nlp_changes_per_field: dict[str, int] = {}
    for li in listings:
        changes = _nlp_extract(li, nlp_dicts)
        for f in changes:
            nlp_changes_per_field[f] = nlp_changes_per_field.get(f, 0) + 1
    if nlp_dicts:
        summary = " ".join(
            f"{f}={c}"
            for f, c in sorted(nlp_changes_per_field.items(), key=lambda x: -x[1])
        ) or "no_changes"
        print(f"[nlp] dicts={len(nlp_dicts)} listings={len(listings)} "
              f"flips_false_to_true: {summary}")

    # Validation layer — drop bad listings, flag suspicious ones, write logs.
    web_data_dir = REPO / "web" / "data"
    listings, val_counts, val_dropped = phase_validate(listings, web_data_dir)
    dropped += val_dropped
    val_total = val_counts['pass'] + val_counts['flag'] + val_counts['drop']
    print(
        f"[validation] PASS={val_counts['pass']} FLAG={val_counts['flag']} "
        f"DROP={val_counts['drop']} (total in={val_total})"
    )
    # Per-type breakdown — empty for land-only datasets, useful as soon
    # as houses/condos appear so red flags surface per type instead of
    # being averaged with land's much larger denominator.
    if len(val_counts.get('by_type', {})) > 1:
        print("[validation] by_type:")
        for pt in sorted(val_counts['by_type']):
            b = val_counts['by_type'][pt]
            tot = b['pass'] + b['flag'] + b['drop']
            print(f"  {pt:6s} pass={b['pass']:>4} flag={b['flag']:>3} drop={b['drop']:>3} (total={tot})")

    # First-seen tracking. Persistent sidecar keyed by "<source>|<source_id>"
    # so that "Newest first" sort and the NEW badge survive re-scrapes —
    # `scraped_at` rewrites every run and can't tell a 1-day-old listing
    # apart from a 6-month-old one we just re-fetched. Idempotent: existing
    # keys keep their original timestamp; new keys get the current run's
    # start time. Same pattern as run_history.json below.
    listings_history_path = web_data_dir / "listings_history.json"
    try:
        first_seen = (
            json.loads(listings_history_path.read_text())
            if listings_history_path.exists() else {}
        )
        if not isinstance(first_seen, dict):
            first_seen = {}
    except Exception:
        first_seen = {}
    started_iso = started.isoformat()
    for li in listings:
        key = f"{li.source}|{li.source_id}"
        if key not in first_seen:
            first_seen[key] = started_iso
        li.first_seen_at = first_seen[key]
    with listings_history_path.open("w", encoding="utf-8") as f:
        json.dump(first_seen, f, ensure_ascii=False)

    # Price history (PRD §FR-3). Sets is_repriced before derived rules and
    # AI run, so downstream fields reflect cross-run price comparison.
    PRICE_HISTORY_MAX_ENTRIES = 365   # ~1 year of daily nightlies
    prices_history_path = web_data_dir / "prices_history.json"
    try:
        prices_history: dict = (
            json.loads(prices_history_path.read_text())
            if prices_history_path.exists() else {}
        )
        if not isinstance(prices_history, dict):
            prices_history = {}
    except Exception:
        prices_history = {}

    repriced_count = 0
    for li in listings:
        if li.price_usd is None:
            continue
        key = f"{li.source}|{li.source_id}"
        history = prices_history.get(key) or []
        last_price = history[-1].get("price_usd") if history else None
        if last_price is None or float(last_price) != float(li.price_usd):
            history.append({"ts": started_iso, "price_usd": float(li.price_usd)})
            history = history[-PRICE_HISTORY_MAX_ENTRIES:]
            prices_history[key] = history
        prior_prices = [h["price_usd"] for h in history[:-1]] if history else []
        if prior_prices:
            if float(li.price_usd) < min(prior_prices):
                li.is_repriced = True
                repriced_count += 1
            else:
                li.is_repriced = False

    with prices_history_path.open("w", encoding="utf-8") as f:
        json.dump(prices_history, f, ensure_ascii=False)
    print(f"[price_history] tracked={len(prices_history)} listings  "
          f"repriced_this_run={repriced_count}")

    # PRD §FR-3.7 — days_listed = CURRENT_DATE - first_seen_date, populated
    # here so the derived-rules engine has it as input.
    now_utc = datetime.now(timezone.utc)
    for li in listings:
        if li.days_listed is None and li.first_seen_at:
            try:
                fs = datetime.fromisoformat(li.first_seen_at.replace("Z", "+00:00"))
                li.days_listed = max(0, (now_utc - fs).days)
            except (ValueError, AttributeError):
                pass

    # PRD §FR-7 — derived field rule engine. Pure functions over upstream
    # fields (NLP-extracted booleans + is_repriced + days_listed). Sets
    # readiness_score / investment_signal / source_label / data_quality_score.
    # MUST run before AI enrichment so the AI fallback module sees the
    # derived signals (Build-Ready, Hot, etc.) when filling source_label.
    deriv_signal_counts: dict[str, int] = {}
    deriv_label_counts:  dict[str, int] = {}
    for li in listings:
        result = _apply_derived_rules(li)
        sig = result.get("investment_signal")
        if sig:
            deriv_signal_counts[sig] = deriv_signal_counts.get(sig, 0) + 1
        for lbl in (result.get("source_label") or []):
            deriv_label_counts[lbl] = deriv_label_counts.get(lbl, 0) + 1
    print(f"[derived] signals={dict(deriv_signal_counts)} "
          f"labels={dict(deriv_label_counts)}")

    # PRD §FR-7.5 — zone median price batch. Computes median price_per_m2
    # per (zone, property_type) bucket from current listings, then sets
    # price_vs_zone_median + price_vs_zone_pct on each scored listing.
    # Pure function of the in-memory catalog — no sidecar; recomputed
    # every run. Listings in buckets below MIN_LISTINGS_PER_ZONE leave
    # both fields as None.
    from automation.zone_medians import compute_and_apply as _zone_medians  # type: ignore
    zm_metrics = _zone_medians(listings)
    print(f"[zone_medians] buckets={zm_metrics['buckets_computed']} "
          f"scored={zm_metrics['listings_scored']} "
          f"skipped_no_zone={zm_metrics['listings_skipped_no_zone']} "
          f"skipped_inactive={zm_metrics['listings_skipped_inactive']} "
          f"skipped_no_bucket_median={zm_metrics['listings_skipped_no_bucket_median']}")

    # PRD WS2 — single-call DeepSeek enrichment. ONE LLM call per eligible
    # listing returns title + description + usps + latlong together (replacing
    # the previous 3-call OpenAI flow + Mapbox geocoding pass). Idempotent
    # via the per-listing sidecar at web/data/llm_enrichment.json: a listing
    # already in the sidecar is rehydrated without an API call. The
    # eligibility rule — skip if any of {title_canonical,
    # short_description_canonical, reasons_to_buy, lat-or-lng} is set —
    # means listings already enriched by prior runs (or grandfathered with
    # Mapbox lat/lng from the legacy geocoding pass) are not re-processed.
    llm_metrics = _llm_enrich(
        listings,
        sidecar_path = web_data_dir / "llm_enrichment.json",
        log_path     = web_data_dir / "llm_enrichment_log.jsonl",
    )
    if llm_metrics.get("skipped_no_token"):
        print("[llm_enrich] DEEPSEEK_API_TOKEN missing — fallback templates only")
    elif llm_metrics.get("skipped_no_package"):
        print("[llm_enrich] openai package not installed — fallback templates only")
    else:
        ge = llm_metrics.get("global_error_seen")
        ge_note = f" GLOBAL_ERROR={ge}" if ge else ""
        lat = llm_metrics.get("latency_ms") or []
        lat_note = ""
        if lat:
            srt = sorted(lat)
            p50 = srt[len(srt) // 2]
            p95 = srt[max(0, int(len(srt) * 0.95) - 1)]
            lat_note = f" latency_p50={p50}ms latency_p95={p95}ms"
        print(f"[llm_enrich] eligible={llm_metrics['eligible']} "
              f"cache_hits={llm_metrics['cache_hits']} "
              f"enriched={llm_metrics['enriched']} "
              f"skipped={llm_metrics['skipped']} "
              f"failed={llm_metrics['failed']} "
              f"cost=${llm_metrics['cost_usd']:.4f}{lat_note}{ge_note}")
        if llm_metrics.get("skip_reasons"):
            print(f"[llm_enrich] skip_reasons={llm_metrics['skip_reasons']}")
        if llm_metrics.get("failure_reasons"):
            print(f"[llm_enrich] failure_reasons={llm_metrics['failure_reasons']}")

    # Deterministic fallback templates (PRD §8.1 + §8.3) for listings the
    # LLM skipped or couldn't enrich. Fills title_canonical and
    # reasons_to_buy from the rule tables; short_description_canonical
    # stays None — that one genuinely needs natural-language generation.
    fb_count = sum(1 for li in listings if _ai_fallback(li))
    print(f"[llm_enrich] fallback_templates_applied={fb_count}")

    # Hero photo download — fetch + resize the first photo URL for each listing.
    # Skips listings with no photo_urls; skips re-download when URL unchanged.
    # Non-fatal: any error is logged and the listing keeps hero_photo_path=None.
    ranked_pre = rank(listings)  # rank before download so we can prioritise by rank
    # Per-type score distribution — surfaces "houses scoring 50.4 median,
    # land scoring 67.2 median" so a regression in either type's metric
    # is visible without staring at ranked.json. Empty for land-only
    # datasets; populated as soon as houses/condos are present.
    _print_per_type_score_distribution(ranked_pre)
    photo_results = _download_hero_photos(ranked_pre, REPO)
    print(f"[photos] attempted={photo_results['attempted']} "
          f"ok={photo_results['ok']} skipped={photo_results['skipped']} "
          f"failed={photo_results['failed']} "
          f"elapsed={photo_results['elapsed_s']:.1f}s")
    ranked = ranked_pre

    # Write all outputs: CSV, ranked.json, ranked-public.json, last_updated.json,
    # run_history.json. Returns the meta dict for downstream use.
    finished = datetime.now(timezone.utc)
    phase_write_outputs(
        ranked=ranked,
        web_data_dir=web_data_dir,
        samples_path=REPO / "samples" / "ranked.csv",
        sources=sources,
        per_source_count=per_source_count,
        source_errors=source_errors,
        source_meta=source_meta,
        errors=errors,
        started=started,
        finished=finished,
        offline=offline,
        fixture_fallback_active=fixture_fallback_active,
        dropped=dropped,
        validation_by_type=val_counts.get('by_type'),
    )

    # PRD WS2 feasibility probe — refreshes web/data/prd_feasibility.{md,json}
    # so weekly drift in field populations is visible without a manual re-run.
    # Non-blocking: any failure is logged and the nightly run still succeeds.
    try:
        run_feasibility_probe(
            input_path = web_data_dir / "ranked.json",
            out_md     = web_data_dir / "prd_feasibility.md",
            out_json   = web_data_dir / "prd_feasibility.json",
        )
        print("[run] prd_feasibility probe ok")
    except Exception as _e:
        print(f"[run] prd_feasibility probe failed (non-fatal): {_e!r}")

    phase_print_summary(
        finished=finished, ranked_count=len(ranked),
        sources=sources, errors=errors, offline=offline,
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())
