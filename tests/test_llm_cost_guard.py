"""Tests for the LLM cost guard (PR-D4)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from automation.llm_cost_guard import (
    BudgetExceededError,
    BudgetSnapshot,
    CRITICAL_FRACTION,
    DEFAULT_DAILY_USD_CAP,
    DEFAULT_MONTHLY_USD_CAP,
    KNOWN_BUDGET_VERDICTS,
    WARN_FRACTION,
    _classify,
    check_budget,
    daily_cap_usd,
    ensure_under_budget,
    monthly_cap_usd,
    record_cost,
)


# ---------- Closed-set contract ----------

def test_known_verdicts_contract():
    """Per CLAUDE.md producer-consumer rule (post-2026-06-02)."""
    assert KNOWN_BUDGET_VERDICTS == frozenset({"ok", "warn", "critical", "blocked"})


def test_defaults_anchored():
    assert DEFAULT_MONTHLY_USD_CAP == 20.0
    assert DEFAULT_DAILY_USD_CAP == 2.0
    assert WARN_FRACTION == 0.80
    assert CRITICAL_FRACTION == 0.95


# ---------- Env override ----------

def test_monthly_cap_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_MONTHLY_USD_CAP", "5.5")
    assert monthly_cap_usd() == 5.5


def test_monthly_cap_falls_back_on_bad_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_MONTHLY_USD_CAP", "not_a_number")
    assert monthly_cap_usd() == DEFAULT_MONTHLY_USD_CAP


def test_daily_cap_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_DAILY_USD_CAP", "0.5")
    assert daily_cap_usd() == 0.5


# ---------- Pure classifier ----------

def test_classify_ok_when_both_under_80pct():
    verdict, reason = _classify(0.5, 0.3)
    assert verdict == "ok"
    assert reason is None


def test_classify_warn_when_monthly_above_80pct():
    verdict, _ = _classify(0.85, 0.1)
    assert verdict == "warn"


def test_classify_warn_when_daily_above_80pct():
    verdict, _ = _classify(0.1, 0.85)
    assert verdict == "warn"


def test_classify_critical_at_95pct():
    verdict, _ = _classify(0.95, 0.1)
    assert verdict == "critical"


def test_classify_blocked_at_100pct_monthly():
    verdict, reason = _classify(1.0, 0.1)
    assert verdict == "blocked"
    assert "monthly" in reason


def test_classify_blocked_at_100pct_daily():
    verdict, reason = _classify(0.1, 1.0)
    assert verdict == "blocked"
    assert "daily" in reason


def test_classify_monthly_block_beats_daily_warn():
    """When monthly is 100%+ and daily is below WARN, block reason is monthly."""
    verdict, reason = _classify(1.5, 0.4)
    assert verdict == "blocked"
    assert "monthly" in reason


# ---------- Persistence ----------

def test_record_cost_creates_file(tmp_path: Path):
    p = tmp_path / "nested" / "history.jsonl"
    record_cost(
        cost_usd=0.001,
        purpose="enrichment",
        history_path=p,
        now=dt.datetime(2026, 6, 5, tzinfo=dt.timezone.utc),
    )
    assert p.exists()
    rows = [json.loads(line) for line in p.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["cost_usd"] == 0.001
    assert rows[0]["purpose"] == "enrichment"
    assert rows[0]["model"] == "deepseek-chat"


def test_record_cost_appends_does_not_overwrite(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    record_cost(cost_usd=0.001, purpose="a", history_path=p)
    record_cost(cost_usd=0.002, purpose="b", history_path=p)
    rows = p.read_text().splitlines()
    assert len(rows) == 2


# ---------- check_budget ----------

def _seed(path: Path, events: list[tuple[str, float]]) -> None:
    """Write cost events (iso_ts, cost_usd) to the history file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ts, cost in events:
            f.write(json.dumps({"ts": ts, "cost_usd": cost, "purpose": "test"}) + "\n")


def test_check_budget_ok_with_low_spend(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    _seed(p, [("2026-06-05T00:00:00+00:00", 0.5)])
    snap = check_budget(
        history_path=p,
        monthly_cap=10.0,
        daily_cap=1.0,
        now=dt.datetime(2026, 6, 5, 12, tzinfo=dt.timezone.utc),
    )
    assert snap.verdict == "ok"
    assert snap.month_to_date_usd == 0.5
    assert snap.today_usd == 0.5


def test_check_budget_warn_at_80pct(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    _seed(p, [("2026-06-05T00:00:00+00:00", 0.8)])
    snap = check_budget(
        history_path=p, monthly_cap=10.0, daily_cap=1.0,
        now=dt.datetime(2026, 6, 5, 12, tzinfo=dt.timezone.utc),
    )
    # daily 0.8/1.0 = 80% → warn
    assert snap.verdict == "warn"


def test_check_budget_critical_at_95pct(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    _seed(p, [("2026-06-05T00:00:00+00:00", 0.95)])
    snap = check_budget(
        history_path=p, monthly_cap=10.0, daily_cap=1.0,
        now=dt.datetime(2026, 6, 5, 12, tzinfo=dt.timezone.utc),
    )
    assert snap.verdict == "critical"


def test_check_budget_blocked_at_100pct(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    _seed(p, [("2026-06-05T00:00:00+00:00", 1.0)])
    snap = check_budget(
        history_path=p, monthly_cap=10.0, daily_cap=1.0,
        now=dt.datetime(2026, 6, 5, 12, tzinfo=dt.timezone.utc),
    )
    assert snap.verdict == "blocked"
    assert snap.blocking_reason is not None


def test_check_budget_excludes_prior_month(tmp_path: Path):
    """Last month's spend doesn't count toward this month's cap."""
    p = tmp_path / "history.jsonl"
    _seed(p, [
        ("2026-05-15T00:00:00+00:00", 100.0),  # prior month
        ("2026-06-05T00:00:00+00:00", 0.1),    # this month
    ])
    snap = check_budget(
        history_path=p, monthly_cap=10.0, daily_cap=1.0,
        now=dt.datetime(2026, 6, 5, 12, tzinfo=dt.timezone.utc),
    )
    assert snap.month_to_date_usd == 0.1
    assert snap.verdict == "ok"


def test_check_budget_excludes_prior_day_from_today(tmp_path: Path):
    """Yesterday's spend doesn't count toward today's cap."""
    p = tmp_path / "history.jsonl"
    _seed(p, [
        ("2026-06-04T00:00:00+00:00", 1.5),  # yesterday — would exceed daily cap
        ("2026-06-05T00:00:00+00:00", 0.1),  # today
    ])
    snap = check_budget(
        history_path=p, monthly_cap=10.0, daily_cap=1.0,
        now=dt.datetime(2026, 6, 5, 12, tzinfo=dt.timezone.utc),
    )
    assert snap.today_usd == 0.1
    # Total monthly still includes yesterday: 1.6, below cap of 10.
    assert snap.month_to_date_usd == 1.6
    assert snap.verdict == "ok"


def test_check_budget_missing_file_is_ok(tmp_path: Path):
    """No history at all → 0 spend, fully ok."""
    snap = check_budget(
        history_path=tmp_path / "absent.jsonl",
        monthly_cap=10.0, daily_cap=1.0,
        now=dt.datetime(2026, 6, 5, 12, tzinfo=dt.timezone.utc),
    )
    assert snap.month_to_date_usd == 0.0
    assert snap.verdict == "ok"


def test_check_budget_tolerates_malformed_rows(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    p.write_text(
        '{"ts":"2026-06-05T00:00:00+00:00","cost_usd":0.1,"purpose":"x"}\n'
        'not json\n'
        '{"ts":"bad-iso","cost_usd":99}\n'
        '{"ts":"2026-06-05T01:00:00+00:00","cost_usd":"not_a_number"}\n'
        '{"ts":"2026-06-05T02:00:00+00:00","cost_usd":0.2,"purpose":"x"}\n'
    )
    snap = check_budget(
        history_path=p, monthly_cap=10.0, daily_cap=1.0,
        now=dt.datetime(2026, 6, 5, 12, tzinfo=dt.timezone.utc),
    )
    # Only the two valid rows summed.
    assert snap.month_to_date_usd == 0.3


# ---------- ensure_under_budget ----------

def test_ensure_under_budget_returns_snapshot_when_ok(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    _seed(p, [("2026-06-05T00:00:00+00:00", 0.1)])
    snap = ensure_under_budget(
        history_path=p, monthly_cap=10.0, daily_cap=1.0,
    )
    assert isinstance(snap, BudgetSnapshot)
    assert snap.verdict == "ok"


def test_ensure_under_budget_raises_when_blocked(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    _seed(p, [("2026-06-05T00:00:00+00:00", 99.9)])  # blow the cap
    with pytest.raises(BudgetExceededError, match="monthly"):
        ensure_under_budget(
            history_path=p, monthly_cap=10.0, daily_cap=1.0,
        )
