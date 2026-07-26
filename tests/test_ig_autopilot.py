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
    select_beautiful_cover,
    topup,
    _beauty,
    _future_approved_count,
    _next_slot,
    _next_day,
    _ordered_fresh_urls,
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


def _fake_selector(listing, assets_dir, slug, *, used_urls=frozenset(), **_):
    # a unique gorgeous cover per listing/day; honours the never-reuse ledger
    url = f"http://x/{slug}.jpg"
    if url in used_urls:
        return None
    return f"web/data/ig_assets/autopilot/{slug}/photo_1.jpg", url


def _run(queue, lookahead=4, cadence=1, photo_selector=_fake_selector):
    return topup(
        queue, CANDS, RANKED_INDEX, now=NOW, lookahead=lookahead, cadence_days=cadence,
        assets_root=Path("/tmp/x"), skip_render=True,
        slide_renderer=_fake_render, photo_selector=photo_selector,
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
        assert it["poster_path"].endswith(".jpg")   # JPEG (deploy-size fix)
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


# ── beauty gate (perfect pics) + scheduling ───────────────────────────

def test_beauty_scores_scenic_over_dull():
    clean_ocean, s1 = _beauty({"has_ocean_view": True, "dist_beach_km": 0.2})
    clean_dull, s2 = _beauty({"dist_beach_km": 40})
    flagged, s3 = _beauty({"hires_aesthetic_issues": ["uninteresting"], "has_ocean_view": True})
    assert clean_ocean and s1 >= 5          # ocean(3)+coast(2)
    assert clean_dull and s2 == 0
    assert flagged is False                 # aesthetic issue → not clean


def test_pick_candidate_beauty_gate_prefers_scenic_clean():
    cands = [
        {"listing_id": "d__1", "hero_photo_quality_score": 100, "rank_score": 99},  # dull, top rank
        {"listing_id": "s__1", "hero_photo_quality_score": 100, "rank_score": 40},  # scenic+clean
        {"listing_id": "u__1", "hero_photo_quality_score": 100, "rank_score": 95},  # uninteresting
    ]
    rindex = {
        "d__1": {"dist_beach_km": 50},
        "s__1": {"has_ocean_view": True, "dist_beach_km": 0.3},
        "u__1": {"hires_aesthetic_issues": ["uninteresting"], "has_ocean_view": True},
    }
    # beauty gate on → the scenic+clean one wins despite lower rank
    assert _pick_candidate(cands, set(), rindex)["listing_id"] == "s__1"
    # no ranked_index → falls back to pure rank (back-compat)
    assert _pick_candidate(cands, set())["listing_id"] == "d__1"


def test_pick_candidate_beauty_falls_back_to_clean_when_no_scenic():
    cands = [{"listing_id": "d__1", "hero_photo_quality_score": 100, "rank_score": 50},
             {"listing_id": "u__1", "hero_photo_quality_score": 100, "rank_score": 90}]
    rindex = {"d__1": {"dist_beach_km": 40},                                  # clean, not scenic
              "u__1": {"hires_aesthetic_issues": ["uninteresting"]}}          # flagged
    # no scenic option → prefer the merely-clean one over the flagged one
    assert _pick_candidate(cands, set(), rindex)["listing_id"] == "d__1"


def test_next_slot_ignores_skipped_items():
    # a skipped post scheduled far out must NOT push the next slot past it
    items = [
        {"scheduled_for": "2026-07-25T01:00:00+00:00", "posted": True},        # latest real
        {"scheduled_for": "2026-07-31T01:00:00+00:00", "skipped": True},        # freed slot
    ]
    nxt = _next_slot(items, datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc), 1)
    assert nxt.date().isoformat() == "2026-07-26"   # backfills, not Aug 1


def test_build_item_returns_none_when_no_gorgeous_photo():
    def _no_cover(listing, assets_dir, slug, *, used_urls=frozenset(), **_):
        return None
    item = build_item(
        day=101, story=STORIES[0], candidate=_cand("src__0"), listing={},
        scheduled_for="2026-07-07T01:00:00+00:00", assets_root=Path("/tmp/x"),
        skip_render=True, slide_renderer=_fake_render, photo_selector=_no_cover,
    )
    assert item is None


def test_item_records_cover_url_and_never_repeats(tmp_path):
    added = _run({"items": []}, lookahead=5)
    urls = [it["cover_photo_url"] for it in added]
    assert all(urls), "every item records the exact photo it used"
    assert len(set(urls)) == len(urls), "no cover photo is reused"


# ── BRAND-SAFE + BEAUTY cover selection (day-218 guard + gorgeous-or-skip)

def test_ordered_fresh_urls_drops_rejected_and_used():
    """Brand safety: the gate's order_photo_indices leads with the hero and
    drops rejected broker frames; the ledger drops already-used photos."""
    urls = ["http://x/flyer_broker.jpg", "http://x/hero.jpg", "http://x/nice.jpg"]
    listing = {"photo_urls": urls, "photos_count": 3,
               "selected_photo_url": "http://x/hero.jpg",
               "photo_urls_rejected": ["http://x/flyer_broker.jpg"]}
    fresh = _ordered_fresh_urls(listing, frozenset())
    assert "http://x/flyer_broker.jpg" not in fresh   # broker flyer dropped
    assert fresh[0] == "http://x/hero.jpg"             # hero leads
    # already-used photo is excluded
    fresh2 = _ordered_fresh_urls(listing, frozenset({"http://x/hero.jpg"}))
    assert "http://x/hero.jpg" not in fresh2


def test_select_beautiful_cover_picks_best_and_skips_dull(tmp_path):
    """Scores each fresh photo and returns the most beautiful; returns None
    when the best isn't gorgeous enough (skip the listing)."""
    from PIL import Image
    imgs = {
        "http://x/dull.jpg": Image.new("RGB", (1200, 1500), (150, 150, 150)),   # concrete
        "http://x/ocean.jpg": Image.new("RGB", (1200, 1500), (85, 155, 230)),   # sky/ocean
    }
    listing = {"photo_urls": list(imgs), "photos_count": 2,
               "selected_photo_url": "http://x/dull.jpg"}
    sel = select_beautiful_cover(listing, tmp_path, "d1__el_mar",
                                 fetcher=lambda u: imgs[u])
    assert sel is not None
    assert sel[1] == "http://x/ocean.jpg"              # the beautiful one wins

    dull_only = {"photo_urls": ["http://x/dull.jpg"], "photos_count": 1,
                 "selected_photo_url": "http://x/dull.jpg"}
    assert select_beautiful_cover(dull_only, tmp_path, "d2__el_mar",
                                  fetcher=lambda u: imgs["http://x/dull.jpg"]) is None
