"""Tests for automation/guard_policy.py (RESILIENCE-AUDIT-PRD R2, slice 1).

The population-regression guard must classify a population-MIX shift as a
warn (ship) while inventory is healthy, and only block on a genuine collapse.
This is the exact fix for run 27050642483.
"""
from __future__ import annotations

import json
from pathlib import Path

from automation.guard_policy import (
    BLOCK,
    WARN,
    GuardDecision,
    append_guard_report,
    evaluate_population_regression,
)

# The literal regression that froze run 27050642483.
REGS = ["is_motivated: 15.3% → 8.1% (relative drop 47.1% > threshold 20%)"]


def test_warn_when_inventory_above_floor():
    d = evaluate_population_regression(REGS, visible_count=2107, floor=1000)
    assert d.severity == WARN
    assert d.decision == WARN
    assert d.recoverable is True
    assert d.name == "population_regression"
    assert d.metrics["visible_count"] == 2107
    assert d.metrics["floor"] == 1000
    assert d.metrics["healthy_above_floor"] is True


def test_warn_at_exactly_floor():
    # At the floor counts as healthy (>=).
    d = evaluate_population_regression(REGS, visible_count=1000, floor=1000)
    assert d.severity == WARN


def test_block_when_inventory_below_floor():
    d = evaluate_population_regression(REGS, visible_count=300, floor=1000)
    assert d.severity == BLOCK
    assert d.decision == BLOCK
    assert d.recoverable is False
    assert d.metrics["healthy_above_floor"] is False


def test_decision_has_prd_shape():
    d = evaluate_population_regression(REGS, visible_count=2000, floor=1000)
    payload = d.to_dict()
    assert set(payload) >= {
        "name", "severity", "decision", "recoverable",
        "message", "metrics", "evidence_uri",
    }
    assert isinstance(d, GuardDecision)
    assert d.severity in (BLOCK, WARN)  # never quarantine for this guard


def test_message_and_metrics_carry_regressions():
    regs = REGS + ["beachfront_tier_near_beach: 2.0% → 0.0%"]
    d = evaluate_population_regression(regs, visible_count=1800, floor=1500)
    assert d.metrics["regression_count"] == 2
    assert d.metrics["regressions"] == regs
    assert "visible=1800" in d.message and "floor=1500" in d.message


def test_append_guard_report_accumulates_a_list(tmp_path: Path):
    d = evaluate_population_regression(REGS, visible_count=2000, floor=1000)
    append_guard_report(tmp_path, d)
    append_guard_report(tmp_path, d)
    data = json.loads((tmp_path / "guard_report.json").read_text())
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["name"] == "population_regression"
    assert data[0]["severity"] == WARN


def test_append_guard_report_is_resilient_to_garbage(tmp_path: Path):
    # A non-list pre-existing file must not crash; it's replaced with a list.
    (tmp_path / "guard_report.json").write_text("not json{", encoding="utf-8")
    d = evaluate_population_regression(REGS, visible_count=2000, floor=1000)
    append_guard_report(tmp_path, d)
    data = json.loads((tmp_path / "guard_report.json").read_text())
    assert isinstance(data, list) and len(data) == 1
