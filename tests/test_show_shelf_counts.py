"""Tests for scripts/show_shelf_counts.py.

Pins the operator-facing shelf rundown so a future refactor that
silently drops the deficit calculation or the renders/non-renders
sort doesn't surprise the operator skimming a job log.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_SPEC = importlib.util.spec_from_file_location(
    "show_shelf_counts",
    REPO / "scripts" / "show_shelf_counts.py",
)
assert _SPEC is not None and _SPEC.loader is not None
sc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sc)


def _dashboard(per_shelf: dict, min_real: int = 10) -> dict:
    return {
        "min_real_listings": min_real,
        "kpi": {"per_shelf_visible": per_shelf},
    }


# ── shelf_rundown ──────────────────────────────────────────────────────


def test_shelf_rundown_sorts_by_deficit_desc():
    """Largest-deficit shelf must appear first — the operator's
    'what should I work on next' is the row at the top of the list."""
    dash = _dashboard({
        "beach_land":   {"count": 250, "renders_on_homepage": True},
        "beach_homes":  {"count": 80,  "renders_on_homepage": True},
        "beach_condos": {"count": 19,  "renders_on_homepage": True},
        "lake_land":    {"count": 15,  "renders_on_homepage": True},
        "lake_homes":   {"count": 2,   "renders_on_homepage": False},
        "lake_condos":  {"count": 1,   "renders_on_homepage": False},
    })
    rows, min_real = sc.shelf_rundown(dash)
    assert min_real == 10
    # lake_condos (count=1) and lake_homes (count=2) have the biggest
    # deficits and must be on top.
    assert rows[0]["shelf"] == "lake_condos"
    assert rows[0]["deficit"] == 9
    assert rows[1]["shelf"] == "lake_homes"


def test_shelf_rundown_deficit_zero_for_rendering_shelves():
    dash = _dashboard({
        "beach_land": {"count": 250, "renders_on_homepage": True},
    })
    rows, _ = sc.shelf_rundown(dash)
    assert rows == [{"shelf": "beach_land", "count": 250, "renders": True, "deficit": 0}]


def test_shelf_rundown_handles_missing_kpi_block():
    """Defensive: kpi_dashboard.json missing the kpi field doesn't
    crash the operator's status check."""
    rows, min_real = sc.shelf_rundown({"min_real_listings": 10})
    assert rows == []
    assert min_real == 10


def test_shelf_rundown_handles_missing_per_shelf_block():
    rows, _ = sc.shelf_rundown({"kpi": {}, "min_real_listings": 10})
    assert rows == []


def test_shelf_rundown_handles_null_info_dict():
    """Defensive: an explicit None entry shouldn't crash the renderer.
    Could happen during dashboard schema migrations."""
    dash = _dashboard({"beach_land": None})  # type: ignore[arg-type]
    rows, _ = sc.shelf_rundown(dash)
    assert rows == [{"shelf": "beach_land", "count": 0, "renders": False, "deficit": 10}]


# ── format_block ───────────────────────────────────────────────────────


def test_format_block_marks_pass_and_fail_distinctly():
    rows = [
        {"shelf": "lake_condos", "count": 1, "renders": False, "deficit": 9},
        {"shelf": "beach_land", "count": 250, "renders": True, "deficit": 0},
    ]
    out = sc.format_block(rows, min_real=10)
    # Failing shelf has the recovery hint; rendering shelf does not.
    assert "✗ lake_condos" in out
    assert "need +9 to activate" in out
    assert "✓ beach_land" in out
    assert "beach_land" in out and "need +" not in out.split("beach_land")[1]


def test_format_block_states_activation_ratio():
    rows = [
        {"shelf": "a", "count": 1, "renders": False, "deficit": 9},
        {"shelf": "b", "count": 100, "renders": True, "deficit": 0},
    ]
    out = sc.format_block(rows, min_real=10)
    assert "1/2 shelves activate the homepage" in out


def test_format_block_empty_rows_returns_no_data_hint():
    out = sc.format_block([], min_real=10)
    assert "no kpi_dashboard.json per_shelf data" in out


# ── main() ─────────────────────────────────────────────────────────────


def test_main_exits_zero_with_dashboard(tmp_path, capsys):
    dash = _dashboard({"beach_land": {"count": 250, "renders_on_homepage": True}})
    path = tmp_path / "kpi_dashboard.json"
    path.write_text(json.dumps(dash))
    rc = sc.main([str(path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SHELF RUNDOWN" in out
    assert "beach_land" in out


def test_main_exits_zero_with_missing_dashboard(tmp_path, capsys):
    """Never block the workflow on a missing dashboard."""
    rc = sc.main([str(tmp_path / "does-not-exist.json")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "not found" in out


def test_main_emits_json_when_flag_set(tmp_path, capsys):
    dash = _dashboard({
        "beach_land": {"count": 250, "renders_on_homepage": True},
        "lake_condos": {"count": 1, "renders_on_homepage": False},
    })
    path = tmp_path / "kpi_dashboard.json"
    path.write_text(json.dumps(dash))
    rc = sc.main([str(path), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["min_real_listings"] == 10
    assert "beach_land" in payload["activating"]
    assert "lake_condos" in payload["below_threshold"]
