"""Tests for automation/ig_autopilot.py — the self-running queue generator.

Renders are stubbed (skip_render / injected fakes) so no Playwright or
network fires; we assert the queue-shaping invariants the campaign brief
requires.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_autopilot import (   # noqa: E402
    BRAND_MESSAGES,
    build_item,
    topup,
    _future_approved_count,
    _next_slot,
    _next_day,
    _pick_candidate,
    _used_listing_ids,
)
from automation.ig_caption_lint import check as lint_check   # noqa: E402


def _cand(lid, rank=50.0, zone="el-tunco"):
    src, sid = lid.split("__")
    return {
        "listing_id": lid, "source": src, "source_id": sid,
        "rank": rank, "rank_score": rank, "zone": zone,
        "area_m2": 1500.0, "price_usd": 200000.0, "palette_suggested": "ink",
        "hero_photo_quality_score": 100,
    }


CANDS = [_cand(f"src__{i}", rank=100 - i, zone=f"z{i}") for i in range(20)]
RANKED_INDEX = {c["listing_id"]: {"photo_urls": ["http://x/1", "http://x/2", "http://x/3"]} for c in CANDS}
NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _fake_render(candidate, listing, ptype, palette, out, overrides=None):
    return out  # no I/O


def _fake_caption(candidate, listing, *, poster_type=None, client=None, overrides=None):
    return f"**{candidate['area_m2']:.0f} m2 en {candidate['zone']}.**\n\npulpo.club · link en bio"


def _fake_photos(listing, assets_dir, slug, **_):
    # 3 good listing photos, no download
    return [f"web/data/ig_assets/autopilot/{slug}/photo_{i + 1}.jpg" for i in range(3)]


def _run(queue, lookahead=4, cadence=1, photo_preparer=_fake_photos):
    return topup(
        queue, CANDS, RANKED_INDEX, now=NOW, lookahead=lookahead, cadence_days=cadence,
        assets_root=Path("/tmp/x"), skip_render=True,
        poster_renderer=_fake_render, caption_generator=_fake_caption,
        photo_preparer=photo_preparer,
    )


# ── brand messages ────────────────────────────────────────────────────

def test_all_brand_captions_lint_clean():
    for i, m in enumerate(BRAND_MESSAGES):
        assert lint_check(m["caption"]) == [], f"BRAND_MESSAGES[{i}] fails lint"
        for k in ("eyebrow", "hook", "hero", "punch", "caption"):
            assert m[k], f"BRAND_MESSAGES[{i}] missing {k}"


# ── every post shows a listing + is auto-approved ─────────────────────

def test_every_item_has_a_listing_and_is_approved():
    q = {"items": []}
    added = _run(q, lookahead=5)
    assert len(added) == 5
    for it in added:
        assert it["approved"] is True
        assert it["posted"] is False
        assert it["primary_listing_id"]
        assert it["carousel_photo_paths"], "every post must carry a listing slide"
        assert it["caption_status"] == "clean"


def test_kinds_alternate_brand_showcase():
    added = _run({"items": []}, lookahead=6)
    kinds = [it["shelf"] for it in added]
    assert kinds == [
        "autopilot_brand", "autopilot_showcase", "autopilot_brand",
        "autopilot_showcase", "autopilot_brand", "autopilot_showcase",
    ]


def test_carousel_composition_and_photo_count():
    added = _run({"items": []}, lookahead=2)
    brand, showcase = added[0], added[1]
    # brand: cover = TYPO_MAX brand poster; carousel = sticker + 3 photos
    assert brand["poster_type"] == "typo_max"
    assert "sticker" in brand["carousel_photo_paths"][0]
    assert sum(1 for p in brand["carousel_photo_paths"] if "photo_" in p) == 3
    # showcase: cover = sticker; carousel = 3 photos (no sticker in carousel)
    assert showcase["poster_type"] == "sticker"
    assert all("photo_" in p for p in showcase["carousel_photo_paths"])
    assert len(showcase["carousel_photo_paths"]) == 3
    # every post shows at least the 2-photo floor of real listing photos
    for it in added:
        assert sum(1 for p in it["carousel_photo_paths"] if "photo_" in p) >= 2


# ── scheduling + dedup ────────────────────────────────────────────────

def test_cadence_spacing_and_future_only():
    # daily (default) spacing
    added = _run({"items": []}, lookahead=3)
    days = [datetime.fromisoformat(it["scheduled_for"]).date() for it in added]
    assert (days[1] - days[0]).days == 1
    assert (days[2] - days[1]).days == 1
    assert all(datetime.fromisoformat(it["scheduled_for"]) > NOW for it in added)
    # cadence is parameterized — still honors a wider spacing
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
    # already at target → a second run adds nothing
    added2 = _run(q, lookahead=3)
    assert added2 == []


def test_topup_respects_existing_future_posts():
    q = {"items": [{
        "day": 100, "selector": "manual", "approved": True, "posted": False,
        "scheduled_for": "2026-07-20T01:00:00+00:00",
        "primary_listing_id": "x", "listing_ids": ["x"],
    }]}
    added = _run(q, lookahead=2)
    # one future post exists → only need 1 more
    assert len(added) == 1
    # new post scheduled AFTER the existing latest (2026-07-20) + cadence
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


# ── first comment (references all post info + hashtags) ───────────────

def test_build_comment_references_all_info_and_hashtags():
    from automation.ig_autopilot import build_comment
    c = {"zone": "el-tunco", "area_m2": 1580.9, "price_usd": 225000.0,
         "price_per_m2": 142.32, "dist_beach_km": 0.0}
    out = build_comment(c, {})
    assert "El Tunco" in out                 # location
    assert "m²" in out                        # size
    assert "$225,000" in out                  # price
    assert "/m²" in out                       # price per m2
    assert "Frente al mar" in out             # coastal distance
    assert "pulpo.club" in out                # CTA
    assert "#Terrenos" in out                 # core hashtag
    assert "#ElTunco" in out                  # zone-specific hashtag


def test_build_comment_inland_shows_distance():
    from automation.ig_autopilot import build_comment
    c = {"zone": "chalchuapa", "area_m2": 5000.0, "price_usd": 90000.0,
         "price_per_m2": 18.0, "dist_beach_km": 51.5}
    out = build_comment(c, {})
    assert "del mar" in out and "Frente al mar" not in out
    assert "#Chalchuapa" in out


def test_every_generated_item_carries_a_comment():
    added = _run({"items": []}, lookahead=4)
    for it in added:
        assert it.get("comment"), "every autopilot item needs a first comment"
        assert "#" in it["comment"], "comment must carry hashtags"


# ── photo-quality gate (brand safety) ─────────────────────────────────

def test_pick_candidate_quality_gate_beats_rank():
    cands = [
        {"listing_id": "a__1", "hero_photo_quality_score": 80, "rank": 99},   # bad photo, top rank
        {"listing_id": "a__2", "hero_photo_quality_score": 100, "rank": 40},  # clean photo
    ]
    # The quality floor excludes the 80 (Google-Maps/billboard class) even
    # though it out-ranks the clean one.
    assert _pick_candidate(cands, set())["listing_id"] == "a__2"


def test_pick_candidate_never_strands_when_no_top_quality():
    cands = [{"listing_id": "a__1", "hero_photo_quality_score": 80, "rank": 99}]
    assert _pick_candidate(cands, set())["listing_id"] == "a__1"


def test_generated_week_all_top_quality():
    # every autopilot pick from a mixed pool has a top-quality photo
    good = [_cand(f"g__{i}", rank=90 - i) for i in range(10)]           # q=100
    bad = [{**_cand(f"b__{i}", rank=100), "hero_photo_quality_score": 80} for i in range(3)]
    pool = bad + good
    added = topup(
        {"items": []}, pool, {c["listing_id"]: {} for c in pool},
        now=NOW, lookahead=5, cadence_days=1, assets_root=Path("/tmp/x"),
        skip_render=True, poster_renderer=_fake_render, caption_generator=_fake_caption,
    )
    for it in added:
        assert not it["primary_listing_id"].startswith("b__"), "bad-photo listing leaked in"


# ── listing photos: resolution gate + skip-thin-listings ──────────────

def test_fit_slide_covers_when_big_enough():
    from automation.ig_autopilot import _fit_slide
    from PIL import Image
    big = Image.new("RGB", (4000, 1848))          # hi-res landscape → cover-crop
    out = _fit_slide(big)
    assert out.size == (1080, 1350)


def test_fit_slide_pads_letterbox_crisp():
    from automation.ig_autopilot import _fit_slide
    from PIL import Image
    wide = Image.new("RGB", (1200, 554))          # letterbox, wide enough → fit+pad
    out = _fit_slide(wide)
    assert out.size == (1080, 1350)


def test_fit_slide_rejects_low_res():
    from automation.ig_autopilot import _fit_slide
    from PIL import Image
    tiny = Image.new("RGB", (640, 480))           # too small → reject
    assert _fit_slide(tiny) is None


def test_topup_skips_listing_with_too_few_photos():
    # a photo_preparer that returns only 1 usable photo → every candidate
    # is skipped, so nothing is queued (never posts a thin listing).
    def _one_photo(listing, assets_dir, slug, **_):
        return [f"web/data/ig_assets/autopilot/{slug}/photo_1.jpg"]
    added = _run({"items": []}, lookahead=3, photo_preparer=_one_photo)
    assert added == []


def test_topup_moves_to_next_listing_when_one_is_thin():
    # first candidate yields 1 photo (thin → skipped); the next yields 3
    # and fills the slot. Proves topup advances past a thin listing.
    calls = {"n": 0}

    def _first_thin(listing, assets_dir, slug, **_):
        calls["n"] += 1
        cnt = 1 if calls["n"] == 1 else 3
        return [f"web/data/ig_assets/autopilot/{slug}/photo_{i + 1}.jpg" for i in range(cnt)]
    added = _run({"items": []}, lookahead=1, photo_preparer=_first_thin)
    assert len(added) == 1        # the one slot got filled by the 2nd listing
    assert calls["n"] == 2        # first (thin) tried + skipped, second used
