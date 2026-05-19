"""Pinned tests for the per-type canary block in pulpo-nightly.yml.

The canary itself is shell-embedded Python in the workflow file; we can't
import-and-call it. These tests grep the workflow YAML to ensure the
canary structure stays intact after future workflow edits.

If a refactor needs to move the logic out into a script file, update
these tests to point at the new location.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/pulpo-nightly.yml"


def _yaml_text() -> str:
    return WORKFLOW.read_text()


def test_per_type_canary_step_present():
    yaml = _yaml_text()
    assert "Per-type canaries" in yaml, (
        "Per-type canary step missing from pulpo-nightly.yml — was it "
        "removed during a workflow refactor?"
    )


def test_per_type_canary_is_blocking():
    """PR-5 of the reliability plan: the 7-day calibration soak is over and
    the canary now FAILS the workflow on violation (LOG_ONLY="false").

    The audit flagged the mismatch where data-quality canaries blocked but
    per-type canaries didn't, letting a classification regression silently
    ship. This pins the post-PR-5 contract — a future edit that flips the
    env back to "true" fails the test.

    The escape-hatch path (`LOG_ONLY="true"` for recalibration) is
    intentionally still supported in the inline Python — but the workflow
    YAML default must be blocking. Mirrors the data-quality canary's
    pattern documented at line 308 of the workflow."""
    yaml = _yaml_text()
    canary_section = yaml.split("Per-type canaries")[1].split("- name:")[0]
    assert 'LOG_ONLY:' in canary_section
    assert '"false"' in canary_section.split('LOG_ONLY:')[1].split('\n')[0], (
        "Per-type canary env defaults LOG_ONLY to something other than \"false\" — "
        "PR-5 promoted this to blocking. If you're recalibrating thresholds, "
        "flip it temporarily and revert in the same PR."
    )


def test_per_type_canary_inline_default_matches_yaml_env():
    """The inline Python reads LOG_ONLY from env with its own default
    (os.environ.get("LOG_ONLY", "false")). If the YAML env is somehow
    not propagated (e.g. a future refactor moves the step into a
    reusable workflow), the inline default must still be blocking
    so a silent regression doesn't slip through."""
    yaml = _yaml_text()
    canary_section = yaml.split("Per-type canaries")[1].split("- name:")[0]
    assert 'os.environ.get("LOG_ONLY", "false")' in canary_section, (
        "Inline-Python default for LOG_ONLY must be \"false\" (blocking). "
        "Otherwise a missing env var silently downgrades the canary."
    )


def test_per_type_canary_floors_set_to_realistic_thresholds():
    """Floors must be 80% of current observed counts (house=50, condo=8)
    so the very next nightly doesn't immediately fail. Spec defaults
    (HOUSE_FLOOR=80) would flunk against today's 50."""
    yaml = _yaml_text()
    canary_section = yaml.split("Per-type canaries")[1].split("- name:")[0]
    # House floor — must be ≤ current production count of 50
    assert 'HOUSE_FLOOR:' in canary_section
    house_floor_line = [
        ln for ln in canary_section.split('\n') if 'HOUSE_FLOOR:' in ln
    ][0]
    house_floor = int(house_floor_line.split('"')[1])
    assert 0 < house_floor <= 50, (
        f"HOUSE_FLOOR={house_floor} would fail next nightly "
        f"(current production has 50 houses)"
    )
    # Condo floor — must be ≤ current 8
    condo_floor_line = [
        ln for ln in canary_section.split('\n') if 'CONDO_FLOOR:' in ln
    ][0]
    condo_floor = int(condo_floor_line.split('"')[1])
    assert 0 < condo_floor <= 8, (
        f"CONDO_FLOOR={condo_floor} would fail next nightly "
        f"(current production has 8 condos)"
    )


def test_per_type_canary_reads_classifier_log():
    """The canary checks classifier-confidence by reading the shadow log
    written by automation/run.py. If the log path changes the canary
    silently no-ops — pin it."""
    yaml = _yaml_text()
    canary_section = yaml.split("Per-type canaries")[1].split("- name:")[0]
    assert "type_classifier_log.jsonl" in canary_section, (
        "Canary doesn't read the classifier log — confidence guard inert"
    )
    # Ceiling on uncertain rate per PRD spec
    assert "UNCERTAIN_PCT_CEILING" in canary_section
    assert '"15"' in canary_section.split("UNCERTAIN_PCT_CEILING:")[1].split('\n')[0]


def test_per_type_canary_reads_ranked_json():
    """Floor check reads ranked.json — the post-pipeline source of truth
    for what was ingested + retained. Reading per_source_raw from
    last_updated.json instead would miss validation drops."""
    yaml = _yaml_text()
    canary_section = yaml.split("Per-type canaries")[1].split("- name:")[0]
    assert "ranked.json" in canary_section


def test_per_type_canary_runs_after_count_canary():
    """The canaries cascade: count canary first (fail fast on total
    collapse), then per-type, then data-quality. Order matters because
    the count canary is the cheapest exit."""
    yaml = _yaml_text()
    count_idx = yaml.find("Count canary")
    per_type_idx = yaml.find("Per-type canaries")
    dq_idx = yaml.find("Data-quality canaries")
    assert count_idx > 0 and per_type_idx > 0 and dq_idx > 0
    assert count_idx < per_type_idx < dq_idx, (
        "Canary ordering wrong — should be count → per-type → data-quality"
    )
