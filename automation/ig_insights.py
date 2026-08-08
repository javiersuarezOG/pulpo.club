"""ig_insights.py — per-post Instagram insights poller (the Sense half).

The publisher fires a post and forgets it. This module closes that gap:
after a post matures (+24h and +72h), it pulls the per-post metrics the
Graph API still exposes — reach, saves, shares, likes, comments, video
views — into a committed artifact (web/data/ig_insights.jsonl). The
Growth Hacker later joins this with the /go router's attributed signups
to learn which post + lever converts.

Why +24h AND +72h: engagement keeps accruing for days; a single early
read undercounts saves/shares (the strongest reach proxies). Two reads
give an early signal and a settled number.

Reliable per-post metrics only: Meta deprecated per-post follows /
profile-visits / website-clicks (Jan 2025, Graph v21). We request the
survivors and store whatever the API returns — no metric is assumed
present, so a platform change degrades to a partial row, never a crash.

Design mirrors ig_publish: soft-fail (no token → skip, exit 0), mockable
at the httpx boundary, append-only artifact. Reads ig_post_log.jsonl for
posted media_ids; idempotent per (media_id, maturity).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

POST_LOG = Path("web/data/ig_post_log.jsonl")
INSIGHTS_ARTIFACT = Path("web/data/ig_insights.jsonl")

# The per-post metrics that survived the Jan-2025 deprecation. saved +
# shares are the strongest reach proxies (the Growth Hacker weights them).
# views covers Reels; the API omits it for images rather than erroring on
# the batch, and we store only what comes back.
METRICS = ["reach", "saved", "shares", "likes", "comments", "views", "total_interactions"]

# Poll a post at these ages (hours after posting).
MATURITIES_H = [24, 72]


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def read_posted(log_path: Optional[Path] = None) -> list[dict]:
    """Posted items with a media_id + parseable timestamp, newest last."""
    log_path = log_path or POST_LOG  # resolve global at call time (monkeypatchable)
    out: list[dict] = []
    if not log_path.exists():
        return out
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("status") == "posted" and e.get("media_id") and _parse_ts(e.get("ts", "")):
            out.append(e)
    return out


def already_polled(artifact: Optional[Path] = None) -> set[tuple[str, int]]:
    """(media_id, maturity_h) pairs already recorded — for idempotency."""
    artifact = artifact or INSIGHTS_ARTIFACT  # resolve global at call time
    seen: set[tuple[str, int]] = set()
    if not artifact.exists():
        return seen
    for line in artifact.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("media_id") and r.get("maturity_h") is not None:
            seen.add((r["media_id"], int(r["maturity_h"])))
    return seen


def due_polls(entry: dict, now: datetime, seen: set[tuple[str, int]]) -> list[int]:
    """Which maturities are due for this post and not yet recorded."""
    posted = _parse_ts(entry.get("ts", ""))
    if posted is None:
        return []
    due = []
    for h in MATURITIES_H:
        if (entry["media_id"], h) in seen:
            continue
        if now >= posted + timedelta(hours=h):
            due.append(h)
    return due


def fetch_media_insights(
    media_id: str, token: str, *, client: httpx.Client, base: str = GRAPH_BASE
) -> dict:
    """Return {metric: value} for a media id. Never raises: on any error
    or an unavailable-metric batch, returns whatever parsed (possibly {})
    so the caller records a partial row instead of losing the poll."""
    try:
        resp = client.get(
            f"{base}/{media_id}/insights",
            params={"metric": ",".join(METRICS), "access_token": token},
        )
    except httpx.HTTPError as err:
        print(f"[ig_insights] {media_id}: request failed ({err}) — partial")
        return {}
    if resp.status_code >= 400:
        # A single unavailable metric 400s the whole batch; retry with a
        # conservative core that every feed post supports.
        core = ["reach", "saved", "shares", "likes", "comments"]
        try:
            resp = client.get(
                f"{base}/{media_id}/insights",
                params={"metric": ",".join(core), "access_token": token},
            )
        except httpx.HTTPError:
            return {}
        if resp.status_code >= 400:
            print(f"[ig_insights] {media_id}: HTTP {resp.status_code} — {resp.text[:120]}")
            return {}
    out: dict = {}
    for item in (resp.json() or {}).get("data", []):
        name = item.get("name")
        values = item.get("values") or [{}]
        if name:
            out[name] = values[0].get("value")
    return out


def run(*, now: Optional[datetime] = None, client: Optional[httpx.Client] = None) -> int:
    """Poll all due posts and append their metrics. Returns rows written.
    Soft-fails to 0 when the token/user is missing (offline/CI)."""
    now = now or datetime.now(timezone.utc)
    token = _env_str("IG_ACCESS_TOKEN")
    if not token:
        print("[ig_insights] IG_ACCESS_TOKEN not set — skipping (0 rows)")
        return 0

    posts = read_posted()
    seen = already_polled()
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    written = 0
    try:
        for e in posts:
            for h in due_polls(e, now, seen):
                metrics = fetch_media_insights(e["media_id"], token, client=client)
                row = {
                    "media_id": e["media_id"],
                    "day": e.get("day"),
                    "shelf": e.get("shelf"),
                    # Carry the content dimensions forward (stamped on the
                    # post-log entry) so ig_learning can join engagement to
                    # story/emotion/category without re-reading the queue.
                    "story_id": e.get("story_id"),
                    "emotion": e.get("emotion"),
                    "color_key": e.get("color_key"),
                    "posted_at": e.get("ts"),
                    "polled_at": now.isoformat(),
                    "maturity_h": h,
                    "metrics": metrics,
                }
                INSIGHTS_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
                with INSIGHTS_ARTIFACT.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                seen.add((e["media_id"], h))
                written += 1
                print(f"[ig_insights] day {e.get('day')} @+{h}h → {metrics}")
    finally:
        if owns_client:
            client.close()
    print(f"[ig_insights] wrote {written} row(s)")
    return written


if __name__ == "__main__":
    run()
