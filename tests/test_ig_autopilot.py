"""Tests for automation/ig_autopilot.py — the self-running queue generator.

Renders are stubbed (skip_render / injected fakes) so no Playwright or
network fires; we assert the queue-shaping invariants: every post shows a
real listing, is auto-approved, carries a lint-clean caption + a first
comment, and the local-voice formats rotate deterministically.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_autopilot import (   # noqa: E402
    build_item,
    topup,
    _future_approved_count,
    _next_slot,
    _next_day,
    _pick_candidate,
    _used_listing_ids,
)
from automation.ig_local_series import FORMAT_ROTATION   # noqa: E402
from automation.ig_caption_lint import check as lint_check   # noqa: E402


def _cand(lid, rank=50.0, zone="el-tunco"):
    src, sid = lid.split("__")
    return {
        "listing_id": lid, "source": src, "source_id": sid,
        "rank": rank, "rank_score": rank, "zone": zone,
        "area_m2": 1500.0, "price_usd": 200000.0, "palette_suggested": "ink",
        "property_type": "land", "dist_beach_km": 0.0, "price_vs_zone_pct": -20.0,
        "price_per_m2": 133.0, "hero_photo_quality_score": 100,
    }


CANDS = [_cand(f"src__{i}", rank=100 - i, zone=f"z{i}") for i in range(20)]
RANKED_INDEX = {c["listing_id"]: {"photo_urls": ["http://x/1", "http://x/2", "http://x/3"]} for c in CANDS}
NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _fake_render(spec, color, out):
    return out  # no I/O


def _fake_photos(listing, assets_dir, slug, want=3, **_):
    # `want` good listing photos, no download
    return [f"web/data/ig_assets/autopilot/{slug}/photo_{i + 1}.jpg" for i in range(want)]


def _run(queue, lookahead=4, cadence=1, photo_preparer=_fake_photos):
    return topup(
        queue, CANDS, RANKED_INDEX, now=NOW, lookahead=lookahead, cadence_days=cadence,
        assets_root=Path("/tmp/x"), skip_render=True,
        slide_renderer=_fake_render, photo_preparer=photo_preparer,
    )


# ── every post shows a listing + is auto-approved + lint-clean ─────────

def test_every_item_has_a_listing_and_is_approved():
    q = {"items": []}
    added = _run(q, lookahead=5)
    assert len(added) == 5
    for it in added:
        assert it["approved"] is True
        assert it["posted"] is False
        assert it["primary_listing_id"]
        assert it["poster_path"], "every post has a cover slide"
        assert it["carousel_photo_paths"], "every post carries follow-on slides"
        assert it["caption_status"] == "clean"
        assert lint_check(it["caption"]) == [], f"caption for {it['format']} must lint clean"


def test_formats_rotate_deterministically():
    added = _run({"items": []}, lookahead=len(FORMAT_ROTATION) * 2)
    formats = [it["format"] for it in added]
    expected = [FORMAT_ROTATION[i % len(FORMAT_ROTATION)] for i in range(len(added))]
    assert formats == expected
    assert set(formats) == {"guess", "numero_uno", "regreso"}


def test_shelf_matches_format():
    added = _run({"items": []}, lookahead=4)
    for it in added:
        assert it["shelf"] == f"autopilot_{it['format']}"


def test_guess_carousel_has_hide_price_cover_and_reveal():
    # first post in the rotation is the guess format
    added = _run({"items": []}, lookahead=1)
    guess = added[0]
    assert guess["format"] == "guess"
    # 3 slides total (cover + 2), all rendered PNGs
    slides = [guess["poster_path"], *guess["carousel_photo_paths"]]
    assert len(slides) == 3
    assert all(p.endswith(".png") for p in slides)


def test_every_generated_item_carries_a_comment_with_hashtags():
    added = _run({"items": []}, lookahead=4)
    for it in added:
        assert it.get("comment"), "every autopilot item needs a first comment"
        assert "#" in it["comment"], "comment must carry hashtags"
        assert "pulpo.club" in it["comment"]


# ── scheduling + dedup ────────────────────────────────────────────────

def test_cadence_spacing_and_future_only():
    added = _run({"items": []}, lookahead=3)
    days = [datetime.fromisoformat(it["scheduled_for"]).date() for it in added]
    assert (days[1] - days[0]).days == 1
    assert (days[2] - days[1]).days == 1
    assert all(datetime.fromisoformat(it["scheduled_for"]) > NOW for it in added)
    wide = _run({"items": []}, lookahead=2, cadence=3)
    wdays = [datetime.fromisoformat(it["scheduled_for"]).date() for it in wide]
    assert (wdays[1] - wdays[0]).days == 3


def test_does_not_refeature_recent_listings():
    added = _run({"items": []}, lookahead=6)
    lids = [it["primary_listing_id"] for it in added]
    assert len(set(lids)) == len(lids)


def test_topup_stops_at_lookahead():
    q = {"items": []}
    _run(q, lookahead=3)
    added2 = _run(q, lookahead=3)
    assert added2 == []


def test_topup_respects_existing_future_posts():
    q = {"items": [{
        "day": 100, "selector": "manual", "approved": True, "posted": False,
        "scheduled_for": "2026-07-20T01:00:00+00:00",
        "primary_listing_id": "x", "listing_ids": ["x"],
    }]}
    added = _run(q, lookahead=2)
    assert len(added) == 1
    assert added[0]["scheduled_for"] > "2026-07-20"


def test_skipped_items_dont_count_as_future():
    q = {"items": [{
        "day": 100, "selector": "autopilot", "approved": False, "skipped": True,
        "posted": False, "scheduled_for": "2026-07-20T01:00:00+00:00",
        "primary_listing_id": "x", "listing_ids": ["x"],
    }]}
    assert _future_approved_count(q["items"], NOW) == 0


def test_next_day_increments():
    assert _next_day([]) == 101
    assert _next_day([{"day": 105}, {"day": 100}]) == 106


# ── photo-quality gate (brand safety) ─────────────────────────────────

def test_pick_candidate_quality_gate_beats_rank():
    cands = [
        {"listing_id": "a__1", "hero_photo_quality_score": 80, "rank": 99},
        {"listing_id": "a__2", "hero_photo_quality_score": 100, "rank": 40},
    ]
    assert _pick_candidate(cands, set())["listing_id"] == "a__2"


def test_pick_candidate_never_strands_when_no_top_quality():
    cands = [{"listing_id": "a__1", "hero_photo_quality_score": 80, "rank": 99}]
    assert _pick_candidate(cands, set())["listing_id"] == "a__1"


def test_generated_week_all_top_quality():
    good = [_cand(f"g__{i}", rank=90 - i) for i in range(10)]
    bad = [{**_cand(f"b__{i}", rank=100), "hero_photo_quality_score": 80} for i in range(3)]
    pool = bad + good
    added = topup(
        {"items": []}, pool, {c["listing_id"]: {"photo_urls": ["u1", "u2", "u3"]} for c in pool},
        now=NOW, lookahead=5, cadence_days=1, assets_root=Path("/tmp/x"),
        skip_render=True, slide_renderer=_fake_render, photo_preparer=_fake_photos,
    )
    for it in added:
        assert not it["primary_listing_id"].startswith("b__"), "bad-photo listing leaked in"


# ── listing photos: resolution gate + skip-thin-listings ──────────────

def test_fit_slide_covers_when_big_enough():
    from automation.ig_autopilot import _fit_slide
    from PIL import Image
    big = Image.new("RGB", (4000, 1848))
    assert _fit_slide(big).size == (1080, 1350)


def test_fit_slide_pads_letterbox_crisp():
    from automation.ig_autopilot import _fit_slide
    from PIL import Image
    wide = Image.new("RGB", (1200, 554))
    assert _fit_slide(wide).size == (1080, 1350)


def test_fit_slide_rejects_low_res():
    from automation.ig_autopilot import _fit_slide
    from PIL import Image
    tiny = Image.new("RGB", (640, 480))
    assert _fit_slide(tiny) is None


def test_topup_skips_listing_when_too_few_photos_for_any_format():
    # zero usable photos → every format's min is unmet → nothing queued.
    def _no_photos(listing, assets_dir, slug, want=3, **_):
        return []
    added = _run({"items": []}, lookahead=3, photo_preparer=_no_photos)
    assert added == []


def test_build_item_returns_none_when_photos_below_format_min():
    # guess needs 2 photos; give it 1 → None (caller tries another listing).
    def _one_photo(listing, assets_dir, slug, want=3, **_):
        return [f"web/data/ig_assets/autopilot/{slug}/photo_1.jpg"]
    item = build_item(
        day=101, fmt="guess", candidate=_cand("src__0"), listing={},
        scheduled_for="2026-07-07T01:00:00+00:00", assets_root=Path("/tmp/x"),
        skip_render=True, slide_renderer=_fake_render, photo_preparer=_one_photo,
    )
    assert item is None
