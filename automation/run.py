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
from pulpo.normalize import normalize  # noqa: E402
from pulpo.ranker import rank  # noqa: E402
from automation.validation import validate  # noqa: E402
from automation.field_audit import build_completeness_block  # noqa: E402
from automation.prd_feasibility import run_probe as run_feasibility_probe  # type: ignore  # noqa: E402
from pulpo.nlp_extractor import (  # type: ignore  # noqa: E402
    load_dictionaries as _load_nlp_dicts,
    extract as _nlp_extract,
)
from pulpo.cli import _row, CSV_FIELDS  # noqa: E402

import csv  # noqa: E402
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
    t0 = _time.monotonic()

    for li in listings:
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
    if elapsed > 300:
        print(f"[photos] WARNING: download step took {elapsed:.0f}s (>5 min)")

    # Orphan pruning — photos with no matching listing move to _archive/
    _prune_orphan_photos(photos_dir, {f"{li.source}_{li.source_id}.jpg" for li in listings})

    return {"attempted": attempted, "ok": ok, "skipped": skipped, "failed": failed,
            "elapsed_s": elapsed}


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
    listings = []
    dropped = 0
    for r in raw:
        li = normalize(r, source=r.get("source") or "unknown")
        if li:
            listings.append(li)
        else:
            dropped += 1

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

    # Validation layer — runs before the ranker.
    # DROP'd listings are excluded entirely. FLAG'd listings pass to the ranker
    # but get validation_status/validation_warnings fields set.
    # Writes web/data/validation_log.jsonl for auditing.
    val_pass = val_flag = val_drop = 0
    val_log_entries: list[dict] = []
    validated_listings: list = []
    for li in listings:
        li_dict = li.to_dict()
        result  = validate(li_dict)
        entry   = {
            "source_id":   li.source_id,
            "source":      li.source,
            "url":         li.url,
            "title":       li.title,
            "disposition": result.disposition,
            "reasons":     result.reasons,
        }
        val_log_entries.append(entry)
        if result.disposition == "DROP":
            val_drop += 1
            dropped  += 1
        elif result.disposition == "FLAG":
            val_flag += 1
            li.validation_status   = "flagged"
            li.validation_warnings = result.reasons
            validated_listings.append(li)
        else:
            val_pass += 1
            validated_listings.append(li)
    listings = validated_listings

    print(
        f"[validation] PASS={val_pass} FLAG={val_flag} DROP={val_drop} "
        f"(total in={val_pass+val_flag+val_drop})"
    )

    # Write validation log for auditability
    web_data_dir = REPO / "web" / "data"
    web_data_dir.mkdir(parents=True, exist_ok=True)
    val_log_path = web_data_dir / "validation_log.jsonl"
    with val_log_path.open("w", encoding="utf-8") as f:
        for entry in val_log_entries:
            import json as _json
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")

    # Legacy price-outlier log (kept for backward compat with the commit step)
    log_path = web_data_dir / "parser_errors.log"
    with log_path.open("w", encoding="utf-8") as f:
        f.write(f"# parser_errors.log — generated {datetime.now(timezone.utc).isoformat()}\n")
        f.write("# Replaced by validation_log.jsonl. Kept empty for git history continuity.\n")

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

    # Hero photo download — fetch + resize the first photo URL for each listing.
    # Skips listings with no photo_urls; skips re-download when URL unchanged.
    # Non-fatal: any error is logged and the listing keeps hero_photo_path=None.
    ranked_pre = rank(listings)  # rank before download so we can prioritise by rank
    photo_results = _download_hero_photos(ranked_pre, REPO)
    print(f"[photos] attempted={photo_results['attempted']} "
          f"ok={photo_results['ok']} skipped={photo_results['skipped']} "
          f"failed={photo_results['failed']} "
          f"elapsed={photo_results['elapsed_s']:.1f}s")
    ranked = ranked_pre

    # Write CSV
    samples_path = REPO / "samples" / "ranked.csv"
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    with samples_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for li in ranked:
            w.writerow(_row(li))

    # Write web JSON. Two files:
    #   ranked.json        — full records, served only by /api/members behind auth
    #   ranked-public.json — broker/url/exact-price fields stripped, safe to serve statically
    web_data_dir = REPO / "web" / "data"
    web_data_dir.mkdir(parents=True, exist_ok=True)
    ranked_dicts = [li.to_dict() for li in ranked]
    with (web_data_dir / "ranked.json").open("w", encoding="utf-8") as f:
        json.dump(ranked_dicts, f, indent=2, ensure_ascii=False, default=str)
    with (web_data_dir / "ranked-public.json").open("w", encoding="utf-8") as f:
        json.dump([li.to_public_dict() for li in ranked], f, indent=2, ensure_ascii=False, default=str)

    # Derive per-source health status for the dashboard status strip.
    #   green  — returned > 0 listings, no exception
    #   yellow — returned > 0 listings but with a caught exception (partial)
    #   red    — returned 0 listings OR raised an exception
    source_status: dict[str, str] = {}
    for src in sources:
        count = per_source_count.get(src)
        had_error = src in source_errors
        if had_error:
            source_status[src] = "red"
        elif count is None or count == 0:
            source_status[src] = "red"
        else:
            source_status[src] = "green"

    # Coverage block: pulled counts + pagination flags per source.
    # supplier is null here (run.py doesn't make extra requests to fetch
    # advertised totals — use automation/coverage_audit.py for that).
    coverage = {
        src: {
            "supplier": None,
            "pulled": per_source_count.get(src, 0),
            "max_pages_hit": source_meta.get(src, {}).get("max_pages_hit", False),
        }
        for src in sources
    }

    # Field completeness snapshot — populated % per field per source.
    field_completeness = build_completeness_block(ranked_dicts)

    # V-leg fallback diagnostic. The Value leg returns a neutral default of
    # 35 when price_per_m2 is None (no_price) or when the comp pool can't
    # form (no_comps). With the V-weight at 0.40, every listing on neutral
    # is contributing the same constant to its composite — a big mass of
    # listings on neutral means the V leg is mostly noise that week. The
    # property_type_counts surfaces classifier drift if a future scraper
    # change starts mass-misclassifying inventory.
    from collections import Counter as _Counter
    property_type_counts = dict(_Counter(li.property_type for li in ranked))
    v_fallback_no_price = sum(1 for li in ranked if li.price_per_m2 is None)
    v_fallback_no_comps = sum(
        1 for li in ranked
        if li.price_per_m2 is not None and li.zone_percentile is None
    )

    # Last-updated metadata
    finished = datetime.now(timezone.utc)
    meta = {
        "last_updated": finished.isoformat(),
        "started_at": started.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 2),
        "total_listings": len(ranked),
        "dropped": dropped,
        "per_source_raw": per_source_count,
        "source_status": source_status,
        "coverage": coverage,
        "field_completeness": field_completeness,
        "property_type_counts": property_type_counts,
        "v_fallback_no_price": v_fallback_no_price,
        "v_fallback_no_comps": v_fallback_no_comps,
        "sources": sources,
        "offline": offline,
        "fixture_fallback_active": fixture_fallback_active,
        "errors": errors,
    }
    with (web_data_dir / "last_updated.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # Append lightweight summary to run history (keep last 60 runs ≈ 15 months weekly).
    history_path = web_data_dir / "run_history.json"
    try:
        history = json.loads(history_path.read_text()) if history_path.exists() else []
    except Exception:
        history = []
    history.append({
        "ts": finished.isoformat(),
        "total": len(ranked),
        "dropped": dropped,
        "duration": round((finished - started).total_seconds(), 2),
        "error_count": len(errors),
        "per_source_raw": per_source_count,
        "source_status": source_status,
    })
    history = history[-60:]
    with history_path.open("w", encoding="utf-8") as f:
        json.dump(history, f)

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

    # Summary line for CI logs
    print(
        f"pulpo run | {finished.isoformat()} | "
        f"{len(ranked)} listings | sources={','.join(sources)} | "
        f"errors={len(errors)} | offline={offline}"
    )
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        # Don't fail the run on partial failures — partial data is better than no data
    return 0

if __name__ == "__main__":
    sys.exit(main())
