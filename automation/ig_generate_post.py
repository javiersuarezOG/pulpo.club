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


def default_gate_cfg() -> dict:
    """The Scout's brand-safe gate — the photo gate's checks (≥6 photos, hero
    score, overlay/agricultural/validation) but WITHOUT terrenos_only, so the
    feed spans the whole catalogue: land + houses + condos + lakefront, not just
    land. Brand safety on real-photo slides is handled downstream (designed
    opener + verified-clean middle slides + human review), not by excluding
    every non-land listing wholesale."""
    cfg = dict(ig_photo_gate._config_snapshot())
    cfg["terrenos_only"] = False
    return cfg


def _dims(li: dict) -> dict:
    """The diversity axes: zone, property type, category (beach/lake/…), price
    band. A varied feed spreads across all four."""
    return {
        "zone": li.get("zone"),
        "type": li.get("property_type") or "other",
        "cat": li.get("master_category") or "other",
        "band": _band(li.get("price_usd")),
    }


def pick_listings(listings: list[dict], n: int, *, gate_cfg=None) -> list[dict]:
    """Top brand-safe listings, greedily diversified across zone + property type
    + category + price band. Each step takes the highest-rank listing that
    introduces the MOST unseen dimension values, so a 7-post week spans land /
    house / condo / lake and coast / lake, never seven-in-a-row of the same
    thing. Rank breaks ties (the pool is rank-sorted, and we keep the first
    max-novelty listing, which is the highest-ranked one)."""
    cfg = gate_cfg if gate_cfg is not None else default_gate_cfg()
    pool = sorted((li for li in listings if ig_photo_gate.passes_gate(li, cfg)),
                  key=_rank, reverse=True)
    picked: list[dict] = []
    seen: dict[str, set] = {"zone": set(), "type": set(), "cat": set(), "band": set()}
    remaining = list(pool)

    def novelty(li: dict) -> int:
        return sum(1 for k, v in _dims(li).items() if v not in seen[k])

    while len(picked) < n and remaining:
        best, best_nov = None, -1
        for li in remaining:                      # rank-sorted → first max wins
            nov = novelty(li)
            if nov > best_nov:
                best, best_nov = li, nov
                if nov == len(seen):              # can't beat full novelty
                    break
        picked.append(best)
        for k, v in _dims(best).items():
            seen[k].add(v)
        remaining.remove(best)
    return picked[:n]


# ── Creative Director (weighted toward the chosen viral angles) ─────────
# Javi's three angles map onto the levers: POV→aspiration, ranking/humor→
# education, diáspora→social_proof/transformation/investment. Those get more
# airtime; scarcity/authority still appear (attribution needs all 7 covered)
# but lead less often. A 7-post week still hits every lever once.
_LEVER_WEIGHT: dict[str, int] = {
    "aspiration": 3, "education": 3,
    "social_proof": 2, "transformation": 2, "investment": 2,
    "scarcity": 1, "authority": 1,
}


def _weighted_sequence() -> list[str]:
    """Levers ordered weight-desc, repeated by weight — round 0 covers all 7
    (favored first), later rounds repeat only the favored ones."""
    ordered = sorted(cats.SLUGS, key=lambda s: (-_LEVER_WEIGHT.get(s, 1), cats.SLUGS.index(s)))
    seq: list[str] = []
    for r in range(max(_LEVER_WEIGHT.values())):
        seq += [s for s in ordered if _LEVER_WEIGHT.get(s, 1) > r]
    return seq


def rotate_levers(n: int, *, start: int = 0) -> list[str]:
    """n levers from the weighted cycle, offset by `start`. The first 7 cover
    every lever (no starvation); beyond that the chosen viral angles repeat more."""
    seq = _weighted_sequence()
    return [seq[(start + i) % len(seq)] for i in range(n)]


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
            "property_type": li.get("property_type"),
            "master_category": li.get("master_category"),
            "price_usd": li.get("price_usd"),
            "hero_photo_path": li.get("hero_photo_path"),
            "slides": slides,
            "slide_count": len(slides),
        })
    return out
