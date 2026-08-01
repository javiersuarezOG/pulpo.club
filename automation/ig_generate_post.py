"""ig_generate_post.py — the generator: Listing Scout + Creative Director.

Ties the Social Brain together into review-ready posts. Given nothing but
ranked.json it will:

  1. LISTING SCOUT — pick brand-safe listings (ig_photo_gate: photo-eligible,
     no broker watermark) and diversify across zone / property-type / price
     band so the feed never feels monotone.
  2. CREATIVE DIRECTOR (v1) — rotate the 7 content levers round-robin so
     every buyer/lever gets airtime. (Data-informed rotation — weighting by
     what converts — is the Growth-Hacker upgrade once attribution has data.)
  3. COPYWRITER + CODE-STAMP — for each (listing, lever): a full bilingual
     caption + first comment (ig_copywriter) and an attribution code
     (ig_code_stamp), producing a review item.

Output is a list of review items — NOT a live queue write and NOT a publish.
generate_batch() is pure + deterministic (llm_polish optional), so a caller
(a nightly, or a wake-up preview) decides what to do with them: render a
review board, or stamp them into ig_queue.json as approved=false for the
veto digest. Nothing here touches the wire.
"""
from __future__ import annotations

from typing import Callable, Optional

from automation import ig_code_stamp
from automation import ig_content_categories as cats
from automation import ig_copywriter
from automation import ig_photo_gate
from automation import ig_story


# ── Listing Scout ──────────────────────────────────────────────────────

def _rank(li: dict) -> float:
    v = li.get("rank_score")
    return float(v) if isinstance(v, (int, float)) else 0.0


def _band(price) -> str:
    p = price or 0
    if p < 100_000:
        return "sub100k"
    if p < 300_000:
        return "100-300k"
    if p < 750_000:
        return "300-750k"
    return "750k+"


def pick_listings(listings: list[dict], n: int, *, gate_cfg=None) -> list[dict]:
    """Top brand-safe listings, diversified by zone then price band. Pass 1
    takes the highest-rank listing from each unused zone (so the feed spans the
    coast, never three-in-a-row from La Libertad); pass 2 breaks ties toward an
    unused price band; pass 3 fills any shortfall by pure rank. Property type is
    NOT a diversity axis — the photo gate is land-only, so it's monotone."""
    cfg = gate_cfg if gate_cfg is not None else ig_photo_gate._config_snapshot()
    pool = sorted((li for li in listings if ig_photo_gate.passes_gate(li, cfg)),
                  key=_rank, reverse=True)
    picked: list[dict] = []
    seen_zone: set[str] = set()
    seen_band: set[str] = set()

    def take(li: dict) -> None:
        picked.append(li)
        seen_zone.add(li.get("zone"))
        seen_band.add(_band(li.get("price_usd")))

    # pass 1 — one per unused zone (the meaningful diversity axis)
    for li in pool:
        if len(picked) >= n:
            break
        if li.get("zone") not in seen_zone:
            take(li)
    # pass 2 — among leftovers, prefer an unused price band before repeating one
    for li in pool:
        if len(picked) >= n:
            break
        if li not in picked and _band(li.get("price_usd")) not in seen_band:
            take(li)
    # pass 3 — fill any shortfall by pure rank
    for li in pool:
        if len(picked) >= n:
            break
        if li not in picked:
            take(li)
    return picked[:n]


# ── Creative Director (v1: round-robin the levers) ─────────────────────

def rotate_levers(n: int, *, start: int = 0) -> list[str]:
    """n levers, round-robin over the 7, offset by `start` for variety
    across runs. Guarantees no lever is starved."""
    slugs = cats.SLUGS
    return [slugs[(start + i) % len(slugs)] for i in range(n)]


# ── the batch ──────────────────────────────────────────────────────────

def _listing_id(li: dict) -> str:
    return f"{li.get('source')}_{li.get('source_id')}"


def generate_batch(
    listings: list[dict],
    n: int,
    *,
    start_day: int = 1,
    lever_start: int = 0,
    llm_polish: Optional[Callable] = None,
    gate_cfg=None,
) -> list[dict]:
    """n review-ready posts: diversified listings × rotated levers → caption +
    comment + attribution code. Deterministic. Never writes a queue or posts."""
    picks = pick_listings(listings, n, gate_cfg=gate_cfg)
    levers = rotate_levers(len(picks), start=lever_start)
    out: list[dict] = []
    for i, (li, lever) in enumerate(zip(picks, levers)):
        post = ig_copywriter.generate_post(li, lever, llm_polish=llm_polish)
        day = start_day + i
        code = ig_code_stamp.make_code(day, lever, post["tier"])
        slides = ig_story.build_storyboard(li, lever)
        out.append({
            "day": day,
            "lever": lever,
            "tier": post["tier"],
            "attribution_code": code,
            "go_url": f"/go/{code}",
            "caption_es": post["caption_es"],
            "caption_en": post["caption_en"],
            "comment_es": post["comment_es"],
            "comment_en": post["comment_en"],
            "facts_cited": post.get("facts_cited", []),
            "model": post["model"],
            "listing_id": _listing_id(li),
            "zone": li.get("zone"),
            "price_usd": li.get("price_usd"),
            "hero_photo_path": li.get("hero_photo_path"),
            "slides": slides,
            "slide_count": len(slides),
        })
    return out
