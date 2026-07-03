"""Tests for scripts/smoke_scraper.py (PR-S1.5).

Pure helper-function tests. The CLI itself is exercised manually
against live sources; these tests just verify the orchestration is
sane (correct module import, error containment, sample shape).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import smoke_scraper  # noqa: E402


# ---------- discover_all_sources ----------

def test_discover_all_sources_returns_existing_scrapers():
    """The function walks pulpo/scrapers/*.py and returns the non-underscore
    module names. It must include the 11 baseline scrapers."""
    slugs = smoke_scraper.discover_all_sources()
    expected_baseline = {
        "bienesraices", "century21", "citymax", "elagente",
        "encuentra24", "essurf", "goodlife", "nexo",
        "oceanside", "realtyelsalvador", "remax",
    }
    assert expected_baseline <= set(slugs), (
        f"missing baseline scrapers: {expected_baseline - set(slugs)}"
    )


def test_discover_all_sources_excludes_underscore_modules():
    """``_base.py``, ``_runtime.py`` etc. are infrastructure, not scrapers."""
    slugs = smoke_scraper.discover_all_sources()
    for slug in slugs:
        assert not slug.startswith("_"), f"underscore module slipped in: {slug}"


def test_discover_all_sources_excludes_init():
    slugs = smoke_scraper.discover_all_sources()
    assert "__init__" not in slugs


# ---------- smoke_one ----------

def test_smoke_one_offline_mode_returns_result():
    """In offline mode the scraper reads from fixtures, so smoke_one
    should return ok=True even without network."""
    result = smoke_scraper.smoke_one("nexo", limit=5, offline=True)
    assert result["slug"] == "nexo"
    # nexo has a fixture so it should return ok
    assert result["ok"] is True, f"unexpected error: {result['error']}"
    assert isinstance(result["raw_count"], int)
    assert isinstance(result["sample"], list)


def test_smoke_one_unknown_slug_returns_error():
    """Bogus slug → ok=False with an importable error, NOT a crash."""
    result = smoke_scraper.smoke_one("this_does_not_exist", limit=5, offline=True)
    assert result["ok"] is False
    assert "this_does_not_exist" in result["error"]


def test_smoke_one_captures_duration():
    """Even errored runs report a duration so the operator can spot
    timeouts vs immediate failures."""
    result = smoke_scraper.smoke_one("this_does_not_exist", limit=5, offline=True)
    assert result["duration_s"] >= 0
    assert isinstance(result["duration_s"], float)


def test_smoke_one_sample_truncates_to_five():
    """The sample is bounded at 5 to keep the report scannable."""
    result = smoke_scraper.smoke_one("nexo", limit=50, offline=True)
    if result["ok"]:
        assert len(result["sample"]) <= 5


def test_smoke_one_result_shape_is_stable():
    """The JSON output (--json flag) is consumed by humans + future
    dashboards. Lock the shape so a refactor doesn't break it."""
    result = smoke_scraper.smoke_one("nexo", limit=1, offline=True)
    required_keys = {
        "slug", "ok", "duration_s", "raw_count", "lifecycle", "error", "sample"
    }
    assert required_keys <= set(result.keys()), (
        f"missing keys: {required_keys - set(result.keys())}"
    )


def test_active_source_zero_count_is_failure(monkeypatch):
    """Active source + zero listings must be red in smoke output."""
    import types

    mod = types.SimpleNamespace(crawl=lambda limit, offline: [])
    monkeypatch.setitem(sys.modules, "pulpo.scrapers.fakeactive", mod)
    monkeypatch.setattr(smoke_scraper, "source_lifecycle", lambda slug: "active")

    result = smoke_scraper.smoke_one("fakeactive", limit=5, offline=False)
    assert result["ok"] is False
    assert "zero listings" in result["error"]


def test_experimental_source_zero_count_is_allowed(monkeypatch):
    """Experimental WAF/discovery sources can be empty without blocking smoke."""
    import types

    mod = types.SimpleNamespace(crawl=lambda limit, offline: [])
    monkeypatch.setitem(sys.modules, "pulpo.scrapers.fakeexperimental", mod)
    monkeypatch.setattr(smoke_scraper, "source_lifecycle", lambda slug: "experimental")

    result = smoke_scraper.smoke_one("fakeexperimental", limit=5, offline=False)
    assert result["ok"] is True
    assert result["raw_count"] == 0


def test_allow_empty_overrides_active_zero_count(monkeypatch):
    import types

    mod = types.SimpleNamespace(crawl=lambda limit, offline: [])
    monkeypatch.setitem(sys.modules, "pulpo.scrapers.fakeempty", mod)
    monkeypatch.setattr(smoke_scraper, "source_lifecycle", lambda slug: "active")

    result = smoke_scraper.smoke_one(
        "fakeempty",
        limit=5,
        offline=False,
        allow_empty=True,
    )
    assert result["ok"] is True


# ---------- print_report doesn't crash on edge cases ----------

def test_print_report_handles_empty_sample(capsys: pytest.CaptureFixture):
    result = {
        "slug": "x",
        "ok": True,
        "duration_s": 0.1,
        "raw_count": 0,
        "error": None,
        "sample": [],
    }
    smoke_scraper.print_report(result)
    captured = capsys.readouterr().out
    assert "x" in captured
    assert "raw_count: 0" in captured


def test_print_report_handles_error_traceback(capsys: pytest.CaptureFixture):
    result = {
        "slug": "x",
        "ok": False,
        "duration_s": 0.1,
        "raw_count": 0,
        "error": "ImportError: no module named foo\n  at line 1\n  at line 2",
        "sample": [],
    }
    smoke_scraper.print_report(result)
    captured = capsys.readouterr().out
    assert "ERR" in captured
    assert "ImportError" in captured
