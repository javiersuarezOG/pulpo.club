from pathlib import Path


def test_row_count_gate_enforces_by_default_and_does_not_append():
    workflow = Path(".github/workflows/pulpo-nightly.yml").read_text()
    assert "ROW_COUNT_GATE_LOG_ONLY: ${{ vars.ROW_COUNT_GATE_LOG_ONLY || 'false' }}" in workflow
    assert "--fail-on-crit" in workflow
    assert "--no-append" in workflow
    assert "web/data/ranked.fresh.json" in workflow
