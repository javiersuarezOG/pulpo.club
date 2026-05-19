"""
Single-command pipeline runner for automation (cron, GitHub Actions, etc.).

Runs all configured scrapers, normalizes, ranks, and writes:
    samples/ranked.csv         (committed for human review)
    web/data/ranked.json       (consumed by web/legacy.html + the new Vite app)
    web/data/last_updated.json (timestamp + counts for the dashboard header)

Exit code 0 on success, 1 on failure.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure repo root is on sys.path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.agents import SOURCES as REGISTRY  # noqa: E402
# Importing pulpo.scrapers triggers registration of all sources via
# module-level decorators. The trailing `assert` pins the reference so
# Pyright doesn't flag the import as unused.
import pulpo.scrapers  # noqa: F401,E402
assert pulpo.scrapers is not None
from pulpo.agents.html_crawler import HTTPX_OK, SELECTOLAX_OK  # noqa: E402
from pulpo.ranker import rank  # noqa: E402
from automation.prd_feasibility import run_probe as run_feasibility_probe  # type: ignore  # noqa: E402
from automation.llm_enrichment import enrich_listings as _llm_enrich  # type: ignore  # noqa: E402
from automation._atomic import atomic_write_json as _atomic_write_json  # noqa: E402
from automation._config import (  # noqa: E402
    env_bool as _env_bool,
    env_float as _env_float,
    env_int as _env_int,
    env_str as _env_str,
)
from automation.ai_enrichment_fallback import apply_fallbacks as _ai_fallback  # type: ignore  # noqa: E402
from pulpo.nlp_extractor import (  # type: ignore  # noqa: E402
    load_dictionaries as _load_nlp_dicts,
    extract as _nlp_extract,
)
from pulpo.derived_rules import (   # type: ignore  # noqa: E402
    apply_all as _apply_derived_rules,
    apply_ia_derives as _apply_ia_derives,
    derive_source_type as _derive_source_type,
    derive_previous_price as _derive_previous_price,
    derive_beachfront_tier as _derive_beachfront_tier,
    derive_land_type as _derive_land_type,
    derive_is_incomplete as _derive_is_incomplete,
)
from automation.pipeline_steps import (  # noqa: E402
    phase_normalize, phase_validate, phase_write_outputs, phase_print_summary,
    compute_derived_population, check_population_regression,
)
from automation.posthog_client import (  # noqa: E402
    capture as _ph_capture,
    set_run_id as _ph_set_run_id,
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


def _hero_file_path(thumbnail_path: Path) -> Path:
    """`<file>.jpg` → `<file>.hero.jpg` (dual-derivative photo storage)."""
    stem = thumbnail_path.name[:-len(".jpg")] if thumbnail_path.name.endswith(".jpg") else thumbnail_path.stem
    return thumbnail_path.parent / f"{stem}.hero.jpg"


def _meta_sidecar_path(image_path: Path) -> Path:
    """`<file>.jpg` → `<file>.jpg.meta.json`. Per the image-enrichment
    protocol: one sidecar per derivative file."""
    return image_path.parent / (image_path.name + ".meta.json")


def _write_sidecar(image_path: Path, raw_bytes: bytes) -> Optional[dict]:
    """Compute image metadata from raw_bytes + write sidecar JSON next
    to image_path. Returns the metadata dict, or None when Pillow isn't
    available / the image fails to decode.
    """
    try:
        from automation.photo_quality import compute_image_metadata
    except ImportError:
        return None
    meta = compute_image_metadata(raw_bytes, file_size_bytes=len(raw_bytes))
    if meta is None:
        return None
    sidecar_path = _meta_sidecar_path(image_path)
    sidecar_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


# U1 (hero re-escalation, 2026-05-18) — cap on how many candidates we
# score per listing. Real-estate listings routinely carry 10–30 photos;
# 5 covers the typical "first few" the broker chose to feature without
# blowing the bandwidth budget. Override via PULPO_PHOTO_MAX_CANDIDATES.
_PHOTO_CANDIDATES_CAP_DEFAULT = 5


def _score_candidates_cheap(photo_urls, on_url_error=None):
    """Phase 4 cost-gating Pass 1 — download + cheap scoring only.

    Returns a list of candidate dicts:
        {url, content, score (technical 0-100), has_text_overlay,
         hero_eligible, cheap_score}

    No LLM call here. ``aesthetic`` is intentionally absent — it gets
    added later by ``_apply_aesthetic_to_eligible`` for candidates the
    orchestrator selected into the top-X% pool. Per-URL fetch errors
    invoke ``on_url_error(url, exception)`` so the caller can log them
    alongside the originating URL.
    """
    if not photo_urls:
        return []

    import httpx
    try:
        from automation.photo_quality import (
            compute_score as _compute_photo_score,
            detect_text_overlay as _detect_text_overlay,
            compute_image_metadata as _compute_image_metadata,
            cheap_quality_score as _cheap_quality_score,
            picker_min_cheap_score as _picker_min_cheap_score,
        )
    except Exception:
        _compute_photo_score = None
        _detect_text_overlay = None
        _compute_image_metadata = None
        _cheap_quality_score = None
        _picker_min_cheap_score = None

    try:
        from automation import picker_excluded as _picker_excluded_store
    except Exception:
        _picker_excluded_store = None

    # Amortize the disk read across all candidates in this call.
    if _picker_excluded_store is not None:
        excluded_store = _picker_excluded_store.load_store()
        excluded_store_dirty = False
    else:
        excluded_store = {}
        excluded_store_dirty = False

    floor = _picker_min_cheap_score() if _picker_min_cheap_score else 40

    cap = max(1, _env_int("PULPO_PHOTO_MAX_CANDIDATES",
                          _PHOTO_CANDIDATES_CAP_DEFAULT))

    candidates = []
    for url in photo_urls[:cap]:
        try:
            r = httpx.get(url, timeout=5.0, follow_redirects=True)
            r.raise_for_status()
        except Exception as e:
            if on_url_error is not None:
                try:
                    on_url_error(url, e)
                except Exception:
                    pass
            continue
        try:
            score = _compute_photo_score(r.content) if _compute_photo_score else None
        except Exception:
            score = None
        try:
            has_text = _detect_text_overlay(r.content) if _detect_text_overlay else None
        except Exception:
            has_text = None
        try:
            meta = _compute_image_metadata(r.content) if _compute_image_metadata else None
        except Exception:
            meta = None
        hero_elig = bool(meta.get("hero_eligible")) if isinstance(meta, dict) else None
        try:
            cheap = _cheap_quality_score(
                r.content,
                technical=score,
                has_text_overlay=has_text,
                hero_eligible=hero_elig,
            ) if _cheap_quality_score else (score if score is not None else 0)
        except Exception:
            cheap = score if score is not None else 0
        # Quality-floor filter: a candidate whose cheap_score is below
        # the floor gets permanently excluded — never sent to the VLM
        # booster on this run OR any future run (persisted by sha1(bytes)
        # in web/data/picker_excluded.json). Pre-existing entries in the
        # store also flag the candidate as excluded; we don't re-evaluate
        # the floor for known-excluded photos.
        already_excluded = False
        if _picker_excluded_store is not None:
            if _picker_excluded_store.is_excluded(r.content, store=excluded_store):
                already_excluded = True
        picker_excluded = already_excluded or (cheap < floor)
        if picker_excluded and not already_excluded and _picker_excluded_store is not None:
            _picker_excluded_store.mark_excluded(
                r.content,
                cheap_score=cheap,
                floor=floor,
                store=excluded_store,
                save=False,
            )
            excluded_store_dirty = True
        candidates.append({
            "url": url,
            "content": r.content,
            "score": score if score is not None else 0,
            "has_text_overlay": has_text,
            "hero_eligible": hero_elig,
            "cheap_score": cheap,
            "picker_excluded": picker_excluded,
        })
    # Persist newly-flagged exclusions in one write per call. Cheap (single
    # write), safe (atomic via Path.write_text), and amortized across all
    # candidates the caller batched together.
    if excluded_store_dirty and _picker_excluded_store is not None:
        try:
            _picker_excluded_store.save_store(excluded_store)
        except Exception:
            # Persistence failure is non-fatal — the in-memory flag still
            # blocks the VLM call on this run. Future runs will just
            # re-evaluate the floor.
            pass
    return candidates


def _apply_aesthetic_to_eligible(scored_candidates, eligible_urls=None):
    """Phase 4 cost-gating Pass 2 — call score_aesthetic on the
    subset of candidates whose URLs are in ``eligible_urls``. Cached
    candidates (whose bytes-hash is already in
    web/data/llm_vision_cache.json) get their cached score for free
    regardless of eligibility — the cache lookup happens inside
    score_aesthetic. Mutates ``scored_candidates`` in place, adding
    an ``aesthetic`` key per candidate (None when uneligible-and-
    uncached or when the provider returned None).

    When ``eligible_urls`` is None (backward-compat for the
    ``_pick_best_photo_url`` wrapper called by tests/test_photos.py),
    every candidate is eligible — matches today's per-listing
    "score every candidate" behavior.
    """
    try:
        from automation.aesthetic_vision import score_aesthetic as _score_aesthetic
    except Exception:
        _score_aesthetic = None

    for c in scored_candidates:
        if _score_aesthetic is None:
            c["aesthetic"] = None
            continue
        if eligible_urls is not None and c["url"] not in eligible_urls:
            c["aesthetic"] = None
            continue
        try:
            c["aesthetic"] = _score_aesthetic(c["content"])
        except Exception:
            c["aesthetic"] = None


def _pick_winner_from_scored(
    scored_candidates,
) -> "tuple[Optional[str], Optional[bytes], Optional[int], Optional[bool]]":
    """Phase 4 cost-gating winner-selection — same composite ranking as
    pre-refactor ``_pick_best_photo_url``: prefer non-text-overlay
    candidates; rank by 70% aesthetic + 30% technical when at least one
    aesthetic score is present, else by technical alone. Returns the
    legacy ``(url, content, score, has_text_overlay)`` tuple."""
    if not scored_candidates:
        return (None, None, None, None)

    # Prefer photos that are NOT flagged as text overlay AND NOT flagged
    # picker_excluded (below quality floor). Same filter pattern: drop
    # excluded ONLY when at least one non-excluded candidate exists so a
    # listing with all-bad photos still gets a hero (graceful degrade —
    # technical ranking decides among the dregs). Treat None for either
    # flag as "not flagged" so missing signals don't disqualify everyone.
    non_excluded = [c for c in scored_candidates if not c.get("picker_excluded")]
    base = non_excluded if non_excluded else list(scored_candidates)
    non_text = [c for c in base if c.get("has_text_overlay") is not True]
    pool = non_text if non_text else base

    any_aesthetic = any(c.get("aesthetic") is not None for c in pool)
    if any_aesthetic:
        def _composite(c):
            tech = float(c["score"])
            aes = c.get("aesthetic")
            if aes is None:
                # Candidate didn't get scored (uneligible for top-X%,
                # mid-day budget exhaustion, or a transient provider
                # blip). Use technical-only so it doesn't lose to a peer
                # just because the LLM was unavailable for that one call.
                return tech
            return 0.3 * tech + 0.7 * (float(aes) * 10.0)
        pool.sort(key=_composite, reverse=True)
    else:
        pool.sort(key=lambda c: c["score"], reverse=True)
    w = pool[0]
    return (w["url"], w["content"], w["score"], w.get("has_text_overlay"))


def _pick_best_photo_url(photo_urls, on_url_error=None):
    """Phase 4 U1 — hero re-escalation. Backward-compat wrapper around
    the refactored two-pass picker. Tests and per-listing callers can
    still invoke this directly; the orchestrator (``_download_hero_photos``)
    uses the underlying primitives so it can compute the global top-X%
    gate across all listings.

    Returns ``(url, content, score, has_text_overlay)`` for the winning
    candidate, or ``(None, None, None, None)`` if every download failed.
    """
    candidates = _score_candidates_cheap(photo_urls, on_url_error=on_url_error)
    # No global gate at this entry point — preserve today's per-listing
    # behavior (every candidate eligible for an aesthetic call).
    _apply_aesthetic_to_eligible(candidates, eligible_urls=None)
    return _pick_winner_from_scored(candidates)


def _select_top_pct_eligible(scored_per_listing, top_pct: int) -> set:
    """Phase 4 cost-gating Pass-1.5 — global gate.

    Given each listing's Phase-1 scored candidates, return the set of
    URLs that should receive an aesthetic LLM call this run. The gate
    operates on **uncached** candidates only (per the plan §4): a
    candidate whose bytes-hash is already in the aesthetic cache pays
    nothing to score this run, so it doesn't count toward the gate.
    The cache fills naturally over many nights without operator
    intervention.

    Per-listing lone-candidate optimization is the caller's job — this
    helper operates on raw candidate dicts, agnostic to listing structure.

    ``top_pct=100`` means "score every uncached candidate this run."
    ``top_pct=0`` means "score none." Both endpoints are valid operator
    settings.
    """
    try:
        from automation.aesthetic_vision import _load_cache, _cache_key
    except Exception:
        # Aesthetic module unavailable — no candidates eligible, the
        # pipeline runs in cheap-only mode. Matches the LLM-off fail-soft
        # contract from the plan.
        return set()
    cache = _load_cache()

    uncached = []
    for scored in scored_per_listing:
        for c in scored:
            content = c.get("content")
            if content is None:
                continue
            # Quality-floor filter: candidates flagged picker_excluded by
            # _score_candidates_cheap (cheap_score below floor OR already
            # in picker_excluded.json) never enter the VLM eligibility pool.
            # Belt-and-suspenders: the flag is set in-memory upstream AND
            # persisted by sha1 — either signal alone blocks the call.
            if c.get("picker_excluded"):
                continue
            key = _cache_key(content)
            if key in cache:
                continue
            uncached.append(c)

    if not uncached or top_pct <= 0:
        return set()
    # Sort by cheap_score desc; ties broken by technical score. Stable
    # secondary key prevents flakey nondeterminism on equal cheap_score.
    uncached.sort(
        key=lambda c: (c.get("cheap_score", 0), c.get("score", 0)),
        reverse=True,
    )
    cutoff = max(1, int(len(uncached) * top_pct / 100))
    eligible = {c["url"] for c in uncached[:cutoff]}
    return eligible


def _read_sidecar(image_path: Path) -> Optional[dict]:
    """Read the sidecar JSON beside image_path. Returns None if missing
    or malformed. Used by the skip-path so we don't re-decode every
    cached photo on every nightly run."""
    sidecar_path = _meta_sidecar_path(image_path)
    if not sidecar_path.exists():
        return None
    try:
        return json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _populate_hires_fields_from_sidecar(li, sidecar: dict, *, quarantined: bool) -> None:
    """Copy hires sidecar values onto the Listing object.

    Called from both the fresh-write path and the cache-hit skip path
    inside ``_download_hires_photos``. Mutates ``li`` in place. The
    sidecar dict is the one written to ``<file>.hires.jpg.meta.json``
    (i.e. the merged result of ``compute_image_metadata`` + the hires
    QC additions: hires_photo_quality_score, resdet_*, quarantined,
    aesthetic). ``quarantined`` is passed separately so the cache-hit
    path can compute it from the marker file even on older sidecars
    that pre-date the ``quarantined`` key.
    """
    if not isinstance(sidecar, dict):
        return
    if sidecar.get("width") is not None:
        li.hires_width = int(sidecar["width"])
    if sidecar.get("height") is not None:
        li.hires_height = int(sidecar["height"])
    # hires_eligible comes from compute_image_metadata which gates on the
    # source bytes' dimensions — exactly the contract pulpo-social needs.
    if "hires_eligible" in sidecar:
        li.hires_eligible = bool(sidecar.get("hires_eligible"))
    if sidecar.get("hires_photo_quality_score") is not None:
        li.hires_photo_quality_score = int(sidecar["hires_photo_quality_score"])
    if "resdet_upscaled" in sidecar:
        v = sidecar.get("resdet_upscaled")
        li.hires_resdet_upscaled = bool(v) if v is not None else None
    li.hires_quarantined = bool(quarantined)
    # hires_available = file present AND not quarantined. The caller has
    # already verified file presence before invoking this helper.
    li.hires_available = not bool(quarantined)


def _download_hero_photos(listings, repo: Path) -> dict:
    """Download the first photo_url for each listing with photos, then write
    two derivatives:

    - ``<file>.jpg``        thumbnail (max 600×400, JPEG Q75) — drives cards
    - ``<file>.hero.jpg``   hero (max 1920×1080, JPEG Q85)   — drives proof row
                            + the rewritten featured-pool picker

    Per-file sidecars at ``<file>.jpg.meta.json`` +
    ``<file>.hero.jpg.meta.json`` record dimensions + eligibility flags
    so the cached-skip path can re-populate ``hero_eligible`` /
    ``card_eligible`` on the Listing without re-decoding the image.

    Uses the URL-hash sidecar (.hash) to skip unchanged photos. Skip
    path also verifies the hero derivative + both meta sidecars are
    present — if either is missing (existed-before-this-rewrite case),
    the URL is re-fetched and the missing files are produced.

    Logs failures to web/data/photo_fetch_log.jsonl (non-fatal).
    Returns summary counts.
    """
    # Pillow is optional — skip the whole step if not installed
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("[photos] Pillow not installed — skipping hero download")
        return {"attempted": 0, "ok": 0, "skipped": 0, "failed": 0, "elapsed_s": 0.0,
                "hero_eligible": 0, "card_eligible": 0}

    # Pillow 10+ moved the resampling enum to Image.Resampling.* and
    # removed the top-level Image.LANCZOS alias. Detect at module load
    # so we don't pay the attribute lookup per-listing.
    try:
        _LANCZOS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
    except AttributeError:
        _LANCZOS = Image.LANCZOS  # type: ignore[attr-defined]

    # httpx is now imported inside _pick_best_photo_url (U1, 2026-05-18).
    # No direct httpx use here anymore — keeping the line would fail ruff.

    photos_dir = repo / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    log_path = repo / "web" / "data" / "photo_fetch_log.jsonl"

    attempted = ok = skipped = failed = 0
    hero_eligible_count = 0
    card_eligible_count = 0
    budget_s = _env_float("PULPO_PHOTO_BUDGET_S", 600.0)
    t0 = _time.monotonic()
    budget_hit = False
    cap = max(1, _env_int("PULPO_PHOTO_MAX_CANDIDATES",
                          _PHOTO_CANDIDATES_CAP_DEFAULT))

    # State stashed for each non-skipped listing — feeds Phase C below.
    # ``None`` entries mark listings the URL-hash cache skipped or that
    # failed download outright; Phase C iterates with a None guard.
    pending: list = []

    # ── Phase A — URL-hash cache resolution + per-listing cheap scoring ──
    # No LLM calls in this loop; every candidate download is cheap
    # (httpx) + cheap scoring (Pillow + optional OpenCV/Tesseract).
    for li in listings:
        if _time.monotonic() - t0 > budget_s:
            budget_hit = True
            break
        if not li.photo_urls:
            continue
        # U1 (2026-05-18) — cache key hashes the WHOLE candidate set
        # in submission order so a scraper re-ordering retriggers
        # selection. The hero file name still keys off the listing id.
        candidate_urls = li.photo_urls[:cap]
        url_hash = hashlib.sha1(
            "|".join(candidate_urls).encode()
        ).hexdigest()[:12]

        fname = f"{li.source}_{li.source_id}.jpg"
        fpath = photos_dir / fname
        hero_fpath = _hero_file_path(fpath)
        hash_path = photos_dir / (fname + ".hash")
        thumb_meta_path = _meta_sidecar_path(fpath)
        hero_meta_path  = _meta_sidecar_path(hero_fpath)

        all_files_present = (
            fpath.exists() and hash_path.exists()
            and hero_fpath.exists()
            and thumb_meta_path.exists() and hero_meta_path.exists()
        )
        if all_files_present and hash_path.read_text().strip() == url_hash:
            li.hero_photo_path = f"/photos/{fname}"
            thumb_meta = _read_sidecar(fpath)
            hero_meta = _read_sidecar(hero_fpath)
            if thumb_meta:
                li.card_eligible = bool(thumb_meta.get("card_eligible", False))
            if hero_meta:
                li.hero_eligible = bool(hero_meta.get("hero_eligible", False))
                # Hero file's dimensions == source dimensions clamped to ≤1920×1080.
                # Surfaced through /api/social/listings so consumers can pre-filter
                # listings whose source is too small to render cleanly at the
                # requested output ratio (e.g. social 1080×1080).
                if hero_meta.get("width") is not None:
                    li.source_width = int(hero_meta["width"])
                if hero_meta.get("height") is not None:
                    li.source_height = int(hero_meta["height"])
                qs = hero_meta.get("hero_photo_quality_score")
                if qs is not None:
                    li.hero_photo_quality_score = qs
                ho = hero_meta.get("has_text_overlay")
                if ho is not None:
                    li.has_text_overlay = ho
            if li.card_eligible:
                card_eligible_count += 1
            if li.hero_eligible:
                hero_eligible_count += 1
            skipped += 1
            continue

        attempted += 1

        def _log_url_error(url, exc, _li=li, _log_path=log_path):
            try:
                with _log_path.open("a", encoding="utf-8") as _lf:
                    _lf.write(json.dumps({
                        "source_id": _li.source_id,
                        "source": _li.source,
                        "url": url,
                        "error": str(exc),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }) + "\n")
            except Exception:
                pass

        try:
            scored = _score_candidates_cheap(candidate_urls,
                                              on_url_error=_log_url_error)
            if not scored:
                raise RuntimeError(
                    f"no_candidate_downloaded_from_{len(candidate_urls)}_urls"
                )
            pending.append({
                "li": li,
                "scored": scored,
                "candidate_urls": candidate_urls,
                "url_hash": url_hash,
                "fname": fname,
                "fpath": fpath,
                "hero_fpath": hero_fpath,
                "hash_path": hash_path,
                "hero_meta_path": hero_meta_path,
            })
        except Exception as e:
            failed += 1
            with log_path.open("a", encoding="utf-8") as lf:
                lf.write(json.dumps({
                    "source_id": li.source_id, "source": li.source,
                    "candidate_urls": candidate_urls,
                    "error": str(e),
                    "ts": datetime.now(timezone.utc).isoformat(),
                }) + "\n")

    # ── Phase B — global top-X% eligibility across uncached candidates ──
    # Operator knob: LLM_VISION_TOP_PCT (default 5). With LLM_VISION_ENABLED
    # unset / false, _apply_aesthetic_to_eligible's import of
    # score_aesthetic returns None for every candidate regardless of
    # eligibility — the gate effectively becomes a no-op without us
    # having to special-case it here. That's the load-bearing
    # fail-soft contract from the plan.
    # _env_int handles the GH Actions footgun where unset secrets resolve
    # to the empty string rather than absent (see automation/_config.py).
    top_pct = _env_int("LLM_VISION_TOP_PCT", 5)
    # Lone-candidate optimization — a listing whose pool reduces to one
    # non-text-overlay survivor has no ranking choice to make. Exclude
    # its candidates from the eligibility pool entirely so the LLM
    # never sees them. (Cached candidates still get their cached score
    # via _apply_aesthetic_to_eligible's fall-through; the gate only
    # controls fresh paid calls.)
    pools_for_gate = []
    for state in pending:
        scored = state["scored"]
        non_text = sum(1 for c in scored if c.get("has_text_overlay") is not True)
        if non_text > 1:
            pools_for_gate.append(scored)
    eligible_urls = _select_top_pct_eligible(pools_for_gate, top_pct=top_pct)

    # ── Phase C — aesthetic scoring + winner pick + derivative write ──
    for state in pending:
        if _time.monotonic() - t0 > budget_s:
            budget_hit = True
            break
        li = state["li"]
        scored = state["scored"]
        candidate_urls = state["candidate_urls"]
        fpath = state["fpath"]
        hero_fpath = state["hero_fpath"]
        hash_path = state["hash_path"]
        hero_meta_path = state["hero_meta_path"]
        fname = state["fname"]
        url_hash = state["url_hash"]

        try:
            # Per-listing lone-candidate skip: when the pool after the
            # text-overlay filter is exactly one survivor, calling the
            # LLM is wasted spend — pass an empty eligibility set so
            # _apply_aesthetic_to_eligible only consults the cache.
            non_text = sum(1 for c in scored if c.get("has_text_overlay") is not True)
            if non_text > 1:
                _apply_aesthetic_to_eligible(scored, eligible_urls=eligible_urls)
            else:
                _apply_aesthetic_to_eligible(scored, eligible_urls=set())

            winning_url, winning_content, winning_score, winning_has_text = (
                _pick_winner_from_scored(scored)
            )
            if winning_url is None or winning_content is None:
                raise RuntimeError(
                    f"winner_pick_failed_from_{len(candidate_urls)}_urls"
                )

            li.hero_photo_quality_score = winning_score if winning_score else None
            li.has_text_overlay = winning_has_text

            from PIL import Image

            # ── Thumbnail (600×400, Q75) — drives every card ──────────
            thumb_img = Image.open(io.BytesIO(winning_content))
            thumb_img.thumbnail((600, 400), _LANCZOS)
            if thumb_img.mode in ("RGBA", "P"):
                thumb_img = thumb_img.convert("RGB")
            thumb_buf = io.BytesIO()
            thumb_img.save(thumb_buf, format="JPEG", quality=75, optimize=True)
            thumb_bytes = thumb_buf.getvalue()
            fpath.write_bytes(thumb_bytes)
            thumb_meta = _write_sidecar(fpath, thumb_bytes)
            if thumb_meta:
                li.card_eligible = bool(thumb_meta.get("card_eligible", False))

            # ── Hero (1920×1080 max, Q85) — drives proof row + featured ─
            hero_img = Image.open(io.BytesIO(winning_content))
            hero_img.thumbnail((1920, 1080), _LANCZOS)
            if hero_img.mode in ("RGBA", "P"):
                hero_img = hero_img.convert("RGB")
            hero_buf = io.BytesIO()
            hero_img.save(hero_buf, format="JPEG", quality=85, optimize=True)
            hero_bytes = hero_buf.getvalue()
            hero_fpath.write_bytes(hero_bytes)
            hero_meta = _write_sidecar(hero_fpath, hero_bytes)
            if hero_meta is not None:
                hero_meta["hero_photo_quality_score"] = winning_score
                hero_meta["has_text_overlay"] = winning_has_text
                hero_meta["winning_url"] = winning_url
                hero_meta["candidate_count"] = len(candidate_urls)
                hero_meta_path.write_text(json.dumps(hero_meta, indent=2) + "\n",
                                          encoding="utf-8")
                li.hero_eligible = bool(hero_meta.get("hero_eligible", False))
                # Mirror the cached-skip path: source_width/source_height
                # are the hero derivative's pixel dimensions (which equal
                # original source dimensions clamped to ≤1920×1080).
                if hero_meta.get("width") is not None:
                    li.source_width = int(hero_meta["width"])
                if hero_meta.get("height") is not None:
                    li.source_height = int(hero_meta["height"])

            hash_path.write_text(url_hash)
            li.hero_photo_path = f"/photos/{fname}"
            if li.card_eligible:
                card_eligible_count += 1
            if li.hero_eligible:
                hero_eligible_count += 1
            ok += 1
        except Exception as e:
            failed += 1
            with log_path.open("a", encoding="utf-8") as lf:
                lf.write(json.dumps({
                    "source_id": li.source_id, "source": li.source,
                    "candidate_urls": candidate_urls,
                    "error": str(e),
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
            "elapsed_s": elapsed, "budget_hit": budget_hit,
            "hero_eligible": hero_eligible_count, "card_eligible": card_eligible_count}


def _hires_file_path(photos_hires_dir: Path, source: str, source_id: str) -> Path:
    """`<source>_<id>` → `<source>_<id>.hires.jpg` (hires-derivative storage)."""
    return photos_hires_dir / f"{source}_{source_id}.hires.jpg"


def _resdet_upscale_check(image_path: Path) -> Optional[dict]:
    """Run vendored resdet against a hires file. Returns dict or None on error.

    Result shape: ``{"detected_width": int, "detected_height": int,
                     "upscaled": bool}``. The upscale judgment compares
    detected dims to the file's actual dims (read by Pillow). Returns
    None when resdet isn't vendored (skip the check silently — caller
    should treat as "unknown" and still keep the file).
    """
    import subprocess
    repo_root = Path(__file__).resolve().parents[1]
    binary = repo_root / "vendor" / "resdet" / "resdet-linux-x64"
    if not binary.exists():
        return None
    try:
        proc = subprocess.run(
            [str(binary), "-v1", str(image_path)],
            capture_output=True, timeout=10, text=True,
        )
        parts = proc.stdout.strip().split()
        if len(parts) < 2:
            return None
        dw = int(parts[0])
        dh = int(parts[1])
        # Read the actual file dims to compare.
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                aw, ah = img.size
        except Exception:
            return None
        wdelta = aw - dw
        hdelta = ah - dh
        upscaled = (wdelta >= 12 and dw > 0) or (hdelta >= 12 and dh > 0)
        return {
            "detected_width": dw,
            "detected_height": dh,
            "upscaled": bool(upscaled),
        }
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def _download_hires_photos(listings, repo: Path) -> dict:
    """Phase 1 of plan v2 — parallel hi-res photo pipeline.

    Fetches the broker's native-resolution photo bytes (bypassing the
    1920×1080 down-sample applied by the existing hero pipeline) and
    writes them to ``web/photos-hires/<source>_<id>.hires.jpg`` with a
    per-file sidecar capturing: dimensions, file size, JPEG quality
    estimate, `compute_score` result, resdet detection, deterministic
    aesthetic score, and the source URL we fetched.

    Gated on ``PULPO_HIRES_ENABLED=1``; defaults OFF so this function
    is a no-op when the env var isn't set. Other env vars:

    - ``PULPO_HIRES_SOURCES`` — comma-separated allowlist, e.g.
      ``"bienesraices,remax,century21,oceanside,nexo"``. Sources not in
      the list are skipped entirely.
    - ``PULPO_HIRES_BUDGET_S`` — wall-clock budget in seconds, default 1500.
    - ``PULPO_HIRES_LIMIT`` — process at most N listings (top by
      rank_score). 0 / unset = process all.
    - ``PULPO_HIRES_SHADOW`` — informational; doesn't change behavior in
      this function (the gating happens in ``api/social/image.js`` via
      ``PULPO_HIRES_SERVE``). When set, the metrics row records the
      shadow flag.

    Output side-effects:
    - ``web/photos-hires/<source>_<id>.hires.jpg`` per processed listing
      (skipped on cache hit, omitted on per-listing failure).
    - ``web/photos-hires/<source>_<id>.hires.jpg.meta.json`` per file.
    - ``web/photos-hires/<source>_<id>.hires.jpg.quarantine`` marker
      file when resdet says the bytes are upscaled despite our fetch
      (broker lied about resolution; the social endpoint will skip
      quarantined files).
    - ``web/photos-hires/<source>_<id>.hires.jpg.hash`` URL-hash cache.
    - Appends one row to ``web/data/hires_pipeline_metrics.jsonl``.
    - Per-listing log lines on stderr (`[hires] start/ok/reject/error/skip/budget`).
    """
    if not _env_bool("PULPO_HIRES_ENABLED", False):
        return {"enabled": False}

    allow_csv = _env_str("PULPO_HIRES_SOURCES", "")
    allow_set = {s.strip() for s in allow_csv.split(",") if s.strip()}
    if not allow_set:
        print("[hires] PULPO_HIRES_SOURCES is empty — nothing to do", file=sys.stderr)
        return {"enabled": True, "skipped_no_allowlist": True}

    budget_s = _env_float("PULPO_HIRES_BUDGET_S", 1500.0)
    limit_n = _env_int("PULPO_HIRES_LIMIT", 0)
    shadow = _env_bool("PULPO_HIRES_SHADOW", False)

    try:
        from PIL import Image  # noqa: F401  -- decode sanity check
    except ImportError:
        print("[hires] Pillow not installed — aborting", file=sys.stderr)
        return {"enabled": True, "error": "pillow_missing"}
    try:
        import httpx
    except ImportError:
        print("[hires] httpx not installed — aborting", file=sys.stderr)
        return {"enabled": True, "error": "httpx_missing"}

    from automation.hires_url_transform import transform_hires_url, describe_transform
    from automation.photo_quality import compute_image_metadata, compute_score
    from automation.aesthetic_deterministic import assess_deterministic_aesthetic

    photos_hires_dir = repo / "web" / "photos-hires"
    photos_hires_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = repo / "web" / "data" / "hires_pipeline_metrics.jsonl"
    log_path = repo / "web" / "data" / "photo_fetch_log.jsonl"

    # Filter + order: only allow-listed sources, sorted by rank_score desc.
    in_scope = [li for li in listings if li.source in allow_set and li.photo_urls]
    in_scope.sort(key=lambda li: (-(li.rank_score or 0), li.source, li.source_id))
    if limit_n > 0:
        in_scope = in_scope[:limit_n]

    attempted = ok = rejected_upscaled = rejected_too_small = errored = skipped_cache = 0
    by_source: dict[str, dict] = {s: {"in_scope": 0, "with_hires": 0} for s in allow_set}
    for li in listings:
        if li.source in by_source:
            by_source[li.source]["in_scope"] += 0  # placeholder; set below
    for li in in_scope:
        by_source.setdefault(li.source, {"in_scope": 0, "with_hires": 0})
        by_source[li.source]["in_scope"] += 1

    fetch_times_ms: list[float] = []
    t0 = _time.monotonic()
    budget_hit = False

    for li in in_scope:
        elapsed_now = _time.monotonic() - t0
        if elapsed_now > budget_s:
            print(f"[hires] budget {li.source}__{li.source_id} reason=time_budget_exceeded "
                  f"budget_s={budget_s} elapsed_s={elapsed_now:.1f}", file=sys.stderr)
            budget_hit = True
            break

        original_url = li.photo_urls[0]
        url = transform_hires_url(li.source, original_url)
        url_hash = hashlib.sha1(url.encode()).hexdigest()[:12]

        hires_path = _hires_file_path(photos_hires_dir, li.source, li.source_id)
        hires_meta_path = _meta_sidecar_path(hires_path)
        hash_path = photos_hires_dir / (hires_path.name + ".hash")

        # URL-hash cache skip path.
        if hires_path.exists() and hires_meta_path.exists() and hash_path.exists():
            try:
                if hash_path.read_text().strip() == url_hash:
                    skipped_cache += 1
                    print(f"[hires] skip   {li.source}__{li.source_id} reason=cache_hit", file=sys.stderr)
                    by_source[li.source]["with_hires"] += 1
                    # Repopulate hires_* fields on the Listing from the
                    # cached sidecar so downstream consumers
                    # (api/social/listings projection, contract test)
                    # see the same values they would on a fresh run.
                    cached_sidecar = _read_sidecar(hires_path)
                    if cached_sidecar is not None:
                        cached_quarantined = bool(cached_sidecar.get("quarantined")) or (
                            photos_hires_dir / (hires_path.name + ".quarantine")
                        ).exists()
                        _populate_hires_fields_from_sidecar(
                            li, cached_sidecar, quarantined=cached_quarantined
                        )
                    continue
            except OSError:
                pass

        attempted += 1
        print(f"[hires] start  {li.source}__{li.source_id} url={url}", file=sys.stderr)
        fetch_t0 = _time.monotonic()
        try:
            r = httpx.get(url, timeout=8.0, follow_redirects=True)
            r.raise_for_status()
            raw = r.content
        except Exception as e:
            errored += 1
            print(f"[hires] error  {li.source}__{li.source_id} {type(e).__name__}: {e}", file=sys.stderr)
            try:
                with log_path.open("a", encoding="utf-8") as lf:
                    lf.write(json.dumps({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "derivative": "hires",
                        "source": li.source,
                        "source_id": li.source_id,
                        "url": url,
                        "error_type": _classify_error(e),
                        "error_message": str(e)[:300],
                    }) + "\n")
            except OSError:
                pass
            continue
        fetch_ms = (_time.monotonic() - fetch_t0) * 1000.0
        fetch_times_ms.append(fetch_ms)

        # Decode + measure dimensions before writing.
        meta = compute_image_metadata(raw, file_size_bytes=len(raw))
        if meta is None:
            errored += 1
            print(f"[hires] error  {li.source}__{li.source_id} reason=decode_failed", file=sys.stderr)
            continue
        if not meta.get("hires_eligible", False):
            rejected_too_small += 1
            print(f"[hires] reject {li.source}__{li.source_id} reason=below_1080 "
                  f"dims={meta['width']}x{meta['height']}", file=sys.stderr)
            continue

        # Write the file before resdet — resdet operates on a path.
        try:
            hires_path.write_bytes(raw)
        except OSError as e:
            errored += 1
            print(f"[hires] error  {li.source}__{li.source_id} reason=write_failed {e}", file=sys.stderr)
            continue

        # In-loop QC: resdet validation + compute_score + deterministic aesthetic.
        resdet_result = _resdet_upscale_check(hires_path)
        score = compute_score(raw, byte_size=len(raw))
        aesthetic = assess_deterministic_aesthetic(raw)

        quarantined = False
        if resdet_result is not None and resdet_result.get("upscaled", False):
            quarantined = True
            quarantine_marker = photos_hires_dir / (hires_path.name + ".quarantine")
            try:
                quarantine_marker.write_text(
                    json.dumps({
                        "reason": "resdet_upscaled",
                        "detected_width": resdet_result["detected_width"],
                        "detected_height": resdet_result["detected_height"],
                        "actual_width": meta["width"],
                        "actual_height": meta["height"],
                        "computed_at": datetime.now(timezone.utc).isoformat(),
                    }, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass

        # Compose the sidecar.
        sidecar = {
            **meta,
            "source_url": url,
            "original_url": original_url,
            "transform_used": describe_transform(li.source),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "hires_photo_quality_score": score,
            "resdet_detected_width": resdet_result["detected_width"] if resdet_result else None,
            "resdet_detected_height": resdet_result["detected_height"] if resdet_result else None,
            "resdet_upscaled": resdet_result["upscaled"] if resdet_result else None,
            "quarantined": quarantined,
            "aesthetic": aesthetic,
        }
        try:
            hires_meta_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
            hash_path.write_text(url_hash)
        except OSError as e:
            errored += 1
            print(f"[hires] error  {li.source}__{li.source_id} reason=sidecar_write_failed {e}",
                  file=sys.stderr)
            continue

        # Populate hires_* fields on the Listing object. Source of truth is
        # the sidecar dict we just persisted, so the in-memory state matches
        # what the cached-skip path reads on subsequent runs.
        _populate_hires_fields_from_sidecar(li, sidecar, quarantined=quarantined)

        if quarantined:
            rejected_upscaled += 1
            print(f"[hires] reject {li.source}__{li.source_id} reason=resdet_upscaled "
                  f"detected={resdet_result['detected_width']}x{resdet_result['detected_height']}",
                  file=sys.stderr)
        else:
            ok += 1
            by_source[li.source]["with_hires"] += 1
            aesthetic_val = aesthetic.get("visual_appeal") if aesthetic else None
            print(f"[hires] ok     {li.source}__{li.source_id} "
                  f"dims={meta['width']}x{meta['height']} "
                  f"bytes={int(meta['file_size_kb'])}KB score={score} "
                  f"aesthetic={aesthetic_val} fetched_in={int(fetch_ms)}ms",
                  file=sys.stderr)

    wall = _time.monotonic() - t0

    def _pct(numer: int, denom: int) -> float:
        return round(100 * numer / denom, 1) if denom > 0 else 0.0

    p50 = round(sorted(fetch_times_ms)[len(fetch_times_ms) // 2], 1) if fetch_times_ms else 0
    p95_idx = max(0, int(0.95 * len(fetch_times_ms)) - 1) if fetch_times_ms else 0
    p95 = round(sorted(fetch_times_ms)[p95_idx], 1) if fetch_times_ms else 0

    summary = {
        "run_id": datetime.now(timezone.utc).isoformat(),
        "git_sha": os.environ.get("GITHUB_SHA", "")[:7],
        "config": {
            "enabled": True,
            "shadow": shadow,
            "sources": sorted(allow_set),
            "budget_s": budget_s,
            "limit": limit_n,
        },
        "results": {
            "attempted": attempted,
            "ok": ok,
            "rejected_upscaled": rejected_upscaled,
            "rejected_too_small": rejected_too_small,
            "error": errored,
            "skipped_cache_hit": skipped_cache,
            "budget_hit": budget_hit,
        },
        "performance": {
            "wall_clock_s": round(wall, 1),
            "p50_fetch_ms": p50,
            "p95_fetch_ms": p95,
        },
        "coverage": {
            "total_listings_in_scope": sum(b["in_scope"] for b in by_source.values()),
            "with_hires": sum(b["with_hires"] for b in by_source.values()),
            "by_source": {
                s: {
                    "in_scope": b["in_scope"],
                    "with_hires": b["with_hires"],
                    "pct": _pct(b["with_hires"], b["in_scope"]),
                }
                for s, b in by_source.items()
            },
        },
    }
    try:
        with metrics_path.open("a", encoding="utf-8") as mf:
            mf.write(json.dumps(summary) + "\n")
    except OSError as e:
        print(f"[hires] WARN: failed to append metrics JSONL: {e}", file=sys.stderr)

    print(f"[hires] done attempted={attempted} ok={ok} rejected_upscaled={rejected_upscaled} "
          f"rejected_too_small={rejected_too_small} error={errored} skipped_cache_hit={skipped_cache} "
          f"wall={wall:.1f}s budget_hit={budget_hit}", file=sys.stderr)

    return summary


def _prune_orphan_photos(photos_dir: Path, live_filenames: set) -> None:
    """Move orphaned hero photos to _archive/<date>/, delete those older than 30d.

    Skips ``.hero.jpg`` files in the glob — those are paired with their
    thumbnail and prune together (the live_filenames set holds thumbnail
    names only). Also moves the matching sidecar JSONs + hash file
    alongside the thumbnail + hero derivative so the archive is
    self-contained.
    """
    from datetime import timedelta
    archive_base = photos_dir / "_archive"
    today_dir = archive_base / datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for f in photos_dir.glob("*.jpg"):
        # Skip the hero derivative — it's keyed off its thumbnail's
        # live-ness, not its own. Handled in the rename block below.
        if f.name.endswith(".hero.jpg"):
            continue
        if f.name not in live_filenames:
            today_dir.mkdir(parents=True, exist_ok=True)
            # Move the thumbnail + hero + every sidecar together so the
            # archive directory holds a complete set per listing.
            related = [
                f,                                       # <file>.jpg
                _hero_file_path(f),                      # <file>.hero.jpg
                _meta_sidecar_path(f),                   # <file>.jpg.meta.json
                _meta_sidecar_path(_hero_file_path(f)),  # <file>.hero.jpg.meta.json
                photos_dir / (f.name + ".hash"),         # <file>.jpg.hash
            ]
            for related_path in related:
                if related_path.exists():
                    related_path.rename(today_dir / related_path.name)

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
    # NOTE: PULPO_OFFLINE intentionally keeps the strict `== "1"` semantics
    # to stay bit-identical with pulpo/agents/html_crawler.py:is_offline().
    # Migrating to env_bool here without the matching update there would
    # silently let one module treat `PULPO_OFFLINE=true` as offline while
    # the other doesn't. Migrate both in lock-step if/when needed.
    offline = os.environ.get("PULPO_OFFLINE") == "1"
    limit = _env_int("PULPO_LIMIT", 30)
    sources = _env_str("PULPO_SOURCES", ",".join(REGISTRY.keys())).split(",")

    started = datetime.now(timezone.utc)
    # PostHog: tag every subsequent capture() in this process with a
    # shared run_id so we can filter the full lifecycle of one nightly
    # invocation in the Events view.
    run_id = _ph_set_run_id()
    print(f"[posthog] run_id={run_id}")
    _ph_capture("pipeline_started", {
        "sources": sources,
        "sources_count": len(sources),
        "offline": offline,
        "limit": limit,
    })
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

    # ── PostHog: per-source crawl results ────────────────────────────
    # Emit one event per source after the loop completes (success or
    # failure) so the Scraper-health dashboard and Pipeline funnel tiles
    # populate. Ordering inside the loop would also work; out-of-loop
    # keeps the loop body focused.
    for _src in sources:
        _src = _src.strip()
        _had_error = _src in source_errors
        _ph_capture(
            "crawl_failed" if _had_error else "crawl_succeeded",
            {
                "source":        _src,
                "count":         per_source_count.get(_src, 0),
                "duration_s":    source_durations.get(_src),
                "error_class":   source_error_class.get(_src),
                "error_msg":     (source_errors.get(_src) or "")[:300] or None,
                "max_pages_hit": source_meta.get(_src, {}).get("max_pages_hit", False),
                "limit_hit":     source_meta.get(_src, {}).get("limit_hit", False),
            },
        )

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
    _atomic_write_json(listings_history_path, first_seen)

    # Price history (PRD §FR-3). Sets is_repriced before derived rules and
    # AI run, so downstream fields reflect cross-run price comparison.
    PRICE_HISTORY_MAX_ENTRIES = 365   # ~1 year of daily nightlies
    prices_history_path = web_data_dir / "prices_history.json"
    # json.loads returns Any — guard against a hand-edited file that
    # contains a list / scalar instead of an object. Don't annotate the
    # initial assignment as `: dict`, or Pyright assumes the guard is
    # tautological and reports the body as unreachable.
    try:
        prices_history = (
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

    _atomic_write_json(prices_history_path, prices_history)
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

    # PR-7 — UX-facing derives that need to land BEFORE apply_all() so the
    # source_label rule (which reads source_type == 'off_market') sees them.
    # source_type: based on the listing.source slug (whitelist).
    # previous_price: read from prices_history when is_repriced=True.
    pr7_source_type_counts: dict[str, int] = {}
    pr7_previous_price_populated = 0
    for li in listings:
        st = _derive_source_type(li)
        li.source_type = st
        pr7_source_type_counts[st] = pr7_source_type_counts.get(st, 0) + 1
        prev = _derive_previous_price(li, prices_history)
        if prev is not None:
            li.previous_price = prev
            pr7_previous_price_populated += 1
    print(f"[pr-7] source_type={dict(pr7_source_type_counts)} "
          f"previous_price_populated={pr7_previous_price_populated}")

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

    # PR-8 — NLP enum derives (beachfront_tier, land_type). Run AFTER
    # apply_all so source_label is already populated; these enums are
    # composed from NLP booleans and don't feed back into source_label.
    pr8_beach_tier_counts: dict[str, int] = {}
    pr8_land_type_counts:  dict[str, int] = {}
    for li in listings:
        bt = _derive_beachfront_tier(li)
        if bt is not None:
            li.beachfront_tier = bt
            pr8_beach_tier_counts[bt] = pr8_beach_tier_counts.get(bt, 0) + 1
        lt = _derive_land_type(li)
        if lt is not None:
            li.land_type = lt
            pr8_land_type_counts[lt] = pr8_land_type_counts.get(lt, 0) + 1
    print(f"[pr-8] beachfront_tier={dict(pr8_beach_tier_counts)} "
          f"land_type={dict(pr8_land_type_counts)}")

    # Quality gate — flag listings where the broker hasn't shared price
    # or area. Runs before rank() so the ranker can hard-floor these.
    incomplete_count = 0
    for li in listings:
        if _derive_is_incomplete(li):
            li.is_incomplete = True
            incomplete_count += 1
    print(f"[incomplete] total={incomplete_count}/{len(listings)}")

    # PRD §FR-7.5 — zone median price batch. Computes median price_per_m2
    # per (zone, property_type) bucket from current listings, then sets
    # price_vs_zone_median + price_vs_zone_pct on each scored listing.
    # Pure function of the in-memory catalog — no sidecar; recomputed
    # every run. Listings in buckets below MIN_LISTINGS_PER_ZONE leave
    # both fields as None.
    from automation.zone_medians import compute_and_apply as _zone_medians  # type: ignore
    # Pass history_path explicitly so the helper writes via REPO (which
    # tests mock to tmp_path) rather than its own `__file__`-derived
    # default (which always resolves to the real repo and pollutes
    # web/data/zone_medians_history.jsonl on every local pytest run).
    zm_metrics = _zone_medians(
        listings,
        history_path=REPO / "web" / "data" / "zone_medians_history.jsonl",
    )
    print(f"[zone_medians] buckets={zm_metrics['buckets_computed']} "
          f"scored={zm_metrics['listings_scored']} "
          f"skipped_no_zone={zm_metrics['listings_skipped_no_zone']} "
          f"skipped_inactive={zm_metrics['listings_skipped_inactive']} "
          f"skipped_no_bucket_median={zm_metrics['listings_skipped_no_bucket_median']}")

    # PRD §FR-5.5 — distance fields. dist_airport_km always populates from
    # the per-zone airport table when the zone is known; haversine from
    # lat/lng (when LLM has populated it) takes priority. The other three
    # distance fields stay None until SV reference geometry lands in a
    # follow-up PR.
    from automation.distance_fields import apply_distances as _apply_distances  # type: ignore
    # Same REPO-explicit path treatment as zone_medians above.
    df_metrics = _apply_distances(
        listings,
        history_path=REPO / "web" / "data" / "distance_fields_history.jsonl",
    )
    print(f"[distance_fields] dist_airport_km: "
          f"scored={df_metrics['scored_total']} "
          f"(latlng={df_metrics['scored_from_latlng']}, "
          f"zone_table={df_metrics['scored_from_zone']}) "
          f"unscored={df_metrics['unscored']}")

    # Cross-source duplicate detection — telemetry only (no listings dropped).
    # Answers "are sources cross-posting?" before we sink effort into
    # encuentra24 or other expansion paths. Pure function of the in-memory
    # catalog; sidecar appends one row per nightly with phone-pair count,
    # coord-pair count, and the by-source-pair breakdown.
    from automation.duplicate_detection import detect_duplicates as _detect_duplicates  # type: ignore  # noqa: E402
    dup_metrics = _detect_duplicates(
        listings,
        history_path=REPO / "web" / "data" / "duplicate_detection_history.jsonl",
    )
    print(f"[duplicate_detection] total={dup_metrics['total_listings']} "
          f"centroids={dup_metrics['centroid_count']} "
          f"(suppressing pairs from {dup_metrics['listings_at_centroids']} listings) "
          f"phone_pairs={dup_metrics['phone_pairs']} "
          f"coord_pairs={dup_metrics['coord_pairs']} "
          f"(suppressed centroid={dup_metrics['coord_pairs_suppressed_centroid']} "
          f"area={dup_metrics['coord_pairs_suppressed_area']}) "
          f"flagged={dup_metrics['duplicate_listings_either']} "
          f"({dup_metrics['duplicate_pct']}%) "
          f"unique_estimate={dup_metrics['unique_listings_estimate']}")
    if dup_metrics["by_source_pair"]:
        # Top 5 source-pair buckets so the per-nightly print stays readable
        # even if the long tail grows (defaults to dict, so sort by count).
        top = sorted(
            dup_metrics["by_source_pair"].items(),
            key=lambda kv: kv[1], reverse=True,
        )[:5]
        print(f"[duplicate_detection] top_pairs={dict(top)}")

    # PRD WS2 — single-call DeepSeek enrichment. ONE LLM call per eligible
    # listing returns title + description + usps + latlong together (replacing
    # the previous 3-call OpenAI flow + Mapbox geocoding pass). Idempotent
    # via the per-listing sidecar at web/data/llm_enrichment.json: a listing
    # already in the sidecar is rehydrated without an API call. The
    # eligibility rule — skip if any of {title_canonical,
    # short_description_canonical, reasons_to_buy, lat-or-lng} is set —
    # means listings already enriched by prior runs (or grandfathered with
    # Mapbox lat/lng from the legacy geocoding pass) are not re-processed.
    #
    # Concurrency + soft-fail deadline:
    # - PULPO_LLM_CONCURRENCY=N caps the in-flight API call fan-out.
    # - PULPO_LLM_DEADLINE_SECONDS=N (optional) sets a wall-clock budget
    #   from now: once it elapses no NEW calls go out. In-flight calls
    #   complete; remaining listings are deferred to the next nightly
    #   (the sidecar persists progress, so cache_hits cover them).
    #   The point is that the pipeline always SHIPS — better to commit
    #   partially-enriched data than time out the whole nightly job.
    _llm_deadline_s = _env_float("PULPO_LLM_DEADLINE_SECONDS", 0.0)
    _llm_deadline = (
        _time.monotonic() + _llm_deadline_s if _llm_deadline_s > 0 else None
    )
    llm_metrics = _llm_enrich(
        listings,
        sidecar_path = web_data_dir / "llm_enrichment.json",
        log_path     = web_data_dir / "llm_enrichment_log.jsonl",
        deadline     = _llm_deadline,
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

    # PostHog: LLM cost + throughput. Feeds the "LLM enrichment cost trend"
    # tile and pairs with cost_usd for spend-alert thresholds. Emitted
    # for every code path (no-token / no-package / live) so the dashboard
    # can distinguish "skipped because misconfigured" from "ran cleanly".
    _lat = llm_metrics.get("latency_ms") or []
    _lat_p50 = _lat_p95 = None
    if _lat:
        _srt = sorted(_lat)
        _lat_p50 = _srt[len(_srt) // 2]
        _lat_p95 = _srt[max(0, int(len(_srt) * 0.95) - 1)]
    _ph_capture("llm_enrichment_completed", {
        "eligible":          llm_metrics.get("eligible"),
        "cache_hits":        llm_metrics.get("cache_hits"),
        "enriched":          llm_metrics.get("enriched"),
        "skipped":           llm_metrics.get("skipped"),
        "failed":            llm_metrics.get("failed"),
        "cost_usd":          llm_metrics.get("cost_usd"),
        "latency_p50_ms":    _lat_p50,
        "latency_p95_ms":    _lat_p95,
        "global_error_seen": bool(llm_metrics.get("global_error_seen")),
        "skip_reasons":      llm_metrics.get("skip_reasons"),
        "failure_reasons":   llm_metrics.get("failure_reasons"),
        "skipped_no_token":  bool(llm_metrics.get("skipped_no_token")),
        "skipped_no_package": bool(llm_metrics.get("skipped_no_package")),
    })

    # Deterministic fallback templates (PRD §8.1 + §8.3) for listings the
    # LLM skipped or couldn't enrich. Fills title_canonical and
    # reasons_to_buy from the rule tables; short_description_canonical
    # stays None — that one genuinely needs natural-language generation.
    fb_count = sum(1 for li in listings if _ai_fallback(li))
    print(f"[llm_enrich] fallback_templates_applied={fb_count}")

    # PR-8.5 — OSM Nominatim geocoding fallback for listings still
    # missing lat/lng after the LLM enrichment pass. Free, rate-limited
    # to 1 req/sec, results cached in web/data/geocoding_nominatim.json
    # so subsequent runs are zero-API-call for previously-geocoded
    # zones. Non-fatal: any HTTP error is logged + the listing's
    # lat/lng stay None.
    try:
        from automation.geocoding_nominatim import geocode_listings as _nominatim_geocode
        nominatim_metrics = _nominatim_geocode(
            listings,
            cache_path = web_data_dir / "geocoding_nominatim.json",
        )
        print(f"[nominatim] scanned={nominatim_metrics['scanned']} "
              f"already_geocoded={nominatim_metrics['skipped_already_geocoded']} "
              f"no_query={nominatim_metrics['skipped_no_query']} "
              f"cache_hits={nominatim_metrics['cache_hits']} "
              f"api_calls={nominatim_metrics['api_calls']} "
              f"api_hits={nominatim_metrics['api_hits']} "
              f"api_misses={nominatim_metrics['api_misses']}")
    except Exception as _e:
        print(f"[nominatim] failed (non-fatal): {_e!r}")

    # PR-8.5 — re-run distance fields AFTER LLM + Nominatim so
    # haversine fires on the freshly-geocoded listings. The first
    # apply_distances pass earlier in the pipeline used zone-table
    # fallback for listings without lat/lng; this second pass upgrades
    # them to haversine and ALSO populates dist_beach_km (PR-8.5
    # addition; needs lat/lng — no zone fallback for the beach).
    try:
        from automation.distance_fields import apply_distances as _redo_distances
        df2 = _redo_distances(
            listings,
            history_path=REPO / "web" / "data" / "distance_fields_history.jsonl",
        )
        print(f"[distance_fields:final] dist_airport_km scored={df2['scored_total']} "
              f"(latlng={df2['scored_from_latlng']}, "
              f"zone_table={df2['scored_from_zone']}) "
              f"unscored={df2['unscored']} | "
              f"dist_beach_km scored={df2['scored_beach']} "
              f"median={df2['median_dist_beach_km']}")
    except Exception as _e:
        print(f"[distance_fields:final] failed (non-fatal): {_e!r}")

    # Unmapped-beach detector — surface listings whose copy claims
    # walking-distance / beachfront but whose haversine to the nearest
    # NAMED_BEACHES entry is > 5km. Two failure modes: a stale-prompt
    # regression (LLM placed lat/lng inland despite the cue) OR a
    # genuinely unmapped beach (we should append to NAMED_BEACHES in
    # automation/distance_fields.py — see docs/named-beach-reference.md).
    try:
        from automation.unmapped_beach_detector import detect_unmapped_beach_clusters
        ub = detect_unmapped_beach_clusters(listings)
        if ub["suspect_count"]:
            print(f"[unmapped_beaches] suspects={ub['suspect_count']} "
                  f"clusters={ub['cluster_count']}")
            for c in ub["top_clusters"][:5]:
                print(f"  cluster ({c['lat']}, {c['lng']}) "
                      f"count={c['count']} "
                      f"median_dist_beach_km={c['median_dist_beach_km']} "
                      f"sample_ids={c['sample_ids']}")
        else:
            print("[unmapped_beaches] suspects=0 (no coastal-claim listings far from named beaches)")
    except Exception as _e:
        print(f"[unmapped_beaches] failed (non-fatal): {_e!r}")

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
          f"elapsed={photo_results['elapsed_s']:.1f}s "
          f"hero_eligible={photo_results.get('hero_eligible', 0)} "
          f"card_eligible={photo_results.get('card_eligible', 0)}")
    # Plan v2 — parallel hi-res pipeline. Runs immediately after the
    # existing hero step with its own time budget. Gated on
    # PULPO_HIRES_ENABLED=1 (default off); when disabled, no-ops in
    # microseconds. Failures here are isolated to the hires layer and
    # never break the rest of the nightly.
    _download_hires_photos(ranked_pre, REPO)
    ranked = ranked_pre

    # IA-axis derives — master_category × subcategory + discovery_tags
    # + star_rating. Runs AFTER rank() so star_rating + the top_rated
    # discovery tag can read rank_score, and AFTER the second
    # apply_distances pass so master_category sees the haversine-derived
    # dist_beach_km on listings that needed Nominatim geocoding.
    ia_bucket_counts: dict[str, int] = {}
    ia_tag_counts:    dict[str, int] = {}
    ia_star_counts:   dict[float, int] = {}
    ia_master_counts: dict[str, int] = {"beach": 0, "lake": 0, "none": 0}
    for li in ranked:
        out = _apply_ia_derives(li)
        mc = out["master_category"]
        sub = out["subcategory"]
        bucket_key = f"{mc or 'none'}_{sub or 'none'}"
        ia_bucket_counts[bucket_key] = ia_bucket_counts.get(bucket_key, 0) + 1
        ia_master_counts[mc or "none"] = ia_master_counts.get(mc or "none", 0) + 1
        for tag in out["discovery_tags"]:
            ia_tag_counts[tag] = ia_tag_counts.get(tag, 0) + 1
        ia_star_counts[out["star_rating"]] = ia_star_counts.get(out["star_rating"], 0) + 1
    print(f"[ia_derives] master={dict(ia_master_counts)} "
          f"buckets={dict(sorted(ia_bucket_counts.items()))} "
          f"tags={dict(sorted(ia_tag_counts.items()))} "
          f"stars={dict(sorted(ia_star_counts.items()))}")

    # PR-7 — population-rate regression guard. Read the previous run's
    # last_updated.json BEFORE we overwrite it, compare derived-field
    # population rates against the new ones, and fail the run if any
    # field's rate dropped > 20% (relative). Catches NLP-keyword
    # regressions / scraper-config mistakes before they hit production.
    #
    # Override: set PULPO_ALLOW_POPULATION_REGRESSION=1 to downgrade
    # to a warning. Useful when intentionally tightening a rule that
    # makes a field stricter (and the temporary drop is expected).
    new_rates = compute_derived_population(ranked)
    prev_meta_path = web_data_dir / "last_updated.json"
    prev_meta = None
    if prev_meta_path.exists():
        try:
            prev_meta = json.loads(prev_meta_path.read_text())
        except Exception as _e:
            print(f"[regression-guard] could not parse previous last_updated.json: {_e!r}")
    regressions = check_population_regression(prev_meta, new_rates, threshold=0.20)
    if regressions:
        # PostHog: emit BEFORE SystemExit so a failing run still reports.
        # atexit flush in posthog_client guarantees the event ships before
        # the process dies.
        _ph_capture("regression_guard_triggered", {
            "regression_count": len(regressions),
            "regressions":      regressions[:20],   # cap payload size
            "override_active":  _env_bool("PULPO_ALLOW_POPULATION_REGRESSION", False),
        })
        msg = "[regression-guard] population-rate drops exceeded 20% threshold:\n  " + "\n  ".join(regressions)
        if _env_bool("PULPO_ALLOW_POPULATION_REGRESSION", False):
            print(f"{msg}\n[regression-guard] override active — continuing.")
        else:
            print(msg, file=sys.stderr)
            print(
                "[regression-guard] failing run. Set PULPO_ALLOW_POPULATION_REGRESSION=1 "
                "to override (use sparingly — this guard exists to catch silent NLP/keyword regressions).",
                file=sys.stderr,
            )
            raise SystemExit(2)
    else:
        print(f"[regression-guard] population rates OK (new={new_rates})")

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

    # PostHog: pipeline run completed. Feeds the "Pipeline run volume"
    # and "Listing pipeline funnel" dashboards. Funnel events chain to
    # pipeline_started via the shared distinct_id (`pipeline:nightly`),
    # so PostHog stitches them by run order; per-run drill-down uses
    # the run_id property propagated by posthog_client.set_run_id.
    _ph_capture("pipeline_completed", {
        "ranked_count":            len(ranked),
        "dropped":                 dropped,
        "errors_count":            len(errors),
        "sources_succeeded":       sum(1 for s in sources if s.strip() not in source_errors and per_source_count.get(s.strip(), 0) > 0),
        "sources_failed":          len([s for s in sources if s.strip() in source_errors]),
        "duration_s":              round((finished - started).total_seconds(), 2),
        "offline":                 offline,
        "fixture_fallback_active": fixture_fallback_active,
    })

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

    # SEO sitemap. Sections + per-listing entries (excluding off-market
    # + sold). Non-fatal: a missing sitemap doesn't break the site,
    # only delays reindexing on the next Search Console crawl.
    try:
        from automation.sitemap import write_sitemap
        web_dir = web_data_dir.parent  # web/
        n_urls = write_sitemap(web_dir / "sitemap.xml", ranked)
        print(f"[sitemap] wrote {n_urls} urls to web/sitemap.xml")
    except Exception as _e:
        print(f"[sitemap] failed (non-fatal): {_e!r}")

    # Cron-stable Discover hero pool. Writes web/data/featured.json
    # with { tier, pool: [...], ... }. Non-fatal: a missing file just
    # lets the FE fall back to a client-side pick.
    try:
        from pulpo.featured_listing import write_featured_json
        pool = write_featured_json(web_data_dir / "featured.json", ranked)
        if pool is not None:
            top = pool.entries[0]
            print(f"[featured] tier={pool.tier} pool_size={len(pool.entries)} "
                  f"top={top.listing_id} rank={top.rank_score:.1f} "
                  f"photo_quality={top.hero_photo_quality_score}")
        else:
            print("[featured] no eligible listing — featured.json not written")
    except Exception as _e:
        print(f"[featured] failed (non-fatal): {_e!r}")

    phase_print_summary(
        finished=finished, ranked_count=len(ranked),
        sources=sources, errors=errors, offline=offline,
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())
