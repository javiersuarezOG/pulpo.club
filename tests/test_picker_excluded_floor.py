"""Quality-floor filter for the picker.

Photos with ``cheap_quality_score < HERO_PICKER_MIN_CHEAP_SCORE`` get
flagged ``picker_excluded=True`` and are permanently kept out of the VLM
booster pool — recorded in ``web/data/picker_excluded.json`` so future
runs short-circuit the check.

Three integration points to verify:
  1. ``photo_quality.picker_min_cheap_score()`` — default + env override.
  2. ``run._select_top_pct_eligible`` — excluded candidates never reach
     the VLM eligibility set.
  3. ``run._pick_winner_from_scored`` — when ≥1 non-excluded candidate
     exists, no excluded one can win; when ALL are excluded, graceful
     degrade picks the best of the dregs.

The ``picker_excluded.json`` store is redirected into ``tmp_path`` via
``_set_store_path_for_testing`` so we never touch the real file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    from automation import picker_excluded as pe
    store_path = tmp_path / "picker_excluded.json"
    pe._set_store_path_for_testing(store_path)
    # Make sure no env override leaks across tests.
    monkeypatch.delenv("HERO_PICKER_MIN_CHEAP_SCORE", raising=False)
    yield store_path


# ── photo_quality.picker_min_cheap_score ────────────────────────────────

def test_floor_default_is_40():
    from automation.photo_quality import picker_min_cheap_score
    assert picker_min_cheap_score() == 40


def test_floor_env_override(monkeypatch):
    from automation.photo_quality import picker_min_cheap_score
    monkeypatch.setenv("HERO_PICKER_MIN_CHEAP_SCORE", "55")
    assert picker_min_cheap_score() == 55


def test_floor_env_garbage_falls_through_to_default(monkeypatch):
    from automation.photo_quality import picker_min_cheap_score
    monkeypatch.setenv("HERO_PICKER_MIN_CHEAP_SCORE", "")
    assert picker_min_cheap_score() == 40
    monkeypatch.setenv("HERO_PICKER_MIN_CHEAP_SCORE", "not-an-int")
    assert picker_min_cheap_score() == 40
    monkeypatch.setenv("HERO_PICKER_MIN_CHEAP_SCORE", "999")
    assert picker_min_cheap_score() == 40  # out-of-range rejected


# ── picker_excluded store roundtrip ────────────────────────────────────

def test_store_marks_and_reads():
    from automation import picker_excluded as pe
    raw = b"\xff\xd8\xff\xe0fake-jpeg-bytes-1"
    assert pe.is_excluded(raw) is False
    pe.mark_excluded(raw, cheap_score=15, floor=40)
    assert pe.is_excluded(raw) is True


def test_store_amortizes_disk_read():
    from automation import picker_excluded as pe
    raw_a = b"a-bytes"
    raw_b = b"b-bytes"
    store = pe.mark_excluded(raw_a, cheap_score=10, floor=40, save=False)
    store = pe.mark_excluded(raw_b, cheap_score=20, floor=40, store=store, save=False)
    pe.save_store(store)
    # Reload fresh and confirm both entries persisted.
    fresh = pe.load_store()
    assert pe._cache_key(raw_a) in fresh
    assert pe._cache_key(raw_b) in fresh
    assert fresh[pe._cache_key(raw_a)]["cheap_score"] == 10
    assert fresh[pe._cache_key(raw_b)]["floor"] == 40


# ── _select_top_pct_eligible excludes flagged candidates ───────────────

def _stub_candidate(url: str, *, cheap: int, excluded: bool, technical: int = 50):
    return {
        "url": url,
        "content": url.encode("utf-8"),  # bytes used only for cache_key
        "score": technical,
        "has_text_overlay": False,
        "hero_eligible": True,
        "cheap_score": cheap,
        "picker_excluded": excluded,
    }


def test_select_top_pct_excludes_picker_excluded(tmp_path, monkeypatch):
    # Redirect aesthetic cache to tmp so no real cache hits leak in.
    from automation import aesthetic_vision
    monkeypatch.setattr(aesthetic_vision, "_REPO_ROOT", tmp_path)
    (tmp_path / "web" / "data").mkdir(parents=True, exist_ok=True)
    from automation.run import _select_top_pct_eligible

    listings = [[
        _stub_candidate("https://x/a.jpg", cheap=80, excluded=False),
        _stub_candidate("https://x/b.jpg", cheap=90, excluded=True),  # highest score but excluded
        _stub_candidate("https://x/c.jpg", cheap=70, excluded=False),
    ]]
    eligible = _select_top_pct_eligible(listings, top_pct=100)
    assert "https://x/a.jpg" in eligible
    assert "https://x/c.jpg" in eligible
    assert "https://x/b.jpg" not in eligible  # excluded — even at top cheap_score


# ── _pick_winner_from_scored prefers non-excluded ──────────────────────

def test_pick_winner_prefers_non_excluded():
    from automation.run import _pick_winner_from_scored
    candidates = [
        _stub_candidate("https://x/a.jpg", cheap=95, excluded=True, technical=95),  # best by score
        _stub_candidate("https://x/b.jpg", cheap=60, excluded=False, technical=60),
    ]
    url, _content, _score, _has_text, _has_marketing = _pick_winner_from_scored(candidates)
    assert url == "https://x/b.jpg"  # excluded one loses despite higher score


def test_pick_winner_falls_back_to_all_excluded_pool():
    from automation.run import _pick_winner_from_scored
    candidates = [
        _stub_candidate("https://x/a.jpg", cheap=15, excluded=True, technical=15),
        _stub_candidate("https://x/b.jpg", cheap=30, excluded=True, technical=30),
    ]
    url, _content, _score, _has_text, _has_marketing = _pick_winner_from_scored(candidates)
    # All excluded → graceful degrade, listing still gets a hero (the
    # least-bad of the dregs).
    assert url == "https://x/b.jpg"


# ── _pick_winner_from_scored drops has_marketing_overlay candidates ─────

def _stub_candidate_with_overlays(url: str, *, technical: int,
                                  has_text: bool, has_marketing: bool):
    return {
        "url": url,
        "content": url.encode("utf-8"),
        "score": technical,
        "has_text_overlay": has_text,
        "has_marketing_overlay": has_marketing,
        "hero_eligible": True,
        "cheap_score": technical,
        "picker_excluded": False,
    }


def test_pick_winner_prefers_non_marketing_overlay():
    """LLM-flagged marketing-banner candidate must lose to a clean peer
    even when its technical score is higher — mirrors the
    has_text_overlay filter for OCR-flagged candidates."""
    from automation.run import _pick_winner_from_scored
    candidates = [
        _stub_candidate_with_overlays("https://x/banner.jpg",
                                       technical=95,
                                       has_text=False,
                                       has_marketing=True),  # high-res banner
        _stub_candidate_with_overlays("https://x/clean.jpg",
                                       technical=60,
                                       has_text=False,
                                       has_marketing=False),
    ]
    url, _content, _score, _has_text, has_marketing = _pick_winner_from_scored(candidates)
    assert url == "https://x/clean.jpg"
    assert has_marketing is False


def test_pick_winner_falls_back_when_all_marketing_overlay():
    """If every candidate carries a marketing overlay, the picker still
    selects one (graceful degrade) — same contract as has_text_overlay."""
    from automation.run import _pick_winner_from_scored
    candidates = [
        _stub_candidate_with_overlays("https://x/a.jpg",
                                       technical=40,
                                       has_text=False,
                                       has_marketing=True),
        _stub_candidate_with_overlays("https://x/b.jpg",
                                       technical=80,
                                       has_text=False,
                                       has_marketing=True),
    ]
    url, _content, _score, _has_text, has_marketing = _pick_winner_from_scored(candidates)
    # All flagged → least-bad of the dregs (higher technical wins).
    assert url == "https://x/b.jpg"
    assert has_marketing is True


def test_pick_winner_treats_none_marketing_overlay_as_unflagged():
    """None on has_marketing_overlay means 'no signal' (legacy cache rows
    predating the field). Picker must not false-reject — mirrors the
    has_text_overlay null-tolerance contract."""
    from automation.run import _pick_winner_from_scored
    candidates = [
        _stub_candidate_with_overlays("https://x/legacy.jpg",
                                       technical=90,
                                       has_text=False,
                                       has_marketing=False),
    ]
    # Overwrite to simulate "no signal" — None instead of False
    candidates[0]["has_marketing_overlay"] = None
    url, _content, _score, _has_text, has_marketing = _pick_winner_from_scored(candidates)
    assert url == "https://x/legacy.jpg"
    assert has_marketing is None
