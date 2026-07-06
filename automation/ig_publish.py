"""ig_publish.py — publish the next due item from ig_queue.json to IG.

Pipeline per due item:

  1. Build the carousel slide list:
       slide_0  = poster_path  (HUNGRY TYPE etc. PNG rendered by ig_poster)
       slide_1+ = carousel_photo_paths  (local hero photos from ranked)
     All paths are converted to public HTTPS URLs at PULPO_PUBLIC_BASE_URL.

  2. Upload each slide as a media container:
       POST /{ig-user-id}/media?image_url=...&is_carousel_item=true
     → returns the container id

  3. Wait for every child container to reach status_code=FINISHED
     (polling /{container-id}?fields=status_code,status).

  4. Create the carousel container:
       POST /{ig-user-id}/media?media_type=CAROUSEL&children=...&caption=...
     → returns carousel container id

  5. Wait for the carousel container to reach FINISHED.

  6. Publish:
       POST /{ig-user-id}/media_publish?creation_id=...
     → returns published media id (the permalink we save to the queue).

  7. Mutate the queue item:
       posted=true, posted_at=<utc-iso>, posted_media_id=<id>
     Persist queue.json (atomic write).  Print one summary line.

Safety gates (all checked before any network call):

  - `IG_PAUSED` env var truthy   → log + exit 0 (skip the run entirely)
  - `--dry-run` flag             → log everything, write nothing
  - item.approved is not true    → skip (operator hasn't OKed it)
  - item.posted is already true  → skip (idempotent re-run)
  - item.scheduled_for in future → skip until the slot opens

One-item-per-invocation:  the cron runs hourly (see
.github/workflows/ig-publish.yml) and we deliberately publish at most
one item per run.  Guarantees we never burn the IG rate limit on a
runaway batch, and a single bad poster never poisons the whole drop —
the operator sees the failure in the next workflow log and fixes one
thing at a time.

CLI:

  python3 -m automation.ig_publish \\
      [--queue web/data/ig_queue.json] [--dry-run] [--now 2026-06-01T18:00:00Z]

`--now` lets the test suite freeze the clock.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import httpx

from automation._atomic import atomic_write_json
from automation._config import env_bool, env_int, env_str


# ── Graph API config ──────────────────────────────────────────────────

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
DEFAULT_PUBLIC_BASE_URL = "https://pulpo.club"

# Polling for media container readiness.  IG quotes "in seconds"; in
# practice carousel items finish in 3-10s, the carousel in another
# 5-15s.  60s budget per wait keeps us under the cron's 5-minute slot
# with margin for the publish call + queue mutation.
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 60


# ── path → public URL ────────────────────────────────────────────────

def _public_url(local_path: str, base_url: str) -> str:
    """Convert a `web/...` repo-relative path to a deployed HTTPS URL.

    IG's `/media?image_url=...` requires a publicly fetchable HTTPS URL —
    `file://` and presigned S3 URLs don't work.  Pulpo serves
    `web/data/*` and `web/photos/*` at `/data/*` and `/photos/*`
    respectively via Vercel static.  We strip the leading `web/`.
    """
    stripped = local_path.lstrip("/")
    if stripped.startswith("web/"):
        stripped = stripped[len("web/"):]
    if not stripped.startswith("/"):
        stripped = "/" + stripped
    return base_url.rstrip("/") + stripped


def _slide_urls(item: dict, base_url: str) -> list[str]:
    """Poster first, then carousel photos.  Hard-cap at 10 slides
    (Instagram carousel max)."""
    urls: list[str] = []
    if item.get("poster_path"):
        urls.append(_public_url(item["poster_path"], base_url))
    for p in (item.get("carousel_photo_paths") or []):
        urls.append(_public_url(p, base_url))
        if len(urls) >= 10:
            break
    return urls


# ── selection ────────────────────────────────────────────────────────

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # `datetime.fromisoformat` accepts the offset-aware ISO 8601 the
        # queue builder writes ("2026-06-02T01:00:00+00:00").  Plain "Z"
        # suffixes get a manual swap.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def select_next_due_item(
    items: list[dict], now: datetime
) -> Optional[dict]:
    """Return the earliest-scheduled item that is (approved, not posted,
    and due).  Returns None when there's nothing to publish."""
    due: list[tuple[datetime, dict]] = []
    for it in items:
        if not it.get("approved"):
            continue
        if it.get("posted"):
            continue
        sched = _parse_iso(it.get("scheduled_for"))
        if sched is None or sched > now:
            continue
        due.append((sched, it))
    if not due:
        return None
    due.sort(key=lambda t: t[0])
    return due[0][1]


def select_forced_item(items: list[dict], day: int) -> Optional[dict]:
    """Return the item for `day` IF it's approved + not posted.

    Used by --force-day (operator's "Publish now" button in /admin/ig-review).
    Bypasses the scheduled_for gate so the operator can test-publish ahead
    of the slot, but still respects approved + not-posted invariants:
    publishing an unapproved draft would defeat the review surface, and
    re-publishing a posted item would duplicate on IG.

    Returns None when the item is missing, unapproved, or already posted.
    """
    for it in items:
        if it.get("day") != day:
            continue
        if not it.get("approved"):
            return None
        if it.get("posted"):
            return None
        return it
    return None


# ── IG API thin client ───────────────────────────────────────────────

class IgClient:
    """Minimal httpx wrapper around the four Graph endpoints we hit.

    Methods are split so tests can mock at the http boundary
    (httpx.Client.post / get) and the publisher's flow logic stays
    testable in isolation."""

    def __init__(
        self,
        ig_user_id: str,
        access_token: str,
        *,
        client: Optional[httpx.Client] = None,
    ):
        self.ig_user_id = ig_user_id
        self.access_token = access_token
        self._client = client or httpx.Client(timeout=30.0)

    def upload_carousel_item(self, image_url: str) -> str:
        """Step 2.  Returns the container id."""
        r = self._client.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media",
            params={
                "image_url":        image_url,
                "is_carousel_item": "true",
                "access_token":     self.access_token,
            },
        )
        return self._extract_id(r, ctx="upload_carousel_item")

    def create_carousel(self, children: list[str], caption: str) -> str:
        """Step 4.  Returns the carousel container id."""
        r = self._client.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media",
            params={
                "media_type":   "CAROUSEL",
                "children":     ",".join(children),
                "caption":      caption,
                "access_token": self.access_token,
            },
        )
        return self._extract_id(r, ctx="create_carousel")

    def publish(self, creation_id: str) -> str:
        """Step 6.  Returns the published media id (a permanent permalink
        ref, NOT the container id)."""
        r = self._client.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media_publish",
            params={
                "creation_id":  creation_id,
                "access_token": self.access_token,
            },
        )
        return self._extract_id(r, ctx="publish")

    def container_status(self, container_id: str) -> str:
        """Graph returns one of {IN_PROGRESS, FINISHED, ERROR, PUBLISHED,
        EXPIRED}.  Used by wait_for_ready below."""
        r = self._client.get(
            f"{GRAPH_BASE}/{container_id}",
            params={
                "fields":       "status_code,status",
                "access_token": self.access_token,
            },
        )
        if r.status_code != 200:
            raise IgApiError(
                "container_status",
                f"HTTP {r.status_code}: {r.text[:200]}",
            )
        body = r.json() or {}
        return body.get("status_code") or body.get("status") or ""

    @staticmethod
    def _extract_id(r: httpx.Response, *, ctx: str) -> str:
        if r.status_code >= 400:
            raise IgApiError(ctx, f"HTTP {r.status_code}: {r.text[:300]}")
        body = r.json() or {}
        rid = body.get("id")
        if not rid:
            raise IgApiError(ctx, f"no id in response: {body!r}")
        return str(rid)


class IgApiError(RuntimeError):
    def __init__(self, ctx: str, detail: str):
        super().__init__(f"{ctx}: {detail}")
        self.ctx = ctx
        self.detail = detail


def wait_for_ready(
    client: IgClient,
    container_id: str,
    *,
    poll_interval: int = POLL_INTERVAL_S,
    timeout: int = POLL_TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Block until `container_id` reports FINISHED (or PUBLISHED for
    carousel containers IG sometimes pre-publishes).  Raises if the
    status reaches ERROR/EXPIRED or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while True:
        status = client.container_status(container_id)
        if status in ("FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise IgApiError(
                "wait_for_ready",
                f"container {container_id} terminal status={status!r}",
            )
        if time.monotonic() >= deadline:
            raise IgApiError(
                "wait_for_ready",
                f"container {container_id} stuck at status={status!r} after {timeout}s",
            )
        sleep(poll_interval)


# ── publish one item end-to-end ──────────────────────────────────────

def publish_item(
    client: IgClient,
    item: dict,
    base_url: str,
    *,
    waiter: Optional[Callable[[IgClient, str], None]] = None,
) -> dict:
    """Run the 6-step publish flow.  Mutates `item` in place + returns
    it for chaining.  Raises IgApiError on any irrecoverable failure.

    `waiter` is resolved at call time (not as a default arg) so the test
    suite can monkeypatch `automation.ig_publish.wait_for_ready` and
    have the patch take effect without threading the arg through every
    caller."""
    if waiter is None:
        waiter = wait_for_ready
    urls = _slide_urls(item, base_url)
    if not urls:
        raise IgApiError("publish_item", f"item d{item.get('day')} has no slides")

    # Step 2: upload each carousel item.
    children: list[str] = []
    for i, url in enumerate(urls):
        cid = client.upload_carousel_item(url)
        children.append(cid)
        print(f"  slide {i+1}/{len(urls)} uploaded → container {cid}")

    # Step 3: wait for every child container to be FINISHED.
    for cid in children:
        waiter(client, cid)

    # Step 4: create the carousel container with the caption.
    caption = (item.get("caption") or "").strip()
    carousel_id = client.create_carousel(children, caption)
    print(f"  carousel container created → {carousel_id}")

    # Step 5: wait for the carousel itself to be FINISHED.
    waiter(client, carousel_id)

    # Step 6: publish.
    media_id = client.publish(carousel_id)
    print(f"  published → media id {media_id}")

    item["posted"] = True
    item["posted_at"] = datetime.now(timezone.utc).isoformat()
    item["posted_media_id"] = media_id
    return item


# ── activity log ──────────────────────────────────────────────────────

DEFAULT_LOG = Path("web/data/ig_post_log.jsonl")


def _build_log_entry(item: dict, status: str, error: Optional[str] = None) -> dict:
    """One activity-log row for a single publish attempt.  Shape is read
    verbatim by api/admin/ig-log.js and rendered in the admin console's
    activity feed, so keep the keys stable."""
    caption = (item.get("caption") or "").replace("**", "").strip()
    preview = caption.split("\n", 1)[0][:90]
    entry = {
        "ts":              datetime.now(timezone.utc).isoformat(),
        "day":             item.get("day"),
        "shelf":           item.get("shelf"),
        "status":          status,   # "posted" | "failed"
        "caption_preview": preview,
        "slides":          1 + len(item.get("carousel_photo_paths") or []),
    }
    if status == "posted":
        entry["media_id"] = item.get("posted_media_id")
    if error:
        entry["error"] = str(error)[:300]
    return entry


def append_post_log(log_path: Path, entry: dict) -> None:
    """Append one JSON line to the activity log.  Defensive: a logging
    failure must never break or mask the publish result, so any error is
    swallowed with a breadcrumb."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:                                          # pragma: no cover
        print(f"[ig_publish] WARN could not write activity log: {e}", file=sys.stderr)


# ── top-level orchestration ──────────────────────────────────────────

def run_publish(
    queue_payload: dict,
    *,
    ig_user_id: str,
    access_token: str,
    base_url: str,
    now: datetime,
    dry_run: bool = False,
    client: Optional[IgClient] = None,
    force_day: Optional[int] = None,
    attempt_log: Optional[list] = None,
) -> dict:
    """Run the publisher against an in-memory queue payload.  Returns
    the (possibly mutated) payload.

    Pure-ish: doesn't read or write the filesystem.  The CLI wrapper
    handles I/O so tests don't need a tempfile.

    When `force_day` is set, publishes that specific item (if approved
    and not yet posted), bypassing the scheduled_for gate.  Used by the
    "Publish now" button in /admin/ig-review for on-the-spot test posts.

    `attempt_log`, when provided, receives one `_build_log_entry` dict per
    publish attempt (posted or failed) — the CLI persists these to the
    activity-log jsonl.  Default None keeps run_publish side-effect-free
    for tests that don't care about the log."""
    items = queue_payload.get("items") or []
    if force_day is not None:
        due = select_forced_item(items, force_day)
        if due is None:
            print(
                f"[ig_publish] forced d{force_day:02d} not eligible "
                f"(missing, unapproved, or already posted) — skipping"
            )
            return queue_payload
    else:
        due = select_next_due_item(items, now)
        if due is None:
            print(
                f"[ig_publish] no due items at {now.isoformat()} "
                f"(scanned {len(items)} queue entries)"
            )
            return queue_payload

    forced_tag = " FORCED" if force_day is not None else ""
    print(
        f"[ig_publish] publishing{forced_tag} d{due['day']:02d} ({due.get('shelf')}) "
        f"scheduled={due.get('scheduled_for')} "
        f"caption_status={due.get('caption_status')} "
        f"slides={1 + len(due.get('carousel_photo_paths') or [])}"
    )

    if dry_run:
        print("[ig_publish] DRY RUN — not calling Graph API, queue unchanged")
        return queue_payload

    ig = client or IgClient(ig_user_id, access_token)
    try:
        publish_item(ig, due, base_url)
        print(
            f"[ig_publish] OK d{due['day']:02d} → media_id={due['posted_media_id']} "
            f"at {due['posted_at']}"
        )
        if attempt_log is not None:
            attempt_log.append(_build_log_entry(due, "posted"))
    except IgApiError as e:
        print(f"[ig_publish] FAILED d{due['day']:02d}: {e}", file=sys.stderr)
        if attempt_log is not None:
            attempt_log.append(_build_log_entry(due, "failed", error=e))
        raise

    return queue_payload


# ── CLI ──────────────────────────────────────────────────────────────

DEFAULT_QUEUE = Path("web/data/ig_queue.json")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish the next due item from ig_queue.json to Instagram.",
    )
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument(
        "--log", type=Path, default=DEFAULT_LOG,
        help="Activity-log jsonl to append each publish attempt to.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log what would be published without calling the Graph API.",
    )
    parser.add_argument(
        "--now", default=None,
        help="ISO datetime to use as 'now' (mostly for tests).  Defaults to UTC now.",
    )
    parser.add_argument(
        "--force-day", type=int, default=None,
        help=(
            "Force-publish a specific queue day, bypassing the scheduled_for "
            "gate.  Still requires the item to be approved and not yet posted. "
            "Used by /admin/ig-review's Publish now button for test posts."
        ),
    )
    args = parser.parse_args(argv)

    if env_bool("IG_PAUSED", False):
        print("[ig_publish] IG_PAUSED=1 — skipping run")
        return 0

    if not args.queue.exists():
        print(f"[ig_publish] queue missing: {args.queue}", file=sys.stderr)
        return 2

    ig_user_id = env_str("IG_USER_ID", "")
    access_token = env_str("IG_ACCESS_TOKEN", "")
    base_url = env_str("PULPO_PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL)
    if not args.dry_run and not (ig_user_id and access_token):
        print(
            "[ig_publish] missing IG_USER_ID and/or IG_ACCESS_TOKEN env vars "
            "(use --dry-run to skip the network).",
            file=sys.stderr,
        )
        return 3

    if args.now:
        now = _parse_iso(args.now)
        if now is None:
            print(f"[ig_publish] --now {args.now!r} is not ISO 8601", file=sys.stderr)
            return 2
    else:
        now = datetime.now(timezone.utc)

    payload = json.loads(args.queue.read_text(encoding="utf-8"))
    attempts: list = []
    try:
        updated = run_publish(
            payload,
            ig_user_id=ig_user_id,
            access_token=access_token,
            base_url=base_url,
            now=now,
            dry_run=args.dry_run,
            force_day=args.force_day,
            attempt_log=attempts,
        )
    except IgApiError:
        # Record the failed attempt before re-raising so the admin
        # activity log shows failures, not just successes.
        if not args.dry_run:
            for entry in attempts:
                append_post_log(args.log, entry)
        raise

    if not args.dry_run:
        for entry in attempts:
            append_post_log(args.log, entry)
        atomic_write_json(args.queue, updated, indent=2)
        print(f"[ig_publish] queue persisted to {args.queue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Silence pyflakes on the env_int import — reserved for future config
# (e.g. IG_PUBLISH_POLL_TIMEOUT) without changing the import list.
_ = env_int
