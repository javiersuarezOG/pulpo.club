"""
Tests for scripts/check_geo_coverage.py.

A guardrail that never fires is decorative, so every detector here is
proven against a known-bad input, and the whole thing is proven to stay
silent on a healthy one. Synthetic fixtures only — this must NEVER read
web/data, or it becomes a data-driven CI blocker (the social-floor
anti-pattern).
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import check_geo_coverage as canary  # noqa: E402

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


def _record(assembled=NOW, statuses=("ok", "ok")):
    return {
        "country": "SV",
        "coords": {"lat": 13.7, "lng": -89.2, "geocoding_source": "estimated"},
        "assembled_at": assembled.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "providers": {
            "open_meteo_elevation": {"status": statuses[0]},
            "nasa_power": {"status": statuses[1]},
        },
    }


def _write(tmp_path, *, records=None, cells=None, history=None):
    if records is not None:
        (tmp_path / "geo_enrichment.json").write_text(json.dumps(records))
    if cells is not None:
        (tmp_path / "geo_cells.json").write_text(json.dumps(cells))
    if history is not None:
        (tmp_path / "geo_enrichment_history.jsonl").write_text(
            "\n".join(json.dumps(r) for r in history) + "\n")
    return tmp_path


def _healthy(tmp_path, n=50):
    return _write(
        tmp_path,
        records={f"t|{i}": _record() for i in range(n)},
        cells={f"open_meteo_elevation|{i}|v1": {"status": "ok"} for i in range(40)},
        history=[
            {"ts": "2026-08-26T02:00:00Z", "cells_cached": 40, "calls_failed": 0,
             "providers_disabled": [], "coverage": {"nasa_power": 1.0,
                                                    "open_meteo_elevation": 1.0}},
            {"ts": "2026-08-27T02:00:00Z", "cells_cached": 40, "calls_failed": 0,
             "providers_disabled": [], "coverage": {"nasa_power": 1.0,
                                                    "open_meteo_elevation": 1.0}},
        ],
    )


def _check(tmp_path, **kw):
    return canary.failing(canary.audit(tmp_path, now=NOW), **kw)


# ── the healthy baseline must stay silent ─────────────────────────────

def test_healthy_data_reports_nothing(tmp_path):
    assert _check(_healthy(tmp_path)) == []


def test_healthy_audit_measures_full_coverage(tmp_path):
    rep = canary.audit(_healthy(tmp_path), now=NOW)
    assert rep["records"] == 50
    assert rep["coverage"] == {"nasa_power": 100.0, "open_meteo_elevation": 100.0}
    assert rep["cells_cached"] == 40
    assert rep["age_hours"] == 0.0


def test_na_counts_as_resolved_not_a_gap(tmp_path):
    """'No modeled river in this cell' is an answer, not missing data."""
    _write(tmp_path, records={"t|1": _record(statuses=("na", "na"))},
           cells={}, history=[])
    rep = canary.audit(tmp_path, now=NOW)
    assert rep["coverage"] == {"nasa_power": 100.0, "open_meteo_elevation": 100.0}


# ── each detector fires on its own known-bad input ────────────────────

def test_fires_when_sidecar_is_missing(tmp_path):
    problems = _check(tmp_path)
    assert len(problems) == 1
    assert "missing" in problems[0]
    assert "git-add" in problems[0]


def test_fires_when_sidecar_is_empty(tmp_path):
    _write(tmp_path, records={}, cells={}, history=[])
    assert any("0 records" in p for p in _check(tmp_path))


def test_fires_when_data_is_stale(tmp_path):
    """The positive heartbeat: the pass stopped running and nobody noticed."""
    _write(tmp_path, records={"t|1": _record(assembled=NOW - timedelta(hours=72))},
           cells={"a|1|v1": {}}, history=[])
    assert any("stale" in p for p in _check(tmp_path))


def test_stale_respects_the_threshold(tmp_path):
    _write(tmp_path, records={"t|1": _record(assembled=NOW - timedelta(hours=30))},
           cells={"a|1|v1": {}}, history=[])
    assert not any("stale" in p for p in _check(tmp_path, max_age_hours=48))
    assert any("stale" in p for p in _check(tmp_path, max_age_hours=24))


def test_fires_when_a_provider_is_under_covered(tmp_path):
    records = {f"t|{i}": _record() for i in range(90)}
    records.update({f"t|bad{i}": _record(statuses=("ok", "pending"))
                    for i in range(30)})
    _write(tmp_path, records=records, cells={"a|1|v1": {}}, history=[])
    problems = _check(tmp_path)
    assert any("nasa_power" in p and "coverage" in p for p in problems)
    assert not any("open_meteo_elevation" in p for p in problems)


def test_fires_on_a_sharp_coverage_drop_between_runs(tmp_path):
    """Catches a provider that just started refusing, before it bottoms out."""
    _write(tmp_path,
           records={f"t|{i}": _record() for i in range(10)},
           cells={"a|1|v1": {}},
           history=[
               {"cells_cached": 40, "coverage": {"nasa_power": 1.0}},
               {"cells_cached": 40, "coverage": {"nasa_power": 0.5}},
           ])
    assert any("dropped" in p and "nasa_power" in p for p in _check(tmp_path))


def test_fires_when_a_provider_was_disabled_mid_run(tmp_path):
    _write(tmp_path,
           records={f"t|{i}": _record() for i in range(10)},
           cells={"a|1|v1": {}},
           history=[{"cells_cached": 40, "providers_disabled": ["soilgrids"],
                     "coverage": {}}])
    assert any("disabled" in p and "soilgrids" in p for p in _check(tmp_path))


def test_fires_on_failed_cell_fetches(tmp_path):
    _write(tmp_path,
           records={f"t|{i}": _record() for i in range(10)},
           cells={"a|1|v1": {}},
           history=[{"cells_cached": 40, "calls_failed": 7, "coverage": {}}])
    assert any("failed" in p for p in _check(tmp_path))


def test_fires_when_the_cell_cache_stops_persisting(tmp_path):
    """The most expensive silent failure: the cache is not committed, so
    every night re-pays every external call."""
    _write(tmp_path,
           records={f"t|{i}": _record() for i in range(10)},
           cells={"a|1|v1": {}},          # 1 cell now...
           history=[
               {"cells_cached": 400, "coverage": {}},   # ...400 before
               {"cells_cached": 1, "coverage": {}},
           ])
    problems = _check(tmp_path)
    assert any("not persisting" in p for p in problems)
    assert any("git-add" in p for p in problems)


def test_cache_growth_is_not_flagged(tmp_path):
    _write(tmp_path,
           records={f"t|{i}": _record() for i in range(10)},
           cells={f"a|{i}|v1": {} for i in range(500)},
           history=[{"cells_cached": 400, "coverage": {}},
                    {"cells_cached": 500, "coverage": {}}])
    assert not any("persisting" in p for p in _check(tmp_path))


# ── never-block contract ──────────────────────────────────────────────

def test_exit_code_is_zero_even_when_unhealthy(tmp_path, capsys, monkeypatch):
    """CLAUDE.md: alert and backfill, never freeze the data commit."""
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert canary.main(["--data-dir", str(tmp_path)]) == 0
    assert "geo-enrichment coverage problem" in capsys.readouterr().out


def test_strict_mode_exits_non_zero_for_the_self_test(tmp_path, monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert canary.main(["--data-dir", str(tmp_path), "--strict"]) == 1


def test_healthy_data_exits_zero(tmp_path, monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert canary.main(["--data-dir", str(_healthy(tmp_path)), "--strict"]) == 0


def test_corrupt_files_do_not_crash(tmp_path):
    (tmp_path / "geo_enrichment.json").write_text("{not json")
    (tmp_path / "geo_cells.json").write_text("[[[")
    (tmp_path / "geo_enrichment_history.jsonl").write_text("nonsense\n")
    assert any("missing" in p for p in _check(tmp_path))
