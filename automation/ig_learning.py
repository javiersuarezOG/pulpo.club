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
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from automation._atomic import atomic_write_json
from automation import posthog_query as _pq

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

# A signup is the money metric, so it dominates engagement when present:
# one signup per 100 people reached adds 0.5 to a post's score, dwarfing a
# typical engagement rate (~0.1). A Pro signup is worth PRO_MULT free ones.
_W_SIGNUP = 50.0
_PRO_MULT = 3.0

# The three dimensions the autopilot can steer on.
DIMENSIONS = ("story_id", "emotion", "color_key")


def _reach(metrics: dict) -> float:
    """The reach denominator for a post: reach, else views (Reels), else 0."""
    def _n(key: str) -> float:
        v = metrics.get(key)
        return float(v) if isinstance(v, (int, float)) else 0.0
    return _n("reach") or _n("views")


def engagement_score(metrics: dict) -> Optional[float]:
    """Engagement-per-reach for one post, or None if the row can't be
    scored (no metrics / no reach signal). Never raises."""
    if not isinstance(metrics, dict) or not metrics:
        return None
    reach = _reach(metrics)
    if reach <= 0:
        return None

    def _n(key: str) -> float:
        v = metrics.get(key)
        return float(v) if isinstance(v, (int, float)) else 0.0

    raw = (_W_SAVED * _n("saved") + _W_SHARES * _n("shares")
           + _W_COMMENTS * _n("comments") + _W_LIKES * _n("likes"))
    return raw / reach


def _signup_bonus(day, reach: float, signups_by_day: dict) -> float:
    """Reach-normalized, Pro-weighted signup term for a post's day. 0 when
    there's no attribution data for that day (v1 behavior)."""
    if not signups_by_day or reach <= 0:
        return 0.0
    sd = signups_by_day.get(day) or {}
    weighted = float(sd.get("free", 0)) + _PRO_MULT * float(sd.get("pro", 0))
    if weighted <= 0:
        return 0.0
    return _W_SIGNUP * weighted / reach


def parse_code_day(code) -> Optional[int]:
    """Extract the day from a /go attribution code 'ig-d<day>-<lever>[-pro]'.
    None if it isn't one of ours (so foreign utm_content is ignored)."""
    if not isinstance(code, str):
        return None
    m = re.match(r"^ig-d(\d{1,4})-", code.strip().lower())
    return int(m.group(1)) if m else None


def fetch_signups_by_day(*, window_days: int = 30) -> dict:
    """Query PostHog for IG-attributed signups grouped by post day. Free =
    newsletter.signup, Pro = webhook.checkout_completed, matched on the
    utm_content the /go router stamps. Returns {day: {'free': n, 'pro': m}};
    empty {} when the read key is absent or the query fails (soft-fail →
    engagement-only learning)."""
    hogql = (
        "SELECT properties.utm_content AS code, event, count() AS n "
        "FROM events "
        "WHERE event IN ('newsletter.signup', 'webhook.checkout_completed') "
        "AND properties.utm_content LIKE 'ig-d%' "
        f"AND timestamp > now() - INTERVAL {int(window_days)} DAY "
        "GROUP BY code, event"
    )
    rows = _pq.query(hogql)
    if not rows:
        return {}
    out: dict = {}
    for r in rows:
        day = parse_code_day(r.get("code"))
        if day is None:
            continue
        n = int(r.get("n") or 0)
        bucket = out.setdefault(day, {"free": 0, "pro": 0})
        if r.get("event") == "webhook.checkout_completed":
            bucket["pro"] += n
        else:
            bucket["free"] += n
    return out


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
    rows: list[dict], queue_meta: Optional[dict] = None,
    signups_by_day: Optional[dict] = None, *, now_iso: str = ""
) -> dict:
    """Pure: turn insights rows + queue metadata (+ optional attributed
    signups) into the scoreboard dict. Deterministic; never raises on a bad
    row (skips it). ``signups_by_day`` None/empty → engagement-only (v1)."""
    queue_meta = queue_meta or {}
    scored = _best_per_media(rows)

    per_dim: dict = {d: defaultdict(list) for d in DIMENSIONS}
    n_posts = 0
    total_signups = {"free": 0, "pro": 0}
    for day_sd in (signups_by_day or {}).values():
        total_signups["free"] += int(day_sd.get("free", 0))
        total_signups["pro"] += int(day_sd.get("pro", 0))
    for row in scored.values():
        eng = engagement_score(row.get("metrics"))
        if eng is None:
            continue
        # Blend the money metric in: engagement + reach-normalized signups.
        score = eng + _signup_bonus(row.get("day"), _reach(row.get("metrics") or {}),
                                    signups_by_day or {})
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
        "signups_attributed": total_signups,
        "scored_on": "engagement+signups" if signups_by_day else "engagement",
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
    # Money-metric half: attributed signups per post day (empty when the
    # PostHog read key is absent → engagement-only, exactly like v1).
    signups_by_day = fetch_signups_by_day()
    board = build_scoreboard(rows, queue_meta, signups_by_day, now_iso=now.isoformat())
    try:
        atomic_write_json(LEARNING_ARTIFACT, board)
    except OSError as err:  # pragma: no cover - disk trouble
        print(f"[ig_learning] write failed: {err}")
        return 0
    lead = board["leaders"]
    su = board["signups_attributed"]
    print(f"[ig_learning] scored {board['n_posts_scored']} post(s) on "
          f"{board['scored_on']} (signups free={su['free']} pro={su['pro']}) → "
          f"story={lead.get('story_id')} emotion={lead.get('emotion')} "
          f"category={lead.get('color_key')} → {LEARNING_ARTIFACT}")
    return board["n_posts_scored"]


if __name__ == "__main__":  # pragma: no cover
    run()
