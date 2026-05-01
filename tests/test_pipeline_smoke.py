"""Full offline pipeline smoke test."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_offline_pipeline_produces_ranked_json(tmp_path, monkeypatch):
    monkeypatch.setenv("PULPO_OFFLINE", "1")
    monkeypatch.setenv("PULPO_LIMIT", "10")

    # Import after env is set so offline mode is picked up
    if "automation.run" in sys.modules:
        del sys.modules["automation.run"]

    sys.path.insert(0, str(REPO))
    from automation.run import main

    exit_code = main()
    assert exit_code == 0

    ranked_path = REPO / "web" / "data" / "ranked.json"
    assert ranked_path.exists(), "ranked.json not written"

    data = json.loads(ranked_path.read_text())
    assert len(data) >= 15, f"Expected ≥15 listings, got {len(data)}"

    for record in data:
        assert record.get("rank") is not None, f"Missing rank in {record.get('source_id')}"
        assert record.get("rank_score") is not None, f"Missing rank_score in {record.get('source_id')}"
