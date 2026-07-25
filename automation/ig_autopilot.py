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


def prepare_listing_photos(
    listing: dict,
    assets_dir: Path,
    slug: str,
    *,
    want: int = PHOTOS_PER_POST,
    fetcher: Callable = _download_image,
) -> list:
    """Download + normalise up to `want` good listing photos. Returns the
    list of web-relative paths (may be shorter than `want`; empty when the
    listing has no usable photos).

    Brand safety (Javier, 2026-07-25 — "no broker logos, tel numbers,
    perfect pics"): photos are taken in the gate's VETTED order —
    ``order_photo_indices`` leads with the quality-scored hero and DROPS any
    frame the per-photo picker rejected (broker flyers, logos, text
    overlays: ``photo_urls_rejected``). This is the fix for the day-218
    broker-phone cover, which used raw ``photo_urls[0]`` and bypassed all of
    that. Falls back to raw order only when the listing predates the
    ordering fields (no photos_count)."""
    from automation.ig_photo_gate import order_photo_indices
    all_urls = listing.get("photo_urls") or []
    idxs = order_photo_indices(listing)
    urls = [all_urls[i] for i in idxs if 0 <= i < len(all_urls)] or all_urls
    out: list = []
    assets_dir.mkdir(parents=True, exist_ok=True)
    for url in urls:
        if len(out) >= want:
            break
        try:
            img = fetcher(url)
            slide = _fit_slide(img)
        except Exception as e:                                  # noqa: BLE001
            print(f"[ig_autopilot] photo skip ({e}): {url[:80]}", file=sys.stderr)
            continue
        if slide is None:
            continue
        idx = len(out) + 1
        fname = f"photo_{idx}.jpg"
        slide.save(assets_dir / fname, "JPEG", quality=88, optimize=True)
        out.append(f"web/data/ig_assets/autopilot/{slug}/{fname}")
    return out


def _predict_photos(listing: dict, assets_dir: Path, slug: str, want: int = PHOTOS_PER_POST, **_) -> list:
    """Offline stand-in for prepare_listing_photos (no download / no I/O) —
    used by --skip-render dry runs and tests.  Predicts up to `want` paths
    from the listing's photo_urls count."""
    n = min(want, len(listing.get("photo_urls") or []))
    return [
        f"web/data/ig_assets/autopilot/{slug}/photo_{i + 1}.jpg" for i in range(n)
    ]


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
    slide_renderer: Callable = _render_slide,
    photo_preparer: Callable = prepare_listing_photos,
) -> Optional[dict]:
    """Build one approved queue item for `story`: the cinematic cover (using
    the brand-safe hero photo) + a photo-free brand closer, an inspirational
    caption, and a first comment that whispers the listing details. Returns
    None when the listing yields no usable (brand-safe) photo."""
    sid = story["id"]
    slug = f"d{day:03d}__{sid}"
    assets_dir = assets_root / slug

    # ONLY the vetted hero (brand-safe ordering leads with it; rejected
    # frames dropped). want=1 so no second, less-vetted frame is ever even
    # downloaded — if the hero URL is dead we skip the listing entirely
    # rather than fall back to a photo that could carry a broker mark.
    photos = photo_preparer(listing, assets_dir, slug, want=1)
    post = _series.build_post(story, candidate, listing, photos)
    if post is None:
        print(
            f"[ig_autopilot] d{day} skip {candidate.get('listing_id')}: "
            f"no usable brand-safe photo for story {sid}",
            file=sys.stderr,
        )
        return None

    color = CATEGORY_COLORS.get(post["color_key"], INSPIRACION)
    rendered: list = []
    for i, spec in enumerate(post["slides"]):
        rel = f"web/data/ig_assets/autopilot/{slug}/slide_{i + 1}.png"
        if not skip_render:
            slide_renderer(spec, color, assets_dir / f"slide_{i + 1}.png")
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
    slide_renderer: Callable = _render_slide,
    photo_preparer: Callable = prepare_listing_photos,
) -> list:
    """Append approved items until `lookahead` future posts exist.
    Returns the list of newly-added items (also appended to queue).

    Stories rotate deterministically over the sequence of autopilot posts
    (see ig_story_series.story_for_index) — no repeat within a 14-post cycle.
    A candidate whose photos aren't brand-safe/usable is skipped and the
    next-best listing is tried instead."""
    items = queue.setdefault("items", [])
    added: list = []
    failed: set = set()
    guard = 0
    max_iters = lookahead * 6 + 4          # room to skip thin listings
    while _future_approved_count(items + added, now) < lookahead and guard < max_iters:
        guard += 1
        used = _used_listing_ids(items + added) | failed
        cand = _pick_candidate(candidates, used, ranked_index)
        if cand is None:
            print("[ig_autopilot] no candidates available — stopping topup", file=sys.stderr)
            break
        day = _next_day(items + added)
        # Rotate the story by the count of autopilot posts so far (existing +
        # this run) so no two consecutive days repeat and the console can
        # preview what's coming.
        autopilot_so_far = sum(1 for it in items + added if str(it.get("selector")) == "autopilot")
        story = _series.story_for_index(autopilot_so_far)
        scheduled = _next_slot(items + added, now, cadence_days).isoformat()
        listing = ranked_index.get(cand.get("listing_id"), {})
        item = build_item(
            day=day, story=story, candidate=cand, listing=listing,
            scheduled_for=scheduled, assets_root=assets_root,
            skip_render=skip_render, slide_renderer=slide_renderer,
            photo_preparer=photo_preparer,
        )
        if item is None:                    # no brand-safe photo → try another
            failed.add(cand.get("listing_id"))
            continue
        added.append(item)
        print(
            f"[ig_autopilot] queued d{day} story={story['id']} "
            f"listing={cand.get('listing_id')} scheduled={scheduled} "
            f"slides={1 + len(item['carousel_photo_paths'])} "
            f"caption_status={item['caption_status']}"
        )
    items.extend(added)
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
    p.add_argument("--now", default=None, help="ISO 'now' override (tests).")
    args = p.parse_args(argv)

    now = _parse_iso(args.now) or datetime.now(timezone.utc)

    if not args.candidates.exists():
        print(f"[ig_autopilot] candidates missing: {args.candidates}", file=sys.stderr)
        return 2
    candidates = json.loads(args.candidates.read_text(encoding="utf-8")).get("candidates", [])
    ranked = json.loads(args.ranked.read_text(encoding="utf-8")) if args.ranked.exists() else []
    ranked_index = _ranked_index(ranked)

    queue = (
        json.loads(args.queue.read_text(encoding="utf-8"))
        if args.queue.exists() else {"version": 1, "batch": "autopilot", "items": []}
    )

    added = topup(
        queue, candidates, ranked_index,
        now=now, lookahead=args.lookahead, cadence_days=args.cadence_days,
        assets_root=args.assets_root, skip_render=args.skip_render,
        # --skip-render is an offline mode → don't hit the network for photos.
        photo_preparer=_predict_photos if args.skip_render else prepare_listing_photos,
    )

    args.queue.parent.mkdir(parents=True, exist_ok=True)
    args.queue.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ig_autopilot] added {len(added)} item(s); queue now {len(queue['items'])} total → {args.queue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
