"""Contract tests for the exhaustiveness schema extension (PR-S1).

These tests pin the closed-set ``KNOWN_CRAWL_STOP_REASONS`` enum and the
degradation-detection rule. Both are consumed by the operator dashboard
(PR-S7) and the watchdog Slack alerter — adding values / changing the
threshold without updating those consumers is forbidden per CLAUDE.md
producer-consumer rule (post-2026-06-02).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pulpo.scrapers.lib.coverage_logger import (
    DEGRADATION_DROP_THRESHOLD,
    DEGRADATION_HISTORY_WINDOW,
    KNOWN_CRAWL_STOP_REASONS,
    log_coverage,
)


# ---------- Closed-set enum contract ----------

def test_known_crawl_stop_reasons_contract():
    """The closed set of crawl-stop reasons. Adding a value without
    updating the operator dashboard tile + Slack formatter is
    forbidden per CLAUDE.md post-2026-06-02 rule."""
    assert KNOWN_CRAWL_STOP_REASONS == frozenset({
        "pagination_exhausted",
        "max_pages_hit",
        "limit_hit",
        "http_error",
        "empty_response",
        "parser_returned_zero",
        "rate_limit",
        "timeout",
        "unknown",
    })


def test_thresholds_anchor():
    """Lock the calibration constants — tuning these is deliberate."""
    assert DEGRADATION_DROP_THRESHOLD == 0.25
    assert DEGRADATION_HISTORY_WINDOW == 7


# ---------- crawl_stop_reason validation ----------

def test_log_coverage_accepts_known_reason(tmp_path: Path):
    out = tmp_path / "cov.jsonl"
    row = log_coverage(
        "elagente",
        raw_count=2,
        kept_count=2,
        crawl_stop_reason="pagination_exhausted",
        path=out,
    )
    assert row["crawl_stop_reason"] == "pagination_exhausted"


def test_log_coverage_accepts_none_reason(tmp_path: Path):
    """Backwards-compat: existing callers without the field stay green."""
    out = tmp_path / "cov.jsonl"
    row = log_coverage("nexo", raw_count=5, kept_count=5, path=out)
    assert row["crawl_stop_reason"] is None


def test_log_coverage_rejects_unknown_reason(tmp_path: Path):
    """A typo in the crawl_stop_reason would silently degrade telemetry
    if accepted. The contract makes it loud."""
    out = tmp_path / "cov.jsonl"
    with pytest.raises(ValueError, match="not in KNOWN_CRAWL_STOP_REASONS"):
        log_coverage(
            "elagente",
            raw_count=2,
            kept_count=2,
            crawl_stop_reason="i_made_this_up",
            path=out,
        )


# ---------- Extended-field write-through ----------

def test_log_coverage_persists_pages_seen(tmp_path: Path):
    out = tmp_path / "cov.jsonl"
    log_coverage(
        "encuentra24",
        raw_count=300,
        kept_count=240,
        pages_seen=12,
        pages_attempted=15,
        limit_hit=False,
        max_pages_hit=True,
        last_page_url="https://www.encuentra24.com/sv/page=15",
        crawl_stop_reason="max_pages_hit",
        path=out,
    )
    row = json.loads(out.read_text().splitlines()[0])
    assert row["pages_seen"] == 12
    assert row["pages_attempted"] == 15
    assert row["limit_hit"] is False
    assert row["max_pages_hit"] is True
    assert row["last_page_url"] == "https://www.encuentra24.com/sv/page=15"


# ---------- Degradation detection ----------

def _seed_history(path: Path, source: str, counts: list[int]) -> None:
    """Seed prior coverage rows so degradation detection has context."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for i, count in enumerate(counts):
            fh.write(json.dumps({
                "ts": f"2026-06-{i + 1:02d}T00:00:00+00:00",
                "source": source,
                "raw": count,
                "kept": count,
                "target_prd": None,
                "target_discovered": None,
                "coverage_ratio_vs_discovered": None,
                "coverage_ratio_vs_prd": None,
                "overlap_ratio": None,
                "status": "ok",
            }) + "\n")


def test_degradation_flips_status_to_degraded(tmp_path: Path):
    """7-run median was 100; current run is 60 (40% drop) → degraded."""
    out = tmp_path / "cov.jsonl"
    _seed_history(out, "remax", [100, 100, 100, 100, 100, 100, 100])
    row = log_coverage("remax", raw_count=60, kept_count=60, path=out)
    assert row["status"] == "degraded"
    assert row["prior_median"] == 100


def test_no_degradation_when_drop_under_25pct(tmp_path: Path):
    """7-run median 100; current run 80 (20% drop) → still ok (NOT
    degraded). The 25% threshold is strictly >."""
    out = tmp_path / "cov.jsonl"
    _seed_history(out, "remax", [100, 100, 100, 100, 100, 100, 100])
    row = log_coverage("remax", raw_count=80, kept_count=80, path=out)
    assert row["status"] == "ok"
    assert row["prior_median"] is None  # degradation NOT flagged


def test_no_degradation_with_short_history(tmp_path: Path):
    """Need at least 3 prior runs. With 2 runs of history we don't
    have enough signal to flag — wait for more data."""
    out = tmp_path / "cov.jsonl"
    _seed_history(out, "remax", [100, 100])
    row = log_coverage("remax", raw_count=10, kept_count=10, path=out)
    # Even though 10 is 90% below 100, history < 3 → no flag
    assert row["status"] == "ok"
    assert row["prior_median"] is None


def test_no_degradation_when_median_zero(tmp_path: Path):
    """Defensive: a fresh source with 0,0,0 history shouldn't divide-
    by-zero its way into "degraded"."""
    out = tmp_path / "cov.jsonl"
    _seed_history(out, "nexo", [0, 0, 0, 0])
    row = log_coverage("nexo", raw_count=0, kept_count=0, path=out)
    assert row["status"] == "ok"


def test_degradation_uses_median_not_mean(tmp_path: Path):
    """Median is robust to a single outlier nightly. With history
    [100,100,100,100,100,100,200], median=100, mean=114 — current 60
    (40% below median) should flag."""
    out = tmp_path / "cov.jsonl"
    _seed_history(out, "remax", [100, 100, 100, 100, 100, 100, 200])
    row = log_coverage("remax", raw_count=60, kept_count=60, path=out)
    assert row["status"] == "degraded"
    assert row["prior_median"] == 100  # median, not 114


def test_degradation_overrides_warn_status(tmp_path: Path):
    """A source with coverage_ratio_vs_prd < 0.8 would normally be
    "warn". If it's ALSO degraded vs history, the more-urgent
    "degraded" status wins."""
    out = tmp_path / "cov.jsonl"
    _seed_history(out, "src", [500, 500, 500, 500, 500, 500, 500])
    row = log_coverage(
        "src",
        raw_count=100,
        kept_count=100,
        target_discovered=1000,  # ratio = 0.1 → would be warn
        path=out,
    )
    assert row["status"] == "degraded"  # NOT "warn"


def test_growth_never_flags_degraded(tmp_path: Path):
    """Doubling listings vs history is good news, not degraded."""
    out = tmp_path / "cov.jsonl"
    _seed_history(out, "src", [50, 50, 50, 50, 50, 50, 50])
    row = log_coverage("src", raw_count=200, kept_count=200, path=out)
    assert row["status"] == "ok"
