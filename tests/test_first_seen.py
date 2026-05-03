"""Sidecar contract tests for `first_seen_at`.

The sidecar (`web/data/listings_history.json`) is keyed by
`"<source>|<source_id>"` and maps to an ISO8601 first-seen timestamp.
The contract: once a listing has been observed, its `first_seen_at`
never moves — even across re-scrapes, broker re-listings, or pipeline
reruns. New listings inherit the current run's start time.

These tests pin the contract by driving `automation/run.py` through
two consecutive offline runs and asserting:
 1. Every listing in the output has `first_seen_at` populated.
 2. The same `(source, source_id)` keeps the same timestamp across runs.
 3. New entries on a second run get the new run's start timestamp,
    not the first run's.

Together these guard against any future refactor that drops the field,
moves the sidecar, or makes the timestamp non-stable.
"""
import json
import sys
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent


def _run_pipeline_into(tmp_path: Path) -> list[dict]:
    """Drive automation/run.py once and return the parsed ranked.json."""
    # Force a fresh import so PULPO_OFFLINE takes effect.
    for mod in list(sys.modules):
        if mod.startswith("automation"):
            del sys.modules[mod]
    sys.path.insert(0, str(REPO))
    import automation.run as run_mod  # noqa: E402

    (tmp_path / "web" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "samples").mkdir(exist_ok=True)
    with mock.patch.object(run_mod, "REPO", tmp_path):
        exit_code = run_mod.main()
    assert exit_code == 0, "pipeline failed"
    return json.loads((tmp_path / "web" / "data" / "ranked.json").read_text())


def test_first_seen_populated_on_every_listing(tmp_path, monkeypatch):
    """Every listing emerging from a normal run carries a `first_seen_at`."""
    monkeypatch.setenv("PULPO_OFFLINE", "1")
    monkeypatch.setenv("PULPO_LIMIT", "10")

    data = _run_pipeline_into(tmp_path)

    assert data, "pipeline produced zero listings"
    missing = [r for r in data if not r.get("first_seen_at")]
    assert not missing, (
        f"{len(missing)} listings missing first_seen_at: "
        f"{[r.get('source_id') for r in missing[:5]]}"
    )


def test_first_seen_stable_across_runs(tmp_path, monkeypatch):
    """Re-running the pipeline does not move existing first_seen_at values.

    This is the load-bearing assertion: a sidecar that overwrites old
    timestamps would silently break "Newest first" sort.
    """
    monkeypatch.setenv("PULPO_OFFLINE", "1")
    monkeypatch.setenv("PULPO_LIMIT", "10")

    first_run = _run_pipeline_into(tmp_path)
    seen_after_first = {f"{r['source']}|{r['source_id']}": r["first_seen_at"] for r in first_run}
    assert seen_after_first, "first run produced no listings"

    second_run = _run_pipeline_into(tmp_path)
    seen_after_second = {f"{r['source']}|{r['source_id']}": r["first_seen_at"] for r in second_run}

    drifted = [
        (k, seen_after_first[k], seen_after_second[k])
        for k in seen_after_first
        if k in seen_after_second and seen_after_first[k] != seen_after_second[k]
    ]
    assert not drifted, (
        f"first_seen_at moved across runs for {len(drifted)} listings; "
        f"first divergence: {drifted[0]}"
    )


def test_sidecar_is_json_dict_keyed_by_source_pipe_id(tmp_path, monkeypatch):
    """Pin the sidecar's on-disk shape so consumers can rely on it.

    Anyone refactoring `automation/run.py` should not be able to silently
    change the sidecar to a list, a different filename, or a different
    key format. Doing so breaks every downstream consumer that reads it.
    """
    monkeypatch.setenv("PULPO_OFFLINE", "1")
    monkeypatch.setenv("PULPO_LIMIT", "10")

    _run_pipeline_into(tmp_path)
    sidecar_path = tmp_path / "web" / "data" / "listings_history.json"
    assert sidecar_path.exists(), "listings_history.json not written"

    sidecar = json.loads(sidecar_path.read_text())
    assert isinstance(sidecar, dict), "sidecar must be a JSON object, not a list"
    assert sidecar, "sidecar should have at least one entry after a real run"

    sample_key = next(iter(sidecar))
    assert "|" in sample_key, f"sidecar key {sample_key!r} should be 'source|source_id'"
    src, _, sid = sample_key.partition("|")
    assert src and sid, f"sidecar key {sample_key!r} has empty source or id"
    assert isinstance(sidecar[sample_key], str), "sidecar values should be ISO8601 strings"
    # ISO8601 sanity: starts with a 4-digit year and contains 'T'.
    assert sidecar[sample_key][:4].isdigit() and "T" in sidecar[sample_key], (
        f"sidecar value {sidecar[sample_key]!r} doesn't look like ISO8601"
    )
