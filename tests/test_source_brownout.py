"""Tests for pulpo.source_health.compute_brownout_states (PRD P1-9).

Audit 2026-06-02 found the legacy `green-when-any-listings-returned`
classifier flagged elagente=2, nexo=5, realtyelsalvador=100 all as
green — even though elagente was ~98% below baseline. The brownout
state machine catches this.
"""
from __future__ import annotations

import datetime as dt

from pulpo.source_health import (
    DEGRADED_RATIO_THRESHOLD,
    RECOVERING_RATIO_CEILING,
    ROLLING_WINDOW,
    compute_brownout_states,
)


def _ts(days_ago: int) -> str:
    return (
        dt.datetime(2026, 6, 3, 0, 0, 0, tzinfo=dt.timezone.utc)
        - dt.timedelta(days=days_ago)
    ).isoformat()


def _row(source: str, days_ago: int, kept: int,
         status: str = "green", failure_id: str | None = None) -> dict:
    out = {
        "source": source,
        "ts": _ts(days_ago),
        "kept": kept,
        "status": status,
    }
    if failure_id is not None:
        out["failure_id"] = failure_id
    return out


def _healthy(source: str, kept: int, days: int = ROLLING_WINDOW + 1) -> list[dict]:
    """Seed a flat-baseline history. Newest row is index `days_ago=0`."""
    return [_row(source, days - 1 - i, kept) for i in range(days)]


def test_green_when_count_above_recovering_ceiling():
    history = _healthy("remax", 100)
    results = compute_brownout_states(history)
    assert len(results) == 1
    r = results[0]
    assert r.source == "remax"
    assert r.status == "green"
    assert r.ratio == 1.0
    assert r.rolling_median_7 == 100


def test_degraded_when_first_dip_below_threshold():
    """One run at 30% of baseline → degraded (not yet red)."""
    history = _healthy("nexo", 100)
    history[-1]["kept"] = 30  # 30% of 100
    results = compute_brownout_states(history)
    r = next(x for x in results if x.source == "nexo")
    assert r.status == "degraded"
    assert r.ratio == 0.3
    assert r.consecutive_degraded_runs == 1


def test_red_after_two_consecutive_degraded_runs():
    """Two consecutive runs <50% → escalates from degraded to red."""
    history = _healthy("nexo", 100)
    history[-2]["kept"] = 10
    history[-1]["kept"] = 10
    results = compute_brownout_states(history)
    r = next(x for x in results if x.source == "nexo")
    assert r.status == "red"
    assert r.consecutive_degraded_runs >= 2


def test_recovering_when_climbing_back_from_red():
    """Previous run was red; current is 70% — `recovering` state lights up."""
    history = _healthy("elagente", 100)
    history[-3]["kept"] = 10  # red baseline
    history[-3]["status"] = "red"
    history[-2]["kept"] = 10
    history[-2]["status"] = "red"
    history[-1]["kept"] = 70  # 70% of 100, after two reds
    results = compute_brownout_states(history)
    r = next(x for x in results if x.source == "elagente")
    assert r.status == "recovering"
    assert r.previous_status == "red"


def test_unknown_when_insufficient_history():
    """Brand-new source (≤3 historical rows) returns `unknown` rather
    than falsely green/red."""
    history = [_row("brand_new", 1, 5), _row("brand_new", 0, 5)]
    results = compute_brownout_states(history)
    r = next(x for x in results if x.source == "brand_new")
    assert r.status == "unknown"


def test_threshold_constants_match_prd():
    assert DEGRADED_RATIO_THRESHOLD == 0.5
    assert RECOVERING_RATIO_CEILING == 0.9
    assert ROLLING_WINDOW == 7


def test_uses_kept_in_preference_to_scraped():
    """Brownout-by-validation: scraper returns 100 placeholders, validation
    drops to 0. Brownout model must catch the post-validation collapse."""
    history = _healthy("placeholder_source", 100)
    history[-1]["kept"] = 0
    history[-1]["scraped"] = 100
    results = compute_brownout_states(history)
    r = next(x for x in results if x.source == "placeholder_source")
    assert r.count == 0
    assert r.status == "degraded"


def test_carries_failure_id_for_alert_body():
    """Slack alert needs the latest failure_id so oncall can dig into
    web/data/scraper_failures/<file> immediately."""
    history = _healthy("kazu", 100)
    history[-1]["kept"] = 5
    history[-1]["failure_id"] = "abc123"
    history[-1]["error_class"] = "HTTPError"
    results = compute_brownout_states(history)
    r = next(x for x in results if x.source == "kazu")
    assert r.failure_id == "abc123"
    assert r.error_class == "HTTPError"


def test_multiple_sources_classified_independently():
    """No cross-contamination — each source uses its own history."""
    rows = _healthy("remax", 100) + _healthy("nexo", 100)
    rows[-1]["kept"] = 10   # nexo dip
    results = compute_brownout_states(rows)
    by_src = {r.source: r for r in results}
    assert by_src["remax"].status == "green"
    assert by_src["nexo"].status == "degraded"
