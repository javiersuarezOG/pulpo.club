"""build_ig_batch.py — generate + render a wave of Social-Brain posts and stage
them into the IG publish queue as APPROVED, dripping one per day.

This is the go-live batch builder. It:
  1. generates N diversified posts (ig_generate_post) — real property mix,
     weighted to the viral angles, intriguing copy;
  2. renders each to real slide JPEGs (ig_render → ig_campaign_poster) — a
     curated zone photo opener where available, designed cards otherwise, and
     NO raw broker photos (so nothing needs per-photo watermark review);
  3. writes the queue items into web/data/ig_queue.json as approved + scheduled
     one-per-day from --start-date, so the hourly publisher drips them out once
     IG_PAUSED is lifted.

Safe by construction: every slide is either designed or the licensed zone photo.
The publisher is still gated by IG_PAUSED — this only STAGES; a human lifting
the pause is the go-live trigger.

    python3 scripts/build_ig_batch.py --n 6 --start-date 2026-08-02
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from automation import ig_generate_post as gen
from automation import ig_render

QUEUE = Path("web/data/ig_queue.json")


def _load_queue() -> list[dict]:
    if QUEUE.exists():
        data = json.loads(QUEUE.read_text())
        return data if isinstance(data, list) else data.get("items", [])
    return []


def _next_day(queue: list[dict]) -> int:
    days = [i.get("day", 0) for i in queue if isinstance(i.get("day"), int)]
    return (max(days) + 1) if days else 301


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--start-date", required=True, help="YYYY-MM-DD of the first post")
    ap.add_argument("--ranked", default="web/data/ranked.json")
    ap.add_argument("--approved", action="store_true",
                    help="stage as approved=True (default False → needs review)")
    ap.add_argument("--dry-run", action="store_true", help="render but don't write the queue")
    args = ap.parse_args()

    start = dt.date.fromisoformat(args.start_date)
    raw = json.loads(Path(args.ranked).read_text())
    items = raw if isinstance(raw, list) else raw.get("listings", [])
    queue = _load_queue()
    day0 = _next_day(queue)

    posts = gen.generate_batch(items, args.n, start_day=day0)
    staged: list[dict] = []
    for i, post in enumerate(posts):
        item = ig_render.render_post(post)
        sched = dt.datetime.combine(start + dt.timedelta(days=i),
                                    dt.time(1, 0)).isoformat() + "+00:00"
        item["scheduled_for"] = sched
        item["approved"] = bool(args.approved)
        staged.append(item)
        print(f"  day {item['day']} {post['lever']:14} {post['zone']:16} "
              f"opener={item['opener_kind']} slides={len(item['carousel_photo_paths'])+1} "
              f"→ {sched[:10]} approved={item['approved']}")

    if args.dry_run:
        print(f"\n[dry-run] {len(staged)} posts rendered, queue NOT written")
        return

    queue += staged
    QUEUE.write_text(json.dumps(queue, indent=1, ensure_ascii=False))
    print(f"\nstaged {len(staged)} posts into {QUEUE} (total {len(queue)} items)")


if __name__ == "__main__":
    main()
