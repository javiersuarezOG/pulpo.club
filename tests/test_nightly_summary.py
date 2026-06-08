"""Tests for the end-of-nightly story summary script."""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import nightly_summary as ns  # type: ignore[import-not-found]  # noqa: E402


def _write_history(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "source_health_history.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def _row(source: str, ts: str, status: str = "green",
         scraped: int | None = None, kept: int | None = None,
         error_class: str | None = None, failure_id: str | None = None,
         phase: str | None = None) -> dict:
    out: dict[str, object] = {"source": source, "ts": ts, "status": status}
    if scraped is not None:
        out["scraped"] = scraped
    if kept is not None:
        out["kept"] = kept
    if error_class is not None:
        out["error_class"] = error_class
    if failure_id is not None:
        out["failure_id"] = failure_id
    if phase is not None:
        out["phase"] = phase
    return out


# ── latest_row_per_source ─────────────────────────────────────────────

def test_latest_row_picks_newest_ts_per_source():
    rows = [
        _row("remax", "2026-06-01T05:00:00Z", "red"),
        _row("remax", "2026-06-01T15:00:00Z", "green"),
        _row("nexo",  "2026-06-01T15:00:00Z", "red"),
    ]
    latest = ns.latest_row_per_source(rows)
    assert latest["remax"]["status"] == "green"
    assert latest["nexo"]["status"] == "red"


# ── count_listings ────────────────────────────────────────────────────

def test_count_listings_returns_length(tmp_path):
    p = tmp_path / "ranked.json"
    p.write_text(json.dumps([{"id": "a"}, {"id": "b"}, {"id": "c"}]))
    assert ns.count_listings(p) == 3


def test_count_listings_none_on_missing(tmp_path):
    assert ns.count_listings(tmp_path / "no.json") is None


def test_count_listings_none_on_malformed(tmp_path):
    p = tmp_path / "ranked.json"
    p.write_text("{not-json")
    assert ns.count_listings(p) is None


def test_count_listings_none_on_dict_payload(tmp_path):
    """A canary-blocked nightly may leave a non-list payload behind."""
    p = tmp_path / "ranked.json"
    p.write_text(json.dumps({"oops": "wrong-shape"}))
    assert ns.count_listings(p) is None


# ── format_source_line ────────────────────────────────────────────────

def test_format_source_line_green_with_kept():
    row = _row("bienesraices", "ts", "green", scraped=568, kept=497)
    line = ns.format_source_line("bienesraices", row)
    assert "✓" in line
    assert "bienesraices" in line
    assert "scraped=568" in line
    assert "kept=497" in line
    assert "green" in line


def test_format_source_line_red_with_error():
    row = _row("elagente", "ts", "red", scraped=0, kept=0,
               error_class="HTTPStatusError", failure_id="abc12345")
    line = ns.format_source_line("elagente", row)
    assert "✗" in line
    assert "error=HTTPStatusError" in line
    assert "failure_id=abc12345" in line
    assert "red" in line


def test_format_source_line_legacy_count_fallback():
    """Pre-NR-C rows used `count` not `scraped`."""
    legacy = {"source": "old", "ts": "ts", "status": "red", "count": 17}
    line = ns.format_source_line("old", legacy)
    assert "scraped=17" in line


def test_format_source_line_kept_missing_renders_n_a():
    """Crawl-phase rows have no `kept` field — should render kept=n/a."""
    row = {"source": "x", "ts": "ts", "status": "green", "count": 10}
    line = ns.format_source_line("x", row)
    assert "kept=n/a" in line


# ── format_summary ────────────────────────────────────────────────────

def _example_rows() -> dict[str, dict]:
    return {
        "bienesraices":     _row("bienesraices",     "ts", "green", scraped=568, kept=497),
        "remax":            _row("remax",            "ts", "green", scraped=354, kept=331),
        "realtyelsalvador": _row("realtyelsalvador", "ts", "green", scraped=100, kept=98),
        "elagente":         _row("elagente",         "ts", "red",   scraped=0,   kept=0,
                                 error_class="HTTPStatusError", failure_id="abc"),
        "nexo":             _row("nexo",             "ts", "green", scraped=5,   kept=5),
    }


def test_format_summary_includes_each_block():
    summary = ns.format_summary(
        listing_count=956,
        pipeline_ts="2026-06-01T20:32:43Z",
        rows_by_src=_example_rows(),
        committed="true",
        deploy_outcome="success",
        run_url="https://github.com/foo/bar/actions/runs/42",
        today_iso="2026-06-01",
    )
    assert "NIGHTLY SUMMARY — 2026-06-01" in summary
    assert "https://github.com/foo/bar/actions/runs/42" in summary
    assert "PIPELINE OUTPUT" in summary
    assert "956 listings" in summary
    assert "2026-06-01T20:32:43Z" in summary
    assert "PER-SOURCE HEALTH" in summary
    assert "bienesraices" in summary
    assert "POST-CANARY OUTCOME" in summary
    assert "✓ COMMITTED" in summary
    assert "✓ DEPLOYED" in summary
    assert "SITE STATE" in summary
    assert "will show" in summary


def test_format_summary_no_commit_no_deploy():
    summary = ns.format_summary(
        listing_count=956,
        pipeline_ts="2026-06-01T20:32:43Z",
        rows_by_src=_example_rows(),
        committed="false",
        deploy_outcome="skipped",
        run_url=None,
        today_iso="2026-06-01",
    )
    assert "NO COMMIT" in summary
    assert "SKIPPED" in summary
    assert "NOT refresh this run" in summary


def test_format_summary_red_sources_listed_first():
    """Red sources sort to the top so an operator skimming sees the
    actionable rows immediately."""
    rows = {
        "ok_big":   _row("ok_big",   "ts", "green", scraped=500, kept=500),
        "broken":   _row("broken",   "ts", "red",   scraped=0,   kept=0,
                         error_class="HTTPError"),
        "ok_small": _row("ok_small", "ts", "green", scraped=5,   kept=5),
    }
    summary = ns.format_summary(
        listing_count=505,
        pipeline_ts="ts",
        rows_by_src=rows,
        committed="true",
        deploy_outcome="success",
        run_url=None,
        today_iso="2026-06-01",
    )
    broken_idx = summary.index("broken")
    ok_big_idx = summary.index("ok_big")
    ok_small_idx = summary.index("ok_small")
    assert broken_idx < ok_big_idx < ok_small_idx


def test_format_summary_no_listing_count():
    """A canary-blocked run may not produce ranked.json — render cleanly."""
    summary = ns.format_summary(
        listing_count=None,
        pipeline_ts=None,
        rows_by_src={},
        committed=None,
        deploy_outcome=None,
        run_url=None,
        today_iso="2026-06-01",
    )
    assert "ranked.json not found" in summary
    assert "no source rows captured" in summary
    assert "NOT REACHED" in summary
    assert "UNKNOWN" in summary


def test_format_summary_deploy_failure():
    summary = ns.format_summary(
        listing_count=956,
        pipeline_ts="ts",
        rows_by_src=_example_rows(),
        committed="true",
        deploy_outcome="failure",
        run_url=None,
        today_iso="2026-06-01",
    )
    assert "DEPLOY FAILED" in summary


# ── main() integration ────────────────────────────────────────────────

def test_main_writes_md_when_requested(tmp_path, monkeypatch, capsys):
    """--write-md persists the summary into the data dir so it survives
    via the diagnostics artifact."""
    _write_history(tmp_path, [
        _row("nexo", "2026-06-01T15:00:00Z", "green", scraped=5, kept=5),
    ])
    (tmp_path / "ranked.json").write_text(json.dumps([{"a": 1}] * 7))
    (tmp_path / "last_updated.json").write_text(json.dumps({
        "last_updated": "2026-06-01T20:32:43Z",
    }))
    monkeypatch.setenv("NIGHTLY_COMMITTED", "true")
    monkeypatch.setenv("NIGHTLY_DEPLOY_OUTCOME", "success")
    monkeypatch.setenv("NIGHTLY_RUN_URL", "https://github.test/runs/1")
    rc = ns.main(["--data-dir", str(tmp_path), "--write-md"])
    assert rc == 0
    out_path = tmp_path / "nightly_summary.md"
    assert out_path.exists()
    text = out_path.read_text()
    assert "7 listings" in text
    assert "https://github.test/runs/1" in text


def test_main_no_write_md_keeps_dir_clean(tmp_path, monkeypatch):
    """Without --write-md the summary only goes to stdout."""
    _write_history(tmp_path, [
        _row("nexo", "2026-06-01T15:00:00Z", "green", scraped=5, kept=5),
    ])
    monkeypatch.delenv("NIGHTLY_COMMITTED", raising=False)
    monkeypatch.delenv("NIGHTLY_DEPLOY_OUTCOME", raising=False)
    monkeypatch.delenv("NIGHTLY_RUN_URL", raising=False)
    rc = ns.main(["--data-dir", str(tmp_path)])
    assert rc == 0
    assert not (tmp_path / "nightly_summary.md").exists()


def test_main_handles_missing_data_dir_gracefully(tmp_path, monkeypatch, capsys):
    """A completely empty data dir (e.g. pipeline step never ran) must
    not crash; the script should still emit a stable summary."""
    monkeypatch.delenv("NIGHTLY_COMMITTED", raising=False)
    monkeypatch.delenv("NIGHTLY_DEPLOY_OUTCOME", raising=False)
    monkeypatch.delenv("NIGHTLY_RUN_URL", raising=False)
    rc = ns.main(["--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "NIGHTLY SUMMARY" in out
    assert "ranked.json not found" in out


def test_main_dedupes_two_rows_per_nightly(tmp_path, monkeypatch, capsys):
    """When run.py writes both crawl + post_validation rows, the worse
    status (red) must win in the summary."""
    rows = [
        _row("nexo", "2026-06-01T15:00:00Z", "green", scraped=100),
        _row("nexo", "2026-06-01T15:00:00Z", "red", scraped=100, kept=0,
             phase="post_validation"),
    ]
    _write_history(tmp_path, rows)
    monkeypatch.delenv("NIGHTLY_COMMITTED", raising=False)
    monkeypatch.delenv("NIGHTLY_DEPLOY_OUTCOME", raising=False)
    monkeypatch.delenv("NIGHTLY_RUN_URL", raising=False)
    rc = ns.main(["--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    # The deduped status should be red — i.e. the summary highlights
    # the post_validation collapse, not the green crawl row.
    assert "✗ nexo" in out
    assert "red" in out


# ── R5: candidate-bundle awareness ─────────────────────────────────────


def _write_candidate_bundle(
    data_dir: Path,
    run_id: str,
    *,
    visible_count: int,
    generated_at: str,
    files: list[dict] | None = None,
):
    staging = data_dir / ".staging" / run_id
    staging.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated_at,
        "visible_count": visible_count,
        "files": files or [{"path": "ranked.json"}, {"path": "bundle_manifest.json"}],
    }
    (staging / "bundle_manifest.json").write_text(json.dumps(manifest))
    (staging / "last_updated.candidate.json").write_text(
        json.dumps({"generated_at": generated_at})
    )


def test_classify_promotion_no_bundle_is_no_bundle():
    """Pre-R1 pipeline path: no bundle present → legacy summary."""
    assert ns.classify_promotion(bundle=None, canonical_meta=None) == ns.PROMOTION_NO_BUNDLE


def test_classify_promotion_empty_candidate_is_no_bundle():
    """Empty candidate is degenerate — treat as no_bundle so summary
    falls through to the legacy "nothing changed today" copy rather
    than scaring the operator with a 0-listing STRANDED line."""
    bundle = {
        "manifest": {"visible_count": 0, "generated_at": "2026-06-07T01:00:00Z"},
        "candidate_meta": {"generated_at": "2026-06-07T01:00:00Z"},
    }
    assert ns.classify_promotion(bundle=bundle, canonical_meta=None) == ns.PROMOTION_NO_BUNDLE


def test_classify_promotion_stranded_when_canonical_missing():
    bundle = {
        "manifest": {"visible_count": 1912, "generated_at": "2026-06-07T01:00:00Z"},
        "candidate_meta": {"generated_at": "2026-06-07T01:00:00Z"},
    }
    assert ns.classify_promotion(bundle=bundle, canonical_meta=None) == ns.PROMOTION_STRANDED


def test_classify_promotion_stranded_when_canonical_older():
    bundle = {
        "manifest": {"visible_count": 1912, "generated_at": "2026-06-07T01:00:00Z"},
        "candidate_meta": {"generated_at": "2026-06-07T01:00:00Z"},
    }
    canonical = {"generated_at": "2026-06-02T08:00:00Z"}
    assert ns.classify_promotion(bundle=bundle, canonical_meta=canonical) == ns.PROMOTION_STRANDED


def test_classify_promotion_promoted_when_canonical_fresher():
    bundle = {
        "manifest": {"visible_count": 1912, "generated_at": "2026-06-07T01:00:00Z"},
        "candidate_meta": {"generated_at": "2026-06-07T01:00:00Z"},
    }
    canonical = {"generated_at": "2026-06-07T02:00:00Z"}
    assert ns.classify_promotion(bundle=bundle, canonical_meta=canonical) == ns.PROMOTION_PROMOTED


def test_format_candidate_block_empty_when_no_bundle():
    """Legacy summary has no placeholder section."""
    assert ns.format_candidate_block(None, ns.PROMOTION_NO_BUNDLE) == []


def test_format_candidate_block_promoted_states_run_id_and_count():
    bundle = {
        "manifest": {
            "run_id": "42",
            "visible_count": 1912,
            "generated_at": "2026-06-07T01:00:00Z",
            "files": [{"path": "ranked.json"}],
        },
        "candidate_meta": {"generated_at": "2026-06-07T01:00:00Z"},
    }
    lines = ns.format_candidate_block(bundle, ns.PROMOTION_PROMOTED)
    body = "\n".join(lines)
    assert "PROMOTED" in body
    assert "1912" in body
    assert "42" in body
    # No recovery hint on the promoted path — the bundle did its job.
    assert "promote_candidate.py" not in body


def test_format_candidate_block_stranded_includes_recovery_command():
    bundle = {
        "manifest": {
            "run_id": "42",
            "visible_count": 1912,
            "generated_at": "2026-06-07T01:00:00Z",
            "files": [{"path": "ranked.json"}],
        },
        "candidate_meta": {"generated_at": "2026-06-07T01:00:00Z"},
    }
    lines = ns.format_candidate_block(bundle, ns.PROMOTION_STRANDED)
    body = "\n".join(lines)
    assert "STRANDED" in body
    assert "promote_candidate.py --run-id 42 --dry-run" in body


def test_read_candidate_bundle_returns_manifest_when_present(tmp_path):
    _write_candidate_bundle(tmp_path, "RUN-X", visible_count=1912, generated_at="2026-06-07T01:00:00Z")
    bundle = ns.read_candidate_bundle(tmp_path, "RUN-X")
    assert bundle is not None
    assert bundle["manifest"]["visible_count"] == 1912
    assert bundle["candidate_meta"]["generated_at"] == "2026-06-07T01:00:00Z"


def test_read_candidate_bundle_returns_none_for_unknown_run(tmp_path):
    bundle = ns.read_candidate_bundle(tmp_path, "DOES-NOT-EXIST")
    assert bundle is None


def test_read_candidate_bundle_returns_none_for_empty_run_id(tmp_path):
    assert ns.read_candidate_bundle(tmp_path, "") is None


def test_resolve_run_id_priority(monkeypatch):
    """explicit > GITHUB_RUN_ID > PULPO_RUN_ID > ''."""
    monkeypatch.setenv("GITHUB_RUN_ID", "from-gh")
    monkeypatch.setenv("PULPO_RUN_ID", "from-pulpo")
    assert ns.resolve_run_id("explicit") == "explicit"
    assert ns.resolve_run_id(None) == "from-gh"
    monkeypatch.delenv("GITHUB_RUN_ID")
    assert ns.resolve_run_id(None) == "from-pulpo"
    monkeypatch.delenv("PULPO_RUN_ID")
    assert ns.resolve_run_id(None) == ""


def test_main_summary_reports_stranded_when_canonical_stale(tmp_path, monkeypatch, capsys):
    """End-to-end: candidate bundle exists with 1912 listings but the
    canonical last_updated.json is 5 days old → summary names the
    incident + tells the operator how to recover."""
    # Stale canonical (the actual 2026-06-06-class symptom).
    (tmp_path / "ranked.json").write_text(json.dumps([{"id": i} for i in range(1000)]))
    (tmp_path / "last_updated.json").write_text(
        json.dumps({"last_updated": "2026-06-02T08:00:00Z", "generated_at": "2026-06-02T08:00:00Z"})
    )
    _write_candidate_bundle(tmp_path, "RUN-STRANDED", visible_count=1912,
                            generated_at="2026-06-07T01:00:00Z")

    # Workflow-mode env: commit/deploy didn't happen (canary blocked promotion).
    monkeypatch.setenv("NIGHTLY_COMMITTED", "false")
    monkeypatch.setenv("NIGHTLY_DEPLOY_OUTCOME", "skipped")
    monkeypatch.setenv("NIGHTLY_RUN_URL", "https://github.com/x/y/runs/RUN-STRANDED")
    monkeypatch.setenv("PULPO_RUN_ID", "RUN-STRANDED")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)

    rc = ns.main(["--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CANDIDATE STATUS" in out
    assert "STRANDED" in out
    assert "1912" in out
    assert "RUN-STRANDED" in out
    assert "promote_candidate.py" in out
    # The legacy SITE STATE block should still say pulpo.club won't
    # refresh — but now with a pointer to CANDIDATE STATUS.
    assert "pulpo.club will NOT refresh" in out


def test_main_summary_reports_promoted_normally(tmp_path, monkeypatch, capsys):
    """Promoted path: bundle exists, canonical is fresher → CANDIDATE
    STATUS shows PROMOTED, SITE STATE uses the normal copy."""
    (tmp_path / "ranked.json").write_text(json.dumps([{"id": i} for i in range(1912)]))
    (tmp_path / "last_updated.json").write_text(
        json.dumps({"last_updated": "2026-06-07T02:00:00Z", "generated_at": "2026-06-07T02:00:00Z"})
    )
    _write_candidate_bundle(tmp_path, "RUN-OK", visible_count=1912,
                            generated_at="2026-06-07T01:00:00Z")

    monkeypatch.setenv("NIGHTLY_COMMITTED", "true")
    monkeypatch.setenv("NIGHTLY_DEPLOY_OUTCOME", "success")
    monkeypatch.setenv("NIGHTLY_RUN_URL", "https://github.com/x/y/runs/RUN-OK")
    monkeypatch.setenv("PULPO_RUN_ID", "RUN-OK")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)

    rc = ns.main(["--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CANDIDATE STATUS" in out
    assert "PROMOTED" in out
    # Recovery hint must not appear on the promoted path.
    assert "promote_candidate.py" not in out
    assert "pulpo.club will show" in out


def test_main_summary_pre_r1_run_falls_through_to_legacy(tmp_path, monkeypatch, capsys):
    """No candidate bundle present (pre-R1 pipeline OR R1 disabled this
    run): CANDIDATE STATUS section must NOT appear. Pure regression
    guard against breaking the legacy summary contract."""
    (tmp_path / "ranked.json").write_text(json.dumps([{"id": 1}]))
    (tmp_path / "last_updated.json").write_text(
        json.dumps({"last_updated": "2026-06-07T02:00:00Z"})
    )
    monkeypatch.setenv("NIGHTLY_COMMITTED", "true")
    monkeypatch.setenv("NIGHTLY_DEPLOY_OUTCOME", "success")
    monkeypatch.setenv("NIGHTLY_RUN_URL", "https://github.com/x/y/runs/RUN-NO-BUNDLE")
    monkeypatch.setenv("PULPO_RUN_ID", "RUN-NO-BUNDLE")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    rc = ns.main(["--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CANDIDATE STATUS" not in out
    # The pre-R5 NIGHTLY SUMMARY contract still holds.
    assert "NIGHTLY SUMMARY" in out
