"""Tests for the pre-canary source-health Slack alert script.

Covers the pure helpers (`latest_row_per_source`, `fresh_red_rows`,
`build_message`) and the CLI integration (file reads, dry-run path,
SLACK_WEBHOOK_URL absence).
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

# Import as a module — the script's `if __name__ == "__main__"` guard
# makes this safe. The runtime path-insert above is invisible to
# Pyright, hence the type-ignore.
import check_source_health as csh  # type: ignore[import-not-found]  # noqa: E402


# Originally a fixed `datetime(2026, 6, 1, 12, 0, 0)`. `csh.main()`
# calls `fresh_red_rows()` without `now=`, which defaults to
# `datetime.now(timezone.utc)`; rows whose ts is >36h old
# (STALE_CUTOFF_HOURS) get filtered out. Once wall-clock UTC moved past
# 2026-06-02 ~16:00 the integration tests below started reporting "no
# red sources" instead of the expected alert text, because every fixture
# row built off the constant was now stale by the script's own clock.
# Anchor on the actual wall clock so the tests track forward in time.
NOW = datetime.now(timezone.utc)


def _row(source: str, ts: str, status: str = "green",
         scraped: int | None = None, kept: int | None = None,
         error_class: str | None = None, failure_id: str | None = None,
         phase: str | None = None) -> dict:
    out: dict[str, object] = {"source": source, "ts": ts, "status": status}
    if scraped is not None:
        out["scraped"] = scraped
    if kept is not None:
        out["kept"] = kept
    if error_class is not None:
        out["error_class"] = error_class
    if failure_id is not None:
        out["failure_id"] = failure_id
    if phase is not None:
        out["phase"] = phase
    return out


def _ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _write_history(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "source_health_history.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


# ── latest_row_per_source ─────────────────────────────────────────────

def test_latest_row_picks_newest_ts_per_source():
    rows = [
        _row("remax", _ts(28), "red"),
        _row("remax", _ts(4),  "green"),
        _row("nexo",  _ts(8),  "red"),
    ]
    latest = csh.latest_row_per_source(rows)
    assert latest["remax"]["status"] == "green"   # most recent wins
    assert latest["nexo"]["status"] == "red"


def test_latest_row_handles_empty_input():
    assert csh.latest_row_per_source([]) == {}


# ── fresh_red_rows ────────────────────────────────────────────────────

def test_fresh_red_rows_returns_red_within_cutoff():
    latest = {
        "remax": _row("remax", _ts(4), "red", scraped=0, error_class="HTTPError"),
        "nexo":  _row("nexo",  _ts(2), "red", scraped=100, kept=0, phase="post_validation"),
        "ok":    _row("ok",    _ts(2), "green"),
    }
    red = csh.fresh_red_rows(latest, now=NOW)
    sources = sorted(r["source"] for r in red)
    assert sources == ["nexo", "remax"]


def test_fresh_red_rows_drops_stale_red():
    """A red row older than STALE_CUTOFF_HOURS is silently ignored.

    The scheduled watchdog already paged on it; re-firing here would be
    noise."""
    latest = {
        "old": _row("old", _ts(48), "red"),
        "now": _row("now", _ts(2),  "green"),
    }
    assert csh.fresh_red_rows(latest, now=NOW) == []


def test_fresh_red_rows_skips_unparsable_ts():
    latest = {
        "bad": _row("bad", "not-a-timestamp", "red"),
        "ok":  _row("ok",  _ts(2), "red"),
    }
    out = csh.fresh_red_rows(latest, now=NOW)
    assert [r["source"] for r in out] == ["ok"]


def test_fresh_red_rows_ignores_skipped_status():
    """The post_validation `phase` writer emits status="skipped" when
    scraped == 0 (the crawl-phase row already captured the red). Those
    must not fire the alert again."""
    latest = {
        "src": _row("src", _ts(2), "skipped", scraped=0, kept=0, phase="post_validation"),
    }
    assert csh.fresh_red_rows(latest, now=NOW) == []


def test_fresh_red_rows_ignores_experimental_sources(monkeypatch):
    monkeypatch.setattr(
        csh,
        "SCRAPER_METADATA",
        {"jamesedition": {"lifecycle": "experimental"}},
    )
    latest = {
        "jamesedition": _row(
            "jamesedition",
            _ts(2),
            "red",
            scraped=0,
            error_class="HTTPError",
        ),
    }
    assert csh.fresh_red_rows(latest, now=NOW) == []


# ── build_message ─────────────────────────────────────────────────────

def test_build_message_includes_each_red_source():
    red = [
        _row("remax", _ts(2), "red", scraped=0, error_class="HTTPError",
             failure_id="abc123"),
        _row("nexo",  _ts(2), "red", scraped=100, kept=0,
             phase="post_validation"),
    ]
    msg = csh.build_message(red, run_url="https://github.com/foo/bar/actions/runs/42")
    assert "2 source(s) red" in msg
    assert "remax" in msg
    assert "nexo" in msg
    assert "scraped=0" in msg
    assert "scraped=100" in msg
    assert "kept=0" in msg
    assert "abc123" in msg
    assert "https://github.com/foo/bar/actions/runs/42" in msg


def test_build_message_uses_zero_records_default_error_class():
    """A red row with no error_class (e.g. empty_yield) gets the
    'ZeroRecords' default in the alert body."""
    red = [_row("src", _ts(2), "red", scraped=0)]
    msg = csh.build_message(red, run_url=None)
    assert "err=ZeroRecords" in msg


def test_build_message_emits_em_dash_when_no_failure_id():
    red = [_row("src", _ts(2), "red", scraped=0)]
    msg = csh.build_message(red, run_url=None)
    assert "failure_id=—" in msg


def test_build_message_falls_back_to_legacy_count_field():
    """Pre-NR-C rows used `count` instead of `scraped`. The message
    builder still reads them so legacy committed rows render cleanly."""
    legacy = {"source": "old", "ts": _ts(2), "status": "red", "count": 17}
    msg = csh.build_message([legacy], run_url=None)
    assert "scraped=17" in msg


# ── main() integration ────────────────────────────────────────────────

def test_main_exits_zero_when_no_red(tmp_path, capsys, monkeypatch):
    """A clean history file → no alert, exit 0, 'OK' line on stdout."""
    _write_history(tmp_path, [_row("remax", _ts(2), "green")])
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csh.main(["--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out and "no red sources" in out


def test_main_prints_alert_in_dry_run(tmp_path, capsys, monkeypatch):
    """--dry-run prints the alert body but does not POST."""
    _write_history(tmp_path, [
        _row("nexo", _ts(2), "red", scraped=100, kept=0,
             phase="post_validation"),
    ])
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/should-not-be-posted")
    rc = csh.main(["--data-dir", str(tmp_path), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nexo" in out
    assert "scraped=100" in out
    assert "not posting" in out


def test_main_no_webhook_skips_post(tmp_path, capsys, monkeypatch):
    """SLACK_WEBHOOK_URL unset → prints alert body + a 'skipping POST'
    breadcrumb. Used for local runs."""
    _write_history(tmp_path, [_row("nexo", _ts(2), "red", scraped=100, kept=0)])
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csh.main(["--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipping POST" in out


def test_main_empty_history_returns_zero(tmp_path, monkeypatch):
    """A missing history file degrades cleanly (e.g. very first nightly)."""
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csh.main(["--data-dir", str(tmp_path)])
    assert rc == 0


def test_main_dedupes_two_rows_per_nightly(tmp_path, capsys, monkeypatch):
    """When run.py writes both a crawl row and a post_validation row for
    the same nightly, the dedup in watchdog._read_source_history must
    collapse them to one (worst status wins). A crawl-green +
    post_validation-red pair must fire the alert."""
    rows = [
        _row("nexo", _ts(2), "green", scraped=100),
        _row("nexo", _ts(2), "red", scraped=100, kept=0,
             phase="post_validation"),
    ]
    _write_history(tmp_path, rows)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csh.main(["--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 source(s) red" in out
    assert "nexo" in out


def test_main_includes_run_url_in_body(tmp_path, capsys, monkeypatch):
    _write_history(tmp_path, [_row("nexo", _ts(2), "red", scraped=100, kept=0)])
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csh.main([
        "--data-dir", str(tmp_path),
        "--run-url", "https://github.com/javiersuarezOG/pulpo.club/actions/runs/12345",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "actions/runs/12345" in out
