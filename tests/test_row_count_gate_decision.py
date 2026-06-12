"""Tests for the floor-aware row-count gate decision.

A single source cratering must not freeze a healthy catalogue. Motivating
incident — nightly 27399389866: xitios 28→0 (critical) hard-failed the run
while the sv __total__ GREW 1590→2104 (+32%), stranding 2104 good listings.
"""
from __future__ import annotations

from automation.row_count_sentinel import TOTAL_KEY, DropVerdict, gate_decision


def _v(source: str, level: str, curr: int, *, prev: int = 0, country: str = "sv") -> DropVerdict:
    return DropVerdict(
        source=source, country=country, prev_count=prev, curr_count=curr,
        delta=curr - prev, pct=0.0, level=level, reason="", prior_median=prev,
    )


def test_single_source_crater_degrades_when_catalogue_healthy():
    # The exact 27399389866 shape: xitios cratered, total grew.
    verdicts = [
        _v("xitios", "critical", 0, prev=28),
        _v(TOTAL_KEY, "ok", 2104, prev=1590),
        _v("nexo", "ok", 5),
    ]
    block, msg = gate_decision(verdicts, floor=1000)
    assert block is False
    assert "DEGRADE" in msg and "xitios" in msg


def test_total_collapse_still_blocks():
    # sv __total__ itself critical → catastrophic → block (the PA-clobber shape).
    verdicts = [
        _v(TOTAL_KEY, "critical", 37, prev=1590),
        _v("bienesraices", "critical", 0, prev=416),
    ]
    block, _ = gate_decision(verdicts, floor=1000)
    assert block is True


def test_below_floor_blocks_even_when_total_not_critical():
    verdicts = [
        _v("xitios", "critical", 0, prev=28),
        _v(TOTAL_KEY, "warn", 800, prev=900),  # not critical, but below floor
    ]
    block, _ = gate_decision(verdicts, floor=1000)
    assert block is True


def test_no_floor_preserves_strict_blocking():
    # Callers that don't pass a floor keep the original any-critical-blocks rule.
    verdicts = [_v("xitios", "critical", 0, prev=28), _v(TOTAL_KEY, "ok", 2104)]
    block, _ = gate_decision(verdicts, floor=None)
    assert block is True


def test_no_critical_passes_clean_with_no_message():
    verdicts = [_v("nexo", "ok", 5), _v(TOTAL_KEY, "ok", 2104)]
    block, msg = gate_decision(verdicts, floor=1000)
    assert block is False and msg == ""


def test_multiple_craters_still_degrade_if_total_healthy():
    # Several small sources die but the catalogue is still well above floor.
    verdicts = [
        _v("xitios", "critical", 0, prev=28),
        _v("agentiz", "critical", 0, prev=5),
        _v(TOTAL_KEY, "ok", 1900, prev=1800),
    ]
    block, msg = gate_decision(verdicts, floor=1000)
    assert block is False
    assert "xitios" in msg and "agentiz" in msg
