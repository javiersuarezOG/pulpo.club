"""Unit tests for scripts/scraper_autorepair.py — the Phase-4 shadow-
mode orchestrator. No network calls — the Anthropic client and the
``gh`` CLI are stubbed out.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import scraper_autorepair as autorepair  # noqa: E402


# ── latest_health_per_source ──────────────────────────────────────────


def test_latest_health_per_source_picks_newest_ts(tmp_path):
    p = tmp_path / "history.jsonl"
    p.write_text(
        json.dumps({"ts": "2026-05-20T00:00:00Z", "source": "x", "status": "green", "count": 10}) + "\n" +
        json.dumps({"ts": "2026-05-21T00:00:00Z", "source": "x", "status": "red",   "count": 0})  + "\n" +
        json.dumps({"ts": "2026-05-20T00:00:00Z", "source": "y", "status": "green", "count": 5})  + "\n",
        encoding="utf-8",
    )
    latest = autorepair.latest_health_per_source(p)
    assert latest["x"]["status"] == "red"
    assert latest["x"]["count"] == 0
    assert latest["y"]["status"] == "green"


def test_latest_health_per_source_ignores_corrupt_lines(tmp_path):
    p = tmp_path / "history.jsonl"
    p.write_text("not-json\n" + json.dumps({"ts": "2026-05-21T00:00:00Z", "source": "x", "status": "red"}) + "\n",
                 encoding="utf-8")
    latest = autorepair.latest_health_per_source(p)
    assert latest == {"x": {"ts": "2026-05-21T00:00:00Z", "source": "x", "status": "red"}}


def test_latest_health_per_source_missing_file(tmp_path):
    p = tmp_path / "no-such-file.jsonl"
    assert autorepair.latest_health_per_source(p) == {}


# ── _resolve_data_dir (PR-NR-D autorepair input plumbing) ─────────────

def test_resolve_data_dir_uses_artifact_when_present(tmp_path, monkeypatch, capsys):
    """When the workflow's download-artifact step writes a path that
    exists, AUTOREPAIR_DATA_DIR points at it and the resolver returns
    that path. The print line lands in the workflow log so the
    artifact-vs-fallback decision is auditable."""
    artifact = tmp_path / "nightly-diagnostics"
    artifact.mkdir()
    monkeypatch.setenv("AUTOREPAIR_DATA_DIR", str(artifact))
    out = autorepair._resolve_data_dir()
    assert out == artifact
    log = capsys.readouterr().out
    assert "nightly artifact" in log


def test_resolve_data_dir_falls_back_when_artifact_missing(tmp_path, monkeypatch, capsys):
    """A non-existent AUTOREPAIR_DATA_DIR path (download-artifact failed,
    older nightly without the upload step) falls back to web/data and
    logs the reason."""
    monkeypatch.setenv("AUTOREPAIR_DATA_DIR", str(tmp_path / "does-not-exist"))
    out = autorepair._resolve_data_dir()
    assert out == autorepair.REPO / "web" / "data"
    log = capsys.readouterr().out
    assert "falling back" in log


def test_resolve_data_dir_empty_env_means_committed_main(monkeypatch, capsys):
    """Manual dispatch path: AUTOREPAIR_DATA_DIR unset / empty → use
    committed main data."""
    monkeypatch.delenv("AUTOREPAIR_DATA_DIR", raising=False)
    out = autorepair._resolve_data_dir()
    assert out == autorepair.REPO / "web" / "data"
    log = capsys.readouterr().out
    assert "committed main" in log


def test_red_sources_filters_by_status():
    rows = {
        "alpha": {"status": "green"},
        "bravo": {"status": "red"},
        "charlie": {"status": "red"},
    }
    out = autorepair.red_sources(rows)
    assert set(out) == {"bravo", "charlie"}


# ── policy enforcement ────────────────────────────────────────────────


def test_attempt_repair_skips_when_policy_blocks(monkeypatch):
    """realtyelsalvador has auto_repair=False in _policy.py — the
    orchestrator must skip it without calling Anthropic. Pin so a
    refactor doesn't accidentally let the WAF-bound source through."""
    monkeypatch.setattr(autorepair, "cooldown_active", lambda *_a, **_k: False)
    res = autorepair.attempt_repair(
        "realtyelsalvador",
        {"source": "realtyelsalvador", "status": "red"},
        mode="shadow", model="claude-opus-4-7", dry_run=True,
    )
    assert res.skipped_reason is not None
    assert "auto_repair=False" in res.skipped_reason


def test_attempt_repair_skips_during_cooldown(monkeypatch):
    """No PR-spam: if there was a recent auto-repair attempt for the
    same source, skip without burning a Claude call."""
    monkeypatch.setattr(autorepair, "cooldown_active", lambda src, days=7: True)
    res = autorepair.attempt_repair(
        "encuentra24",
        {"source": "encuentra24", "status": "red"},
        mode="shadow", model="claude-opus-4-7", dry_run=True,
    )
    assert res.skipped_reason is not None
    assert "cooldown" in res.skipped_reason


def test_attempt_repair_skips_when_scraper_missing(monkeypatch):
    monkeypatch.setattr(autorepair, "cooldown_active", lambda *_a, **_k: False)
    res = autorepair.attempt_repair(
        "does-not-exist",
        {"source": "does-not-exist", "status": "red"},
        mode="shadow", model="claude-opus-4-7", dry_run=True,
    )
    assert res.skipped_reason is not None
    assert "not found" in res.skipped_reason


# ── prompt construction ──────────────────────────────────────────────


def test_build_prompt_includes_required_sections():
    ctx = autorepair.RepairContext(
        source="goodlife",
        failure_id="abc12345",
        failure_payload={"source": "goodlife", "kind": "exception", "exception": {"class": "HTTPError"}},
        scraper_path=Path("pulpo/scrapers/goodlife.py"),
        scraper_code="# scraper code here\nprint('hi')",
        last_good_fixture="<html>last good</html>",
        recent_commits="abc123 2026-05-20 fix(goodlife): tweak",
        health_row={"source": "goodlife", "status": "red", "count": 0, "failure_id": "abc12345"},
    )
    prompt = autorepair.build_prompt(ctx)
    # The prompt must constrain the model on scope.
    assert "Only modify pulpo/scrapers/goodlife.py" in prompt
    assert "## Diagnosis" in prompt
    assert "## Proposed patch" in prompt
    assert "## Confidence" in prompt
    assert "scraper code here" in prompt
    assert "HTTPError" in prompt   # failure payload made it in
    assert "<html>last good</html>" in prompt
    assert "abc123 2026-05-20" in prompt


def test_build_prompt_caps_fixture_size():
    """Fixture HTML capped at 30KB to keep prompt size predictable."""
    big = "X" * 100_000
    ctx = autorepair.RepairContext(
        source="goodlife", failure_id=None, failure_payload=None,
        scraper_path=Path("pulpo/scrapers/goodlife.py"),
        scraper_code="", last_good_fixture=big,
        recent_commits="", health_row={},
    )
    prompt = autorepair.build_prompt(ctx)
    # Count the X-block directly: the fixture is embedded between
    # the opening ```html and the closing ``` before the scraper code.
    x_block = prompt[prompt.find("```html"):prompt.find("```\n\nCurrent scraper code")]
    x_count = x_block.count("X")
    assert x_count <= 30_000, f"fixture not capped: {x_count}"


# ── call_anthropic dry-run ───────────────────────────────────────────


def test_call_anthropic_dry_run_returns_stub():
    """Dry-run path must NOT touch the network. Returns a deterministic
    stub the rest of the orchestrator can post to the watchdog issue."""
    out = autorepair.call_anthropic("test prompt", model="claude-opus-4-7", dry_run=True)
    assert "DRY-RUN" in out
    assert "Diagnosis" in out


def test_call_anthropic_no_api_key_returns_stub(monkeypatch):
    """When ANTHROPIC_API_KEY is unset the function returns the stub —
    workflow can run end-to-end before the secret is provisioned."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = autorepair.call_anthropic("test prompt", model="claude-opus-4-7", dry_run=False)
    assert "DRY-RUN" in out


# ── shadow-mode comment flow ─────────────────────────────────────────


def test_shadow_mode_posts_comment_on_found_issue(monkeypatch):
    """Happy path: dry-run, found watchdog issue, comment posted."""
    monkeypatch.setattr(autorepair, "cooldown_active", lambda *_a, **_k: False)
    monkeypatch.setattr(autorepair, "find_watchdog_issue_for", lambda src: 42)
    posted: dict = {}

    def _post(issue_no, body):
        posted["issue"] = issue_no
        posted["body"] = body
        return True

    monkeypatch.setattr(autorepair, "post_comment", _post)
    res = autorepair.attempt_repair(
        "goodlife",
        {"source": "goodlife", "status": "red", "count": 0},
        mode="shadow", model="claude-opus-4-7", dry_run=True,
    )
    assert res.posted_to_issue == 42
    assert not res.errors
    assert "goodlife" in posted["body"]
    assert "shadow" in posted["body"].lower()
    # The DRY-RUN stub must appear in the comment.
    assert "DRY-RUN" in posted["body"]


def test_shadow_mode_records_error_when_no_issue_found(monkeypatch):
    monkeypatch.setattr(autorepair, "cooldown_active", lambda *_a, **_k: False)
    monkeypatch.setattr(autorepair, "find_watchdog_issue_for", lambda src: None)
    res = autorepair.attempt_repair(
        "goodlife",
        {"source": "goodlife", "status": "red", "count": 0},
        mode="shadow", model="claude-opus-4-7", dry_run=True,
    )
    assert "no_watchdog_issue_to_comment_on" in res.errors


# ── main() entry point ───────────────────────────────────────────────


def test_main_exits_zero_when_no_red_sources(monkeypatch, tmp_path):
    p = tmp_path / "history.jsonl"
    p.write_text(json.dumps({"ts": "2026-05-21T00:00:00Z", "source": "goodlife",
                             "status": "green", "count": 10}) + "\n", encoding="utf-8")
    monkeypatch.setattr(autorepair, "HEALTH_PATH", p)
    monkeypatch.delenv("AUTOREPAIR_TARGETS", raising=False)
    rc = autorepair.main()
    assert rc == 0


def test_main_respects_targets_env_var(monkeypatch, tmp_path):
    """When AUTOREPAIR_TARGETS is set, the script processes ONLY those
    sources — useful for workflow_dispatch manual triggers."""
    p = tmp_path / "history.jsonl"
    p.write_text("", encoding="utf-8")
    monkeypatch.setattr(autorepair, "HEALTH_PATH", p)
    monkeypatch.setenv("AUTOREPAIR_TARGETS", "goodlife")
    monkeypatch.setenv("AUTOREPAIR_DRY_RUN", "1")

    seen: list[str] = []

    def _fake_attempt(src, *args, **kwargs):
        seen.append(src)
        return autorepair.RepairResult(source=src, skipped_reason="test")

    monkeypatch.setattr(autorepair, "attempt_repair", _fake_attempt)
    rc = autorepair.main()
    assert rc == 0
    assert seen == ["goodlife"]
