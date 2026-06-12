"""Tests for scripts/explain_run.py (PRD R9 recovery/operator CLI).

Covers the pure ``render`` (the report string) + the health-row reducer.
Read-only tool; no IO is exercised here beyond the pure functions.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from explain_run import latest_health_by_source, render  # noqa: E402


def test_render_blocked_run_surfaces_the_blocker():
    outcome = {
        "run_id": "27394603436",
        "run_url": "https://github.com/x/actions/runs/27394603436",
        "outcome": "blocked_by_data_quality",
        "committed": "",
        "deploy_conclusion": "skipped",
        "job_status": "failure",
        "failed_step": "Photo-contract truth canary (committed SV state)",
    }
    guards = [{"name": "population_regression", "severity": "warn", "message": "is_motivated 15%→8%"}]
    meta = {
        "total_listings": 1932,
        "dropped": 197,
        "started_at": "2026-06-12T06:00:00Z",
        "duration_seconds": 7000,
        "offline": False,
        "errors": [],
    }
    health = {
        "nexo": {"source": "nexo", "status": "green"},
        "goodlife": {"source": "goodlife", "status": "red", "error_class": "Timeout"},
    }
    out = render(outcome, guards, meta, health)

    assert "27394603436" in out
    assert "blocked_by_data_quality" in out
    assert "blocked at: Photo-contract truth canary" in out
    assert "1932 listings" in out and "dropped 197" in out
    assert "[warn] population_regression" in out
    assert "Sources: 1/2 green" in out
    assert "RED: goodlife(Timeout)" in out


def test_render_committed_run_has_no_block_line():
    outcome = {
        "run_id": "1", "outcome": "committed", "committed": "true",
        "deploy_conclusion": "success", "job_status": "success", "failed_step": None,
    }
    out = render(outcome, None, {"total_listings": 1950}, {})
    assert "committed=true" in out
    assert "blocked at:" not in out


def test_render_is_resilient_to_missing_artifacts():
    out = render(None, None, None, {})
    assert "no nightly_outcome.json" in out
    # No crash, always newline-terminated.
    assert out.endswith("\n")


def test_latest_health_takes_last_row_and_skips_post_validation():
    rows = [
        {"source": "nexo", "status": "red"},
        {"source": "nexo", "status": "green"},                       # later wins
        {"source": "nexo", "phase": "post_validation", "status": "red"},  # skipped
        {"source": "remax", "status": "green"},
    ]
    h = latest_health_by_source(rows)
    assert h["nexo"]["status"] == "green"
    assert h["remax"]["status"] == "green"
    assert set(h) == {"nexo", "remax"}
