"""ig_campaign.py — "Tu pedazo de paraíso" campaign plan + queue builder.

The bilingual (🇸🇻 ES / 🇺🇸 EN) 14-post campaign Sebastian approved on
2026-07-10.  This module is the source of truth for the plan and turns a
day's spec into a real ig_queue.json item: it renders the 3 carousel
slides (via ig_campaign_poster) and assembles the bilingual caption +
first comment the publisher will post.

We roll out one post at a time (approved cadence: "starting with the next
upcoming post"), so this ships Day 1 — the "Escasez" inspiration post,
which is design-only (no listing photo) and therefore needs zero
photo-gate work.  Later days (the Top-10 posts) add hand-inspected photo
slides once the photo-gate is extended to homes/condos; their copy lives
on the approved review board and lands in follow-up increments.

Bilingual on the wire: Instagram captions are one text field, so we join
ES then EN with a thin divider.  The caption keeps ``**bold**`` markers —
the admin preview renders them and ig_publish._caption_for_ig strips them
before the Graph API call.

CLI:

    python3 -m automation.ig_campaign --day 1 --render          # render PNGs only
    python3 -m automation.ig_campaign --day 1 --render --apply  # + patch ig_queue.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from automation._atomic import atomic_write_text
from automation.ig_campaign_poster import CATEGORY_COLORS, render_slide

QUEUE_PATH = Path("web/data/ig_queue.json")
ASSETS_ROOT = Path("web/data/ig_assets/campaign")

# Bilingual wire divider (ES ⁄ EN) — a thin, neutral separator.
DIV = "\n\n· · ·\n\n"


def _bilingual(es: str, en: str, tail: str = "") -> str:
    out = f"{es}{DIV}{en}"
    if tail:
        out = f"{out}\n\n{tail}"
    return out


# ── the plan ───────────────────────────────────────────────────────────
# Each post: day id, ISO schedule, category color key, ribbon label, the
# 3 slide specs (see ig_campaign_poster for slide types), and bilingual
# caption/comment/hashtags.  Day 1 is fully live below.

PLAN: list[dict] = [
    {
        "day": 201,
        "slug": "d01_escasez",
        "kind": "inspira",
        "color_key": "inspiracion",
        "scheduled_for": "2026-07-11T01:00:00+00:00",
        "slides": [
            {"t": "statement", "eyebrow": "El Salvador",  # multi-country-exempt: hand-written SV marketing copy (Sebas-approved campaign)
             "l1": "La costa", "l2": "no crece.", "punch": "Pero la fila sí."},
            {"t": "stat", "big": "139",
             "label": "de 1,916 propiedades a la venta\nestán de verdad frente al mar",
             "src": "Datos Pulpo · jul 2026"},
            {"t": "usp", "eyebrow": "Cómo ayuda Pulpo", "title": "Las tenemos todas.",
             "body": "Rankeadas por valor, en un solo lugar. Vos escogés sin perder tiempo."},
        ],
        "capES": ("**La tierra frente al mar no se fabrica. Y ya casi no queda.**\n\n"
                  "De cada 1,916 propiedades a la venta en El Salvador, solo 139 están de "
                  "verdad frente al mar. Menos del 8%.\n\n"
                  "En Pulpo las tenemos todas juntas y rankeadas, para que veás las mejores "
                  "sin revisar mil sitios.\n\npulpo.club · link en bio"),
        "capEN": ("**Oceanfront land isn't being made — and there's barely any left.**\n\n"
                  "Of the 1,916 properties for sale in El Salvador, only 139 are truly "
                  "oceanfront. Under 8%.\n\n"
                  "At Pulpo we keep them all in one place, ranked, so you see the best "
                  "without digging through a dozen sites.\n\npulpo.club · link in bio"),
        "comES": ("Comparamos cada propiedad por precio, zona y acceso, y te mostramos solo "
                  "las mejores.\n\nRankeadas. El Top 10 en tu correo cada domingo.\n\npulpo.club"),
        "comEN": ("We compare every property by price, location, and access, and show you only "
                  "the best.\n\nRanked. The Top 10 in your inbox every Sunday.\n\npulpo.club"),
        "tags": ("#ElSalvador #BienesRaices #FrenteAlMar #SurfCity #Terrenos "
                 "#PlayasDeElSalvador #TuPedazoDeParaiso"),
    },
    # Days 202-214 (Top-10 + inspiration rotation) land in follow-up
    # increments as the photo-gate is extended to homes/condos.  Their
    # approved copy + slide specs live on the review board.
]

PLAN_BY_DAY = {p["day"]: p for p in PLAN}


# ── build ──────────────────────────────────────────────────────────────

def render_post(post: dict) -> dict:
    """Render a post's slides to PNGs under ASSETS_ROOT/<slug>/ and return
    a fully-formed ig_queue.json item (approved, not posted)."""
    color = CATEGORY_COLORS[post["color_key"]]
    out_dir = ASSETS_ROOT / post["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)

    slide_paths: list[str] = []
    for i, spec in enumerate(post["slides"], start=1):
        path = out_dir / f"slide{i}.png"
        render_slide(spec, color, path)
        slide_paths.append(str(path).replace("\\", "/"))

    caption = _bilingual(post["capES"], post["capEN"])
    comment = _bilingual(post["comES"], post["comEN"], tail=post["tags"])

    return {
        "day": post["day"],
        "shelf": f"campaign_{post['kind']}",
        "selector": "campaign_v1",
        "poster_type": "campaign",
        "palette": post["color_key"],
        "scheduled_for": post["scheduled_for"],
        "assets_dir": str(ASSETS_ROOT / post["slug"]).replace("\\", "/"),
        "poster_path": slide_paths[0],
        "poster_overrides": {},
        "caption": caption,
        "comment": comment,
        "lint_violations": [],
        "caption_status": "clean",
        "carousel_photo_paths": slide_paths[1:],
        "listing_ids": [],
        "primary_listing_id": None,
        "status": "scheduled",
        "approved": True,
        "posted": False,
        "posted_at": None,
        "posted_media_id": None,
    }


def patch_queue(item: dict, queue_path: Path = QUEUE_PATH) -> None:
    """Insert `item` into the queue and supersede the old-design pending
    items so the publisher's next due pick is this campaign post.

    Superseding = approved:false + status:"superseded_campaign_v1" on any
    still-unposted item that isn't part of campaign_v1.  Posted items are
    left untouched (history).  Idempotent: re-running replaces the same
    day id rather than duplicating it.
    """
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    items = data.get("items", [])

    superseded = 0
    for it in items:
        if it.get("posted"):
            continue
        if it.get("selector") == "campaign_v1":
            continue
        if it.get("approved"):
            it["approved"] = False
            it["status"] = "superseded_campaign_v1"
            superseded += 1

    items = [it for it in items if it.get("day") != item["day"]]
    items.append(item)
    items.sort(key=lambda it: it.get("scheduled_for") or "")
    data["items"] = items

    atomic_write_text(queue_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"queue patched: +day {item['day']}, superseded {superseded} old-design item(s)")


def _main() -> None:
    ap = argparse.ArgumentParser(description="Build a campaign post into the IG queue.")
    ap.add_argument("--day", type=int, required=True, help="campaign day id (e.g. 201) or 1-based index")
    ap.add_argument("--render", action="store_true", help="render the slide PNGs")
    ap.add_argument("--apply", action="store_true", help="patch ig_queue.json with the built item")
    args = ap.parse_args()

    # Accept either the day id (201) or the 1-based ordinal (1).
    post = PLAN_BY_DAY.get(args.day)
    if post is None and 1 <= args.day <= len(PLAN):
        post = PLAN[args.day - 1]
    if post is None:
        raise SystemExit(f"no plan entry for day {args.day}; known: {sorted(PLAN_BY_DAY)}")

    if not args.render:
        print(json.dumps(post, indent=2, ensure_ascii=False))
        return

    item = render_post(post)
    print(f"rendered {len(post['slides'])} slides → {item['assets_dir']}")
    if args.apply:
        patch_queue(item)
    else:
        print("(dry: not patching queue; pass --apply to write ig_queue.json)")


if __name__ == "__main__":
    _main()
