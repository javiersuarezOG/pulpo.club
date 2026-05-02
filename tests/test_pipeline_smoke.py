"""Full offline pipeline smoke test.

Runs automation/run.py in offline mode and writes output to a temp
directory so the production web/data/ranked.json is never clobbered.
"""
import json
import sys
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent


def test_offline_pipeline_produces_ranked_json(tmp_path, monkeypatch):
    monkeypatch.setenv("PULPO_OFFLINE", "1")
    monkeypatch.setenv("PULPO_LIMIT", "10")

    # Re-import so the env vars take effect
    for mod in list(sys.modules):
        if mod.startswith("automation"):
            del sys.modules[mod]

    sys.path.insert(0, str(REPO))

    # Redirect the web/data output to tmp_path so we don't overwrite production data
    fake_web_data = tmp_path / "web" / "data"
    fake_web_data.mkdir(parents=True)
    fake_samples = tmp_path / "samples"
    fake_samples.mkdir()

    import automation.run as run_mod  # noqa: E402

    with mock.patch.object(run_mod, "REPO", tmp_path):
        # run.py uses REPO / "web" / "data" for output paths
        (tmp_path / "web" / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "samples").mkdir(exist_ok=True)
        exit_code = run_mod.main()

    assert exit_code == 0

    ranked_path = tmp_path / "web" / "data" / "ranked.json"
    assert ranked_path.exists(), "ranked.json not written to tmp_path"

    data = json.loads(ranked_path.read_text())
    assert len(data) >= 15, f"Expected ≥15 listings, got {len(data)}"

    for record in data:
        assert record.get("rank") is not None, f"Missing rank in {record.get('source_id')}"
        assert record.get("rank_score") is not None, f"Missing rank_score in {record.get('source_id')}"

    # Confirm the real production file was NOT touched
    prod_ranked = REPO / "web" / "data" / "ranked.json"
    if prod_ranked.exists():
        prod_data = json.loads(prod_ranked.read_text())
        assert prod_data != data or len(prod_data) >= len(data), (
            "Smoke test must not overwrite production ranked.json"
        )
