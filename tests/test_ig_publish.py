"""Tests for automation/ig_publish.py.

Mocks the IG Graph API at the IgClient boundary so no network calls
fire and the publisher's gate logic + flow orchestration are tested
in isolation.

Resilience: tests/test_first_seen.py nukes sys.modules['automation.*'].
Tests that patch `automation.ig_publish.X` use the `pub` fixture below
to re-import the module, ensuring the patch targets the LIVE instance.
"""
from __future__ import annotations
import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_publish import (   # noqa: E402
    DEFAULT_PUBLIC_BASE_URL,
    IgApiError,
    IgClient,
    _parse_iso,
    _public_url,
    _slide_urls,
    main as publish_main,
    publish_item,
    run_publish,
    select_forced_item,
    select_next_due_item,
    wait_for_ready,
)


@pytest.fixture
def pub():
    """Re-import automation.ig_publish so module-attribute patches
    target the LIVE module even after test_first_seen nukes sys.modules.
    Used by the small subset of tests that monkey-patch module-level
    attributes (wait_for_ready, etc.)."""
    import automation.ig_publish as mod
    return importlib.reload(mod)


# ── _public_url ───────────────────────────────────────────────────────

@pytest.mark.parametrize("local,base,expected", [
    ("web/data/ig_assets/drop_01/d02__top_rank_1/poster.png",
     "https://pulpo.club",
     "https://pulpo.club/data/ig_assets/drop_01/d02__top_rank_1/poster.png"),
    ("web/photos/bienesraices_1529.hero.jpg",
     "https://pulpo.club",
     "https://pulpo.club/photos/bienesraices_1529.hero.jpg"),
    # Leading slash on the source path is tolerated.
    ("/web/photos/x.jpg",
     "https://pulpo.club",
     "https://pulpo.club/photos/x.jpg"),
    # base_url with trailing slash gets normalized.
    ("web/data/x.png",
     "https://pulpo.club/",
     "https://pulpo.club/data/x.png"),
    # Custom base URL (e.g. preview deploy) works.
    ("web/photos/x.jpg",
     "https://pulpo-club-pr-123.vercel.app",
     "https://pulpo-club-pr-123.vercel.app/photos/x.jpg"),
])
def test_public_url(local, base, expected):
    assert _public_url(local, base) == expected


# ── _slide_urls ───────────────────────────────────────────────────────

def test_slide_urls_poster_first():
    """Poster MUST be slide 1 — it's the brand cover, captures the
    swipe-right intent."""
    item = {
        "poster_path": "web/data/ig_assets/d02/poster.png",
        "carousel_photo_paths": [
            "web/photos/a.jpg",
            "web/photos/b.jpg",
        ],
    }
    urls = _slide_urls(item, DEFAULT_PUBLIC_BASE_URL)
    assert len(urls) == 3
    assert "poster.png" in urls[0]
    assert "a.jpg" in urls[1]
    assert "b.jpg" in urls[2]


def test_slide_urls_caps_at_10():
    """Instagram carousels max out at 10 slides — extras must be dropped
    silently rather than 400 the publish call."""
    item = {
        "poster_path": "web/data/p.png",
        "carousel_photo_paths": [f"web/photos/x{i}.jpg" for i in range(20)],
    }
    urls = _slide_urls(item, DEFAULT_PUBLIC_BASE_URL)
    assert len(urls) == 10


def test_slide_urls_handles_missing_poster():
    """If the poster wasn't rendered (e.g. needs_human), we still want
    to be able to publish the photos.  Returns photos only."""
    item = {"poster_path": None, "carousel_photo_paths": ["web/photos/x.jpg"]}
    urls = _slide_urls(item, DEFAULT_PUBLIC_BASE_URL)
    assert len(urls) == 1
    assert "x.jpg" in urls[0]


def test_slide_urls_empty():
    item = {"poster_path": None, "carousel_photo_paths": []}
    assert _slide_urls(item, DEFAULT_PUBLIC_BASE_URL) == []


# ── _parse_iso ────────────────────────────────────────────────────────

def test_parse_iso_offset_aware():
    d = _parse_iso("2026-06-02T01:00:00+00:00")
    assert d is not None
    assert d.tzinfo is not None
    assert d.year == 2026 and d.day == 2 and d.hour == 1


def test_parse_iso_z_suffix():
    """`Z` suffix isn't valid ISO 8601 for fromisoformat in 3.10-; we
    coerce it.  This format is what the queue builder writes (via
    isoformat()), but defensive against IG-side timestamps too."""
    d = _parse_iso("2026-06-02T01:00:00Z")
    assert d is not None
    assert d.hour == 1


def test_parse_iso_invalid():
    assert _parse_iso(None) is None
    assert _parse_iso("") is None
    assert _parse_iso("not-a-date") is None


# ── select_next_due_item ──────────────────────────────────────────────

def _it(**kw):
    base = {
        "day": 1, "shelf": "test", "scheduled_for": "2026-06-01T01:00:00+00:00",
        "poster_path": "web/data/p.png",
        "carousel_photo_paths": [],
        "approved": False, "posted": False, "caption": "x",
    }
    base.update(kw)
    return base


def test_select_skips_unapproved():
    now = datetime(2026, 6, 1, 5, 0, tzinfo=timezone.utc)
    items = [_it(day=1, approved=False)]
    assert select_next_due_item(items, now) is None


def test_select_skips_already_posted():
    now = datetime(2026, 6, 1, 5, 0, tzinfo=timezone.utc)
    items = [_it(day=1, approved=True, posted=True)]
    assert select_next_due_item(items, now) is None


def test_select_skips_future():
    """An approved item scheduled for tomorrow doesn't get published
    today.  Earliest scheduling rules."""
    now = datetime(2026, 6, 1, 5, 0, tzinfo=timezone.utc)
    items = [_it(day=1, approved=True, scheduled_for="2026-06-02T01:00:00+00:00")]
    assert select_next_due_item(items, now) is None


def test_select_picks_earliest_due():
    """When multiple items are due, take the one with the earliest
    scheduled_for so the calendar drift stays bounded."""
    now = datetime(2026, 6, 5, 5, 0, tzinfo=timezone.utc)
    items = [
        _it(day=3, approved=True, scheduled_for="2026-06-03T01:00:00+00:00"),
        _it(day=1, approved=True, scheduled_for="2026-06-01T01:00:00+00:00"),
        _it(day=2, approved=True, scheduled_for="2026-06-02T01:00:00+00:00"),
    ]
    pick = select_next_due_item(items, now)
    assert pick is not None
    assert pick["day"] == 1


def test_select_skips_items_without_scheduled_for():
    """A queue item with no scheduled_for (operator-edited, half-built)
    must not crash the publisher — silent skip is the safe move."""
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)
    items = [_it(day=1, approved=True, scheduled_for=None)]
    assert select_next_due_item(items, now) is None


# ── select_forced_item (operator's "Publish now" path) ────────────────

def test_force_picks_approved_unposted_even_when_scheduled_future():
    """The whole point of force-day: bypass the scheduled_for gate so
    an item scheduled for tomorrow can be test-published today."""
    items = [_it(day=3, approved=True, scheduled_for="2026-07-01T01:00:00+00:00")]
    pick = select_forced_item(items, day=3)
    assert pick is not None
    assert pick["day"] == 3


def test_force_returns_none_for_unapproved():
    """The approved gate is the operator's safety net — never bypass it
    just because the day matches."""
    items = [_it(day=3, approved=False)]
    assert select_forced_item(items, day=3) is None


def test_force_returns_none_for_posted():
    """Posted items must NEVER be re-published — would duplicate on IG."""
    items = [_it(day=3, approved=True, posted=True)]
    assert select_forced_item(items, day=3) is None


def test_force_returns_none_for_missing_day():
    """Operator may submit a stale day from a refresh-race; clean skip
    rather than crash."""
    items = [_it(day=1, approved=True), _it(day=2, approved=True)]
    assert select_forced_item(items, day=99) is None


def test_force_does_not_pick_a_different_day():
    """Even if day 1 is the natural next-due, --force-day 5 must
    return day 5 (not day 1)."""
    items = [
        _it(day=1, approved=True, scheduled_for="2026-06-01T01:00:00+00:00"),
        _it(day=5, approved=True, scheduled_for="2026-06-05T01:00:00+00:00"),
    ]
    pick = select_forced_item(items, day=5)
    assert pick is not None and pick["day"] == 5


# ── publish_item with mock IgClient ───────────────────────────────────

def _mock_client():
    """IgClient stand-in that returns deterministic ids."""
    client = MagicMock(spec=IgClient)
    client.upload_carousel_item.side_effect = (
        lambda url: f"cid::{url.rsplit('/', 1)[-1]}"
    )
    client.create_carousel.side_effect = (
        lambda children, caption: f"carousel::{len(children)}slides"
    )
    client.publish.side_effect = lambda creation_id: "media_17841234567890"
    return client


def test_publish_item_full_flow_mutates_item():
    item = _it(
        day=2, approved=True, caption="**Caption.**",
        poster_path="web/data/ig_assets/p.png",
        carousel_photo_paths=["web/photos/a.jpg", "web/photos/b.jpg"],
    )
    client = _mock_client()
    waiter = MagicMock()                         # skip the real polling

    publish_item(client, item, "https://pulpo.club", waiter=waiter)

    # Uploaded 3 slides (poster + 2 photos)
    assert client.upload_carousel_item.call_count == 3
    # Created 1 carousel with 3 children
    assert client.create_carousel.call_count == 1
    children = client.create_carousel.call_args[0][0]
    assert len(children) == 3
    # Markdown bold markers are stripped for the plain-text IG caption.
    assert client.create_carousel.call_args[0][1] == "Caption."
    # Published once
    assert client.publish.call_count == 1
    # Waiter called for each child + once for the carousel = 4 calls
    assert waiter.call_count == 4
    # Item mutated
    assert item["posted"] is True
    assert item["posted_media_id"] == "media_17841234567890"
    assert item["posted_at"]


def test_publish_item_raises_without_slides():
    item = _it(day=1, approved=True, poster_path=None, carousel_photo_paths=[])
    client = _mock_client()
    with pytest.raises(IgApiError, match="no slides"):
        publish_item(client, item, "https://pulpo.club", waiter=MagicMock())


def test_publish_item_caption_strips_whitespace():
    item = _it(
        day=1, approved=True, caption="   leading + trailing\n\n",
        poster_path="web/data/p.png",
    )
    client = _mock_client()
    publish_item(client, item, "https://pulpo.club", waiter=MagicMock())
    caption_arg = client.create_carousel.call_args[0][1]
    assert caption_arg == "leading + trailing"


# ── run_publish orchestrator ──────────────────────────────────────────

def test_run_publish_returns_unchanged_when_nothing_due():
    """Common case (most hourly runs): no approved+due+unposted items —
    the function exits with no mutation."""
    now = datetime(2026, 6, 1, 5, 0, tzinfo=timezone.utc)
    payload = {
        "version": 1,
        "items": [_it(day=1, approved=False)],
    }
    result = run_publish(
        payload, ig_user_id="x", access_token="y",
        base_url="https://pulpo.club", now=now,
        client=_mock_client(),
    )
    assert result["items"][0]["posted"] is False


def test_run_publish_dry_run_skips_network():
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)
    payload = {
        "version": 1,
        "items": [_it(day=1, approved=True, poster_path="web/data/p.png")],
    }
    client = _mock_client()
    run_publish(
        payload, ig_user_id="x", access_token="y",
        base_url="https://pulpo.club", now=now,
        dry_run=True, client=client,
    )
    # No API calls fired in dry-run
    client.upload_carousel_item.assert_not_called()
    client.publish.assert_not_called()
    # Item NOT marked posted (so the next non-dry run can publish it)
    assert payload["items"][0]["posted"] is False


def test_run_publish_marks_item_posted(pub):
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)
    payload = {
        "version": 1,
        "items": [_it(
            day=1, approved=True, posted=False,
            scheduled_for="2026-06-01T01:00:00+00:00",
            caption="x", poster_path="web/data/p.png",
            carousel_photo_paths=["web/photos/a.jpg"],
        )],
    }
    client = _mock_client()
    with patch.object(pub, "wait_for_ready") as waiter:
        pub.run_publish(
            payload, ig_user_id="x", access_token="y",
            base_url="https://pulpo.club", now=now,
            client=client,
        )
    assert payload["items"][0]["posted"] is True
    assert payload["items"][0]["posted_media_id"] == "media_17841234567890"
    # 2 children (poster + 1 photo) + 1 carousel container = 3 waits.
    assert waiter.call_count == 3


def test_run_publish_force_day_picks_future_scheduled_item(pub):
    """The whole point of --force-day: skip the scheduled_for gate.
    Day 5 is scheduled a month out; force-publishing day 5 today must
    pick it (since it's approved + not posted)."""
    now = datetime(2026, 6, 1, 5, 0, tzinfo=timezone.utc)
    payload = {
        "version": 1,
        "items": [
            _it(day=1, approved=False, scheduled_for="2026-06-01T01:00:00+00:00"),
            _it(
                day=5, approved=True, posted=False,
                scheduled_for="2026-07-05T01:00:00+00:00",  # weeks out
                caption="x", poster_path="web/data/p5.png",
                carousel_photo_paths=["web/photos/a.jpg"],
            ),
        ],
    }
    client = _mock_client()
    with patch.object(pub, "wait_for_ready"):
        pub.run_publish(
            payload, ig_user_id="x", access_token="y",
            base_url="https://pulpo.club", now=now,
            client=client, force_day=5,
        )
    items_by_day = {it["day"]: it for it in payload["items"]}
    assert items_by_day[5]["posted"] is True
    assert items_by_day[1]["posted"] is False


def test_run_publish_force_day_skips_unapproved_item():
    """Force-day must still refuse to publish unapproved drafts —
    bypassing the approved gate would defeat the review surface."""
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)
    payload = {
        "version": 1,
        "items": [_it(day=3, approved=False, poster_path="web/data/p.png")],
    }
    client = _mock_client()
    result = run_publish(
        payload, ig_user_id="x", access_token="y",
        base_url="https://pulpo.club", now=now,
        client=client, force_day=3,
    )
    client.upload_carousel_item.assert_not_called()
    assert result["items"][0]["posted"] is False


# ── wait_for_ready ────────────────────────────────────────────────────

def test_wait_for_ready_returns_when_finished():
    client = MagicMock(spec=IgClient)
    client.container_status.side_effect = ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]
    sleeps = []
    wait_for_ready(
        client, "cid_1",
        poll_interval=1, timeout=30,
        sleep=lambda s: sleeps.append(s),
    )
    assert client.container_status.call_count == 3
    assert sleeps == [1, 1]  # one sleep between each non-FINISHED poll


def test_wait_for_ready_returns_for_published_status():
    """Carousel containers can transition straight to PUBLISHED."""
    client = MagicMock(spec=IgClient)
    client.container_status.return_value = "PUBLISHED"
    wait_for_ready(client, "cid", poll_interval=1, timeout=10, sleep=lambda _: None)
    client.container_status.assert_called_once()


def test_wait_for_ready_raises_on_error_status():
    client = MagicMock(spec=IgClient)
    client.container_status.return_value = "ERROR"
    with pytest.raises(IgApiError, match="terminal status='ERROR'"):
        wait_for_ready(
            client, "cid", poll_interval=1, timeout=10,
            sleep=lambda _: None,
        )


def test_wait_for_ready_times_out():
    """Stuck IN_PROGRESS for longer than `timeout` raises."""
    client = MagicMock(spec=IgClient)
    client.container_status.return_value = "IN_PROGRESS"
    # Use a monotonic mock so timeout = 0 fires immediately.
    times = iter([0.0, 100.0, 200.0])
    with patch("time.monotonic", lambda: next(times)):
        with pytest.raises(IgApiError, match="stuck at status"):
            wait_for_ready(
                client, "cid", poll_interval=1, timeout=50,
                sleep=lambda _: None,
            )


# ── CLI ──────────────────────────────────────────────────────────────

def test_main_dry_run_with_queue_writes_no_mutation(tmp_path):
    """Smoke the CLI dry-run path: parses queue, finds no due items,
    exits 0 without mutating the file."""
    qp = tmp_path / "ig_queue.json"
    initial = {"version": 1, "items": [_it(day=1, approved=False)]}
    qp.write_text(json.dumps(initial))

    rc = publish_main([
        "--queue", str(qp),
        "--dry-run",
        "--now", "2026-06-05T05:00:00+00:00",
    ])
    assert rc == 0
    # Dry-run doesn't write; file content unchanged.
    after = json.loads(qp.read_text())
    assert after == initial


def test_main_requires_token_unless_dry_run(tmp_path, monkeypatch):
    qp = tmp_path / "q.json"
    qp.write_text(json.dumps({"version": 1, "items": []}))
    monkeypatch.delenv("IG_USER_ID", raising=False)
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("IG_PAUSED", raising=False)
    rc = publish_main(["--queue", str(qp)])
    assert rc == 3


def test_main_ig_paused_short_circuits(tmp_path, monkeypatch):
    qp = tmp_path / "q.json"
    qp.write_text(json.dumps({"version": 1, "items": []}))
    monkeypatch.setenv("IG_PAUSED", "1")
    rc = publish_main(["--queue", str(qp), "--dry-run"])
    assert rc == 0


def test_main_missing_queue(tmp_path, monkeypatch):
    monkeypatch.delenv("IG_PAUSED", raising=False)
    rc = publish_main(["--queue", str(tmp_path / "nope.json"), "--dry-run"])
    assert rc == 2


def test_main_invalid_now_format(tmp_path, monkeypatch):
    qp = tmp_path / "q.json"
    qp.write_text(json.dumps({"version": 1, "items": []}))
    monkeypatch.delenv("IG_PAUSED", raising=False)
    rc = publish_main([
        "--queue", str(qp), "--dry-run",
        "--now", "not-a-date",
    ])
    assert rc == 2


# ── IgClient.upload_carousel_item / _extract_id ──────────────────────

def test_ig_client_extract_id_success():
    r = MagicMock(status_code=200)
    r.json.return_value = {"id": "9876"}
    assert IgClient._extract_id(r, ctx="x") == "9876"


def test_ig_client_extract_id_raises_on_4xx():
    r = MagicMock(status_code=400)
    r.text = '{"error":{"message":"Invalid image_url"}}'
    with pytest.raises(IgApiError, match="HTTP 400"):
        IgClient._extract_id(r, ctx="upload")


def test_ig_client_extract_id_raises_on_missing_id():
    r = MagicMock(status_code=200)
    r.json.return_value = {"weird": "shape"}
    with pytest.raises(IgApiError, match="no id"):
        IgClient._extract_id(r, ctx="upload")


# ── caption sanitizer (bold markers must not leak to IG) ─────────────

def test_caption_for_ig_strips_bold_markers():
    from automation.ig_publish import _caption_for_ig
    stored = (
        "**Todos los terrenos de El Salvador, rankeados cada semana.**\n\n"
        "Un solo lugar para ver lo que de verdad vale la pena.\n\n"
        "pulpo.club · link en bio"
    )
    out = _caption_for_ig(stored)
    assert "**" not in out
    assert out.startswith("Todos los terrenos")
    # body + CTA preserved verbatim
    assert "pulpo.club · link en bio" in out
    assert "de verdad vale la pena" in out


def test_caption_for_ig_leaves_single_asterisk_alone():
    from automation.ig_publish import _caption_for_ig
    assert _caption_for_ig("3 * 4 metros") == "3 * 4 metros"


def test_publish_item_sends_clean_caption(monkeypatch):
    """The caption handed to create_carousel carries no `**`."""
    from automation import ig_publish
    client = MagicMock()
    client.upload_carousel_item.side_effect = ["c1", "c2"]
    client.create_carousel.return_value = "car1"
    client.publish.return_value = "media123"
    item = {
        "day": 100,
        "caption": "**Bold hook.**\n\nbody.",
        "poster_path": "web/data/ig_assets/x/slide1.png",
        "carousel_photo_paths": ["web/data/ig_assets/x/slide2.png"],
    }
    ig_publish.publish_item(client, item, "https://pulpo.club", waiter=lambda *_: None)
    sent_caption = client.create_carousel.call_args.args[1]
    assert "**" not in sent_caption
    assert sent_caption.startswith("Bold hook.")
