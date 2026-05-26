"""ig_queue_builder.py — assemble the 14-post batch for IG drop 01.

Inputs:
  - web/data/ig_candidates.json   (from PR-1: 78 listings that pass the
                                   photo gate)
  - web/data/ranked.json          (full records; needed for photo_urls
                                   and other fields not in the slim
                                   candidate payload)
  - (optional) web/data/ig_triggers.json — observation-only in batch 1

Outputs:
  - web/data/ig_queue.json        — the 14-item queue, status=pending
  - web/data/ig_assets/<slug>/poster_<type>_<palette>.png
                                  — one rendered poster per item

Selection: shelf-driven (see ``BATCH_1_PLAN`` below).  Each of the 14
days maps to a specific shelf semantic (top rank, bargain alert,
mejor $/m², top 5 by zone/band, diversifier, intro, wrap).  Within
each shelf we pick deterministically from the candidate pool so a
re-run with the same inputs produces an identical queue (modulo the
DeepSeek-touched descriptive lines in captions).

For each item we:
  1. Pick poster_type + palette per the plan
  2. Render the poster PNG via ig_poster.render_poster()
  3. Generate the caption via ig_caption.generate_caption() (DeepSeek
     enhanced if DEEPSEEK_API_TOKEN is set, template-only otherwise)
  4. Persist the entry to ig_queue.json with approved=false

The queue is consumed by:
  - /admin/ig-review widget (PR-3b) — humans approve/skip/regenerate
  - ig_publish.py (PR-4) — only publishes items with approved=true

CLI:

    python3 -m automation.ig_queue_builder \\
        [--candidates web/data/ig_candidates.json] \\
        [--ranked     web/data/ranked.json] \\
        [--output     web/data/ig_queue.json] \\
        [--start-date 2026-06-01] \\
        [--skip-render] \\
        [--skip-llm]

`--skip-render` skips the Playwright PNG step (fast dry-run for the
selection logic).  `--skip-llm` forces template-only captions.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

from automation._atomic import atomic_write_json
from automation._config import env_bool, env_str
from automation.ig_caption import generate_caption as _generate_caption
from automation.ig_caption import _build_client as _build_caption_client  # noqa: E501
from automation.ig_caption_lint import check as lint_check
from automation.ig_poster import (
    BIG_NUMBER, MAP_MARK, POST_IT, RECEIPT, STICKER, TYPO_MAX,
    render_poster as _render_poster,
)


# ── zone groupings ────────────────────────────────────────────────────

# El Salvador's three macro-regions, used by shelf selectors that filter
# by region rather than by individual zone slug.
ORIENTE_DEPARTMENTS = frozenset({
    "San Miguel", "La Unión", "La Union", "Usulután", "Usulutan", "Morazán", "Morazan",
})
OCCIDENTE_DEPARTMENTS = frozenset({
    "Ahuachapán", "Ahuachapan", "Sonsonate", "Santa Ana",
})
CENTRAL_DEPARTMENTS = frozenset({
    "San Salvador", "La Libertad", "La Paz", "Cuscatlán", "Cuscatlan",
    "San Vicente", "Chalatenango", "Cabañas", "Cabanas",
})

# Zones inside the "Surf City" macro-area along the central coast.  Used
# by the shelf:"top5_zone:la-libertad" — broader than the
# `zone == "la-libertad"` exact match, since Surf City spans several
# fine-grained zones in the data.
SURF_CITY_ZONES = frozenset({
    "el-tunco", "el-sunzal", "el-zonte", "la-libertad",
    "playa-san-diego", "playa-el-tunco", "el-palmarcito",
    "tamanique",
})


# ── BATCH_1_PLAN — the 14-day shelf mapping (Direction A locked) ─────

# Each tuple: (day, shelf_id, selector_spec, poster_type, palette)
#
# Tuple order = PROCESSING order in PASS 1.  Days assign the calendar
# slot but heroes are picked in tuple order so high-priority shelves
# (by_*) consume listings before diversifiers + multis.  The output is
# sorted by `day` at the end so downstream consumers see chronological
# order.
#
# Selector specs:
#   "by_rank_score"            top unused by rank_score
#   "by_bargain_pct"           most-negative price_vs_zone_pct (≤ −20)
#   "by_ppm_in_surf_city"      lowest $/m² inside SURF_CITY_ZONES
#   "top5_zone:<key>"          5 best of <key> (zone slug or macro-region
#                              "oriente"/"central"/"occidente" or
#                              "surf_city")
#   "top5_band:<min>-<max>"    5 best where min ≤ price_usd < max
#   "diversify_region:<key>"   highest-rank candidate in region not yet
#                              picked by an earlier hero shelf
#   "multi:<intent>"           multi-listing carousel; <intent> ∈
#                              {"intro", "wrap"}.  No single primary
#                              listing — uses the already-selected
#                              heroes as carousel slides.
BATCH_1_PLAN: Tuple[Tuple[int, str, str, str, str], ...] = (
    # ── PRIORITY 1: hero by_* shelves (exclusive) ───────────────────
    (2,  "top_rank_1",             "by_rank_score",                   STICKER,    "ink"),
    (9,  "top_rank_2",             "by_rank_score",                   STICKER,    "ink"),
    (3,  "bargain_1",              "by_bargain_pct",                  POST_IT,    "paper"),
    (11, "bargain_2",              "by_bargain_pct",                  POST_IT,    "paper"),
    (7,  "best_ppm",               "by_ppm_in_surf_city",             BIG_NUMBER, "gold"),
    # ── PRIORITY 2: diversifiers (fill in after heroes locked) ──────
    (5,  "diversify_oriente",      "diversify_region:oriente",        TYPO_MAX,   "ink"),
    (13, "diversify_central",      "diversify_region:central",        TYPO_MAX,   "paper"),
    # ── PRIORITY 3: listicles (no exclusivity — can reuse heroes) ───
    (4,  "top5_zone_surf_city",    "top5_zone:surf_city",             RECEIPT,    "cream"),
    (6,  "top5_band_below_300k",   "top5_band:0-300000",              RECEIPT,    "ink"),
    (8,  "top5_band_300_500k",     "top5_band:300000-500000",         RECEIPT,    "cream"),
    (10, "top5_band_500k_1m",      "top5_band:500000-1000000",        RECEIPT,    "cream"),
    (12, "top5_zone_oriente",      "top5_zone:oriente",               MAP_MARK,   "cream"),
    # ── PRIORITY 4: multi-listing carousels (resolved last) ─────────
    (1,  "intro",                  "multi:intro",                     TYPO_MAX,   "cream"),
    (14, "wrap",                   "multi:wrap",                      RECEIPT,    "ink"),
)


# ── selectors ──────────────────────────────────────────────────────────

def _region_of(c: dict) -> Optional[str]:
    dept = c.get("department")
    if dept in ORIENTE_DEPARTMENTS:
        return "oriente"
    if dept in CENTRAL_DEPARTMENTS:
        return "central"
    if dept in OCCIDENTE_DEPARTMENTS:
        return "occidente"
    return None


def _is_in_zone_key(c: dict, key: str) -> bool:
    """True if candidate `c` matches the zone selector `key`.

    `key` may be:
      - "surf_city"             matches the SURF_CITY_ZONES set
      - "oriente"/"central"/"occidente"  region match (by department)
      - any other string        exact zone slug match
    """
    if key == "surf_city":
        return (c.get("zone") or "") in SURF_CITY_ZONES
    if key in ("oriente", "central", "occidente"):
        return _region_of(c) == key
    return c.get("zone") == key


def _pick_by_rank_score(
    candidates: list[dict], used: set[str]
) -> Optional[dict]:
    """Top unused candidate by rank_score.  Returns None if exhausted.

    Sequence semantics: when called multiple times across different
    shelves (top_rank_1 / top_rank_2 / etc.), each call picks the NEXT
    best unused candidate — the iteration order in BATCH_1_PLAN
    determines which gets the global #1, which gets #2, etc."""
    pool = [c for c in candidates if c["listing_id"] not in used]
    if not pool:
        return None
    return max(pool, key=lambda c: c.get("rank_score") or 0)


def _pick_by_bargain_pct(
    candidates: list[dict], used: set[str]
) -> Optional[dict]:
    """Most-negative price_vs_zone_pct (≤ −20%), excluding already-used.

    Same sequence semantics as _pick_by_rank_score: bargain_1 + bargain_2
    each grab the next-best bargain remaining."""
    pool = [
        c for c in candidates
        if c["listing_id"] not in used and (c.get("price_vs_zone_pct") or 0) <= -20
    ]
    if not pool:
        return None
    return min(pool, key=lambda c: c.get("price_vs_zone_pct") or 0)


def _pick_by_ppm_in_surf_city(
    candidates: list[dict], used: set[str]
) -> Optional[dict]:
    """Lowest price_per_m2 inside SURF_CITY_ZONES, excluding used."""
    pool = [
        c for c in candidates
        if c["listing_id"] not in used
        and _is_in_zone_key(c, "surf_city")
        and c.get("price_per_m2") is not None
    ]
    pool.sort(key=lambda c: c["price_per_m2"])
    return pool[0] if pool else None


def _pick_top5_zone(
    candidates: list[dict], key: str
) -> list[dict]:
    """Top 5 by rank_score within zone (does NOT exclude used heros —
    a listicle slide may reuse a hero, that's fine)."""
    pool = [c for c in candidates if _is_in_zone_key(c, key)]
    pool.sort(key=lambda c: -(c.get("rank_score") or 0))
    return pool[:5]


def _pick_top5_band(
    candidates: list[dict], lo: float, hi: float
) -> list[dict]:
    """Top 5 by rank_score within the price band [lo, hi)."""
    pool = [
        c for c in candidates
        if c.get("price_usd") is not None and lo <= c["price_usd"] < hi
    ]
    pool.sort(key=lambda c: -(c.get("rank_score") or 0))
    return pool[:5]


def _pick_diversify_region(
    candidates: list[dict], region: str, used: set[str]
) -> Optional[dict]:
    """Best candidate of `region` not yet used as a hero.  Falls back
    to any candidate of that region if the unused pool is empty."""
    region_pool = [c for c in candidates if _region_of(c) == region]
    if not region_pool:
        return None
    unused = [c for c in region_pool if c["listing_id"] not in used]
    pool = unused or region_pool   # graceful fallback
    pool.sort(key=lambda c: -(c.get("rank_score") or 0))
    return pool[0]


def _select(
    spec: str, candidates: list[dict], used: set[str],
) -> Tuple[Optional[dict], list[dict]]:
    """Dispatch on selector spec.  Returns (primary, all_listings_for_item).

    For single-listing shelves (typo_max/sticker/post_it/big_number/
    map_mark heroes), primary == the one listing AND all_listings == [primary].
    For multi-listing shelves (receipts, intro, wrap), primary is the
    first item (used for default poster overrides) AND all_listings is
    the full set of items for the carousel."""
    if spec == "by_rank_score":
        c = _pick_by_rank_score(candidates, used)
        return (c, [c] if c else [])
    if spec == "by_bargain_pct":
        c = _pick_by_bargain_pct(candidates, used)
        return (c, [c] if c else [])
    if spec == "by_ppm_in_surf_city":
        c = _pick_by_ppm_in_surf_city(candidates, used)
        return (c, [c] if c else [])
    if spec.startswith("top5_zone:"):
        key = spec.split(":", 1)[1]
        rows = _pick_top5_zone(candidates, key)
        return (rows[0] if rows else None, rows)
    if spec.startswith("top5_band:"):
        lo_str, hi_str = spec.split(":", 1)[1].split("-")
        rows = _pick_top5_band(candidates, float(lo_str), float(hi_str))
        return (rows[0] if rows else None, rows)
    if spec.startswith("diversify_region:"):
        region = spec.split(":", 1)[1]
        c = _pick_diversify_region(candidates, region, used)
        return (c, [c] if c else [])
    if spec.startswith("multi:"):
        # multi: solved later, after all heroes are picked.  Signal it
        # by returning (None, []) so the orchestrator knows to fill
        # in from already-selected heroes.
        return (None, [])
    raise ValueError(f"unknown selector spec: {spec!r}")


# ── carousel resolution (intro + wrap) ────────────────────────────────

def _resolve_intro_listings(items_so_far: list[dict], all_candidates: list[dict]) -> list[dict]:
    """Pick 6 listings for the D1 intro carousel.  Prefers zone variety
    across the heroes already selected; falls back to top-rank candidates
    if the heroes don't span 6 distinct zones."""
    chosen: list[dict] = []
    seen_zones: set[str] = set()
    for item in items_so_far:
        primary = item.get("_primary_candidate")
        if not primary:
            continue
        z = primary.get("zone")
        if z and z not in seen_zones:
            chosen.append(primary)
            seen_zones.add(z)
        if len(chosen) >= 6:
            break
    # Pad with top-rank candidates of unseen zones if needed.
    for c in sorted(all_candidates, key=lambda c: -(c.get("rank_score") or 0)):
        if len(chosen) >= 6:
            break
        z = c.get("zone")
        if z and z not in seen_zones:
            chosen.append(c)
            seen_zones.add(z)
    return chosen[:6]


def _resolve_wrap_listings(items_so_far: list[dict]) -> list[dict]:
    """Wrap is "top 6 by engagement of the batch".  For drop 01 we have
    zero engagement data yet, so we fall back to top 6 by rank_score
    among the heroes already selected.  The publisher (PR-4) will
    eventually swap this for PostHog-driven selection once data exists."""
    primaries = [
        it["_primary_candidate"]
        for it in items_so_far
        if it.get("_primary_candidate")
    ]
    primaries.sort(key=lambda c: -(c.get("rank_score") or 0))
    return primaries[:6]


# ── scheduling ─────────────────────────────────────────────────────────

# Post slot: 19:00 CST (= UTC-6 = 01:00 UTC next day).  IG accepts UTC.
_CST = timezone(timedelta(hours=-6))
_POST_TIME = time(19, 0, 0, tzinfo=_CST)


def _schedule_dates(start: date, n: int) -> list[datetime]:
    return [
        datetime.combine(start + timedelta(days=i), _POST_TIME).astimezone(timezone.utc)
        for i in range(n)
    ]


# ── render orchestration ──────────────────────────────────────────────

def _default_assets_dir(item: dict, output_root: Path) -> Path:
    """Stable per-item directory: drop_01/d01__intro/ — sortable, human-
    readable, doesn't collide if a listing appears in multiple items."""
    return output_root / "drop_01" / f"d{item['day']:02d}__{item['shelf']}"


def _build_item_overrides(
    item: dict, listings: list[dict], full_ranked: dict
) -> dict:
    """Per-poster-type overrides for `build_html`.  Receipt + map_mark
    + intro/wrap multis need their items list populated; heroes use
    defaults."""
    poster_type = item["poster_type"]
    if poster_type == RECEIPT:
        return {
            "title":    item.get("title")    or item["shelf"].replace("_", " ").title(),
            "subtitle": item.get("subtitle") or "5 TERRENOS · CURADOS POR RANKING",
            "brand":    "PULPO · TOP 5",
            "items": [
                {
                    "n":      f"{i+1:02d}",
                    "desc":   (full_ranked.get(c["listing_id"], {}).get("zone")
                               or c.get("zone") or "").replace("-", " ").title(),
                    "sub":    f"{int(c.get('area_m2') or 0):,} m²",
                    "price":  _short_price(c.get("price_usd")),
                }
                for i, c in enumerate(listings[:5])
            ],
            "totals": [
                {"label": "RANGO",   "value": _band_label(listings)},
                {"label": "5 ITEMS", "value": "CURADO"},
            ],
            "footer": f"pulpo.club · {item['shelf'].replace('_', ' ')}",
        }
    if poster_type == MAP_MARK and item.get("region"):
        return {"region": item["region"]}
    return {}


def _short_price(usd: Optional[float]) -> str:
    """"$140K", "$2.5M", "—".  Compact form for the receipt rail."""
    if usd is None or usd <= 0:
        return "—"
    if usd >= 1_000_000:
        return f"${usd/1_000_000:.1f}M".replace(".0M", "M")
    return f"${int(round(usd/1000))}K"


def _band_label(listings: list[dict]) -> str:
    """"$140K — $500K" from the price spread of a listicle."""
    prices = [c.get("price_usd") for c in listings if c.get("price_usd")]
    if not prices:
        return "—"
    return f"{_short_price(min(prices))} — {_short_price(max(prices))}"


def _render_one_item(
    item: dict,
    listings: list[dict],
    full_ranked_index: dict,
    *,
    output_root: Path,
    skip_render: bool,
    caption_client: Any,
    poster_renderer: Callable = _render_poster,
    caption_generator: Callable = _generate_caption,
) -> dict:
    """Render the poster + generate the caption for a single queue item.
    Returns the item mutated with poster_path / caption / status."""
    primary = item.get("_primary_candidate")
    assets_dir = _default_assets_dir(item, output_root)

    item["assets_dir"] = str(assets_dir)

    if primary is None:
        # multi without resolved listings — defensive; shouldn't happen
        # if _resolve_intro/wrap_listings ran.  Set all "always present"
        # keys to safe defaults so the stats aggregator + the queue.json
        # consumer (admin widget) don't need null-checks on every field.
        item["status"] = "needs_human"
        item["caption"] = ""
        item["caption_status"] = "skipped"
        item["lint_violations"] = []
        item["poster_path"] = None
        item["poster_overrides"] = {}
        item["carousel_photo_paths"] = []
        item["listing_ids"] = []
        item["primary_listing_id"] = None
        item.pop("_primary_candidate", None)
        return item

    full_listing = full_ranked_index.get(primary["listing_id"], {})
    overrides = _build_item_overrides(item, listings, full_ranked_index)

    # POSTER
    poster_filename = f"poster_{item['poster_type']}_{item['palette']}.png"
    poster_path = assets_dir / poster_filename
    if not skip_render:
        try:
            poster_renderer(
                primary, full_listing,
                item["poster_type"], item["palette"], poster_path,
                overrides=overrides,
            )
        except Exception as e:                       # pragma: no cover (browser path)
            print(f"[ig_queue] poster render failed for {item['shelf']}: {e!r}",
                  file=sys.stderr)
            item["status"] = "needs_human"
            item["poster_render_error"] = repr(e)
    item["poster_path"] = str(poster_path)
    item["poster_overrides"] = overrides

    # CAPTION
    caption = caption_generator(
        primary, full_listing,
        poster_type=item["poster_type"],
        client=caption_client,
    )
    violations = lint_check(caption)
    item["caption"] = caption
    item["lint_violations"] = violations
    item["caption_status"] = "ok" if not violations else "lint_failed"
    if violations and item.get("status") != "needs_human":
        item["status"] = "needs_human"

    # Carousel photo paths (slides 2..N): for now, the local hero file
    # of each listing in the carousel.  PR-4 publisher will resolve to
    # absolute Vercel URLs.
    item["carousel_photo_paths"] = [
        f"web/photos/{li.get('source')}_{li.get('source_id')}.hero.jpg"
        for li in listings if li
    ]
    item["listing_ids"] = [li["listing_id"] for li in listings if li]
    item["primary_listing_id"] = primary["listing_id"] if primary else None

    # Drop the internal-only key before serialising.
    item.pop("_primary_candidate", None)
    return item


# ── public API ─────────────────────────────────────────────────────────

def build_queue(
    candidates_payload: dict,
    ranked: list[dict],
    *,
    plan: Tuple[Tuple[int, str, str, str, str], ...] = BATCH_1_PLAN,
    start_date: Optional[date] = None,
    output_root: Path = Path("web/data/ig_assets"),
    skip_render: bool = False,
    caption_client: Any = None,
    poster_renderer: Callable = _render_poster,
    caption_generator: Callable = _generate_caption,
) -> dict:
    """Top-level: build the queue payload + render all posters.

    `poster_renderer` and `caption_generator` are dependency-injected so
    tests can pass mocks without touching Chromium or DeepSeek.  The
    defaults wire up the real ig_poster + ig_caption modules.
    """
    candidates = candidates_payload.get("candidates", [])
    if not candidates:
        raise ValueError("ig_candidates.json has no candidates — gate failed?")

    ranked_index = {
        f"{li.get('source')}__{li.get('source_id')}": li for li in ranked
    }
    if start_date is None:
        start_date = (datetime.now(timezone.utc).date() + timedelta(days=1))
    schedule = _schedule_dates(start_date, len(plan))

    # ── PASS 1: pick primaries + listings for all single/multi-listing shelves
    used_hero_ids: set[str] = set()
    items: list[dict] = []
    multi_indices: list[int] = []

    for i, (day, shelf, spec, poster_type, palette) in enumerate(plan):
        primary, listings = _select(spec, candidates, used_hero_ids)
        item = {
            "day":             day,
            "shelf":           shelf,
            "selector":        spec,
            "poster_type":     poster_type,
            "palette":         palette,
            # schedule is indexed by day (1-based) so day 14 always gets
            # day-14 schedule regardless of where the tuple sits in the
            # processing order.
            "scheduled_for":   schedule[day - 1].isoformat(),
            "_primary_candidate": primary,   # internal: dropped on render
            "_listings":       listings,
        }
        # Tag the MAP_MARK region for downstream overrides.
        if poster_type == MAP_MARK and spec.startswith("top5_zone:"):
            key = spec.split(":", 1)[1]
            if key in ("oriente", "central", "occidente"):
                item["region"] = key

        if spec.startswith("multi:"):
            multi_indices.append(i)
        elif primary is not None:
            # Mark hero as used so subsequent shelves don't reuse it as
            # a hero (listicle slides may reuse — that's fine).
            if spec.startswith("by_") or spec.startswith("diversify_"):
                used_hero_ids.add(primary["listing_id"])
        items.append(item)

    # ── PASS 2: resolve multi-listing carousels using picked heros
    for i in multi_indices:
        intent = items[i]["selector"].split(":", 1)[1]
        if intent == "intro":
            listings = _resolve_intro_listings(items, candidates)
        elif intent == "wrap":
            listings = _resolve_wrap_listings(items)
        else:
            raise ValueError(f"unknown multi intent: {intent!r}")
        if listings:
            items[i]["_primary_candidate"] = listings[0]
            items[i]["_listings"] = listings

    # ── PASS 3: render + caption every item
    rendered: list[dict] = []
    for raw in items:
        listings = raw.pop("_listings", [])
        rendered.append(_render_one_item(
            raw, listings, ranked_index,
            output_root=output_root,
            skip_render=skip_render,
            caption_client=caption_client,
            poster_renderer=poster_renderer,
            caption_generator=caption_generator,
        ))
        # Set status (status may already be "needs_human" from render/caption)
        rendered[-1].setdefault("status", "pending")
        rendered[-1].setdefault("approved", False)
        rendered[-1].setdefault("posted", False)
        rendered[-1].setdefault("posted_at", None)
        rendered[-1].setdefault("posted_media_id", None)

    # Sort by display day for the final output — downstream consumers
    # (admin widget, publisher) expect chronological order, not the
    # processing order from BATCH_1_PLAN.
    rendered.sort(key=lambda it: it["day"])

    # ── Stats for the bot summary line
    shelves_used = Counter(it["shelf"] for it in rendered)
    items_needing = sum(1 for it in rendered if it["status"] == "needs_human")
    items_pending = sum(1 for it in rendered if it["status"] == "pending")
    items_with_violations = sum(1 for it in rendered if it["lint_violations"])

    return {
        "version":      1,
        "batch":        "drop_01",
        "computed_at":  datetime.now(timezone.utc).isoformat(),
        "config": {
            "plan_length":     len(plan),
            "start_date":      start_date.isoformat(),
            "skip_render":     skip_render,
            "llm_used":        caption_client is not None,
        },
        "stats": {
            "candidates_seen":              len(candidates),
            "items_built":                  len(rendered),
            "items_pending_review":         items_pending,
            "items_needing_human":          items_needing,
            "items_with_lint_violations":   items_with_violations,
            "shelves_used":                 dict(shelves_used),
        },
        "items":        rendered,
    }


# ── CLI ────────────────────────────────────────────────────────────────

DEFAULT_CANDIDATES = Path("web/data/ig_candidates.json")
DEFAULT_RANKED     = Path("web/data/ranked.json")
DEFAULT_OUTPUT     = Path("web/data/ig_queue.json")
DEFAULT_ASSETS     = Path("web/data/ig_assets")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble the 14-post IG queue for drop 01 (Direction A)."
    )
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--ranked",     type=Path, default=DEFAULT_RANKED)
    parser.add_argument("--output",     type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument(
        "--start-date", type=lambda s: date.fromisoformat(s),
        default=None,
        help="ISO date for D1 (default: tomorrow UTC).",
    )
    parser.add_argument(
        "--skip-render", action="store_true",
        help="Skip Playwright poster render (selector-only dry-run).",
    )
    parser.add_argument(
        "--skip-llm", action="store_true",
        help="Force template-only captions (no DeepSeek call).",
    )
    args = parser.parse_args(argv)

    if not args.candidates.exists():
        print(f"[ig_queue] missing input: {args.candidates}", file=sys.stderr)
        return 2
    if not args.ranked.exists():
        print(f"[ig_queue] missing input: {args.ranked}", file=sys.stderr)
        return 2

    candidates_payload = json.loads(args.candidates.read_text(encoding="utf-8"))
    ranked = json.loads(args.ranked.read_text(encoding="utf-8"))

    client = None
    if not args.skip_llm:
        client, err = _build_caption_client()
        if err:
            print(f"[ig_queue] LLM unavailable ({err}) — captions template-only",
                  file=sys.stderr)

    payload = build_queue(
        candidates_payload, ranked,
        output_root=args.assets_dir,
        skip_render=args.skip_render,
        caption_client=client,
    )

    atomic_write_json(args.output, payload, indent=2)
    s = payload["stats"]
    print(
        f"[ig_queue] built {s['items_built']} items "
        f"(pending={s['items_pending_review']}, "
        f"needs_human={s['items_needing_human']}, "
        f"lint_violations={s['items_with_lint_violations']}) "
        f"shelves={s['shelves_used']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Silence pyflakes for env helpers we expose for future CLI flags.
_ = env_bool, env_str
