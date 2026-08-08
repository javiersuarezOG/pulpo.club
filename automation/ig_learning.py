"""ig_learning.py — the Growth Hacker's scoreboard (the Learn half).

The publisher posts and the insights poller measures; this module is the
piece that *learns*. It joins per-post engagement
(``web/data/ig_insights.jsonl``) with each post's story / emotion /
category and scores which content dimensions earn the most engagement per
person reached, then writes a committed scoreboard
(``web/data/ig_learning.json``). The autopilot consults it (epsilon-greedy)
to bias future picks toward what works while still exploring —
``pick_weight`` / ``explore_or_exploit`` below are that consumer surface.

Metric — engagement-per-reach. saves + shares are the strongest reach
proxies (Instagram ranks by them), so they weigh most; comments next,
likes least. Views/likes on a tiny account are noisy, so the score is
normalized by reach and only trusted once a dimension has enough posts::

    raw   = 3*saved + 3*shares + 2*comments + 1*likes
    score = raw / max(reach, 1)          # engagement per person reached
    dim   = mean(score over that dimension's posts)  IF n >= MIN_SAMPLES
            else None                                 (neutral / cold-start)

Only rows that actually carry metrics count; the settled +72h reading is
preferred over the early +24h one for the same media. Metadata
(story_id / emotion / color_key) is read off the insights row when present
(post-2026-08-08 rows are self-describing) and otherwise resolved by
``day`` against a supplied queue — so the scoreboard works on historical
data too.

Contract: pure-ish, deterministic, soft-fail. ``build_scoreboard`` never
raises on a malformed row (it skips it); ``run`` writes atomically and
returns 0 on any I/O trouble. Offline/CI safe (no network, no token).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from automation._atomic import atomic_write_json

INSIGHTS_ARTIFACT = Path("web/data/ig_insights.jsonl")
QUEUE_PATH = Path("web/data/ig_queue.json")
LEARNING_ARTIFACT = Path("web/data/ig_learning.json")

# A dimension needs at least this many measured posts before its score is
# trusted; below it, the score is None (neutral) so one lucky/unlucky post
# never captures the whole feed. Deliberately low (3) because the account
# is small and we want the loop to start biasing early, but not on n=1.
MIN_SAMPLES = 3

# Engagement weights — saves & shares are the reach proxies IG rewards.
_W_SAVED = 3.0
_W_SHARES = 3.0
_W_COMMENTS = 2.0
_W_LIKES = 1.0

# The three dimensions the autopilot can steer on.
DIMENSIONS = ("story_id", "emotion", "color_key")


def engagement_score(metrics: dict) -> Optional[float]:
    """Engagement-per-reach for one post, or None if the row can't be
    scored (no metrics / no reach signal). Never raises."""
    if not isinstance(metrics, dict) or not metrics:
        return None

    def _n(key: str) -> float:
        v = metrics.get(key)
        return float(v) if isinstance(v, (int, float)) else 0.0

    reach = _n("reach")
    if reach <= 0:
        # Without reach we can't normalize; fall back to raw views so a
        # post with plays but no reach signal isn't silently dropped.
        reach = _n("views")
    if reach <= 0:
        return None
    raw = (_W_SAVED * _n("saved") + _W_SHARES * _n("shares")
           + _W_COMMENTS * _n("comments") + _W_LIKES * _n("likes"))
    return raw / reach


def _load_queue_metadata(queue_path: Path) -> dict:
    """Map day -> {story_id, emotion, color_key} from the queue's items.
    Used to resolve metadata for historical insights rows that predate the
    self-describing row format. Missing/broken queue → empty map."""
    try:
        raw = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = raw.get("items") if isinstance(raw, dict) else raw
    out: dict = {}
    for it in items or []:
        day = it.get("day")
        if day is None:
            continue
        out[day] = {
            "story_id": it.get("story_id"),
            "emotion": it.get("emotion"),
            "color_key": it.get("color_key"),
        }
    return out


def _resolve_meta(row: dict, queue_meta: dict) -> dict:
    """Prefer metadata stamped on the row; fall back to the queue by day."""
    meta = {k: row.get(k) for k in DIMENSIONS}
    if any(meta.values()):
        return meta
    return queue_meta.get(row.get("day"), {})


def _read_rows(insights_path: Path) -> list[dict]:
    try:
        text = insights_path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _best_per_media(rows: list[dict]) -> dict:
    """One scored reading per media_id — the settled +72h one wins over the
    +24h one; among equal maturities the last written wins."""
    best: dict = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        mid = r.get("media_id")
        if mid is None or engagement_score(r.get("metrics")) is None:
            continue
        prev = best.get(mid)
        if prev is None or (r.get("maturity_h") or 0) >= (prev.get("maturity_h") or 0):
            best[mid] = r
    return best


def build_scoreboard(
    rows: list[dict], queue_meta: Optional[dict] = None, *, now_iso: str = ""
) -> dict:
    """Pure: turn insights rows + queue metadata into the scoreboard dict.
    Deterministic; never raises on a bad row (skips it)."""
    queue_meta = queue_meta or {}
    scored = _best_per_media(rows)

    per_dim: dict = {d: defaultdict(list) for d in DIMENSIONS}
    n_posts = 0
    for row in scored.values():
        score = engagement_score(row.get("metrics"))
        if score is None:
            continue
        meta = _resolve_meta(row, queue_meta)
        counted = False
        for dim in DIMENSIONS:
            key = meta.get(dim)
            if key:
                per_dim[dim][key].append(score)
                counted = True
        n_posts += 1 if counted else 0

    out: dict = {
        "version": 1,
        "computed_at": now_iso,
        "n_posts_scored": n_posts,
        "min_samples": MIN_SAMPLES,
        "dimensions": {},
        "leaders": {},
    }
    for dim in DIMENSIONS:
        table: dict = {}
        for key, scores in per_dim[dim].items():
            n = len(scores)
            mean = sum(scores) / n if n else 0.0
            table[key] = {
                "score": round(mean, 5) if n >= MIN_SAMPLES else None,
                "n": n,
                "trusted": n >= MIN_SAMPLES,
            }
        out["dimensions"][dim] = table
        trusted = {k: v["score"] for k, v in table.items() if v["trusted"]}
        out["leaders"][dim] = max(trusted, key=trusted.get) if trusted else None
    return out


def pick_weight(scoreboard: dict, dimension: str, key: str) -> float:
    """Multiplier a selector can apply to `key` in `dimension`. 1.0 = neutral
    (untrusted / unknown). Trusted keys scale ~[0.5, 2.0] around the
    dimension's mean trusted score, so a proven winner is favored without a
    cold or thin key ever being zeroed out (exploration stays alive)."""
    table = (scoreboard.get("dimensions") or {}).get(dimension) or {}
    entry = table.get(key)
    if not entry or not entry.get("trusted") or entry.get("score") is None:
        return 1.0
    trusted_scores = [v["score"] for v in table.values()
                      if v.get("trusted") and v.get("score") is not None]
    if len(trusted_scores) < 2:
        return 1.0
    avg = sum(trusted_scores) / len(trusted_scores)
    if avg <= 0:
        return 1.0
    ratio = entry["score"] / avg
    return max(0.5, min(2.0, ratio))


def run(*, now: Optional[datetime] = None) -> int:
    """Build the scoreboard from disk and write it atomically. Returns the
    number of posts scored (0 on any trouble). Soft-fail, offline-safe."""
    now = now or datetime.now(timezone.utc)
    rows = _read_rows(INSIGHTS_ARTIFACT)
    queue_meta = _load_queue_metadata(QUEUE_PATH)
    board = build_scoreboard(rows, queue_meta, now_iso=now.isoformat())
    try:
        atomic_write_json(LEARNING_ARTIFACT, board)
    except OSError as err:  # pragma: no cover - disk trouble
        print(f"[ig_learning] write failed: {err}")
        return 0
    lead = board["leaders"]
    print(f"[ig_learning] scored {board['n_posts_scored']} post(s) → "
          f"story={lead.get('story_id')} emotion={lead.get('emotion')} "
          f"category={lead.get('color_key')} → {LEARNING_ARTIFACT}")
    return board["n_posts_scored"]


if __name__ == "__main__":  # pragma: no cover
    run()
