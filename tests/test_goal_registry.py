"""Contract tests for the goals/ optimization registry.

Two jobs:

1. Every registered goal-spec is structurally valid AND its declared
   tunable variables still exist in the codebase — each variable's
   ``file`` must exist and its ``symbol`` must grep in that file.
   Renaming a tunable without updating the registry fails here on
   purpose (the registry is the /goal protocol's map of the territory;
   a stale map means an iteration edits the wrong thing).

2. The validator itself fires on known-bad specs (a guardrail that
   never triggers is decorative — CLAUDE.md precedent).

Hermetic: reads only files committed to the repo, no network, no
web/data dependency.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from goal_registry import (  # noqa: E402
    GOALS_DIR,
    goal_names,
    load_journal,
    load_spec,
    validate_spec,
)

VALID_JOURNAL_ACTIONS = {"init", "change", "hold", "keep", "revert", "ack_required"}


def test_registry_has_goals():
    assert goal_names(), f"no goals registered under {GOALS_DIR}"


def test_every_spec_is_structurally_valid():
    problems = []
    for name in goal_names():
        spec = load_spec(name)
        errors = validate_spec(spec)
        if errors:
            problems.append(f"{name}: " + "; ".join(errors))
        if spec.get("name") != name:
            problems.append(f"{name}: spec name {spec.get('name')!r} != directory name")
    assert not problems, "\n".join(problems)


def test_every_variable_file_and_symbol_exists():
    problems = []
    for name in goal_names():
        spec = load_spec(name)
        for v in spec.get("variables", []):
            rel = v.get("file", "")
            symbol = v.get("symbol", "")
            path = REPO_ROOT / rel
            if not path.is_file():
                problems.append(f"{name}.{v.get('id')}: file not found: {rel}")
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if symbol not in text:
                problems.append(
                    f"{name}.{v.get('id')}: symbol {symbol!r} no longer greps in {rel} "
                    "— tunable renamed/moved? Update the goal-spec."
                )
    assert not problems, "\n".join(problems)


def test_every_journal_parses_and_actions_are_known():
    problems = []
    for name in goal_names():
        journal = load_journal(name)  # raises on malformed JSONL
        if not journal:
            problems.append(f"{name}: journal.jsonl empty — needs at least an init entry")
            continue
        for i, entry in enumerate(journal):
            action = entry.get("action")
            if action not in VALID_JOURNAL_ACTIONS:
                problems.append(f"{name}: journal line {i + 1} has unknown action {action!r}")
            if "ts" not in entry:
                problems.append(f"{name}: journal line {i + 1} missing ts")
    assert not problems, "\n".join(problems)


def test_supply_series_names_resolve_to_extractors():
    # A goal-spec naming a series with no extractor would only fail at
    # measurement time — surface it in CI instead.
    from goal_supply_metrics import SERIES  # noqa: E402  (same sys.path)

    problems = []
    for name in goal_names():
        spec = load_spec(name)
        metric = spec.get("metric", {})
        if metric.get("source") == "supply":
            for series in metric.get("series", []):
                if series not in SERIES:
                    problems.append(f"{name}: metric series {series!r} has no extractor")
        for g in spec.get("guardrails", []):
            if g.get("source") == "supply" and g.get("series") not in SERIES:
                problems.append(
                    f"{name}: guardrail {g.get('name')!r} series {g.get('series')!r} "
                    "has no extractor"
                )
    assert not problems, "\n".join(problems)


# ---- validator self-test: known-bad specs must be rejected ----------------

def _valid_base() -> dict:
    return {
        "name": "self-test",
        "status": "active",
        "owner_goal": 1,
        "surface": "self-test",
        "cadence": "weekly",
        "human_ack_required": False,
        "metric": {
            "source": "posthog",
            "direction": "maximize",
            "unit": "ratio",
            "hogql": "SELECT 1 AS value, 1 AS sample_n",
        },
        "guardrails": [],
        "variables": [
            {
                "id": "x",
                "file": "scripts/goal_registry.py",
                "symbol": "validate_spec",
                "kind": "code",
                "current": 5,
                "range": [1, 10],
                "step": 1,
            }
        ],
        "decision": {"method": "one-at-a-time", "min_sample": 100, "window_days": 7},
        "verification": ["true"],
    }


def test_validator_accepts_a_valid_spec():
    assert validate_spec(_valid_base()) == []


def test_validator_rejects_current_outside_range():
    spec = _valid_base()
    spec["variables"][0]["current"] = 99
    assert any("outside range" in e for e in validate_spec(spec))


def test_validator_rejects_missing_metric_query():
    spec = _valid_base()
    del spec["metric"]["hogql"]
    assert any("hogql" in e for e in validate_spec(spec))


def test_validator_rejects_unknown_status_and_cadence():
    spec = _valid_base()
    spec["status"] = "yolo"
    spec["cadence"] = "hourly"
    errors = validate_spec(spec)
    assert any("status" in e for e in errors)
    assert any("cadence" in e for e in errors)


def test_validator_rejects_empty_variables():
    spec = _valid_base()
    spec["variables"] = []
    assert any("non-empty" in e for e in validate_spec(spec))


def test_validator_rejects_bad_guardrail():
    spec = _valid_base()
    spec["guardrails"] = [{"name": "g", "source": "supply", "op": "<", "threshold": "high"}]
    errors = validate_spec(spec)
    assert any("op" in e for e in errors)
    assert any("threshold" in e for e in errors)
    assert any("series" in e for e in errors)


def test_validator_is_side_effect_free():
    spec = _valid_base()
    snapshot = copy.deepcopy(spec)
    validate_spec(spec)
    assert spec == snapshot
