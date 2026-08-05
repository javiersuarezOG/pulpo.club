"""Shared loader for the goals/ optimization registry.

Each goal lives at goals/<name>/GOAL.md. The machine-readable spec is a
fenced JSON block inside the markdown, marked with the info string
``json goal-spec``:

    ```json goal-spec
    { "name": "...", ... }
    ```

JSON (not YAML) on purpose: the pytest suite is hermetic (no PyYAML in
requirements.txt) and a hand-rolled YAML subset parser is a bug farm.
The prose around the block carries the rationale and the ready-to-paste
/goal condition; this module only cares about the spec.

The journal at goals/<name>/journal.jsonl is append-only, one JSON
object per line. See goals/README.md for the entry schema.

Used by: scripts/goal_metrics.py, scripts/goal_supply_metrics.py,
scripts/goal_status.py, tests/test_goal_registry.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOALS_DIR = REPO_ROOT / "goals"

_SPEC_BLOCK_RE = re.compile(
    r"```json goal-spec\s*\n(.*?)\n```", re.DOTALL
)

VALID_STATUS = {"active", "paused", "done"}
VALID_CADENCE = {"nightly", "weekly", "biweekly", "per-deploy"}
VALID_METRIC_SOURCE = {"posthog", "supply"}
VALID_DIRECTION = {"maximize", "minimize"}
VALID_METHOD = {"one-at-a-time", "ab-flag"}
VALID_GUARDRAIL_OP = {"<=", ">="}


def goal_names() -> list[str]:
    """Every registered goal (directories under goals/ with a GOAL.md)."""
    if not GOALS_DIR.is_dir():
        return []
    return sorted(
        p.parent.name for p in GOALS_DIR.glob("*/GOAL.md")
    )


def goal_dir(name: str) -> Path:
    return GOALS_DIR / name


def load_spec(name: str) -> dict:
    """Parse the ``json goal-spec`` block out of goals/<name>/GOAL.md."""
    path = goal_dir(name) / "GOAL.md"
    text = path.read_text(encoding="utf-8")
    match = _SPEC_BLOCK_RE.search(text)
    if not match:
        raise ValueError(f"{path}: no ```json goal-spec fenced block found")
    try:
        spec = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: goal-spec block is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise ValueError(f"{path}: goal-spec must be a JSON object")
    return spec


def load_journal(name: str) -> list[dict]:
    """Parse goals/<name>/journal.jsonl (append-only, may be empty)."""
    path = goal_dir(name) / "journal.jsonl"
    if not path.exists():
        return []
    entries: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{i}: bad JSONL line: {exc}") from exc
    return entries


def validate_spec(spec: dict) -> list[str]:
    """Return a list of human-readable problems (empty = valid).

    Structural validation only — file/symbol existence checks live in
    tests/test_goal_registry.py where the repo tree is available.
    """
    errors: list[str] = []

    def need(key: str, types: tuple) -> bool:
        if key not in spec:
            errors.append(f"missing required key: {key}")
            return False
        if not isinstance(spec[key], types):
            errors.append(f"key {key} must be {types}, got {type(spec[key]).__name__}")
            return False
        return True

    need("name", (str,))
    if need("status", (str,)) and spec["status"] not in VALID_STATUS:
        errors.append(f"status must be one of {sorted(VALID_STATUS)}, got {spec['status']!r}")
    if need("cadence", (str,)) and spec["cadence"] not in VALID_CADENCE:
        errors.append(f"cadence must be one of {sorted(VALID_CADENCE)}, got {spec['cadence']!r}")
    need("surface", (str,))
    need("owner_goal", (int,))
    need("human_ack_required", (bool,))

    if need("metric", (dict,)):
        metric: dict = spec["metric"]
        source = metric.get("source")
        if source not in VALID_METRIC_SOURCE:
            errors.append(f"metric.source must be one of {sorted(VALID_METRIC_SOURCE)}")
        if metric.get("direction") not in VALID_DIRECTION:
            errors.append(f"metric.direction must be one of {sorted(VALID_DIRECTION)}")
        if source == "posthog" and not isinstance(metric.get("hogql"), str):
            errors.append("metric.source=posthog requires metric.hogql string")
        if source == "supply":
            series = metric.get("series")
            if not (isinstance(series, list) and series and all(isinstance(s, str) for s in series)):
                errors.append("metric.source=supply requires metric.series non-empty string list")

    if need("guardrails", (list,)):
        guardrails: list = spec["guardrails"]
        for i, g in enumerate(guardrails):
            where = f"guardrails[{i}]"
            if not isinstance(g, dict):
                errors.append(f"{where}: must be an object")
                continue
            if not isinstance(g.get("name"), str):
                errors.append(f"{where}: missing name")
            gsource = g.get("source")
            if gsource not in VALID_METRIC_SOURCE:
                errors.append(f"{where}: source must be one of {sorted(VALID_METRIC_SOURCE)}")
            elif gsource == "posthog" and not isinstance(g.get("hogql"), str):
                errors.append(f"{where}: source=posthog requires hogql")
            elif gsource == "supply" and not isinstance(g.get("series"), str):
                errors.append(f"{where}: source=supply requires series (single name)")
            if g.get("op") not in VALID_GUARDRAIL_OP:
                errors.append(f"{where}: op must be one of {sorted(VALID_GUARDRAIL_OP)}")
            if not isinstance(g.get("threshold"), (int, float)):
                errors.append(f"{where}: threshold must be a number")

    if need("variables", (list,)):
        variables: list = spec["variables"]
        if not variables:
            errors.append("variables must be non-empty")
        for i, v in enumerate(variables):
            where = f"variables[{i}]"
            if not isinstance(v, dict):
                errors.append(f"{where}: must be an object")
                continue
            for key in ("id", "file", "symbol"):
                if not isinstance(v.get(key), str) or not v.get(key):
                    errors.append(f"{where}: missing {key}")
            rng = v.get("range")
            cur = v.get("current")
            if not (isinstance(rng, list) and len(rng) == 2
                    and all(isinstance(x, (int, float)) for x in rng)):
                errors.append(f"{where}: range must be [min, max] numbers")
            elif rng[0] >= rng[1]:
                errors.append(f"{where}: range min must be < max")
            elif isinstance(cur, (int, float)) and not (rng[0] <= cur <= rng[1]):
                errors.append(f"{where}: current {cur} outside range {rng}")
            if not isinstance(cur, (int, float, bool)):
                errors.append(f"{where}: current must be a number or bool")

    if need("decision", (dict,)):
        decision: dict = spec["decision"]
        if decision.get("method") not in VALID_METHOD:
            errors.append(f"decision.method must be one of {sorted(VALID_METHOD)}")
        if not isinstance(decision.get("min_sample"), int):
            errors.append("decision.min_sample must be an int")
        if not isinstance(decision.get("window_days"), int):
            errors.append("decision.window_days must be an int")

    if need("verification", (list,)) and not all(
        isinstance(x, str) for x in spec["verification"]
    ):
        errors.append("verification must be a list of shell-command strings")

    return errors


def active_surface_locks(exclude: str | None = None) -> dict[str, str]:
    """Map surface -> goal name for every ACTIVE goal whose latest journal
    action is an in-flight 'change' (i.e. a variable edit awaiting its
    decision window). Used to enforce one active change per surface."""
    locks: dict[str, str] = {}
    for name in goal_names():
        if name == exclude:
            continue
        try:
            spec = load_spec(name)
        except ValueError:
            continue
        if spec.get("status") != "active":
            continue
        journal = load_journal(name)
        if journal and journal[-1].get("action") == "change":
            locks[str(spec.get("surface"))] = name
    return locks
