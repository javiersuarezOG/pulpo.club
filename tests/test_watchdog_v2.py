"""
Tests for the v2 watchdog checks added in PR #40.

check_source_consecutive_red — alerts when a source has been status=red
for SOURCE_CONSECUTIVE_RED_THRESHOLD or more consecutive runs.

check_source_latency_regression — alerts when a source's latest
duration_s is >LATENCY_REGRESSION_RATIO× its rolling median.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.watchdog import (   # noqa: E402
    check_source_consecutive_red,
    check_source_latency_regression,
    run as watchdog_run,
    SOURCE_CONSECUTIVE_RED_THRESHOLD,
    SOURCE_STALENESS_HOURS,
    LATENCY_REGRESSION_RATIO,
    LATENCY_MIN_SAMPLES,
    LATENCY_MIN_DURATION_S,
)

# Fixed "now" used by the consecutive-red tests. All timestamps in those
# tests are relative to this — keeps them deterministic regardless of when
# the suite is run, and guarantees the staleness guard treats them as fresh.
NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)


def _ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _write_health(rows: list[dict], data_dir: Path) -> None:
    path = data_dir / "source_health_history.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _row(source: str, ts: str, status: str = "green",
         count: int = 30, duration_s: float = 12.0,
         error_class: str | None = None) -> dict:
    return {
        "ts":          ts,
        "source":      source,
        "status":      status,
        "count":       count,
        "duration_s":  duration_s,
        "error_class": error_class,
    }


# ── check_source_consecutive_red ──────────────────────────────────────

def test_consecutive_red_returns_ok_when_no_history(tmp_path):
    ok, msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert ok
    assert "no history" in msg


def test_consecutive_red_alerts_on_two_red_in_a_row(tmp_path):
    """Default threshold = 2 consecutive reds."""
    _write_health([
        _row("remax", _ts(28), "red",  count=0, error_class="ParseError"),
        _row("remax", _ts(4),  "red",  count=0, error_class="ParseError"),
        _row("goodlife", _ts(4)),
    ], tmp_path)
    ok, msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert not ok
    assert "remax" in msg
    assert "ParseError" in msg


def test_consecutive_red_quiet_after_recovery(tmp_path):
    """Yesterday red, today green → no alert."""
    _write_health([
        _row("remax", _ts(28), "red", count=0),
        _row("remax", _ts(4),  "green"),
    ], tmp_path)
    ok, _msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert ok


def test_consecutive_red_quiet_with_only_one_red_run(tmp_path):
    _write_health([
        _row("remax", _ts(4), "red", count=0, error_class="NetworkTimeout"),
    ], tmp_path)
    ok, _ = check_source_consecutive_red(tmp_path, now=NOW)
    assert ok   # one red is noise; threshold is 2


def test_consecutive_red_handles_two_sources_simultaneously(tmp_path):
    rows = [
        _row("remax",     _ts(28), "red", count=0, error_class="ParseError"),
        _row("remax",     _ts(4),  "red", count=0, error_class="ParseError"),
        _row("century21", _ts(28), "red", count=0, error_class="HTTPError"),
        _row("century21", _ts(4),  "red", count=0, error_class="HTTPError"),
    ]
    _write_health(rows, tmp_path)
    ok, msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert not ok
    assert "remax" in msg
    assert "century21" in msg


# Regression: NR-C — run.py writes a second post_validation row per source
# per nightly starting 2026-06. Without (source, ts) dedup, the two rows
# from a single nightly fill the consecutive-red detector's top-N window
# and the streak across nightlies becomes invisible. /qa 2026-06-01.
# Report: ~/.claude/plans/the-last-nightly-run-tranquil-starfish.md
def test_consecutive_red_dedupes_two_rows_per_nightly(tmp_path):
    """A nightly that writes crawl+post_validation rows for the SAME (source, ts)
    must collapse to one row before streak detection runs, so a two-nightly
    placeholder-storm still fires the alert."""
    rows = [
        # Nightly 1: scraped 100 but kept 0 (placeholder-storm).
        _row("nexo", _ts(28), "green", count=100, error_class=None),
        {
            "ts":     _ts(28),
            "source": "nexo",
            "phase":  "post_validation",
            "status": "red",
            "scraped": 100,
            "kept":    0,
        },
        # Nightly 2: same pattern.
        _row("nexo", _ts(4), "green", count=100, error_class=None),
        {
            "ts":     _ts(4),
            "source": "nexo",
            "phase":  "post_validation",
            "status": "red",
            "scraped": 100,
            "kept":    0,
        },
    ]
    _write_health(rows, tmp_path)
    ok, msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert not ok, (
        "Dedup must collapse each (source, ts) group to one row whose status is "
        "the worse of the pair (red here), so two consecutive nightlies of "
        "placeholder-storms trip the alert."
    )
    assert "nexo" in msg


def test_dedup_keeps_single_run_quiet(tmp_path):
    """A single nightly with one crawl-green + one post_validation-red row
    collapses to ONE red row — not enough for the threshold (default 2)."""
    rows = [
        _row("nexo", _ts(4), "green", count=100),
        {
            "ts":     _ts(4),
            "source": "nexo",
            "phase":  "post_validation",
            "status": "red",
            "scraped": 100,
            "kept":    0,
        },
    ]
    _write_health(rows, tmp_path)
    ok, _ = check_source_consecutive_red(tmp_path, now=NOW)
    assert ok  # 1 deduped red row is below the 2-row threshold


def test_dedup_keeps_legacy_rows_unchanged(tmp_path):
    """Existing single-row-per-(source,ts) JSONL (pre-NR-C schema) must
    behave exactly as before — dedup is a no-op on groups of size 1."""
    rows = [
        _row("remax", _ts(28), "red", count=0, error_class="ParseError"),
        _row("remax", _ts(4),  "red", count=0, error_class="ParseError"),
    ]
    _write_health(rows, tmp_path)
    ok, msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert not ok
    assert "remax" in msg
    assert "ParseError" in msg


def test_consecutive_red_threshold_is_documented():
    """Sanity guard: SOURCE_CONSECUTIVE_RED_THRESHOLD shouldn't drift to 1."""
    assert SOURCE_CONSECUTIVE_RED_THRESHOLD >= 2


def test_consecutive_red_skips_stale_source(tmp_path):
    """Regression for issues #62→#325: a source whose most-recent row is
    older than SOURCE_STALENESS_HOURS must NOT trigger the alert. Those
    are scrapers that aren't being attempted anymore (intentionally
    disabled from PULPO_SOURCES or import-broken), not active failures.
    """
    # Both rows are well past the 48h staleness cutoff — mirrors the real
    # production data (realtyelsalvador frozen at 2026-05-06).
    _write_health([
        _row("realtyelsalvador", _ts(SOURCE_STALENESS_HOURS + 24), "red",
             count=0, error_class=None),
        _row("realtyelsalvador", _ts(SOURCE_STALENESS_HOURS + 1),  "red",
             count=0, error_class=None),
    ], tmp_path)
    ok, msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert ok, f"stale red rows should not trigger alert, got: {msg}"
    assert "realtyelsalvador" in msg          # mentioned as "skipped stale"
    assert "stale" in msg


def test_consecutive_red_alerts_on_fresh_red_skips_stale(tmp_path):
    """A fresh failing source should still alert even when another source
    has stale red rows — staleness must not silence active failures."""
    _write_health([
        # Stale dead source (e.g. realtyelsalvador) — should be skipped
        _row("realtyelsalvador", _ts(SOURCE_STALENESS_HOURS + 24), "red", count=0),
        _row("realtyelsalvador", _ts(SOURCE_STALENESS_HOURS + 1),  "red", count=0),
        # Freshly failing source — should fire
        _row("remax", _ts(28), "red", count=0, error_class="ParseError"),
        _row("remax", _ts(4),  "red", count=0, error_class="ParseError"),
    ], tmp_path)
    ok, msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert not ok
    assert "remax" in msg
    assert "ParseError" in msg
    # The stale source is acknowledged as skipped, not as an active streak
    assert "realtyelsalvador" in msg
    assert "stale" in msg


def test_consecutive_red_staleness_boundary(tmp_path):
    """Rows JUST inside the staleness window still count as fresh."""
    _write_health([
        _row("nexo", _ts(SOURCE_STALENESS_HOURS - 1), "red", count=0,
             error_class="ParseError"),
        _row("nexo", _ts(2),                          "red", count=0,
             error_class="ParseError"),
    ], tmp_path)
    ok, msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert not ok
    assert "nexo" in msg


def test_staleness_constant_documented():
    """Staleness must be at least one nightly cycle, so a single missed
    run doesn't flip the alert silent prematurely."""
    assert SOURCE_STALENESS_HOURS >= 24


# ── check_source_latency_regression ───────────────────────────────────

def test_latency_returns_ok_when_no_history(tmp_path):
    ok, msg = check_source_latency_regression(tmp_path)
    assert ok
    assert "no history" in msg


def test_latency_alerts_on_3x_jump(tmp_path):
    """5 baseline runs at 10s + 1 latest at 45s → 4.5× median, alert fires."""
    rows = [
        _row("oceanside", f"2026-04-{20+i:02d}T12:00:00+00:00",
             duration_s=10.0)
        for i in range(LATENCY_MIN_SAMPLES + 1)
    ]
    rows.append(_row("oceanside", "2026-05-04T12:00:00+00:00",
                     duration_s=45.0))
    _write_health(rows, tmp_path)
    ok, msg = check_source_latency_regression(tmp_path)
    assert not ok
    assert "oceanside" in msg
    assert "4.5" in msg or "4.5×" in msg


def test_latency_quiet_below_ratio(tmp_path):
    rows = [
        _row("goodlife", f"2026-04-{20+i:02d}T12:00:00+00:00",
             duration_s=10.0)
        for i in range(LATENCY_MIN_SAMPLES + 1)
    ]
    rows.append(_row("goodlife", "2026-05-04T12:00:00+00:00",
                     duration_s=20.0))   # 2× — below 3× ratio
    _write_health(rows, tmp_path)
    ok, _ = check_source_latency_regression(tmp_path)
    assert ok


def test_latency_quiet_with_insufficient_history(tmp_path):
    """Need at least LATENCY_MIN_SAMPLES historical points."""
    rows = [
        _row("nexo", "2026-04-30T12:00:00+00:00", duration_s=8.0),
        _row("nexo", "2026-05-01T12:00:00+00:00", duration_s=120.0),  # huge jump but n=1 history
    ]
    _write_health(rows, tmp_path)
    ok, _ = check_source_latency_regression(tmp_path)
    assert ok   # not enough samples to compute a stable median


def test_latency_quiet_with_jittery_low_baseline(tmp_path):
    """When median < LATENCY_MIN_DURATION_S, suppress alerts (too noisy)."""
    # baseline 1s, latest 4s — 4× ratio but baseline below floor
    rows = [
        _row("century21", f"2026-04-{20+i:02d}T12:00:00+00:00",
             duration_s=1.0)
        for i in range(LATENCY_MIN_SAMPLES + 1)
    ]
    rows.append(_row("century21", "2026-05-04T12:00:00+00:00",
                     duration_s=4.0))
    _write_health(rows, tmp_path)
    ok, _ = check_source_latency_regression(tmp_path)
    assert ok


def test_latency_constants_documented():
    """Sanity: constants haven't drifted to nonsensical values."""
    assert LATENCY_REGRESSION_RATIO >= 2.0
    assert LATENCY_MIN_SAMPLES >= 2
    assert LATENCY_MIN_DURATION_S >= 1.0


# ── Robustness ─────────────────────────────────────────────────────────

def test_consecutive_red_skips_malformed_lines(tmp_path):
    """Bad JSON lines should be silently dropped (not crash the watchdog)."""
    path = tmp_path / "source_health_history.jsonl"
    path.write_text(
        "{not json\n"
        + json.dumps(_row("remax", _ts(28), "red", count=0)) + "\n"
        + json.dumps(_row("remax", _ts(4),  "red", count=0)) + "\n"
    )
    ok, msg = check_source_consecutive_red(tmp_path, now=NOW)
    assert not ok
    assert "remax" in msg


def test_latency_skips_zero_or_missing_duration(tmp_path):
    """Rows without a usable duration_s are excluded from the median."""
    rows = [
        _row("goodlife", f"2026-04-{20+i:02d}T12:00:00+00:00",
             duration_s=10.0)
        for i in range(LATENCY_MIN_SAMPLES + 1)
    ]
    # Add a row with duration_s=None — mustn't crash the median calc
    rows.append({"ts": "2026-05-03T12:00:00+00:00", "source": "goodlife",
                 "status": "red", "count": 0, "duration_s": None})
    rows.append(_row("goodlife", "2026-05-04T12:00:00+00:00", duration_s=12.0))
    _write_health(rows, tmp_path)
    ok, _ = check_source_latency_regression(tmp_path)
    assert ok   # 12s vs 10s baseline — well within ratio


# ── fatal vs advisory split (2026-06-30 audit) ────────────────────────
# The two source-level checks above are ADVISORY: they surface a WARN but must
# NEVER fail the watchdog on their own. Freeze detection (freshness / volume /
# parser / public-deploy) is the only thing that pages. Regression guard for
# the daily false-red where agentiz + jamesedition (ZeroRecords) turned the
# freeze-watchdog red every night and buried a real freeze in the noise.

def _fresh_data_dir(tmp_path, *, age_hours: float = 2.0, count: int = 800):
    """A data dir the fatal checks consider healthy: fresh + sane volume."""
    d = tmp_path / "data"
    d.mkdir()
    ts = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    (d / "last_updated.json").write_text(json.dumps({
        "last_updated": ts.isoformat(), "total_listings": count,
    }))
    (d / "ranked.json").write_text(json.dumps([{"id": i} for i in range(count)]))
    return d


def _real_now_iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_dead_sources_are_advisory_not_fatal(tmp_path):
    """Two dead scrapers (consecutive-red, fresh rows) must NOT fatally fail
    the watchdog — they downgrade to a non-paging WARN line."""
    d = _fresh_data_dir(tmp_path)
    _write_health([
        _row("agentiz",      _real_now_iso(28), "red", count=0, error_class="ZeroRecords"),
        _row("agentiz",      _real_now_iso(2),  "red", count=0, error_class="ZeroRecords"),
        _row("jamesedition", _real_now_iso(28), "red", count=0, error_class="ZeroRecords"),
        _row("jamesedition", _real_now_iso(2),  "red", count=0, error_class="ZeroRecords"),
    ], d)
    results = watchdog_run(data_dir=d, skip_deploy=True)
    fatal = [r for r in results if r.startswith("FAIL")]
    warns = [r for r in results if r.startswith("WARN")]
    assert not fatal, f"dead sources must not fatally fail the watchdog: {fatal}"
    assert any("agentiz" in w for w in warns), f"expected a source_health WARN: {warns}"


def test_real_freeze_still_pages(tmp_path):
    """The trip-wire is NOT decorative: stale data (a freeze) still produces a
    fatal FAIL even when the same run has dead sources."""
    d = _fresh_data_dir(tmp_path, age_hours=48)   # 48h old = stale = freeze
    _write_health([
        _row("agentiz", _real_now_iso(28), "red", count=0, error_class="ZeroRecords"),
        _row("agentiz", _real_now_iso(2),  "red", count=0, error_class="ZeroRecords"),
    ], d)
    results = watchdog_run(data_dir=d, skip_deploy=True)
    fatal = [r for r in results if r.startswith("FAIL")]
    assert any("freshness" in r for r in fatal), f"stale data must fatally fail: {results}"
