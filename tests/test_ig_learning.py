"""Tests for automation/ig_learning.py — the Growth Hacker scoreboard.

Synthetic, deterministic, offline. Covers the scoring math, the cold-start
guard, the 72h-over-24h dedup, metadata resolution (row + queue fallback),
malformed-row tolerance, the pick_weight consumer contract, and that
pick_story with weights biases WITHOUT breaking anti-repeat.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_learning import (   # noqa: E402
    MIN_SAMPLES,
    build_scoreboard,
    engagement_score,
    fetch_signups_by_day,
    parse_code_day,
    pick_weight,
)
from automation import posthog_query as pq   # noqa: E402
from automation.ig_story_series import pick_story, STORIES   # noqa: E402


def _row(mid, story, metrics, *, day=None, maturity_h=72, emotion=None, color="terrenos_playa"):
    return {"media_id": mid, "day": day, "maturity_h": maturity_h,
            "story_id": story, "emotion": emotion, "color_key": color,
            "metrics": metrics}


def M(reach=100, saved=0, shares=0, comments=0, likes=0, views=0):
    return {"reach": reach, "saved": saved, "shares": shares,
            "comments": comments, "likes": likes, "views": views}


# ── engagement_score ───────────────────────────────────────────────────

def test_engagement_score_weights_saves_and_shares_highest():
    # 3*saved + 3*shares + 2*comments + 1*likes, over reach
    s = engagement_score(M(reach=100, saved=2, shares=1, comments=1, likes=4))
    assert abs(s - (3 * 2 + 3 * 1 + 2 * 1 + 1 * 4) / 100) < 1e-9  # 0.15


def test_engagement_score_none_on_empty_or_missing():
    assert engagement_score({}) is None
    assert engagement_score(None) is None


def test_engagement_score_falls_back_to_views_when_no_reach():
    # reach 0 but views present → normalize by views, not None
    assert engagement_score(M(reach=0, saved=1, views=50)) == 3 * 1 / 50


def test_engagement_score_none_without_reach_or_views():
    assert engagement_score(M(reach=0, saved=5, views=0)) is None


# ── build_scoreboard: cold-start + trust ───────────────────────────────

def test_dimension_untrusted_below_min_samples():
    rows = [_row(f"m{i}", "el_mar", M(reach=100, saved=3)) for i in range(MIN_SAMPLES - 1)]
    board = build_scoreboard(rows)
    entry = board["dimensions"]["story_id"]["el_mar"]
    assert entry["trusted"] is False
    assert entry["score"] is None
    assert board["leaders"]["story_id"] is None   # nothing trusted yet


def test_dimension_trusted_at_min_samples_and_leads():
    rows = [_row(f"m{i}", "el_mar", M(reach=100, saved=3)) for i in range(MIN_SAMPLES)]
    rows += [_row(f"w{i}", "raices", M(reach=100, saved=0)) for i in range(MIN_SAMPLES)]
    board = build_scoreboard(rows)
    hot = board["dimensions"]["story_id"]["el_mar"]
    cold = board["dimensions"]["story_id"]["raices"]
    assert hot["trusted"] and hot["score"] > cold["score"]
    assert board["leaders"]["story_id"] == "el_mar"


# ── 72h wins over 24h for the same media ───────────────────────────────

def test_settled_72h_reading_wins_over_24h():
    rows = [
        _row("m1", "el_mar", M(reach=100, saved=1), maturity_h=24),
        _row("m1", "el_mar", M(reach=100, saved=9), maturity_h=72),  # settled
    ]
    # only the 72h reading should count → score reflects saved=9
    board = build_scoreboard([*rows,
                              _row("m2", "el_mar", M(reach=100, saved=9)),
                              _row("m3", "el_mar", M(reach=100, saved=9))])
    assert board["dimensions"]["story_id"]["el_mar"]["score"] == 3 * 9 / 100


# ── metadata resolution: row first, queue fallback ─────────────────────

def test_metadata_falls_back_to_queue_by_day():
    # rows carry no story_id/emotion/color_key → resolve from the queue
    rows = [{"media_id": f"m{i}", "day": 5, "maturity_h": 72,
             "metrics": M(reach=100, saved=3)} for i in range(MIN_SAMPLES)]
    queue_meta = {5: {"story_id": "el_mar", "emotion": "regreso", "color_key": "terrenos_lago"}}
    board = build_scoreboard(rows, queue_meta)
    assert board["dimensions"]["story_id"]["el_mar"]["trusted"] is True
    assert board["dimensions"]["color_key"]["terrenos_lago"]["trusted"] is True


def test_malformed_rows_are_skipped_not_fatal():
    rows = ["not-a-dict", {"metrics": "bad"}, {"media_id": None},
            _row("m1", "el_mar", M(reach=100, saved=3))]
    board = build_scoreboard(rows)  # must not raise
    assert board["n_posts_scored"] == 1


# ── pick_weight consumer contract ──────────────────────────────────────

def _board_two_stories(hot_score, cold_score):
    return {"dimensions": {"story_id": {
        "hot":  {"score": hot_score,  "n": 5, "trusted": True},
        "cold": {"score": cold_score, "n": 5, "trusted": True},
    }}}


def test_pick_weight_favors_winner_and_caps():
    board = _board_two_stories(hot_score=1.0, cold_score=0.0)  # avg 0.5
    assert pick_weight(board, "story_id", "hot") == 2.0        # 1.0/0.5=2.0 cap
    assert pick_weight(board, "story_id", "cold") == 0.5       # floored


def test_pick_weight_neutral_when_untrusted_or_unknown():
    board = {"dimensions": {"story_id": {
        "thin": {"score": None, "n": 1, "trusted": False}}}}
    assert pick_weight(board, "story_id", "thin") == 1.0
    assert pick_weight(board, "story_id", "missing") == 1.0
    assert pick_weight({}, "story_id", "x") == 1.0


# ── consumer: pick_story bias preserves anti-repeat ────────────────────

def test_pick_story_weights_none_is_legacy():
    recent = ["el_mar"]
    assert pick_story(recent, coastal=True) is pick_story(recent, coastal=True, weights=None)


def test_pick_story_weight_cannot_resurface_just_used_story():
    # even a 2.0 weight on the most-recent story can't pick it (staleness 0)
    just_used = STORIES[0]["id"]
    got = pick_story([just_used], coastal=True, weights={just_used: 2.0})
    assert got["id"] != just_used


def test_pick_story_weight_breaks_toward_winner_among_unused():
    # two never-used stories; weighting one up makes it win the tie
    ids = [s["id"] for s in STORIES if not s.get("needs_coast")][:2]
    a, b = ids[0], ids[1]
    # with b weighted up, b should be chosen over a (both never used)
    got = pick_story(["x"], coastal=False, weights={b: 2.0, a: 0.5})
    assert got["id"] == b


# ── run(): writes the artifact ─────────────────────────────────────────

# ── v2: signup attribution ─────────────────────────────────────────────

def test_parse_code_day():
    assert parse_code_day("ig-d247-scarcity") == 247
    assert parse_code_day("ig-d5-social_proof-pro") == 5
    assert parse_code_day("IG-D12-X") == 12          # case-insensitive
    assert parse_code_day("nope") is None
    assert parse_code_day(None) is None


def test_rows_to_dicts_shapes():
    assert pq.rows_to_dicts({"columns": ["a", "b"], "results": [[1, 2], [3, 4]]}) == \
        [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert pq.rows_to_dicts({"columns": ["a"], "results": [[1, 2]]}) == []  # len mismatch skipped
    assert pq.rows_to_dicts(None) is None
    assert pq.rows_to_dicts({"bad": 1}) is None


def test_fetch_signups_by_day_maps_events(monkeypatch):
    import automation.ig_learning as L
    rows = [
        {"code": "ig-d247-x", "event": "newsletter.signup", "n": 3},
        {"code": "ig-d247-x", "event": "webhook.checkout_completed", "n": 1},
        {"code": "foreign", "event": "newsletter.signup", "n": 9},   # ignored
    ]
    monkeypatch.setattr(L._pq, "query", lambda *a, **k: rows)
    assert L.fetch_signups_by_day() == {247: {"free": 3, "pro": 1}}


def test_fetch_signups_by_day_softfails_to_empty(monkeypatch):
    import automation.ig_learning as L
    monkeypatch.setattr(L._pq, "query", lambda *a, **k: None)   # no key / failure
    assert L.fetch_signups_by_day() == {}


def test_signups_blend_lifts_the_converting_story():
    rows = []
    for i in range(MIN_SAMPLES):
        rows.append(_row(f"w{i}", "winner", M(reach=100, saved=1), day=100 + i))
        rows.append(_row(f"l{i}", "loser", M(reach=100, saved=1), day=200 + i))
    signups = {100 + i: {"free": 2, "pro": 0} for i in range(MIN_SAMPLES)}
    board = build_scoreboard(rows, None, signups)
    assert board["leaders"]["story_id"] == "winner"
    assert board["scored_on"] == "engagement+signups"
    assert board["signups_attributed"]["free"] == 2 * MIN_SAMPLES
    # winner's score is dominated by the signup term, not engagement
    assert board["dimensions"]["story_id"]["winner"]["score"] > \
        board["dimensions"]["story_id"]["loser"]["score"]


def test_pro_signup_weighted_above_free():
    rows_free = [_row(f"f{i}", "s", M(reach=100, saved=0), day=10 + i) for i in range(MIN_SAMPLES)]
    rows_pro = [_row(f"p{i}", "s", M(reach=100, saved=0), day=10 + i) for i in range(MIN_SAMPLES)]
    free_board = build_scoreboard(rows_free, None, {10 + i: {"free": 1, "pro": 0} for i in range(MIN_SAMPLES)})
    pro_board = build_scoreboard(rows_pro, None, {10 + i: {"free": 0, "pro": 1} for i in range(MIN_SAMPLES)})
    assert pro_board["dimensions"]["story_id"]["s"]["score"] > \
        free_board["dimensions"]["story_id"]["s"]["score"]


def test_signups_none_is_backward_compatible():
    rows = [_row(f"m{i}", "el_mar", M(reach=100, saved=3)) for i in range(MIN_SAMPLES)]
    assert build_scoreboard(rows)["dimensions"] == build_scoreboard(rows, None, None)["dimensions"]
    assert build_scoreboard(rows)["scored_on"] == "engagement"


def test_run_writes_scoreboard(tmp_path, monkeypatch):
    # Resolve BOTH the module and run() from the same live import.
    # tests/test_first_seen.py nukes every `automation*` entry from
    # sys.modules, so a `run` bound at collection time can end up
    # holding the globals of a stale module object while this
    # `import` returns a fresh one — the monkeypatches below would
    # then land on a module run() never reads, and it would write the
    # real web/data/ artifacts. Same reasoning as the `pub` fixture in
    # tests/test_ig_publish.py.
    import automation.ig_learning as L
    run = L.run
    ins = tmp_path / "ig_insights.jsonl"
    ins.write_text("\n".join(json.dumps(_row(f"m{i}", "el_mar", M(reach=100, saved=3)))
                             for i in range(MIN_SAMPLES)))
    out = tmp_path / "ig_learning.json"
    monkeypatch.setattr(L, "INSIGHTS_ARTIFACT", ins)
    monkeypatch.setattr(L, "QUEUE_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(L, "LEARNING_ARTIFACT", out)
    n = run()
    assert n == MIN_SAMPLES
    board = json.loads(out.read_text())
    assert board["leaders"]["story_id"] == "el_mar"
