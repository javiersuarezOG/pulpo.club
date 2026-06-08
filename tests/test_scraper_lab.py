"""Tests for automation.scraper_lab — PR-FB-1 of SCRAPER-FEEDBACK-CYCLE-PRD.

The lab is a dev tool, so the tests don't verify ranker output quality
or validation rule correctness — those live in their own test files.
What we verify here is the orchestration contract:

- lab_run returns the expected counts at each stage
- with_validate / with_dedup / with_rank short-circuit cleanly
- write_dir writes the four PRD files
- a missing scraper module is surfaced as ok=False with a useful error
- the human report doesn't crash on minimal input
"""
from __future__ import annotations

import json
from pathlib import Path

from automation.scraper_lab import lab_run, render_human_report


# Every Phase-C scraper that exists offline-fixture-supported is fair
# game; pick "nexo" because its offline fixture is small (2 listings)
# and stable, so the test stays fast and deterministic.
OFFLINE_SOURCE = "nexo"


def test_lab_run_basic_offline():
    result = lab_run(OFFLINE_SOURCE, limit=5, offline=True)
    assert result.ok is True
    assert result.slug == OFFLINE_SOURCE
    assert result.raw_count >= 1
    assert result.normalized_count >= 1
    assert result.duration_s >= 0
    # Default flags: validate / dedup / rank all run
    total = (
        result.validation["pass"]
        + result.validation["flag"]
        + result.validation["drop"]
    )
    assert total == result.normalized_count


def test_lab_run_skip_all_stages():
    result = lab_run(
        OFFLINE_SOURCE,
        limit=5,
        offline=True,
        with_validate=False,
        with_dedup=False,
        with_rank=False,
    )
    assert result.ok is True
    assert result.ranked_count == 0
    assert result.dedup["duplicate"] == 0
    # Validation skipped means every normalized record passes through
    # untouched; validation counts default to pass=normalized
    assert result.validation["pass"] == result.normalized_count


def test_lab_run_missing_scraper_surfaces_error():
    result = lab_run("this-scraper-does-not-exist", limit=1, offline=True)
    assert result.ok is False
    assert result.error
    assert "no scraper module" in result.error


def test_lab_run_writes_outputs(tmp_path: Path):
    write_dir = tmp_path / "lab-out"
    result = lab_run(
        OFFLINE_SOURCE, limit=5, offline=True, write_dir=write_dir
    )
    assert result.ok is True
    assert (write_dir / "raw.jsonl").exists()
    assert (write_dir / "normalized.jsonl").exists()
    assert (write_dir / "failures.jsonl").exists()
    assert (write_dir / "ranked.json").exists()
    # The four files must be valid as their declared formats
    raw_lines = (write_dir / "raw.jsonl").read_text().splitlines()
    assert len(raw_lines) == result.raw_count
    for line in raw_lines:
        json.loads(line)  # raises on malformed line
    ranked = json.loads((write_dir / "ranked.json").read_text())
    assert isinstance(ranked, list)
    assert len(ranked) == result.ranked_count


def test_render_human_report_includes_funnel_counts():
    result = lab_run(OFFLINE_SOURCE, limit=5, offline=True)
    report = render_human_report(result)
    assert "source: " + OFFLINE_SOURCE in report
    assert "fetched: " in report
    assert "normalized: " in report
    assert "validated: " in report
    assert "dedup_kept: " in report
    assert "ranked: " in report
    assert "duration: " in report


def test_render_human_report_handles_error():
    result = lab_run("this-scraper-does-not-exist", limit=1, offline=True)
    report = render_human_report(result)
    assert "status: ERR" in report
    assert "duration: " in report


def test_to_json_is_serializable():
    result = lab_run(OFFLINE_SOURCE, limit=5, offline=True)
    serialized = json.dumps(result.to_json(), default=str)
    parsed = json.loads(serialized)
    assert parsed["slug"] == OFFLINE_SOURCE
    assert "raw_count" in parsed
    assert "validation" in parsed
    assert "dedup" in parsed
