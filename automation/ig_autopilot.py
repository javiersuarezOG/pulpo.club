"""ig_autopilot.py — the self-running IG post generator (local-voice).

Keeps `web/data/ig_queue.json` topped up with **approved, scheduled**
posts so the hourly publisher (automation/ig_publish.py) can post on its
own.  The operator's only lever is Skip (in /admin/ig) + the IG_PAUSED
kill switch.

Content comes from the story engine (``automation/ig_story_series.py``):
**inspire, don't sell.** Every post is a cinematic *story* — a real
listing's brand-safe hero photo + one poetic line — from a 14-strong library
that rotates with no repeat inside a cycle, rendered via
``automation/ig_campaign_poster.py``.  Each post shows a real listing,
picked highest-rank-first and not re-featured recently; the ONLY photo shown
is the pipeline-vetted hero (brand-safety: no broker logos / phone numbers).

Design: the content engine is pure (decides what each post says + shows);
this module downloads the listing photos, renders the slides, and shapes
the queue item.  Renderers + photo-preparer are injectable so tests run
offline with skip_render.

CLI (run by .github/workflows/ig-autopilot.yml on a daily cron):
    python3 -m automation.ig_autopilot --lookahead 7 --cadence-days 1

Autopilot NEVER flips IG_PAUSED and NEVER posts — it only queues.
Posting stays with the publisher cron, which the operator gates with
IG_PAUSED.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

# Render via the campaign slide renderer (branded 1080×1350 slides); get
# each post's copy + slide plan from the local-voice content engine.
from automation.ig_campaign_poster import render_slide as _render_slide
from automation.ig_campaign_poster import CATEGORY_COLORS, INSPIRACION
from automation.ig_caption_lint import check as _lint_check
from automation import ig_story_series as _series

DEFAULT_QUEUE = Path("web/data/ig_queue.json")
DEFAULT_CANDIDATES = Path("web/data/ig_candidates.json")
DEFAULT_RANKED = Path("web/data/ranked.json")
DEFAULT_ASSETS_ROOT = Path("web/data/ig_assets/autopilot")
DEFAULT_PUBLISH_HOUR_UTC = 1   # 19:00 CST ≈ 01:00 UTC next day

# ── helpers ───────────────────────────────────────────────────────────

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _ranked_index(ranked: list) -> dict:
    """Key by `{source}__{source_id}` == candidate.listing_id."""
    return {f"{li.get('source')}__{li.get('source_id')}": li for li in ranked}


def _used_listing_ids(items: list, recent: int = 12) -> set:
    """listing_ids featured by the most recent `recent` queue items, so
    the autopilot doesn't re-feature the same land two posts running."""
    used: set = set()
    for it in items[-recent:]:
        if it.get("primary_listing_id"):
            used.add(it["primary_listing_id"])
        for lid in it.get("listing_ids") or []:
            used.add(lid)
    return used


def _featured_listing_ids(items: list) -> set:
    """Every listing featured by a non-skipped queue item (posted or
    upcoming). Used to spread photo coverage across listings/zones rather
    than re-featuring the same lot with a different frame."""
    out: set = set()
    for it in items:
        if it.get("skipped"):
            continue
        if it.get("primary_listing_id"):
            out.add(it["primary_listing_id"])
    return out


# A "true value gem" (Javi, 2026-08-02): the only listings allowed to post
# with a poor photo (via humor copy). Exceptional value = priced well below
# its zone. Candidate carries price_vs_zone_pct (negative = under zone).
GEM_ZONE_DISCOUNT = -25.0        # ≥25% below the zone price
POOR_PHOTO_MAX_SHARE = 0.20      # ≤20% of the feed may be poor-photo gems


def is_value_gem(candidate: dict) -> bool:
    pct = candidate.get("price_vs_zone_pct")
    return isinstance(pct, (int, float)) and pct <= GEM_ZONE_DISCOUNT


def _poor_share(items: list) -> float:
    live = [it for it in items if it.get("primary_listing_id") and not it.get("skipped")]
    if not live:
        return 0.0
    poor = sum(1 for it in live if it.get("photo_tier") == "poor")
    return poor / len(live)


def _is_coastal(listing: dict) -> bool:
    """Coastal enough for a sea/coast story line: an ocean view or within
    ~2 km of the beach."""
    if listing.get("has_ocean_view"):
        return True
    d = listing.get("dist_beach_km")
    return d is not None and d <= 2.0


def _next_day(items: list) -> int:
    return (max((it.get("day") or 0) for it in items) + 1) if items else 101


def _future_approved_count(items: list, now: datetime) -> int:
    """Approved, unposted, not-skipped, scheduled in the future."""
    n = 0
    for it in items:
        if it.get("approved") and not it.get("posted") and not it.get("skipped"):
            sched = _parse_iso(it.get("scheduled_for"))
            if sched and sched > now:
                n += 1
    return n


def _next_slot(items: list, now: datetime, cadence_days: int) -> datetime:
    """Latest scheduled (posted or future) + cadence, floored at
    now + cadence so the operator always has a skip window.

    Skipped items are ignored: skipping a post frees its slot, so the next
    post should backfill it rather than schedule after the freed date (this
    is what caused the Jul 26–31 gap when the sales posts were skipped)."""
    latest = None
    for it in items:
        if it.get("skipped"):
            continue
        sched = _parse_iso(it.get("scheduled_for"))
        if sched and (latest is None or sched > latest):
            latest = sched
    base = latest if latest and latest > now else now
    nxt = base + timedelta(days=cadence_days)
    return nxt.replace(hour=DEFAULT_PUBLISH_HOUR_UTC, minute=0, second=0, microsecond=0)


# Hero-photo quality floor. Brand-safety + quality gate: the photo-gate
# (ig_photo_gate) filters broker watermarks but NOT Google-Maps satellite
# screenshots or third-party billboards in the scene. Empirically those
# score BELOW 100 on hero_photo_quality_score (a Google-Maps screenshot
# scored 80, a Davivienda-billboard shot 90) while clean land photos score
# 100. Gating to 100 keeps the autonomous feed brand-safe without a
# per-listing blocklist. The human Skip in /admin/ig is the backstop for
# anything that still slips through.
MIN_PHOTO_QUALITY = 100


# ── beauty gate (Javier, 2026-07-25 — "perfect pics") ─────────────────
#
# Brand-safe is not enough for an INSPIRE feed: the pipeline still lets
# through technically-clean-but-dull land shots (it even flags them
# ``hires_aesthetic_issues: ['uninteresting']``). The story feed draws
# only from listings whose hero is *clean AND scenic* — ocean/mountain view
# or genuinely coastal — with a graceful fallback to merely-clean so the
# generator never strands. The join to the ranked listing carries these
# fields (candidates don't), so beauty is scored via ranked_index.

def _beauty(listing: dict) -> tuple[bool, float]:
    """Return (is_clean, scenic_score) for a listing's hero.

    is_clean  → no ``hires_aesthetic_issues`` (drops 'uninteresting' etc.).
    scenic    → ocean view (3) + coastal ≤1km (2) + mountain view (1)."""
    clean = not (listing.get("hires_aesthetic_issues") or [])
    score = 0.0
    if listing.get("has_ocean_view"):
        score += 3
    if (listing.get("dist_beach_km") if listing.get("dist_beach_km") is not None else 99) <= 1.0:
        score += 2
    if listing.get("has_mountain_view"):
        score += 1
    return clean, score


def _pick_candidate(
    candidates: list, used: set, ranked_index: Optional[dict] = None
) -> Optional[dict]:
    """Pick the best unused candidate with a top-quality hero.

    When ``ranked_index`` is given (the story feed), apply the beauty gate:
    prefer clean+scenic listings, fall back to clean, then to any — so the
    cover is always as beautiful as the inventory allows, never dull-by-
    default, but the generator still never strands."""
    quality = [
        c for c in candidates
        if (c.get("hero_photo_quality_score") or 0) >= MIN_PHOTO_QUALITY
    ]
    base = quality or candidates          # never strand the generator
    pool = [c for c in base if c.get("listing_id") not in used] or base
    if not pool:
        return None

    if ranked_index is None:
        return max(pool, key=lambda c: c.get("rank_score") or c.get("rank") or 0)

    def _b(c):
        return _beauty(ranked_index.get(c.get("listing_id"), {}))

    scenic_clean = [c for c in pool if (lambda cl, s: cl and s > 0)(*_b(c))]
    clean = [c for c in pool if _b(c)[0]]
    tier = scenic_clean or clean or pool
    # within the chosen tier: most scenic first, then highest rank
    return max(tier, key=lambda c: (_b(c)[1], c.get("rank_score") or c.get("rank") or 0))


# ── listing photos (real, resolution-checked, 1080×1350) ──────────────
#
# Every post shows real photos of the listing at good resolution. Broker
# photos vary wildly (letterbox 1200×554, hi-res 4000×1848, tiny 661×960),
# so we download each, reject anything too small to look crisp, and
# normalise onto a 1080×1350 (4:5 — matches the slide) branded canvas:
# cover-crop when it fills without notable upscale, else fit + pad on cream.
# These become the `img` backgrounds the slide renderer composites the
# ribbon / hook / price pill over.
#
# Brand safety: only the hero photo is quality-scored (the q100 gate); the
# extra photos come from the ACCEPTED photo_urls set. The human Skip in
# /admin/ig — with the full-carousel viewer — is the backstop for any
# brand/quality issue in a non-hero photo.

_SLIDE_W, _SLIDE_H = 1080, 1350
_PAD_BG = (244, 239, 230)          # cream (--color-bg-cream)
_MIN_COVER_UPSCALE = 1.15          # fill the frame only if upscale ≤ this
_MIN_FIT_WIDTH = 1000              # else must be ≥ this wide to stay crisp
PHOTOS_PER_POST = 3                # ideal — enough for the richest format


def _download_image(url: str, timeout: int = 20):
    from PIL import Image
    req = urllib.request.Request(url, headers={"User-Agent": "pulpo-ig-autopilot"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return Image.open(io.BytesIO(data)).convert("RGB")


def _fit_slide(img):
    """Normalise a PIL image to a crisp 1080×1350 slide, or None if it's
    too low-res to look good."""
    from PIL import Image
    w, h = img.size
    cover = max(_SLIDE_W / w, _SLIDE_H / h)
    if cover <= _MIN_COVER_UPSCALE:
        nw, nh = round(w * cover), round(h * cover)
        img = img.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - _SLIDE_W) // 2, (nh - _SLIDE_H) // 2
        return img.crop((left, top, left + _SLIDE_W, top + _SLIDE_H))
    if w >= _MIN_FIT_WIDTH:
        s = _SLIDE_W / w
        nw, nh = _SLIDE_W, round(h * s)
        if nh > _SLIDE_H:                      # very tall → fit height instead
            s = _SLIDE_H / h
            nw, nh = round(w * s), _SLIDE_H
        img = img.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (_SLIDE_W, _SLIDE_H), _PAD_BG)
        canvas.paste(img, ((_SLIDE_W - nw) // 2, (_SLIDE_H - nh) // 2))
        return canvas
    return None                                # too small to look sharp


# ── beautiful-cover selection (the listing's OWN best fresh photo) ────
#
# Javier, 2026-07-26: the cover must be a GORGEOUS photo OF the listing
# (same location, guaranteed), never one used before, no repeats. So for
# each candidate we score every brand-safe, not-yet-used photo and take the
# most beautiful — and if the best isn't good enough, we skip the listing
# entirely (quality over cadence). ``used_urls`` is the no-repeat / never-
# reused ledger (web/data/ig_used_photos.json).

DEFAULT_USED_PHOTOS = Path("web/data/ig_used_photos.json")
_COVER_SCAN_CAP = 8            # photos to score per listing (network budget)


def _ordered_fresh_urls(listing: dict, used_urls: frozenset) -> list:
    """Brand-safe photo URLs (order_photo_indices: hero-first, rejected
    frames dropped) minus anything already used."""
    from automation.ig_photo_gate import order_photo_indices
    all_urls = listing.get("photo_urls") or []
    idxs = order_photo_indices(listing)
    urls = [all_urls[i] for i in idxs if 0 <= i < len(all_urls)] or all_urls
    return [u for u in urls if u not in used_urls]


PHOTOS_PER_POST = 3           # richer format uses up to 3 real photos (Javi 08-08)


def select_beautiful_photos(
    listing: dict,
    assets_dir: Path,
    slug: str,
    *,
    used_urls: frozenset = frozenset(),
    fetcher: Callable = _download_image,
    scorer: Callable = None,
    want: int = PHOTOS_PER_POST,
    cap: int = _COVER_SCAN_CAP,
) -> Optional[list]:
    """Download + score the listing's brand-safe, unused photos; save + return
    the BEST ``want`` as a list of ``(web_relative_path, url, score)`` (best
    first) — or None only when the listing has no usable photo at all.

    The richer format (Javi, 2026-08-08) uses up to 3 real photos so it isn't
    one photo + five gradient cards. The tier decision stays with the caller
    and uses the best photo's score: a great cover posts as-is; a poor cover
    posts ONLY if the listing is a true value gem (with humor copy)."""
    from automation.ig_photo_beauty import score_photo
    scorer = scorer or score_photo

    scored = []                                        # (score, img, url)
    for url in _ordered_fresh_urls(listing, used_urls)[:cap]:
        try:
            img = fetcher(url)
        except Exception as e:                         # noqa: BLE001
            print(f"[ig_autopilot] photo fetch skip ({e}): {url[:80]}", file=sys.stderr)
            continue
        scored.append((scorer(img), img, url))
    if not scored:
        return None
    scored.sort(key=lambda t: -t[0])                   # most beautiful first
    assets_dir.mkdir(parents=True, exist_ok=True)
    out: list = []
    for sc, img, url in scored[:want]:
        slide = _fit_slide(img)
        if slide is None:
            continue
        fname = f"photo_{len(out) + 1}.jpg"
        slide.save(assets_dir / fname, "JPEG", quality=90, optimize=True)
        out.append((f"web/data/ig_assets/autopilot/{slug}/{fname}", url, sc))
    if not out:
        return None
    print(f"[ig_autopilot] photos={len(out)} beauty={out[0][2]:.0f} {out[0][1][:60]}")
    return out


def _predict_photos(listing, assets_dir, slug, *, used_urls=frozenset(), want=PHOTOS_PER_POST, **_) -> Optional[list]:
    """Offline stand-in for select_beautiful_photos (no download / no score) —
    used by --skip-render dry runs and tests. Returns the first fresh brand-safe
    urls with a nominal 'great' score (80)."""
    urls = _ordered_fresh_urls(listing, used_urls)[:want]
    if not urls:
        return None
    return [(f"web/data/ig_assets/autopilot/{slug}/photo_{i + 1}.jpg", u, 80.0)
            for i, u in enumerate(urls)]


def _predict_cover(listing, assets_dir, slug, *, used_urls=frozenset(), **_) -> Optional[tuple]:
    """Deprecated single-photo offline stub (kept for any external caller)."""
    urls = _ordered_fresh_urls(listing, used_urls)
    if not urls:
        return None
    return f"web/data/ig_assets/autopilot/{slug}/photo_1.jpg", urls[0], 80.0


# ── item construction ─────────────────────────────────────────────────

def build_item(
    *,
    day: int,
    story: dict,                    # a STORIES entry (ig_story_series)
    candidate: dict,
    listing: dict,
    scheduled_for: str,
    assets_root: Path,
    skip_render: bool,
    used_urls: frozenset = frozenset(),
    allow_poor: bool = True,
    slide_renderer: Callable = _render_slide,
    photo_selector: Callable = select_beautiful_photos,
) -> Optional[dict]:
    """Build one approved queue item. EVERY post has a real hero photo (the
    listing's own best, unused, brand-safe frame). Tiering (Javi, 2026-08-02):
    a great photo (score ≥ GORGEOUS_MIN) posts as-is; a poor photo posts ONLY
    when the listing is a true value gem AND the <20% poor budget allows
    (``allow_poor``) — with Salvadoran-humor copy that owns the bad photo;
    otherwise the listing is skipped and the caller tries another."""
    from automation.ig_photo_beauty import GORGEOUS_MIN
    sid = story["id"]
    slug = f"d{day:03d}__{sid}"
    assets_dir = assets_root / slug

    sel = photo_selector(listing, assets_dir, slug, used_urls=used_urls)
    if not sel:
        print(f"[ig_autopilot] d{day} skip {candidate.get('listing_id')}: no usable photo",
              file=sys.stderr)
        return None
    photos = [p for p, _u, _s in sel]        # up to 3, most-beautiful first
    cover_url = sel[0][1]
    score = sel[0][2]                        # tier on the best (cover) photo
    used_now = [u for _p, u, _s in sel]      # every photo used → ledger

    humor = False
    if score < GORGEOUS_MIN:
        # poor cover → only a true value gem earns a slot, and only within
        # the <20% poor budget; otherwise skip and try a better listing.
        if not is_value_gem(candidate) or not allow_poor:
            print(f"[ig_autopilot] d{day} skip {candidate.get('listing_id')}: "
                  f"poor photo (beauty={score:.0f}), not a gem/over budget", file=sys.stderr)
            return None
        humor = True

    post = _series.build_post(story, candidate, listing, photos, humor=humor)
    if post is None:
        return None

    color = CATEGORY_COLORS.get(post["color_key"], INSPIRACION)
    rendered: list = []
    for i, spec in enumerate(post["slides"]):
        # JPEG, not PNG: photographic slides as PNG are 2–3 MB and bloated
        # the Vercel deploy past its size limit (2026-07-26 incident).
        rel = f"web/data/ig_assets/autopilot/{slug}/slide_{i + 1}.jpg"
        if not skip_render:
            slide_renderer(spec, color, assets_dir / f"slide_{i + 1}.jpg")
        rendered.append(rel)

    caption = post["caption"]
    violations = _lint_check(caption)
    return {
        "day": day,
        "shelf": "autopilot_story",
        "format": "story",
        "story_id": sid,
        "emotion": post.get("emotion"),
        "selector": "autopilot",
        "color_key": post["color_key"],
        # kept for the review widget's summary line (poster_type · palette);
        # autopilot items normally render in the console, not review.
        "poster_type": sid,
        "palette": post["color_key"],
        "scheduled_for": scheduled_for,
        "assets_dir": f"web/data/ig_assets/autopilot/{slug}",
        # poster_path = cover (slide 1); carousel = the rest — matches what
        # the publisher (_slide_urls) and the console (_slidesOf) expect.
        "poster_path": rendered[0],
        "poster_overrides": {},
        "caption": caption,
        "comment": post["comment"],
        "lint_violations": violations,
        "caption_status": "clean" if not violations else "lint_failed",
        "carousel_photo_paths": rendered[1:],
        "listing_ids": [candidate.get("listing_id")],
        "primary_listing_id": candidate.get("listing_id"),
        # the exact photos used — all appended to the no-repeat ledger so
        # none is reused again. cover_photo_url = the hero (back-compat).
        "cover_photo_url": cover_url,
        "cover_photo_urls": used_now,
        # photo tier for the <20%-poor budget + observability.
        "photo_tier": "poor" if humor else "great",
        "cover_beauty": round(score, 1),
        "humor": humor,
        "status": "scheduled",
        # Auto-approve model: posts publish on schedule; operator only skips.
        "approved": True,
        "posted": False,
        "posted_at": None,
        "posted_media_id": None,
    }


def topup(
    queue: dict,
    candidates: list,
    ranked_index: dict,
    *,
    now: datetime,
    lookahead: int,
    cadence_days: int,
    assets_root: Path,
    skip_render: bool,
    used_urls: Optional[set] = None,
    slide_renderer: Callable = _render_slide,
    photo_selector: Callable = select_beautiful_photos,
) -> list:
    """Append approved items until `lookahead` future posts exist.
    Returns the list of newly-added items (also appended to queue).

    Stories rotate deterministically over the sequence of autopilot posts
    (see ig_story_series.story_for_index) — no repeat within a 14-post cycle.
    A candidate with no gorgeous, unused, brand-safe photo is skipped and the
    next-best listing is tried instead.  ``used_urls`` (the never-reuse
    ledger) grows as covers are chosen, so no photo is used twice."""
    items = queue.setdefault("items", [])
    added: list = []
    failed: set = set()
    used_photos: set = set(used_urls or set())
    # seed the ledger with every photo already used in the queue (prior runs)
    for it in items:
        for u in it.get("cover_photo_urls") or ([it["cover_photo_url"]] if it.get("cover_photo_url") else []):
            used_photos.add(u)
    guard = 0
    max_iters = lookahead * 6 + 4          # room to skip thin listings
    while _future_approved_count(items + added, now) < lookahead and guard < max_iters:
        guard += 1
        # Photo COVERAGE: spread across listings — exclude every listing
        # already featured anywhere (posted or upcoming), not just the recent
        # window, so we don't re-feature the same lot while others qualify.
        # _pick_candidate falls back to the full pool if that empties.
        used_listings = _featured_listing_ids(items + added) | failed
        cand = _pick_candidate(candidates, used_listings, ranked_index)
        if cand is None:
            print("[ig_autopilot] no candidates available — stopping topup", file=sys.stderr)
            break
        day = _next_day(items + added)
        listing = ranked_index.get(cand.get("listing_id"), {})
        # Candidate-first, then a story that FITS the place: coast/sea lines
        # only on coastal listings (no "caminó esta costa" over an inland
        # lot). Least-recently-used → cycles the fitting set before repeating.
        recent_stories = [it.get("story_id") for it in reversed(items + added) if it.get("story_id")]
        story = _series.pick_story(recent_stories, _is_coastal(listing))
        scheduled = _next_slot(items + added, now, cadence_days).isoformat()
        # <20% poor-photo budget: only allow a poor-photo gem while the feed's
        # poor share is under the cap.
        allow_poor = _poor_share(items + added) < POOR_PHOTO_MAX_SHARE
        item = build_item(
            day=day, story=story, candidate=cand, listing=listing,
            scheduled_for=scheduled, assets_root=assets_root,
            skip_render=skip_render, used_urls=frozenset(used_photos),
            allow_poor=allow_poor,
            slide_renderer=slide_renderer, photo_selector=photo_selector,
        )
        if item is None:                    # no gorgeous unused photo → try another
            failed.add(cand.get("listing_id"))
            continue
        for u in item.get("cover_photo_urls") or []:   # never reuse these photos
            used_photos.add(u)
        added.append(item)
        print(
            f"[ig_autopilot] queued d{day} story={story['id']} coast={_is_coastal(listing)} "
            f"listing={cand.get('listing_id')} scheduled={scheduled} "
            f"slides={1 + len(item['carousel_photo_paths'])} "
            f"caption_status={item['caption_status']}"
        )
    items.extend(added)

    # Coverage visibility: how much gorgeous, unfeatured inventory is left.
    featured = _featured_listing_ids(items)
    runway = sum(1 for c in candidates if c.get("listing_id") not in featured)
    print(f"[ig_autopilot] photo coverage: {runway} unfeatured candidate(s) remain "
          f"of {len(candidates)} (added {len(added)} this run)")
    if len(added) < lookahead:
        print(f"[ig_autopilot] WARNING: only filled {len(added)}/{lookahead} — "
              f"gorgeous/unused photo inventory is thin", file=sys.stderr)
    return added


# ── CLI ───────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Top up the IG queue with approved, scheduled posts.")
    p.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    p.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    p.add_argument("--ranked", type=Path, default=DEFAULT_RANKED)
    p.add_argument("--assets-root", type=Path, default=DEFAULT_ASSETS_ROOT)
    p.add_argument("--lookahead", type=int, default=7, help="Keep this many future posts queued (a week at daily cadence).")
    p.add_argument("--cadence-days", type=int, default=1)
    p.add_argument("--skip-render", action="store_true", help="Skip Playwright (queue only).")
    p.add_argument("--used-photos", type=Path, default=DEFAULT_USED_PHOTOS,
                   help="Ledger of photo URLs already used as covers (never reused).")
    p.add_argument("--now", default=None, help="ISO 'now' override (tests).")
    args = p.parse_args(argv)

    now = _parse_iso(args.now) or datetime.now(timezone.utc)

    if not args.candidates.exists():
        print(f"[ig_autopilot] candidates missing: {args.candidates}", file=sys.stderr)
        return 2
    candidates = json.loads(args.candidates.read_text(encoding="utf-8")).get("candidates", [])
    ranked = json.loads(args.ranked.read_text(encoding="utf-8")) if args.ranked.exists() else []
    ranked_index = _ranked_index(ranked)

    # Read the queue in EITHER shape (dict or the bare list a manual staging
    # run left behind) and work on a dict (2026-08-02 fix).
    from automation import ig_queue_io
    _items, _meta = ig_queue_io.load(args.queue)
    queue = ig_queue_io.as_dict(_items, _meta)

    # Never-reuse ledger: every photo ever used as a cover.
    used_urls: set = set()
    if args.used_photos.exists():
        try:
            used_urls = set(json.loads(args.used_photos.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            used_urls = set()

    added = topup(
        queue, candidates, ranked_index,
        now=now, lookahead=args.lookahead, cadence_days=args.cadence_days,
        assets_root=args.assets_root, skip_render=args.skip_render, used_urls=used_urls,
        # --skip-render is an offline mode → don't hit the network for photos.
        photo_selector=_predict_photos if args.skip_render else select_beautiful_photos,
    )

    args.queue.parent.mkdir(parents=True, exist_ok=True)
    args.queue.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Persist the ledger: prior + every photo chosen this run.
    for it in added:
        for u in it.get("cover_photo_urls") or ([it["cover_photo_url"]] if it.get("cover_photo_url") else []):
            used_urls.add(u)
    args.used_photos.parent.mkdir(parents=True, exist_ok=True)
    args.used_photos.write_text(json.dumps(sorted(used_urls), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[ig_autopilot] added {len(added)} item(s); queue now {len(queue['items'])} total; "
          f"ledger {len(used_urls)} photos → {args.queue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
