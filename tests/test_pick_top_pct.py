"""
Phase 4 cost-gating Pass-1.5 — global top-X% eligibility selection.

These tests exercise ``_select_top_pct_eligible`` directly with hand-
built candidate pools so we don't have to spin up the network stack.
The helper operates on raw candidate dicts and consults the on-disk
aesthetic cache to exclude already-paid candidates from the gate.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Redirect the aesthetic cache file into tmp_path so we don't
    touch the real ``web/data/llm_vision_cache.json``."""
    from automation import aesthetic_vision
    monkeypatch.setattr(aesthetic_vision, "_REPO_ROOT", tmp_path)
    (tmp_path / "web" / "data").mkdir(parents=True, exist_ok=True)
    yield


def _candidate(url: str, content: bytes, cheap_score: int, score: int = 50):
    return {
        "url": url,
        "content": content,
        "score": score,
        "has_text_overlay": False,
        "hero_eligible": True,
        "cheap_score": cheap_score,
    }


def test_top_pct_5_picks_one_from_twenty():
    """20 candidates → top 5% = 1 candidate (rounded floor with minimum
    of 1). Selected URL must be the highest-cheap-score candidate."""
    from automation.run import _select_top_pct_eligible

    pool = [
        [_candidate(f"https://example.com/c{i}.jpg", bytes([i]), cheap_score=i)
         for i in range(10)],
        [_candidate(f"https://example.com/d{i}.jpg", bytes([i + 100]), cheap_score=i + 50)
         for i in range(10)],
    ]

    eligible = _select_top_pct_eligible(pool, top_pct=5)
    # Top cheap_score across both lists is 59 (i=9 in second list).
    assert eligible == {"https://example.com/d9.jpg"}


def test_top_pct_20_picks_top_four_of_twenty():
    """20 candidates → top 20% = 4 candidates. Verifies bulk selection
    is by global cheap_score, not per-listing."""
    from automation.run import _select_top_pct_eligible

    pool = [
        [_candidate(f"https://example.com/c{i}.jpg", bytes([i]), cheap_score=i)
         for i in range(10)],
        [_candidate(f"https://example.com/d{i}.jpg", bytes([i + 100]), cheap_score=i + 50)
         for i in range(10)],
    ]

    eligible = _select_top_pct_eligible(pool, top_pct=20)
    # Top 4 cheap_scores are d6=56, d7=57, d8=58, d9=59. All from second list.
    assert eligible == {
        "https://example.com/d6.jpg",
        "https://example.com/d7.jpg",
        "https://example.com/d8.jpg",
        "https://example.com/d9.jpg",
    }


def test_top_pct_100_picks_every_uncached_candidate():
    """top_pct=100 = legacy 'score everything' behavior."""
    from automation.run import _select_top_pct_eligible

    pool = [[
        _candidate("https://example.com/a.jpg", b"a", cheap_score=10),
        _candidate("https://example.com/b.jpg", b"b", cheap_score=20),
        _candidate("https://example.com/c.jpg", b"c", cheap_score=30),
    ]]
    eligible = _select_top_pct_eligible(pool, top_pct=100)
    assert eligible == {
        "https://example.com/a.jpg",
        "https://example.com/b.jpg",
        "https://example.com/c.jpg",
    }


def test_top_pct_0_skips_all():
    """top_pct=0 = score nothing. Operator's kill-switch for spend."""
    from automation.run import _select_top_pct_eligible

    pool = [[
        _candidate("https://example.com/a.jpg", b"a", cheap_score=99),
        _candidate("https://example.com/b.jpg", b"b", cheap_score=88),
    ]]
    eligible = _select_top_pct_eligible(pool, top_pct=0)
    assert eligible == set()


def test_cached_candidates_excluded_from_gate():
    """The load-bearing 'first-run vs incremental' behavior: candidates
    whose bytes-hash is already in the cache do NOT count toward the
    top-X% budget. Pre-populate the cache for two of three candidates;
    only the one un-cached candidate becomes eligible at top_pct=100.
    """
    from automation.aesthetic_vision import _cache_key, _cache_path
    from automation.run import _select_top_pct_eligible

    a, b, c = b"image_a", b"image_b", b"image_c"
    cache_path = _cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        _cache_key(a): {"score": 5.0, "provider": "segmind",
                         "model": "qwen3-vl-flash", "ts": "2026-05-18"},
        _cache_key(c): {"score": 7.0, "provider": "segmind",
                         "model": "qwen3-vl-flash", "ts": "2026-05-18"},
    }))

    pool = [[
        _candidate("https://example.com/a.jpg", a, cheap_score=90),
        _candidate("https://example.com/b.jpg", b, cheap_score=80),
        _candidate("https://example.com/c.jpg", c, cheap_score=70),
    ]]
    eligible = _select_top_pct_eligible(pool, top_pct=100)
    # Only b is uncached → only b is in the gate's eligible set.
    assert eligible == {"https://example.com/b.jpg"}


def test_top_pct_when_all_cached_returns_empty():
    """Steady-state scenario: every candidate already cached → zero
    paid calls this run. The gate yields an empty set; the picker still
    works because cached candidates get their scores via the cache
    lookup inside score_aesthetic, not through the gate."""
    from automation.aesthetic_vision import _cache_key, _cache_path
    from automation.run import _select_top_pct_eligible

    a, b = b"cached_image_a", b"cached_image_b"
    cache_path = _cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        _cache_key(a): {"score": 6.0, "provider": "segmind",
                         "model": "qwen3-vl-flash", "ts": "2026-05-18"},
        _cache_key(b): {"score": 5.0, "provider": "segmind",
                         "model": "qwen3-vl-flash", "ts": "2026-05-18"},
    }))

    pool = [[
        _candidate("https://example.com/a.jpg", a, cheap_score=95),
        _candidate("https://example.com/b.jpg", b, cheap_score=85),
    ]]
    eligible = _select_top_pct_eligible(pool, top_pct=5)
    assert eligible == set()


def test_aesthetic_module_unavailable_returns_empty_set():
    """If the aesthetic module import fails (e.g. dependency missing
    in a stripped-down environment), the gate returns the empty set so
    the pipeline runs in cheap-only mode. Matches the fail-soft contract."""
    from automation.run import _select_top_pct_eligible

    # Simulate the import path failing by patching the module's
    # _load_cache / _cache_key into raising at import time.
    with mock.patch.dict("sys.modules", {"automation.aesthetic_vision": None}):
        pool = [[
            _candidate("https://example.com/a.jpg", b"a", cheap_score=90),
        ]]
        eligible = _select_top_pct_eligible(pool, top_pct=100)
    assert eligible == set()
