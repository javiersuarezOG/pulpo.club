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
    }


CANDS = [_cand(f"src__{i}", rank=100 - i, zone=f"z{i}") for i in range(20)]
RANKED_INDEX = {c["listing_id"]: {"photo_urls": ["http://x/img.jpg"]} for c in CANDS}
NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _fake_render(candidate, listing, ptype, palette, out, overrides=None):
    return out  # no I/O


def _fake_caption(candidate, listing, *, poster_type=None, client=None, overrides=None):
    return f"**{candidate['area_m2']:.0f} m2 en {candidate['zone']}.**\n\npulpo.club · link en bio"


def _run(queue, lookahead=4, cadence=2):
    return topup(
        queue, CANDS, RANKED_INDEX, now=NOW, lookahead=lookahead, cadence_days=cadence,
        assets_root=Path("/tmp/x"), skip_render=True,
        poster_renderer=_fake_render, caption_generator=_fake_caption,
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


def test_showcase_slide1_is_listing_brand_slide2_is_listing():
    added = _run({"items": []}, lookahead=2)
    brand, showcase = added[0], added[1]
    # brand: slide 1 = TYPO_MAX brand poster, slide 2 = sticker listing
    assert brand["poster_type"] == "typo_max"
    assert "sticker" in brand["carousel_photo_paths"][0]
    # showcase: slide 1 = sticker listing, slide 2 = hero photo
    assert showcase["poster_type"] == "sticker"
    assert showcase["carousel_photo_paths"][0].endswith(".hero.jpg")


# ── scheduling + dedup ────────────────────────────────────────────────

def test_two_day_spacing_and_future_only():
    added = _run({"items": []}, lookahead=3, cadence=2)
    days = [datetime.fromisoformat(it["scheduled_for"]).date() for it in added]
    assert (days[1] - days[0]).days == 2
    assert (days[2] - days[1]).days == 2
    assert all(datetime.fromisoformat(it["scheduled_for"]) > NOW for it in added)


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
