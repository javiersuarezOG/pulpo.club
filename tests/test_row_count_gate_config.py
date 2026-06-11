from pathlib import Path


def test_row_count_gate_enforces_by_default_and_does_not_append():
    workflow = Path(".github/workflows/pulpo-nightly.yml").read_text()
    assert "ROW_COUNT_GATE_LOG_ONLY: ${{ vars.ROW_COUNT_GATE_LOG_ONLY || 'false' }}" in workflow
    assert "--fail-on-crit" in workflow
    assert "--no-append" in workflow
    assert "ranked_arg=\"web/data/ranked.fresh.SV.json\"" in workflow
    assert "--fresh-ranked web/data/ranked.fresh.SV.json" in workflow
    gate_step = workflow.split("- name: Per-source row-count delta gate", 1)[1].split(
        "- name: Per-type canaries", 1
    )[0]
    assert "web/data/ranked.fresh.json" not in gate_step
    assert "missing $ranked_arg" in gate_step
