"""Tests for automation/ig_autopilot.py — the self-running story generator.

Renders are stubbed (skip_render / injected fakes) so no Playwright or
network fires; we assert the queue-shaping invariants: every post shows a
real listing via the brand-safe hero, is auto-approved, carries a
lint-clean caption + first comment, and the stories rotate with no repeat.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_autopilot import (   # noqa: E402
    build_item,
    prepare_listing_photos,
    topup,
    _future_approved_count,
    _next_slot,
    _next_day,
    _pick_candidate,
)
from automation.ig_story_series import STORIES, story_for_index   # noqa: E402
from automation.ig_caption_lint import check as lint_check   # noqa: E402


def _cand(lid, rank=50.0, zone="el-tunco"):
    src, sid = lid.split("__")
    return {
        "listing_id": lid, "source": src, "source_id": sid,
        "rank": rank, "rank_score": rank, "zone": zone,
        "area_m2": 1500.0, "price_usd": 200000.0, "hero_photo_quality_score": 100,
    }


CANDS = [_cand(f"src__{i}", rank=100 - i, zone=f"z{i}") for i in range(20)]
RANKED_INDEX = {c["listing_id"]: {"photo_urls": ["http://x/1", "http://x/2"]} for c in CANDS}
NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _fake_render(spec, color, out):
    return out  # no I/O


def _fake_photos(listing, assets_dir, slug, want=2, **_):
    return [f"web/data/ig_assets/autopilot/{slug}/photo_{i + 1}.jpg" for i in range(want)]


def _run(queue, lookahead=4, cadence=1, photo_preparer=_fake_photos):
    return topup(
        queue, CANDS, RANKED_INDEX, now=NOW, lookahead=lookahead, cadence_days=cadence,
        assets_root=Path("/tmp/x"), skip_render=True,
        slide_renderer=_fake_render, photo_preparer=photo_preparer,
    )


# ── every post is a story, auto-approved, lint-clean ──────────────────

def test_every_item_is_a_lintclean_approved_story():
    added = _run({"items": []}, lookahead=5)
    assert len(added) == 5
    for it in added:
        assert it["format"] == "story"
        assert it["story_id"] and it["emotion"]
        assert it["approved"] is True and it["posted"] is False
        assert it["primary_listing_id"]
        assert it["poster_path"].endswith(".png")
        assert it["caption_status"] == "clean"
        assert lint_check(it["caption"]) == []
        assert lint_check(it["comment"]) == []


def test_stories_rotate_with_no_repeat_in_a_cycle():
    added = _run({"items": []}, lookahead=len(STORIES))
    ids = [it["story_id"] for it in added]
    assert len(set(ids)) == len(ids), "a story repeated inside one 14-post cycle"
    assert ids == [story_for_index(i)["id"] for i in range(len(added))]


def test_post_is_cover_plus_photofree_closer():
    added = _run({"items": []}, lookahead=1)
    it = added[0]
    slides = [it["poster_path"], *it["carousel_photo_paths"]]
    assert len(slides) == 2, "story = cover + brand closer"
    assert it["shelf"] == "autopilot_story"


def test_comment_whispers_details_with_hashtags():
    added = _run({"items": []}, lookahead=3)
    for it in added:
        assert it["comment"] and "#" in it["comment"] and "pulpo.club" in it["comment"]


# ── scheduling + dedup ────────────────────────────────────────────────

def test_cadence_spacing_and_future_only():
    added = _run({"items": []}, lookahead=3)
    days = [datetime.fromisoformat(it["scheduled_for"]).date() for it in added]
    assert (days[1] - days[0]).days == 1 and (days[2] - days[1]).days == 1
    assert all(datetime.fromisoformat(it["scheduled_for"]) > NOW for it in added)


def test_does_not_refeature_recent_listings():
    added = _run({"items": []}, lookahead=6)
    lids = [it["primary_listing_id"] for it in added]
    assert len(set(lids)) == len(lids)


def test_topup_stops_at_lookahead():
    q = {"items": []}
    _run(q, lookahead=3)
    assert _run(q, lookahead=3) == []


def test_skipped_items_dont_count_as_future():
    q = {"items": [{"day": 100, "selector": "autopilot", "approved": False,
                    "skipped": True, "posted": False,
                    "scheduled_for": "2026-07-20T01:00:00+00:00"}]}
    assert _future_approved_count(q["items"], NOW) == 0


def test_next_day_increments():
    assert _next_day([]) == 101
    assert _next_day([{"day": 105}, {"day": 100}]) == 106


# ── photo-quality gate (brand safety) ─────────────────────────────────

def test_pick_candidate_quality_gate_beats_rank():
    cands = [{"listing_id": "a__1", "hero_photo_quality_score": 80, "rank": 99},
             {"listing_id": "a__2", "hero_photo_quality_score": 100, "rank": 40}]
    assert _pick_candidate(cands, set())["listing_id"] == "a__2"


def test_build_item_returns_none_without_a_photo():
    def _no_photos(listing, assets_dir, slug, want=2, **_):
        return []
    item = build_item(
        day=101, story=STORIES[0], candidate=_cand("src__0"), listing={},
        scheduled_for="2026-07-07T01:00:00+00:00", assets_root=Path("/tmp/x"),
        skip_render=True, slide_renderer=_fake_render, photo_preparer=_no_photos,
    )
    assert item is None


# ── BRAND-SAFE photo selection (the day-218 regression guard) ─────────

def test_prepare_photos_uses_gate_order_and_drops_rejected(tmp_path):
    """The day-218 broker-phone cover came from raw photo_urls[0]. The fix
    routes through the gate's order_photo_indices: hero first, and any frame
    in photo_urls_rejected (broker flyers / logos) dropped entirely."""
    from PIL import Image
    urls = ["http://x/flyer_broker.jpg",   # idx 0 — a rejected broker graphic
            "http://x/hero.jpg",           # idx 1 — the hero
            "http://x/nice.jpg"]           # idx 2 — clean extra
    listing = {
        "photo_urls": urls, "photos_count": 3,
        "selected_photo_url": "http://x/hero.jpg",          # hero = idx 1
        "photo_urls_rejected": ["http://x/flyer_broker.jpg"],  # broker flyer dropped
    }
    fetched: list[str] = []

    def _fetch(url):
        fetched.append(url)
        return Image.new("RGB", (1080, 1350), (30, 90, 140))

    out = prepare_listing_photos(listing, tmp_path, "d999__el_mar", want=2, fetcher=_fetch)
    # the broker flyer is never even fetched…
    assert "http://x/flyer_broker.jpg" not in fetched
    # …and the hero leads the order.
    assert fetched[0] == "http://x/hero.jpg"
    assert len(out) == 2
