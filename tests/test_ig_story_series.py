"""Tests for automation/ig_story_series.py — the inspirational story engine.

Pure functions; no I/O. We assert: 14 unique stories, no-repeat rotation,
every caption + comment passes the linter, the image carries no price (the
price whispers in the comment), and brand-safety (cover = hero, closer = no
photo).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pytest   # noqa: E402

from automation import ig_story_series as S   # noqa: E402
from automation.ig_caption_lint import check as lint_check   # noqa: E402


def _cand(**over):
    base = {"zone": "el-tunco", "area_m2": 1580.9, "price_usd": 225000.0}
    base.update(over)
    return base


def test_fourteen_unique_stories():
    ids = [s["id"] for s in S.STORIES]
    assert len(ids) == 14
    assert len(set(ids)) == 14, "story ids must be unique"
    for s in S.STORIES:
        assert s["line"] and s["eye"] and s["emotion"] and s["cap"]


def test_rotation_no_repeat_within_a_cycle():
    ids = [S.story_for_index(i)["id"] for i in range(14)]
    assert len(set(ids)) == 14
    assert S.story_for_index(14)["id"] == S.story_for_index(0)["id"]


@pytest.mark.parametrize("story", S.STORIES, ids=lambda s: s["id"])
def test_each_story_builds_and_lints_clean(story):
    post = S.build_post(story, _cand(), {}, ["hero.jpg", "b.jpg"])
    assert post["story_id"] == story["id"]
    assert lint_check(post["caption"]) == [], f"{story['id']} caption trips lint"
    assert lint_check(post["comment"]) == [], f"{story['id']} comment trips lint"


def test_accent_is_a_substring_of_the_line():
    # the poster highlights `accent` inside `line`; it must actually occur
    for s in S.STORIES:
        acc = s.get("accent")
        if acc:
            assert acc in s["line"], f"{s['id']}: accent {acc!r} not in line"


def test_image_carries_no_price_but_comment_does():
    post = S.build_post(S.STORIES[0], _cand(price_usd=225000.0), {}, ["hero.jpg"])
    # the story cover slide has no price text anywhere
    cover = post["slides"][0]
    blob = " ".join(str(v) for v in cover.values())
    assert "$" not in blob and "225" not in blob
    # the price whispers in the first comment instead
    assert "$225,000" in post["comment"]


def test_brand_safe_shape_cover_hero_plus_photofree_closer():
    post = S.build_post(S.STORIES[3], _cand(), {}, ["hero.jpg", "second.jpg"])
    types = [s["t"] for s in post["slides"]]
    assert types == ["story", "cta"], "cover(story) + photo-free closer(cta)"
    # only the hero photo is referenced; the closer has no img
    assert post["slides"][0]["img"] == "hero.jpg"
    assert "img" not in post["slides"][1]


def test_build_post_none_without_photo():
    assert S.build_post(S.STORIES[0], _cand(), {}, []) is None
