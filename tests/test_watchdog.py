"""Unit tests for automation/watchdog.py — all synthetic, no live data."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.watchdog import (  # noqa: E402
    check_freshness,
    check_parser_errors,
    check_volume,
    FRESHNESS_HOURS,
    VOLUME_TOLERANCE,
    VOLUME_FLOOR,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _write_meta(tmp_path: Path, ts: datetime, total: int = 800) -> Path:
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    (d / "last_updated.json").write_text(json.dumps({
        "last_updated": ts.isoformat(),
        "total_listings": total,
    }))
    return d


def _write_ranked(data_dir: Path, count: int) -> None:
    (data_dir / "ranked.json").write_text(json.dumps([{"id": i} for i in range(count)]))


def _write_history(data_dir: Path, totals: list[int], days_ago: int = 0) -> None:
    now = datetime.now(timezone.utc)
    entries = [
        {"ts": (now - timedelta(days=days_ago + i)).isoformat(), "total": t}
        for i, t in enumerate(totals)
    ]
    (data_dir / "run_history.json").write_text(json.dumps(entries))


# ── Freshness ──────────────────────────────────────────────────────────

def test_freshness_recent(tmp_path):
    d = _write_meta(tmp_path, datetime.now(timezone.utc) - timedelta(hours=2))
    ok, msg = check_freshness(d)
    assert ok
    assert msg.startswith("OK")


def test_freshness_stale(tmp_path):
    d = _write_meta(tmp_path, datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_HOURS + 1))
    ok, msg = check_freshness(d)
    assert not ok
    assert "FAIL" in msg


def test_freshness_exactly_at_limit(tmp_path):
    d = _write_meta(tmp_path, datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_HOURS - 0.1))
    ok, _ = check_freshness(d)
    assert ok


def test_freshness_missing_file(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    ok, msg = check_freshness(d)
    assert not ok
    assert "missing" in msg


# ── Volume ─────────────────────────────────────────────────────────────

def test_volume_within_tolerance(tmp_path):
    d = _write_meta(tmp_path, datetime.now(timezone.utc))
    _write_ranked(d, 820)
    _write_history(d, [800, 810, 820, 830, 840, 850, 800])
    ok, msg = check_volume(d)
    assert ok, msg


def test_volume_too_low(tmp_path):
    d = _write_meta(tmp_path, datetime.now(timezone.utc))
    _write_ranked(d, 400)     # 50% below median of ~820
    _write_history(d, [800, 810, 820, 830, 840, 850, 800])
    ok, msg = check_volume(d)
    assert not ok
    assert "FAIL" in msg


def test_volume_too_high(tmp_path):
    d = _write_meta(tmp_path, datetime.now(timezone.utc))
    _write_ranked(d, 1100)    # ~34% above median of ~820
    _write_history(d, [800, 810, 820, 830, 840, 850, 800])
    ok, msg = check_volume(d)
    assert not ok
    assert "FAIL" in msg


def test_volume_exactly_at_upper_bound(tmp_path):
    median = 800
    d = _write_meta(tmp_path, datetime.now(timezone.utc))
    _write_ranked(d, int(median * (1 + VOLUME_TOLERANCE)))
    _write_history(d, [median] * 5)
    ok, _ = check_volume(d)
    assert ok


def test_volume_no_history_falls_back_to_floor(tmp_path):
    d = _write_meta(tmp_path, datetime.now(timezone.utc))
    _write_ranked(d, 100)
    ok, msg = check_volume(d)
    assert ok
    assert "floor" in msg


def test_volume_no_history_below_floor(tmp_path):
    d = _write_meta(tmp_path, datetime.now(timezone.utc))
    _write_ranked(d, VOLUME_FLOOR - 1)
    ok, msg = check_volume(d)
    assert not ok
    assert "FAIL" in msg


def test_volume_excludes_test_runs_from_median(tmp_path):
    """Runs with total < 200 (test/offline runs) must not skew the median."""
    d = _write_meta(tmp_path, datetime.now(timezone.utc))
    _write_ranked(d, 820)
    # Mix of full runs and test runs
    _write_history(d, [800, 820, 95, 21, 830, 810, 840])
    ok, msg = check_volume(d)
    assert ok, f"Test runs should be excluded from median: {msg}"


def test_volume_old_history_excluded(tmp_path):
    """Runs older than 7 days should not count toward the median."""
    d = _write_meta(tmp_path, datetime.now(timezone.utc))
    _write_ranked(d, 820)
    # All history is 8 days old — should fall back to floor
    _write_history(d, [800, 810, 820], days_ago=8)
    ok, msg = check_volume(d)
    assert ok
    assert "floor" in msg


# ── Parser errors ──────────────────────────────────────────────────────

def test_parser_errors_absent(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    ok, msg = check_parser_errors(d)
    assert ok
    assert "absent" in msg


def test_parser_errors_header_only(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "parser_errors.log").write_text(
        "# parser_errors.log — generated 2026-05-03\n"
        "# Replaced by validation_log.jsonl.\n"
    )
    ok, msg = check_parser_errors(d)
    assert ok
    assert "header-only" in msg


def test_parser_errors_has_errors(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    log = d / "parser_errors.log"
    log.write_text(
        "# header\n"
        "[bienesraices] $4.3 / 320000m²\n"
        "  title: Some lot\n"
    )
    ok, msg = check_parser_errors(d)
    assert not ok
    assert "FAIL" in msg


def test_parser_errors_old_errors_pass(tmp_path):
    """Old errors (from a run >36h ago) should not fail the watchdog."""
    import time
    d = tmp_path / "data"
    d.mkdir()
    log = d / "parser_errors.log"
    log.write_text("# header\n[source] $1 / 500000m²\n  title: stale error\n")
    # Set mtime to 48 hours ago
    old_time = time.time() - 48 * 3600
    import os
    os.utime(log, (old_time, old_time))
    ok, msg = check_parser_errors(d)
    assert ok
    assert "old" in msg.lower() or "not from this run" in msg
