"""Tests for the flag-gated stale-listing filter (PR-S4c).

The filter logic lives inline in automation/run.py just before the
rank() call. These tests exercise the same predicate-and-filter idiom
in isolation so we can assert:

  * default OFF (no env var) → no filtering, but telemetry still counts
  * flag ON → listings with existence_status="stale" are dropped
  * flag ON + no stale listings → no-op
  * flag ON + listings without the attribute → keep them
  * various truthy / falsy values of the env var

The inline block in run.py is intentionally simple (a list-comprehension
filter behind an env var check), so the tests below mirror it. If the
inline code grows enough to be worth extracting, hoist it into a
``automation/ranker_stale_filter.py`` module and import here.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Iterable

import pytest


# ---------- Helpers (mirror the predicate used in run.py) ----------

def _flag_is_on(env_val: str | None) -> bool:
    """The same boolean parsing run.py uses."""
    if env_val is None:
        return False
    return env_val.strip().lower() in ("1", "true", "yes")


def _filter_stale(listings: Iterable, drop_stale: bool) -> tuple[list, int, int]:
    """Mirror of the inline filter in automation/run.py. Returns
    (kept, dropped_count, stale_candidates_count)."""
    listings = list(listings)
    if drop_stale:
        before = len(listings)
        kept = [li for li in listings
                if getattr(li, "existence_status", None) != "stale"]
        return kept, before - len(kept), 0
    # Flag off — count stale candidates for telemetry, keep everything.
    stale_candidates = sum(
        1 for li in listings
        if getattr(li, "existence_status", None) == "stale"
    )
    return listings, 0, stale_candidates


def _li(existence_status: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        source="goodlife",
        source_id="X",
        existence_status=existence_status,
    )


# ---------- Flag parsing ----------

@pytest.mark.parametrize("val,expected", [
    ("1", True),
    ("true", True),
    ("TRUE", True),
    ("yes", True),
    ("YES", True),
    (" 1 ", True),  # whitespace stripped
    ("0", False),
    ("false", False),
    ("no", False),
    ("", False),
    ("garbage", False),
    (None, False),
])
def test_flag_parsing(val, expected):
    assert _flag_is_on(val) is expected


# ---------- Filter behavior ----------

def test_default_off_keeps_everything_including_stale():
    """Default OFF: no listings dropped, stale candidates counted only."""
    listings = [
        _li("confirmed_current"),
        _li("missing_recently"),
        _li("stale"),
        _li(None),
    ]
    kept, dropped, candidates = _filter_stale(listings, drop_stale=False)
    assert len(kept) == 4
    assert dropped == 0
    assert candidates == 1  # the one stale listing


def test_flag_on_drops_stale_keeps_others():
    listings = [
        _li("confirmed_current"),
        _li("missing_recently"),
        _li("stale"),
        _li("stale"),
        _li(None),
    ]
    kept, dropped, _ = _filter_stale(listings, drop_stale=True)
    statuses = [getattr(li, "existence_status", None) for li in kept]
    assert "stale" not in statuses
    assert dropped == 2  # two stale dropped
    assert len(kept) == 3


def test_flag_on_no_stale_is_noop():
    listings = [_li("confirmed_current"), _li("missing_recently")]
    kept, dropped, _ = _filter_stale(listings, drop_stale=True)
    assert dropped == 0
    assert len(kept) == 2


def test_flag_on_listings_without_attribute_are_kept():
    """Defensive: a listing object without existence_status (e.g.,
    legacy fixture, smoke test mock) must NOT be filtered. The
    ledger has never seen it; treat as confirmed_current."""

    class BareListing:
        source = "x"
        source_id = "1"
        # no existence_status attr at all

    listings = [BareListing(), _li("confirmed_current")]
    kept, dropped, _ = _filter_stale(listings, drop_stale=True)
    assert dropped == 0
    assert len(kept) == 2


def test_flag_on_existence_status_none_is_kept():
    """existence_status=None → kept. Same rationale as the no-attr case."""
    listings = [_li(None), _li("stale")]
    kept, dropped, _ = _filter_stale(listings, drop_stale=True)
    assert dropped == 1  # only the explicit "stale" one
    assert len(kept) == 1
    assert kept[0].existence_status is None


def test_flag_on_empty_listings_is_safe():
    kept, dropped, candidates = _filter_stale([], drop_stale=True)
    assert kept == []
    assert dropped == 0
    assert candidates == 0


def test_default_off_empty_listings_is_safe():
    kept, dropped, candidates = _filter_stale([], drop_stale=False)
    assert kept == []
    assert dropped == 0
    assert candidates == 0


# ---------- End-to-end: env-var driven ----------

def test_env_var_off_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PULPO_RANKER_DROP_STALE", raising=False)
    assert _flag_is_on(os.environ.get("PULPO_RANKER_DROP_STALE")) is False


def test_env_var_explicit_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PULPO_RANKER_DROP_STALE", "0")
    assert _flag_is_on(os.environ.get("PULPO_RANKER_DROP_STALE")) is False


def test_env_var_explicit_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PULPO_RANKER_DROP_STALE", "1")
    assert _flag_is_on(os.environ.get("PULPO_RANKER_DROP_STALE")) is True
