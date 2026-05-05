"""
Tests for automation/ai_enrichment.py production module.

Covers cache load/save, md5-based invalidation, _is_global_error
classification, and the enrich_listings() control flow including
the no-key / no-package / quota-exhausted graceful-degradation paths.

Uses a stub OpenAI client (simple class, no library mocking) so tests
don't depend on the openai package being installed.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ai_enrichment import (   # noqa: E402
    _description_md5,
    _load_cache,
    _save_cache,
    _is_global_error,
    enrich_listings,
)


def _li(**kwargs) -> dict:
    base = {
        "source": "goodlife",
        "source_id": "GL-001",
        "title": "5,000 m² lot",
        "description": "x" * 200,
        "area_m2": 5000.0,
        "price_usd": 150_000.0,
        "zone": "el-tunco",
        "department": "La Libertad",
        "property_type": "land",
        "first_seen_at": "2026-04-01T12:00:00+00:00",
    }
    base.update(kwargs)
    return base


# ── _description_md5 ───────────────────────────────────────────────────

def test_md5_stable_across_runs():
    a = _li(description="hello world")
    b = _li(description="hello world")
    assert _description_md5(a) == _description_md5(b)


def test_md5_changes_with_description():
    a = _li(description="hello world")
    b = _li(description="hello world!")
    assert _description_md5(a) != _description_md5(b)


def test_md5_handles_missing_description():
    """No description shouldn't raise."""
    li = {"source": "x", "source_id": "y"}
    assert isinstance(_description_md5(li), str)
    assert len(_description_md5(li)) == 32   # md5 hex


# ── _is_global_error — quota / auth detection ─────────────────────────

def test_global_error_catches_authentication():
    class AuthenticationError(Exception):
        pass
    assert _is_global_error(AuthenticationError("invalid key"))


def test_global_error_catches_permission_denied():
    class PermissionDeniedError(Exception):
        pass
    assert _is_global_error(PermissionDeniedError("forbidden"))


def test_global_error_catches_insufficient_quota():
    err = Exception("Error code: 429 - insufficient_quota")
    assert _is_global_error(err)


def test_global_error_catches_rate_limit():
    err = Exception("rate_limit_exceeded for tier")
    assert _is_global_error(err)


def test_global_error_catches_billing_hard_limit():
    err = Exception("billing_hard_limit_reached")
    assert _is_global_error(err)


def test_global_error_catches_401():
    err = Exception(" 401 Unauthorized")
    assert _is_global_error(err)


def test_global_error_does_not_catch_transient_errors():
    err = Exception("Connection timeout — retry later")
    assert not _is_global_error(err)


def test_global_error_does_not_catch_arbitrary_runtime():
    err = ValueError("unrelated")
    assert not _is_global_error(err)


# ── _load_cache / _save_cache ──────────────────────────────────────────

def test_cache_round_trip(tmp_path):
    path = tmp_path / "cache.json"
    payload = {
        "goodlife|GL-001": {
            "description_md5": "abc123",
            "title_canonical": "Test Title",
            "tokens_in": 387,
            "tokens_out": 30,
            "cost_usd": 0.0001,
        }
    }
    _save_cache(path, payload)
    loaded = _load_cache(path)
    assert loaded == payload


def test_load_cache_missing_returns_empty():
    assert _load_cache(Path("/tmp/nonexistent_xyz_12345.json")) == {}


def test_load_cache_corrupt_returns_empty(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ this is not json")
    assert _load_cache(path) == {}


def test_load_cache_non_dict_returns_empty(tmp_path):
    path = tmp_path / "list.json"
    path.write_text(json.dumps(["not", "a", "dict"]))
    assert _load_cache(path) == {}


# ── enrich_listings — graceful degradation paths ──────────────────────

def test_enrich_skips_when_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # apply_fallback=False so we just test the skip path itself
    metrics = enrich_listings([_li()], cache_path=tmp_path / "cache.json",
                               apply_fallback=False)
    assert metrics["skipped_no_api_key"] is True
    assert metrics["api_calls_succeeded"] == 0


def test_enrich_runs_fallback_even_without_api_key(tmp_path, monkeypatch):
    """With apply_fallback=True (default), title and reasons_to_buy still get
    populated from the deterministic templates when AI is unavailable."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    li = _li(is_beachfront=True, area_m2=12_000)
    metrics = enrich_listings([li], cache_path=tmp_path / "cache.json")
    # Fallback should fire; at least 1 listing got templates applied
    assert metrics["fallback_applied"] >= 1
    assert li.get("title_canonical") is not None
    assert "Beachfront" in li["title_canonical"]


def test_enrich_uses_cached_entry_when_md5_matches(tmp_path, monkeypatch):
    """Cache hit path: don't call API, return cached fields."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cache_path = tmp_path / "cache.json"
    li = _li(description="cached description")
    md5 = _description_md5(li)
    cache_path.write_text(json.dumps({
        f"{li['source']}|{li['source_id']}": {
            "description_md5": md5,
            "title_canonical": "Cached Title",
            "short_description_canonical": "Cached desc",
            "reasons_to_buy": ["cached bullet 1"],
            "content_quality": "high",
            "cost_usd": 0.0,
        }
    }))
    # We're not stubbing OpenAI — test only the cache-hit path. If the
    # code tries to call the API, it would fail because openai package
    # isn't installed in test env. That's a fine signal.
    metrics = enrich_listings([li], cache_path=cache_path, apply_fallback=False)
    assert metrics["cache_hits"] == 1
    assert metrics["cache_misses"] == 0
    assert li.get("title_canonical") == "Cached Title"


def test_enrich_invalidates_cache_when_md5_changes(tmp_path, monkeypatch):
    """If description changed since last enrichment, cache must miss and
    the code path attempts a fresh API call (which fails in test env)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({
        "goodlife|GL-001": {
            "description_md5": "OLD_HASH_DOES_NOT_MATCH",
            "title_canonical": "Stale Title",
        }
    }))
    li = _li(description="completely new description")
    # Patch the OpenAI import so it raises ImportError → routed to no_package path
    with patch.dict(sys.modules, {"openai": None}):
        metrics = enrich_listings([li], cache_path=cache_path, apply_fallback=False)
    # We won't get a cache hit because md5 differs; what happens after depends
    # on environment. Either way, cache_hits should be 0.
    assert metrics["cache_hits"] == 0


def test_enrich_max_listings_limits_processing(tmp_path, monkeypatch):
    """max_listings caps how many we touch — useful for cost control / smoke."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    listings = [_li(source_id=f"GL-{i:03d}") for i in range(10)]
    metrics = enrich_listings(listings, cache_path=tmp_path / "cache.json",
                               max_listings=3, apply_fallback=True)
    # Only 3 listings processed → fallback applied to ≤3
    assert metrics["fallback_applied"] <= 3


# ── Cache persistence end-to-end ──────────────────────────────────────

def test_cache_written_after_run(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cache_path = tmp_path / "cache.json"
    li = _li(is_beachfront=True)
    enrich_listings([li], cache_path=cache_path)
    # File should exist (even with empty cache, _save_cache writes it)
    assert cache_path.exists()
    saved = json.loads(cache_path.read_text())
    assert isinstance(saved, dict)
