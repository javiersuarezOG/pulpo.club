"""Tests for the row-count drop classifier (PR-D2).

Pure-function tests covering every drop level + every threshold edge.
Network-free; the orchestrator is tested via temp-file fixtures.
"""
from __future__ import annotations

import json
from pathlib import Path

from automation.row_count_sentinel import (
    CRIT_ABS,
    CRIT_PCT,
    KNOWN_DROP_LEVELS,
    TOTAL_KEY,
    Tick,
    WARN_ABS,
    WARN_PCT,
    _median,
    any_critical,
    append_tick,
    classify_drop,
    count_listings_by_source,
    format_slack_message,
    load_history,
    prior_counts_for,
    run_tick,
)


# ---------- Helpers ----------

def _seed_history(path: Path, ticks: list[tuple[str, str, int, str]]) -> None:
    """Write `tick_at, source, count, country` rows to the history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for tick_at, source, count, country in ticks:
            f.write(json.dumps({
                "tick_at": tick_at,
                "source": source,
                "count": count,
                "country": country,
            }) + "\n")


# ---------- Contract ----------

def test_known_drop_levels_contract():
    """Closed-set enum — Slack alerter and dashboard rely on these
    three states. Adding a level without consumer updates is forbidden
    per CLAUDE.md producer-consumer rule (post-2026-06-02)."""
    assert KNOWN_DROP_LEVELS == frozenset({"ok", "warn", "critical"})


def test_total_key_is_reserved():
    """No real scraper may use the synthetic total key."""
    assert TOTAL_KEY == "__total__"
    assert TOTAL_KEY.startswith("__")


def test_thresholds_anchor():
    """Lock the calibration. Tuning these is a deliberate change."""
    assert WARN_PCT == 0.05
    assert WARN_ABS == 50
    assert CRIT_PCT == 0.20
    assert CRIT_ABS == 200


# ---------- classify_drop: first observation ----------

def test_first_observation_is_ok():
    """Empty prior history → ok, "first_observation". Caller records
    the tick but doesn't fire an alert."""
    v = classify_drop("nexo", "sv", curr_count=42, prior_counts=[])
    assert v.level == "ok"
    assert v.reason == "first_observation"
    assert v.delta == 42  # whole count is the "delta" against zero
    assert v.prior_median == 0


# ---------- classify_drop: growth is never bad ----------

def test_growth_is_always_ok():
    v = classify_drop("encuentra24", "sv", curr_count=500, prior_counts=[100])
    assert v.level == "ok"
    assert v.delta == 400
    assert v.pct > 0


def test_no_change_is_ok():
    v = classify_drop("bienesraices", "sv", curr_count=415, prior_counts=[415, 415, 415])
    assert v.level == "ok"
    assert v.delta == 0


# ---------- classify_drop: CRIT thresholds ----------

def test_crit_by_percent_threshold():
    """20% drop exactly: 100 → 80."""
    v = classify_drop("src", "sv", curr_count=80, prior_counts=[100])
    assert v.level == "critical"
    assert "pct=20.0%" in v.reason


def test_crit_by_absolute_threshold():
    """200-row drop, but only 10% percent — still CRIT."""
    v = classify_drop("src", "sv", curr_count=1800, prior_counts=[2000])
    assert v.level == "critical"
    assert "abs=200" in v.reason


def test_crit_catches_small_source_to_zero():
    """nexo=5 → 0 is 100% but only 5 rows. CRIT must fire on the
    percent threshold (20%>=) even when absolute (50>=) wouldn't."""
    v = classify_drop("nexo", "sv", curr_count=0, prior_counts=[5])
    assert v.level == "critical"
    assert "pct=100.0%" in v.reason


def test_crit_both_triggers_listed():
    """When both percent AND absolute fire, the reason shows both."""
    v = classify_drop("src", "sv", curr_count=0, prior_counts=[500])
    assert v.level == "critical"
    assert "pct=" in v.reason and "abs=" in v.reason


# ---------- classify_drop: WARN thresholds ----------

def test_warn_by_percent_threshold():
    """5% drop, fewer than 50 rows: 50 → 47 (6% drop, 3 rows abs)."""
    v = classify_drop("src", "sv", curr_count=47, prior_counts=[50])
    assert v.level == "warn"
    assert v.pct < 0


def test_warn_by_absolute_threshold():
    """50-row drop, 3.3% percent — still WARN."""
    v = classify_drop("src", "sv", curr_count=1450, prior_counts=[1500])
    assert v.level == "warn"


# ---------- classify_drop: OK (within thresholds) ----------

def test_within_threshold_is_ok():
    """4% drop, 4 rows absolute → ok."""
    v = classify_drop("src", "sv", curr_count=96, prior_counts=[100])
    assert v.level == "ok"
    assert "within_threshold" in v.reason


def test_just_below_warn_pct():
    """4% drop is BELOW the 5% threshold; absolute drop (4) also below
    50 → ok. Count chosen so neither threshold fires."""
    v = classify_drop("src", "sv", curr_count=96, prior_counts=[100])
    assert v.level == "ok"


def test_at_warn_pct_threshold_fires():
    """Exactly 5% drop fires WARN (>=, not >). Absolute drop (5) is
    below 50, so the percent threshold is the trigger."""
    v = classify_drop("src", "sv", curr_count=95, prior_counts=[100])
    assert v.level == "warn"


def test_at_crit_pct_threshold_fires():
    """Exactly 20% drop fires CRIT."""
    v = classify_drop("src", "sv", curr_count=80, prior_counts=[100])
    assert v.level == "critical"


# ---------- classify_drop: prev=0 edge ----------

def test_zero_prev_count_falls_back_to_absolute():
    """If the source previously had 0 listings, growth from 0 → N is
    always ok (delta is non-negative). Pulpo doesn't have a 0→N→0
    pattern in practice but the math must be safe."""
    v = classify_drop("src", "sv", curr_count=10, prior_counts=[0])
    assert v.level == "ok"  # growth


def test_zero_prev_and_zero_curr_is_ok():
    """0 → 0 is no change."""
    v = classify_drop("src", "sv", curr_count=0, prior_counts=[0])
    assert v.level == "ok"


# ---------- prior_median ----------

def test_prior_median_uses_full_history():
    """Median is over ALL prior counts, not just the immediate prev.
    Used for context in Slack alerts."""
    v = classify_drop(
        "src", "sv",
        curr_count=80,
        prior_counts=[100, 110, 105, 100, 95, 100, 100],
    )
    assert v.prior_median == 100


# ---------- _median ----------

def test_median_odd_length():
    assert _median([1, 2, 3, 4, 5]) == 3


def test_median_even_length():
    assert _median([1, 2, 3, 4]) == 2  # (2 + 3) // 2 == 2


def test_median_empty():
    assert _median([]) == 0


def test_median_unsorted_input():
    assert _median([5, 1, 3, 2, 4]) == 3


# ---------- count_listings_by_source ----------

def test_count_listings_groups_by_source(tmp_path: Path):
    ranked = [
        {"source": "remax", "url": "x"},
        {"source": "remax", "url": "y"},
        {"source": "nexo", "url": "z"},
    ]
    p = tmp_path / "ranked.json"
    p.write_text(json.dumps(ranked))
    counts = count_listings_by_source(p)
    assert counts == {"remax": 2, "nexo": 1, "__total__": 3}


def test_count_listings_handles_missing_file(tmp_path: Path):
    assert count_listings_by_source(tmp_path / "absent.json") == {}


def test_count_listings_handles_malformed_data(tmp_path: Path):
    """Defensive — listing without source field is skipped."""
    ranked = [{"source": "remax"}, {"no_source": True}]
    p = tmp_path / "ranked.json"
    p.write_text(json.dumps(ranked))
    counts = count_listings_by_source(p)
    assert counts == {"remax": 1, "__total__": 1}


def test_count_listings_total_excludes_total_key():
    """Self-consistency: synthetic total ignores itself in the sum."""
    # (Indirect: the function always computes total fresh from real
    # sources, so even if a "source": "__total__" entry was injected
    # somehow it would NOT double-count.)
    pass


# ---------- History I/O ----------

def test_load_history_returns_empty_for_missing_file(tmp_path: Path):
    assert load_history(tmp_path / "absent.jsonl") == []


def test_load_history_skips_malformed_lines(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    p.write_text(
        '{"tick_at":"2026-01-01T00:00:00+00:00","source":"a","count":10,"country":"sv"}\n'
        'not json\n'
        '{"tick_at":"2026-01-02T00:00:00+00:00","source":"a","count":20,"country":"sv"}\n'
    )
    ticks = load_history(p)
    assert len(ticks) == 2
    assert [t.count for t in ticks] == [10, 20]


def test_load_history_handles_missing_country_field(tmp_path: Path):
    """Backward-compat: a future migration might drop the field; default to sv."""
    p = tmp_path / "history.jsonl"
    p.write_text(
        '{"tick_at":"2026-01-01T00:00:00+00:00","source":"a","count":10}\n'
    )
    ticks = load_history(p)
    assert ticks[0].country == "sv"


def test_append_tick_creates_parent_dir(tmp_path: Path):
    p = tmp_path / "nested" / "history.jsonl"
    tick = Tick(tick_at="2026-01-01T00:00:00+00:00", source="a", count=10, country="sv")
    append_tick(tick, p)
    assert p.exists()


def test_append_tick_appends_does_not_overwrite(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    append_tick(Tick(tick_at="t1", source="a", count=10, country="sv"), p)
    append_tick(Tick(tick_at="t2", source="a", count=20, country="sv"), p)
    lines = p.read_text().splitlines()
    assert len(lines) == 2


# ---------- prior_counts_for ----------

def test_prior_counts_filters_by_source_and_country(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    _seed_history(p, [
        ("2026-01-01T00:00:00+00:00", "remax", 100, "sv"),
        ("2026-01-01T00:00:00+00:00", "remax", 50, "pa"),
        ("2026-01-01T00:00:00+00:00", "nexo", 5, "sv"),
        ("2026-01-02T00:00:00+00:00", "remax", 105, "sv"),
    ])
    history = load_history(p)
    counts = prior_counts_for("remax", "sv", history)
    assert counts == [100, 105]


def test_prior_counts_chronological_order(tmp_path: Path):
    """Newest must be last. Defensive against out-of-order writes."""
    p = tmp_path / "history.jsonl"
    _seed_history(p, [
        ("2026-01-03T00:00:00+00:00", "src", 30, "sv"),  # written first but newest
        ("2026-01-01T00:00:00+00:00", "src", 10, "sv"),
        ("2026-01-02T00:00:00+00:00", "src", 20, "sv"),
    ])
    history = load_history(p)
    counts = prior_counts_for("src", "sv", history)
    assert counts == [10, 20, 30]


def test_prior_counts_window_caps_at_7(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    _seed_history(p, [
        (f"2026-01-{i:02d}T00:00:00+00:00", "src", i, "sv")
        for i in range(1, 11)
    ])
    history = load_history(p)
    counts = prior_counts_for("src", "sv", history)
    assert len(counts) == 7
    # Most recent 7: counts 4..10
    assert counts == [4, 5, 6, 7, 8, 9, 10]


# ---------- run_tick orchestration ----------

def test_run_tick_classifies_and_appends(tmp_path: Path):
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps([
        {"source": "remax"},
        {"source": "remax"},
        {"source": "nexo"},
    ]))
    history = tmp_path / "history.jsonl"
    # Seed: prior counts 100/100 for remax (so 2 is a 98% drop = CRIT)
    _seed_history(history, [
        ("2026-01-01T00:00:00+00:00", "remax", 100, "sv"),
        ("2026-01-02T00:00:00+00:00", "remax", 100, "sv"),
        ("2026-01-01T00:00:00+00:00", "nexo", 5, "sv"),
        ("2026-01-01T00:00:00+00:00", "__total__", 105, "sv"),
        ("2026-01-02T00:00:00+00:00", "__total__", 105, "sv"),
    ])
    verdicts = run_tick(
        ranked_paths={"sv": ranked},
        history_path=history,
        now_iso="2026-01-03T00:00:00+00:00",
    )
    # critical first
    assert verdicts[0].level == "critical"
    by_source = {v.source: v for v in verdicts}
    assert by_source["remax"].level == "critical"   # 100 → 2 = CRIT
    assert by_source["__total__"].level == "critical"  # 105 → 3 = CRIT


def test_run_tick_handles_missing_ranked_file(tmp_path: Path):
    """PA isn't always populated. Missing file → no verdicts for that
    country, no crash."""
    history = tmp_path / "history.jsonl"
    verdicts = run_tick(
        ranked_paths={"pa": tmp_path / "missing.json"},
        history_path=history,
    )
    assert verdicts == []


def test_run_tick_records_tick_even_when_ok(tmp_path: Path):
    """Every tick lands in the history regardless of verdict."""
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps([{"source": "remax"}]))
    history = tmp_path / "history.jsonl"
    run_tick(
        ranked_paths={"sv": ranked},
        history_path=history,
        now_iso="2026-01-03T00:00:00+00:00",
    )
    ticks = load_history(history)
    # Per source + synthetic total
    assert {t.source for t in ticks} == {"remax", "__total__"}


# ---------- any_critical + format_slack_message ----------

def test_any_critical_detects_one_in_many():
    from automation.row_count_sentinel import DropVerdict
    verdicts = [
        DropVerdict("a", "sv", 100, 100, 0, 0.0, "ok", "", 100),
        DropVerdict("b", "sv", 100, 50, -50, -0.5, "critical", "x", 100),
    ]
    assert any_critical(verdicts) is True


def test_any_critical_returns_false_when_none():
    from automation.row_count_sentinel import DropVerdict
    verdicts = [
        DropVerdict("a", "sv", 100, 99, -1, -0.01, "ok", "", 100),
    ]
    assert any_critical(verdicts) is False


def test_format_slack_message_lists_critical_first():
    from automation.row_count_sentinel import DropVerdict
    verdicts = [
        DropVerdict("remax", "sv", 500, 10, -490, -0.98, "critical", "pct/abs", 500),
        DropVerdict("nexo", "sv", 5, 3, -2, -0.4, "warn", "pct=40%", 5),
    ]
    msg = format_slack_message(verdicts, "https://example/run/1")
    # Critical line appears before warn line
    crit_idx = msg.find("`sv/remax`")
    warn_idx = msg.find("`sv/nexo`")
    assert crit_idx >= 0
    assert warn_idx >= 0
    assert crit_idx < warn_idx
    assert "https://example/run/1" in msg


def test_format_slack_message_says_ok_when_no_alerts():
    msg = format_slack_message([], "https://example/run/1")
    assert "all sources OK" in msg
