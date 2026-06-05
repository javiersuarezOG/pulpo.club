"""Smoke test for the probe-audit workflow YAML (PR-S3c)."""
from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO / ".github" / "workflows" / "pulpo-probe-audit.yml"


def test_workflow_yaml_exists():
    assert WORKFLOW_PATH.exists(), f"workflow not at {WORKFLOW_PATH}"


def test_workflow_yaml_basic_structure():
    """The workflow file contains the canonical blocks. Text-based
    check (no PyYAML dep) — PyYAML isn't in requirements.txt and the
    structural sanity check doesn't need a full parse."""
    text = WORKFLOW_PATH.read_text()
    assert "name:" in text
    assert "on:" in text
    assert "jobs:" in text


def test_workflow_runs_weekly_sunday_10utc():
    """Calibration anchor — the cron expression must be the canonical
    Sunday-10-UTC. Changing the schedule is deliberate."""
    text = WORKFLOW_PATH.read_text()
    assert '"0 10 * * 0"' in text or "'0 10 * * 0'" in text, (
        "expected weekly Sunday 10UTC cron in workflow"
    )


def test_workflow_invokes_probe_audit_script():
    text = WORKFLOW_PATH.read_text()
    assert "scripts/run_probe_audit.py" in text
    assert "--fail-on-low-match" in text


def test_workflow_has_slack_step_with_failure_or_regression_guard():
    """The alerting-step `if:` must fire on BOTH low-match-rate AND
    relative regression — that's the defense-in-depth contract."""
    text = WORKFLOW_PATH.read_text()
    assert "steps.audit.outcome == 'failure'" in text
    assert "steps.regression.outputs.regressed == 'true'" in text


def test_workflow_has_job_crash_canary():
    """The 'alerting-system silence canary' step (separate from the
    main Slack alert) must fire on failure() || cancelled()."""
    text = WORKFLOW_PATH.read_text()
    assert "failure() || cancelled()" in text
    assert "JOB CRASHED" in text


def test_seed_probes_json_parses_and_has_entries():
    import json
    path = REPO / "config" / "probes" / "sv.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    assert len(data) >= 5  # we expanded the seed list in PR-S3c


def test_seed_probes_have_required_fields():
    """Each seed entry needs the fields Probe.from_dict reads to
    produce a useful match. _comment is allowed for human notes."""
    import json
    path = REPO / "config" / "probes" / "sv.json"
    data = json.loads(path.read_text())
    for i, entry in enumerate(data):
        assert isinstance(entry, dict), f"entry {i} not a dict"
        assert entry.get("title"), f"entry {i} missing title"
        assert entry.get("source_url"), f"entry {i} missing source_url"
        assert entry.get("probe_kind"), f"entry {i} missing probe_kind"
