"""ig_review_board.py — render a generated batch as an eyeball-able HTML board.

NOT part of the pipeline and NOT a publish path. It calls ig_generate_post to
produce N review posts, then writes a self-contained HTML board (photos
hot-linked from production, so it renders anywhere) to --out. A human opens it,
reads every caption + comment + attribution code, and decides. The board is the
human veto surface the Social Brain hangs off of — nothing reaches Instagram
without a person seeing this first.

    python3 scripts/ig_review_board.py --n 7 --out /tmp/board.html
"""
from __future__ import annotations

import argparse
import html
import json

from automation import ig_generate_post as gen

PHOTO_BASE = "https://pulpo.club"
LEVER_COLOR = {
    "scarcity": "#e8462a", "authority": "#1f6feb", "social_proof": "#8957e5",
    "aspiration": "#d4a017", "investment": "#2da44e", "transformation": "#cf222e",
    "education": "#0969da",
}


def _photo_url(path: str | None) -> str:
    if not path:
        return ""
    return path if path.startswith("http") else f"{PHOTO_BASE}{path}"


def _card(p: dict) -> str:
    e = html.escape
    color = LEVER_COLOR.get(p["lever"], "#57606a")
    price = f"${int(p['price_usd']):,}" if p.get("price_usd") else "—"
    facts = ", ".join(p.get("facts_cited") or []) or "—"
    return f"""
    <article class="card">
      <div class="ph"><img loading="lazy" src="{_photo_url(p.get('hero_photo_path'))}" alt=""></div>
      <div class="body">
        <div class="meta">
          <span class="lever" style="background:{color}">{e(p['lever'])}</span>
          <span class="tier">{e(p['tier'])}</span>
          <span class="day">day {p['day']}</span>
        </div>
        <div class="listing">{e(p.get('zone') or '')} · {price} · <code>{e(p['go_url'])}</code></div>
        <div class="cap-label">caption · ES</div><div class="cap">{e(p['caption_es'])}</div>
        <div class="cap-label">caption · EN</div><div class="cap en">{e(p['caption_en'])}</div>
        <div class="cap-label">first comment · ES</div><div class="cap sm">{e(p['comment_es'])}</div>
        <div class="cap-label">facts cited</div><div class="cap sm">{e(facts)}</div>
      </div>
    </article>"""


def render(batch: list[dict]) -> str:
    cards = "\n".join(_card(p) for p in batch)
    levers = ", ".join(sorted({p["lever"] for p in batch}))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Social Brain — review board</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#0d1117; color:#e6edf3; padding:24px; }}
  header {{ max-width:1200px; margin:0 auto 20px; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .sub {{ color:#8b949e; font-size:13px; }}
  .grid {{ max-width:1200px; margin:0 auto; display:grid;
          grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:18px; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:12px; overflow:hidden; }}
  .ph {{ aspect-ratio:4/3; background:#0d1117; }}
  .ph img {{ width:100%; height:100%; object-fit:cover; display:block; }}
  .body {{ padding:14px; }}
  .meta {{ display:flex; gap:8px; align-items:center; margin-bottom:8px; }}
  .lever {{ color:#fff; font-weight:600; font-size:11px; text-transform:uppercase;
           letter-spacing:.04em; padding:3px 8px; border-radius:20px; }}
  .tier {{ font-size:11px; color:#8b949e; text-transform:uppercase; border:1px solid #30363d;
          padding:2px 7px; border-radius:20px; }}
  .day {{ font-size:11px; color:#8b949e; margin-left:auto; }}
  .listing {{ font-size:12px; color:#8b949e; margin-bottom:10px; }}
  .listing code {{ color:#58a6ff; }}
  .cap-label {{ font-size:10px; text-transform:uppercase; letter-spacing:.05em;
               color:#6e7681; margin:10px 0 3px; }}
  .cap {{ white-space:pre-wrap; font-size:13.5px; }}
  .cap.en {{ color:#adbac7; }}
  .cap.sm {{ font-size:12px; color:#8b949e; }}
</style></head><body>
<header>
  <h1>🐙 Social Brain — review board</h1>
  <div class="sub">{len(batch)} generated posts · levers: {levers} · deterministic, nothing published.
  Read each caption; codes are live at <code>/go/…</code> for attribution once approved.</div>
</header>
<div class="grid">
{cards}
</div>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=7)
    ap.add_argument("--start-day", type=int, default=301)
    ap.add_argument("--ranked", default="web/data/ranked.json")
    ap.add_argument("--out", default="ig_review_board.html")
    args = ap.parse_args()

    raw = json.load(open(args.ranked))
    items = raw if isinstance(raw, list) else raw.get("listings", [])
    batch = gen.generate_batch(items, args.n, start_day=args.start_day)
    with open(args.out, "w") as f:
        f.write(render(batch))
    print(f"wrote {args.out} · {len(batch)} posts · "
          f"levers={sorted({p['lever'] for p in batch})}")


if __name__ == "__main__":
    main()
