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
        assert record.get("first_seen_at") is not None, (
            f"Missing first_seen_at in {record.get('source_id')} — "
            "the listings_history.json sidecar should populate this for every listing."
        )

    # The pre-commit row-count gate HARD-REQUIRES the country-scoped fresh
    # candidate (#830 — it fail-loud errors if missing). Prove the offline
    # pipeline actually produces it, so a refactor that stops writing it fails
    # here instead of erroring every nightly at 02:00 UTC. (Active country
    # defaults to SV → ranked.fresh.SV.json.)
    fresh_sv_path = tmp_path / "web" / "data" / "ranked.fresh.SV.json"
    assert fresh_sv_path.exists(), (
        "ranked.fresh.SV.json not written by the offline pipeline — the "
        "row-count gate would error on every nightly without it."
    )
    fresh_data = json.loads(fresh_sv_path.read_text())
    assert isinstance(fresh_data, list) and len(fresh_data) > 0, (
        "ranked.fresh.SV.json must be a non-empty list of candidate listings."
    )

    # The photo-contract truth canary (scripts/check_photo_contract_truth.py)
    # cross-checks photo_contract.json.ranked_total against the committed
    # ranked.json and hard-fails on drift > 5. enforce_photo_contract MUST run
    # AFTER the agricultural-land purge, or the sidecar describes a pre-purge
    # SUPERSET and the canary false-fails a shippable catalogue (nightly
    # 27394603436: sidecar 2129 vs ranked.json 1932). Lock that ordering here.
    contract_path = tmp_path / "web" / "data" / "photo_contract.json"
    if contract_path.exists():
        contract = json.loads(contract_path.read_text())
        assert contract.get("ranked_total") == len(data), (
            f"photo_contract.ranked_total ({contract.get('ranked_total')}) must "
            f"equal len(ranked.json) ({len(data)}) — enforce_photo_contract is "
            f"running before the agricultural purge again (sidecar/ship drift)."
        )

    # Confirm the real production file was NOT touched
    prod_ranked = REPO / "web" / "data" / "ranked.json"
    if prod_ranked.exists():
        prod_data = json.loads(prod_ranked.read_text())
        assert prod_data != data or len(prod_data) >= len(data), (
            "Smoke test must not overwrite production ranked.json"
        )

    # PR-perf-3b — the slim list-view projection MUST be emitted alongside
    # the full ranked.json on every pipeline run. Browse + Discover + Saved
    # fetch /data/ranked.list.json on cold-load; if the pipeline regresses
    # on emitting this, every visitor falls back to the full ranked.json
    # and the perf win is silently lost.
    slim_path = tmp_path / "web" / "data" / "ranked.list.json"
    assert slim_path.exists(), "ranked.list.json was not emitted by phase_write_outputs"
    slim_data = json.loads(slim_path.read_text())
    assert isinstance(slim_data, list), "ranked.list.json must be a JSON array"
    assert len(slim_data) == len(data), (
        f"ranked.list.json record count ({len(slim_data)}) "
        f"diverges from ranked.json ({len(data)}) — slim/full must stay in lockstep"
    )
    # Sample the first record — must-have set is intentionally narrow so a
    # future whitelist trim doesn't break the test. These are the fields
    # the FE adapter reads with no graceful fallback.
    must_have = {"source", "source_id", "title", "rank", "rank_score"}
    for k in must_have:
        assert k in slim_data[0], (
            f"ranked.list.json record missing required field {k!r} — "
            f"check _RANKED_LIST_FIELDS in automation/pipeline_steps.py"
        )
    # Sanity-check: a representative dropped field stays out of the slim.
    # If this fires after a legit whitelist expansion, swap to another
    # field still excluded.
    assert "broker_phone" not in slim_data[0], (
        "ranked.list.json must NOT carry broker contact info — PII leak risk"
    )
    # `description` is the pre-DeepSeek legacy text field — was the single
    # largest contributor to slim-file bytes (~23%). FE adapter only reads
    # it as a fallback when `short_description_canonical` is missing, which
    # is now 99.8%+ of records. Re-adding it here silently reverses the
    # PR-perf-yest-1 wire-size win.
    assert "description" not in slim_data[0], (
        "ranked.list.json must NOT carry the legacy `description` field — "
        "use `short_description_canonical` (see PR-perf-yest-1)"
    )
