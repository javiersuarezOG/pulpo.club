from __future__ import annotations

from automation.delta_decision import (
    KNOWN_DELTA_DECISIONS,
    classify_decision,
    decide_deltas,
    format_slack_decision,
)
from automation.row_count_sentinel import DropVerdict


def _v(source: str = "src", curr: int = 0, level: str = "critical") -> DropVerdict:
    return DropVerdict(source, "sv", 100, curr, curr - 100, -1.0, level, "pct=100%", 100)


def test_known_delta_decisions_contract():
    assert KNOWN_DELTA_DECISIONS == frozenset({
        "source_failed",
        "source_partial",
        "validation_collapse",
        "expected_change",
        "unknown",
    })


def test_classifies_source_failed_from_red_health():
    decision = classify_decision(
        _v(),
        latest_health={"src": {"status": "red", "failure_id": "abc123"}},
        succeeded_sources={"src"},
    )
    assert decision.bucket == "source_failed"
    assert decision.failure_id == "abc123"


def test_classifies_validation_collapse():
    decision = classify_decision(
        _v(curr=0),
        latest_health={"src": {"status": "green", "scraped": 50, "kept": 0}},
        succeeded_sources={"src"},
    )
    assert decision.bucket == "validation_collapse"


def test_classifies_source_partial():
    decision = classify_decision(
        _v(curr=80),
        latest_health={"src": {"status": "green", "scraped": 80, "kept": 80}},
        succeeded_sources={"src"},
    )
    assert decision.bucket == "source_partial"


def test_classifies_expected_change_for_ok_and_experimental():
    ok = classify_decision(_v(curr=100, level="ok"), succeeded_sources={"src"})
    experimental = classify_decision(
        _v("jamesedition"),
        succeeded_sources=set(),
        metadata={"jamesedition": {"lifecycle": "experimental"}},
    )
    assert ok.bucket == "expected_change"
    assert experimental.bucket == "expected_change"


def test_classifies_unknown_when_no_bucket_fits():
    decision = classify_decision(
        _v(curr=100, level="warn"),
        latest_health={"src": {"status": "green", "scraped": 100, "kept": 100}},
        succeeded_sources={"src"},
    )
    assert decision.bucket == "unknown"


def test_decide_deltas_excludes_total_and_formats_slack():
    decisions = decide_deltas(
        [_v("__total__"), _v("src")],
        source_health_rows=[{"source": "src", "status": "red", "failure_id": "abc123"}],
        succeeded_sources=set(),
    )
    assert [d.source for d in decisions] == ["src"]
    message = format_slack_decision(decisions, "https://example.test/run")
    assert "source_failed" in message
    assert "abc123" in message
    assert "https://example.test/run" in message
