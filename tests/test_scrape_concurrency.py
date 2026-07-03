"""Concurrency safety for the nightly crawl loop (Win #1).

automation/run.py crawls each source through `_crawl_one` and then applies the
outcomes in `sources` order. When PULPO_SCRAPE_CONCURRENCY > 1 the crawls fan
out across a bounded thread pool, but the *merge* stays in source order so the
aggregated `raw` list — and therefore ranked.json — is bit-identical to the
sequential path. These tests pin that invariant plus telemetry + failure
isolation under the pool.

All run offline (PULPO_OFFLINE=1) and redirect run.py's REPO to a tmp dir so
production web/data is never touched (same pattern as test_pipeline_smoke.py).
"""
import json
import sys
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent

# A small offline source subset — the pool/merge invariant is independent of
# source count, so we restrict to keep each full-pipeline run ~9s instead of
# ~60s (the determinism test runs it twice). All four yield offline fixtures.
_TEST_SOURCES = ["goodlife", "nexo", "oceanside", "bienesraices"]


def _fresh_run_mod():
    """Re-import automation.run with offline env in effect (mirrors the
    smoke test) and return the module."""
    for mod in list(sys.modules):
        if mod.startswith("automation"):
            del sys.modules[mod]
    sys.path.insert(0, str(REPO))
    import automation.run as run_mod  # noqa: E402
    return run_mod


def _run_offline(run_mod, repo_dir, *, monkeypatch, concurrency,
                 sources=_TEST_SOURCES, fail_source=None):
    """Run the full offline pipeline into `repo_dir` at the given scrape
    concurrency. Optionally replace one registered source with a scraper that
    raises, to exercise failure isolation. Returns (exit_code, ranked_list)."""
    monkeypatch.setenv("PULPO_OFFLINE", "1")
    monkeypatch.setenv("PULPO_LIMIT", "10")
    monkeypatch.setenv("PULPO_SCRAPE_CONCURRENCY", str(concurrency))
    monkeypatch.setenv("PULPO_SOURCES", ",".join(sources))
    # Keep tests hermetic: scraper_failures snapshots write to a module-level
    # path (not run_mod.REPO), so disable capture. The exception is still
    # recorded (red health row + error_class); only the snapshot file is skipped.
    monkeypatch.setenv("PULPO_DISABLE_FAILURE_CAPTURE", "1")

    (repo_dir / "web" / "data").mkdir(parents=True, exist_ok=True)
    (repo_dir / "samples").mkdir(exist_ok=True)

    if fail_source is not None:
        class _Boom:
            # No crawl_with_meta attr → takes the plain crawl() path in
            # _crawl_one, then raises → exercises the exception branch.
            def crawl(self, limit=30, offline=None):
                raise RuntimeError("boom: simulated source failure")
        assert fail_source in run_mod.REGISTRY, f"{fail_source} not registered"
        monkeypatch.setitem(run_mod.REGISTRY, fail_source, _Boom())

    with mock.patch.object(run_mod, "REPO", repo_dir):
        exit_code = run_mod.main()

    ranked_path = repo_dir / "web" / "data" / "ranked.json"
    ranked = json.loads(ranked_path.read_text()) if ranked_path.exists() else []
    return exit_code, ranked


def _rank_signature(ranked):
    """The deterministic part of ranked.json — excludes wall-clock fields
    (first_seen_at / scraped_at) that legitimately differ run-to-run."""
    return [
        (r.get("source"), r.get("source_id"), r.get("rank"), r.get("rank_score"))
        for r in ranked
    ]


def test_pool_matches_sequential_offline(tmp_path, monkeypatch):
    """The load-bearing invariant: a parallel crawl (concurrency=6) produces
    the SAME ranked ordering as the sequential path (concurrency=1). Proves the
    deterministic merge — not pool-completion order — governs output."""
    run_mod = _fresh_run_mod()

    code_seq, ranked_seq = _run_offline(
        run_mod, tmp_path / "seq", monkeypatch=monkeypatch, concurrency=1
    )
    code_par, ranked_par = _run_offline(
        run_mod, tmp_path / "par", monkeypatch=monkeypatch, concurrency=6
    )

    assert code_seq == 0 and code_par == 0
    assert len(ranked_seq) == len(ranked_par) > 0
    assert _rank_signature(ranked_seq) == _rank_signature(ranked_par), (
        "Parallel crawl diverged from sequential — the merge must re-apply "
        "outcomes in `sources` order so raw ordering (and ranked.json) is "
        "identical regardless of how the pool scheduled the work."
    )


def test_per_source_health_rows_emitted_under_concurrency(tmp_path, monkeypatch):
    """Per-source observability must survive the pool: exactly one crawl-phase
    source_health_history row per crawled source."""
    run_mod = _fresh_run_mod()
    expected_sources = set(_TEST_SOURCES)

    code, _ = _run_offline(
        run_mod, tmp_path / "health", monkeypatch=monkeypatch, concurrency=6
    )
    assert code == 0

    health_path = tmp_path / "health" / "web" / "data" / "source_health_history.jsonl"
    assert health_path.exists(), "source_health_history.jsonl not written"
    rows = [json.loads(ln) for ln in health_path.read_text().splitlines() if ln.strip()]
    # Crawl-phase rows have no "phase" key; post_validation rows do.
    crawl_rows = [r for r in rows if "phase" not in r]
    seen = [r["source"] for r in crawl_rows]

    assert set(seen) == expected_sources, (
        f"Crawl-phase health rows cover {set(seen)}, expected {expected_sources}"
    )
    assert len(seen) == len(expected_sources), (
        f"Expected one crawl-phase row per source, got {len(seen)} for "
        f"{len(expected_sources)} sources (duplicates under concurrency?)"
    )


def test_single_source_failure_does_not_abort_pool(tmp_path, monkeypatch):
    """A crashing source must not take down the pool: main() still returns 0,
    the other sources' listings still land, and the failed source is recorded
    red — preserving the sequential path's `continue`-on-error semantics."""
    run_mod = _fresh_run_mod()
    fail_source = "goodlife"  # a real registered source

    code, ranked = _run_offline(
        run_mod, tmp_path / "fail", monkeypatch=monkeypatch,
        concurrency=6, fail_source=fail_source,
    )

    assert code == 0, "one failing source must not fail the whole run"
    assert len(ranked) > 0, "other sources should still produce listings"
    surviving_sources = {r.get("source") for r in ranked}
    assert fail_source not in surviving_sources, "failed source should yield no rows"
    assert len(surviving_sources) >= 2, "the pool should have kept the other sources"

    health_path = tmp_path / "fail" / "web" / "data" / "source_health_history.jsonl"
    rows = [json.loads(ln) for ln in health_path.read_text().splitlines() if ln.strip()]
    fail_rows = [r for r in rows if r.get("source") == fail_source and "phase" not in r]
    assert fail_rows, f"no crawl-phase health row for {fail_source}"
    assert fail_rows[0]["status"] == "red", "failed source must be marked red"
    assert fail_rows[0].get("error_class"), "failed source must carry an error_class"
