"""ig_autopilot.py — the self-running IG post generator.

Keeps `web/data/ig_queue.json` topped up with **approved, scheduled**
posts so the hourly publisher (automation/ig_publish.py) can post on its
own.  The operator's only lever is Skip (in /admin/ig) + the IG_PAUSED
kill switch.

Two rules baked in per the campaign brief:
  1. EVERY post shows a real listing (photo-gated, from ig_candidates.json
     — so no broker-watermarked photos leak).
  2. MIX both content types ongoing:
       - brand-led   → slide 1 = editorial brand message (TYPO_MAX),
                       slide 2 = a branded listing card (STICKER).
       - showcase    → slide 1 = a branded listing card (STICKER),
                       slide 2 = the listing's hero photo.
     Alternates by post index so the feed stays varied.

Design: reuses the low-level render + caption libs directly
(ig_poster.render_poster, ig_caption.generate_caption) — the same
surface ig_queue_builder uses — without the selector/plan machinery.
Renderers are injectable so tests run offline with skip_render.

CLI (run by .github/workflows/ig-autopilot.yml on a daily cron):
    python3 -m automation.ig_autopilot --lookahead 3 --cadence-days 1

Autopilot NEVER flips IG_PAUSED and NEVER posts — it only queues.
Posting stays with the publisher cron, which the operator gates with
IG_PAUSED.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

# Reuse the exact render + caption + lint surface the queue builder uses.
from automation.ig_poster import render_poster as _render_poster
from automation.ig_poster import TYPO_MAX, STICKER
from automation.ig_caption import generate_caption as _generate_caption
from automation.ig_caption_lint import check as _lint_check
from pulpo.countries import active as _active_country

# Country name comes from the active-country manifest, never a hardcoded
# literal — so the copy follows the platform when a new country is added
# (and satisfies scripts/check_country_hardcodes.py).
_COUNTRY = _active_country().name_en  # the active country's display name

# ── evergreen brand messages (slide 1 of brand-led posts) ─────────────
#
# Each drives a TYPO_MAX poster (eyebrow/hook/hero/punch) + a complete,
# lint-clean caption.  Cycled in order; when exhausted it wraps.  Keep
# every caption through ig_caption_lint (no banned words, no `!`).
# `{_COUNTRY}` is interpolated from the manifest (see above).

BRAND_MESSAGES: tuple[dict, ...] = (
    {
        "eyebrow": _COUNTRY.upper(), "hook": f"Todos los terrenos de {_COUNTRY},",
        "hero": "rankeados.", "punch": "Cada semana.",
        "caption": (
            f"**Todos los terrenos de {_COUNTRY}, rankeados cada semana.**\n\n"
            "Un solo lugar para ver lo que de verdad vale la pena. Sin listas infinitas.\n\n"
            "pulpo.club · link en bio"
        ),
    },
    {
        "eyebrow": "CÓMO FUNCIONA", "hook": "Revisamos cada terreno a la venta.",
        "hero": "Los 10 mejores.", "punch": "Sin ruido, cada semana.",
        "caption": (
            "**No es otra lista de terrenos. Es un ranking.**\n\n"
            "Calificamos cada terreno por precio, zona y acceso, y publicamos solo los mejores.\n\n"
            "pulpo.club · link en bio"
        ),
    },
    {
        "eyebrow": "SIN RUIDO", "hook": "Nada de listas infinitas.",
        "hero": "Menos ruido.", "punch": "Mejores terrenos.",
        "caption": (
            "**Menos ruido, mejores terrenos.**\n\n"
            "Nada de listas infinitas ni precios inflados. Filtramos el mercado y te mostramos lo que vale.\n\n"
            "pulpo.club · link en bio"
        ),
    },
    {
        "eyebrow": "TODO EL PAÍS", "hook": "De la playa a la montaña,",
        "hero": f"todo {_COUNTRY}.", "punch": "En un solo lugar.",
        "caption": (
            f"**De la playa a la montaña, todo {_COUNTRY}.**\n\n"
            "Surf City, oriente, occidente — cada terreno a la venta, en un solo lugar.\n\n"
            "pulpo.club · link en bio"
        ),
    },
    {
        "eyebrow": "CADA DOMINGO", "hook": "Café, terrenos, cero prisa.",
        "hero": "Domingo de Pulpo.", "punch": "Suscríbete gratis.",
        "caption": (
            "**Cada domingo, los mejores terrenos en tu correo.**\n\n"
            "Gratis. Un resumen tranquilo de lo mejor de la semana, sin prisa.\n\n"
            "pulpo.club · link en bio"
        ),
    },
    {
        "eyebrow": "EL TENTÁCULO", "hook": "Buscamos en todo el país,",
        "hero": "sin parar.", "punch": "Para traerte lo mejor.",
        "caption": (
            "**Un pulpo revisa cada terreno a la venta.**\n\n"
            f"Buscamos en todo {_COUNTRY}, todos los días, para traerte los mejores terrenos.\n\n"
            "pulpo.club · link en bio"
        ),
    },
)

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


def _hero_path(candidate: dict) -> str:
    """Local Vercel-served hero photo for a candidate (single-underscore)."""
    return f"web/photos/{candidate.get('source')}_{candidate.get('source_id')}.hero.jpg"


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
    now + cadence so the operator always has a skip window."""
    latest = None
    for it in items:
        sched = _parse_iso(it.get("scheduled_for"))
        if sched and (latest is None or sched > latest):
            latest = sched
    base = latest if latest and latest > now else now
    nxt = base + timedelta(days=cadence_days)
    return nxt.replace(hour=DEFAULT_PUBLISH_HOUR_UTC, minute=0, second=0, microsecond=0)


def _pick_candidate(candidates: list, used: set) -> Optional[dict]:
    """Highest-rank photo-gated candidate not featured recently."""
    pool = [c for c in candidates if c.get("listing_id") not in used]
    if not pool:
        pool = candidates[:]   # everyone's been used recently → allow repeats
    if not pool:
        return None
    return max(pool, key=lambda c: c.get("rank_score") or c.get("rank") or 0)


# ── first comment (posted under each post) ────────────────────────────
#
# IG feed captions stay clean/editorial; the discovery hashtags + the full
# listing spec live in the FIRST COMMENT so the caption reads well and the
# comment carries everything the post is about.  `_C` (no-space country)
# keeps country hashtags off the check_country_hardcodes.py radar and lets
# them follow the manifest.

_C = _COUNTRY.replace(" ", "")

_CORE_HASHTAGS: tuple[str, ...] = (
    f"#{_C}", "#Terrenos", "#BienesRaices", f"#TerrenosEn{_C}",
    f"#InvertirEn{_C}", "#InversionInmobiliaria", "#TerrenoEnVenta",
    "#SurfCity", f"#PlayasDe{_C}", "#SalvadorenosPorElMundo", "#BitcoinCountry",
)


def _zone_title(zone: Optional[str]) -> str:
    """"el-tunco" → "El Tunco"."""
    if not zone:
        return _COUNTRY
    return " ".join(w.capitalize() for w in str(zone).replace("_", "-").split("-"))


def _zone_hashtag(zone: Optional[str]) -> str:
    if not zone:
        return ""
    return "#" + "".join(w.capitalize() for w in str(zone).replace("_", "-").split("-"))


def build_comment(candidate: dict, listing: dict) -> str:
    """The first comment for a post — references ALL the post's info
    (size, location, price, price/m², distance to sea) + the CTA +
    discovery hashtags.  Kept out of the caption so the caption stays
    clean; this is what the publisher posts as comment #1."""
    from automation.ig_units import (
        format_area_m2, format_price_usd, format_price_per_m2, format_distance,
    )
    zone = _zone_title(candidate.get("zone"))
    lines = [f"{format_area_m2(candidate.get('area_m2'))} en {zone}."]

    spec = f"{format_price_usd(candidate.get('price_usd'))}"
    ppm = candidate.get("price_per_m2")
    if ppm is not None:
        spec += f" · {format_price_per_m2(ppm)}"
    lines.append(spec)

    dist = candidate.get("dist_beach_km")
    if dist is not None:
        lines.append("Frente al mar." if dist <= 0.05 else f"A {format_distance(dist)} del mar.")

    lines += [
        "",
        f"Los mejores terrenos de {_COUNTRY}, rankeados cada semana.",
        "Todos los detalles en pulpo.club — link en bio.",
        "",
    ]

    tags = list(_CORE_HASHTAGS)
    zt = _zone_hashtag(candidate.get("zone"))
    if zt and zt not in tags:
        tags.insert(8, zt)
    lines.append(" ".join(tags))
    return "\n".join(lines)


# ── item construction ─────────────────────────────────────────────────

def build_item(
    *,
    day: int,
    kind: str,                      # "brand" | "showcase"
    candidate: dict,
    listing: dict,
    brand_msg: dict,
    scheduled_for: str,
    assets_root: Path,
    skip_render: bool,
    poster_renderer: Callable = _render_poster,
    caption_generator: Callable = _generate_caption,
) -> dict:
    """Build one approved, listing-bearing queue item.

    brand    → [TYPO_MAX brand poster, STICKER listing card]
    showcase → [STICKER listing card, listing hero photo]
    Either way slide-2..N carries a real listing, so every post shows one.
    """
    slug = f"d{day:03d}__{kind}"
    assets_dir = assets_root / slug
    palette = candidate.get("palette_suggested") or "ink"
    hero = _hero_path(candidate)

    def _render(ptype, pal, overrides, name):
        out = assets_dir / f"poster_{name}.png"
        if not skip_render:
            poster_renderer(candidate, listing, ptype, pal, out, overrides=overrides)
        return f"web/data/ig_assets/autopilot/{slug}/poster_{name}.png"

    if kind == "brand":
        brand_overrides = {
            "eyebrow": brand_msg["eyebrow"], "hook": brand_msg["hook"],
            "hero": brand_msg["hero"], "punch": brand_msg["punch"],
            "price": "pulpo.club", "loc": "link en bio",
        }
        poster_path = _render(TYPO_MAX, "cream", brand_overrides, "typo_max_cream")
        sticker_path = _render(STICKER, palette, {}, f"sticker_{palette}")
        carousel = [sticker_path]
        caption = brand_msg["caption"]
    else:  # showcase
        sticker_path = _render(STICKER, palette, {}, f"sticker_{palette}")
        poster_path = sticker_path
        carousel = [hero]
        caption = caption_generator(candidate, listing, poster_type=STICKER, client=None)

    violations = _lint_check(caption)
    return {
        "day": day,
        "shelf": f"autopilot_{kind}",
        "selector": "autopilot",
        "poster_type": STICKER if kind == "showcase" else TYPO_MAX,
        "palette": palette,
        "scheduled_for": scheduled_for,
        "assets_dir": f"web/data/ig_assets/autopilot/{slug}",
        "poster_path": poster_path,
        "poster_overrides": {},
        "caption": caption,
        "comment": build_comment(candidate, listing),
        "lint_violations": violations,
        "caption_status": "clean" if not violations else "lint_failed",
        "carousel_photo_paths": carousel,
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
    poster_renderer: Callable = _render_poster,
    caption_generator: Callable = _generate_caption,
    brand_messages: tuple = BRAND_MESSAGES,
) -> list:
    """Append approved items until `lookahead` future posts exist.
    Returns the list of newly-added items (also appended to queue)."""
    items = queue.setdefault("items", [])
    added: list = []
    guard = 0
    while _future_approved_count(items + added, now) < lookahead and guard < lookahead + 2:
        guard += 1
        used = _used_listing_ids(items + added)
        cand = _pick_candidate(candidates, used)
        if cand is None:
            print("[ig_autopilot] no candidates available — stopping topup", file=sys.stderr)
            break
        day = _next_day(items + added)
        # Alternate brand-led / showcase by post index (mix, per brief).
        autopilot_so_far = sum(1 for it in items + added if str(it.get("selector")) == "autopilot")
        kind = "brand" if autopilot_so_far % 2 == 0 else "showcase"
        brand_msg = brand_messages[autopilot_so_far % len(brand_messages)]
        scheduled = _next_slot(items + added, now, cadence_days).isoformat()
        listing = ranked_index.get(cand.get("listing_id"), {})
        item = build_item(
            day=day, kind=kind, candidate=cand, listing=listing,
            brand_msg=brand_msg, scheduled_for=scheduled, assets_root=assets_root,
            skip_render=skip_render, poster_renderer=poster_renderer,
            caption_generator=caption_generator,
        )
        added.append(item)
        print(
            f"[ig_autopilot] queued d{day} kind={kind} "
            f"listing={cand.get('listing_id')} scheduled={scheduled} "
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
    p.add_argument("--lookahead", type=int, default=3, help="Keep this many future posts queued.")
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
    )

    args.queue.parent.mkdir(parents=True, exist_ok=True)
    args.queue.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ig_autopilot] added {len(added)} item(s); queue now {len(queue['items'])} total → {args.queue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
