"""Tests for scripts/check_stranded_inventory.py (R6 of the resilience PRD).

Covers the detection contract:

- No bundle → not stranded.
- Bundle with zero visible → not stranded.
- Bundle with N>0 visible but no canonical last_updated.json → stranded.
- Bundle with N>0 visible and canonical older than bundle → stranded.
- Bundle with N>0 visible and canonical fresher than bundle → promoted.

Also exercises the alert composer (Slack body + Issue title) so a
future refactor that drops the run_id / visible_count / recovery
command from the body trips a loud regression instead of silently
making the alert useless.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Import the script as a module via its file path. The script is a
# `scripts/` entry point not a packaged module, so we wire it up
# manually rather than expanding sys.path semantics.
import importlib.util  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "check_stranded_inventory",
    REPO / "scripts" / "check_stranded_inventory.py",
)
assert _SPEC is not None and _SPEC.loader is not None
csi = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(csi)


# ── Fixtures ──────────────────────────────────────────────────────────


def _write_bundle(
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
        "files": files or [],
    }
    (staging / "bundle_manifest.json").write_text(json.dumps(manifest))
    (staging / "last_updated.candidate.json").write_text(
        json.dumps({"generated_at": generated_at})
    )
    return staging


# ── detect_stranded ────────────────────────────────────────────────────


def test_detect_no_run_id_returns_not_stranded():
    """Without a run_id we can't locate a bundle — silent no-op."""
    stranded, manifest = csi.detect_stranded(Path("/tmp/does-not-matter"), "")
    assert stranded is False
    assert manifest is None


def test_detect_no_bundle_returns_not_stranded(tmp_path):
    """No bundle = pipeline didn't reach R1 (either disabled or crashed
    before write). Not R6's incident to raise."""
    stranded, manifest = csi.detect_stranded(tmp_path, "run-123")
    assert stranded is False
    assert manifest is None


def test_detect_zero_visible_returns_not_stranded(tmp_path):
    """Empty candidate carries nothing to strand; do not page."""
    _write_bundle(tmp_path, "run-1", visible_count=0, generated_at="2026-06-07T01:00:00Z")
    stranded, manifest = csi.detect_stranded(tmp_path, "run-1")
    assert stranded is False
    assert manifest is not None
    assert manifest["visible_count"] == 0


def test_detect_visible_but_no_canonical_is_stranded(tmp_path):
    """Bundle has content but the canonical last_updated.json never
    landed (or doesn't exist yet on a fresh repo) → operator must know."""
    _write_bundle(tmp_path, "run-2", visible_count=1900, generated_at="2026-06-07T01:00:00Z")
    stranded, manifest = csi.detect_stranded(tmp_path, "run-2")
    assert stranded is True
    assert manifest is not None
    assert manifest["visible_count"] == 1900


def test_detect_canonical_older_than_bundle_is_stranded(tmp_path):
    """Canonical exists but it's stale relative to the bundle —
    promotion never happened this run. This is THE incident R6 exists
    to surface."""
    _write_bundle(tmp_path, "run-3", visible_count=1900, generated_at="2026-06-07T01:00:00Z")
    (tmp_path / "last_updated.json").write_text(
        json.dumps({"generated_at": "2026-06-02T08:00:00Z"})
    )
    stranded, _ = csi.detect_stranded(tmp_path, "run-3")
    assert stranded is True


def test_detect_canonical_fresher_means_promoted(tmp_path):
    """Canonical is at or ahead of the candidate → promotion happened
    via the existing post-guard write path. Silent."""
    _write_bundle(tmp_path, "run-4", visible_count=1900, generated_at="2026-06-07T01:00:00Z")
    (tmp_path / "last_updated.json").write_text(
        json.dumps({"generated_at": "2026-06-07T02:00:00Z"})
    )
    stranded, _ = csi.detect_stranded(tmp_path, "run-4")
    assert stranded is False


def test_detect_missing_timestamps_treated_as_stranded(tmp_path):
    """If the bundle has timestamps but the canonical is missing
    ``generated_at`` (e.g. legacy file shape) we can't prove
    promotion — err on the loud side so the operator at least sees
    the schema drift."""
    _write_bundle(tmp_path, "run-5", visible_count=10, generated_at="2026-06-07T01:00:00Z")
    (tmp_path / "last_updated.json").write_text(json.dumps({"some_other_field": True}))
    stranded, _ = csi.detect_stranded(tmp_path, "run-5")
    assert stranded is True


# ── is_promoted: pure helper isolation ─────────────────────────────────


def test_is_promoted_none_bundle_meta_means_promoted():
    """No candidate meta file means R1 isn't active yet — don't
    fire alerts on pre-R1 pipelines."""
    assert csi.is_promoted(bundle_meta=None, canonical_meta=None) is True


def test_is_promoted_missing_canonical_means_not_promoted():
    assert csi.is_promoted(
        bundle_meta={"generated_at": "2026-06-07T01:00:00Z"},
        canonical_meta=None,
    ) is False


def test_is_promoted_equal_timestamps_count_as_promoted():
    ts = "2026-06-07T01:00:00Z"
    assert csi.is_promoted(
        bundle_meta={"generated_at": ts},
        canonical_meta={"generated_at": ts},
    ) is True


# ── Alert composition ──────────────────────────────────────────────────


def test_alert_body_includes_critical_fields():
    """The Slack/Issue body MUST carry run_id, visible_count,
    generated_at, and the recovery command. Future refactors that
    drop any of these silently make the alert un-actionable."""
    manifest = {
        "visible_count": 1900,
        "generated_at": "2026-06-07T01:00:00Z",
        "files": [{"path": "ranked.json"}, {"path": "bundle_manifest.json"}],
    }
    alert = csi.build_alert(
        run_id="42",
        manifest=manifest,
        run_url="https://github.com/x/y/actions/runs/42",
        artifact_hint="candidate_bundle_42 on the Actions run page",
        commit_status="skipped (guard failure)",
    )
    body = alert["body"]
    assert "run_id: `42`" in body
    assert "visible_count: 1900" in body
    assert "2026-06-07T01:00:00Z" in body
    assert "promote_candidate.py --run-id 42" in body
    assert "candidate_bundle_42" in body
    assert "skipped (guard failure)" in body
    assert "RESILIENCE-AUDIT-PRD" in body


def test_alert_title_carries_run_id_and_visible_count():
    """Title is what shows up in the GitHub Issue list + Slack
    notification preview — it must be enough to identify the incident
    without opening the body."""
    manifest = {"visible_count": 1900, "generated_at": "2026-06-07T01:00:00Z"}
    alert = csi.build_alert(
        run_id="42",
        manifest=manifest,
        run_url=None,
        artifact_hint=None,
        commit_status=None,
    )
    assert "42" in alert["title"]
    assert "1900" in alert["title"]
    assert "stranded" in alert["title"].lower()


# ── End-to-end: main() entry point ─────────────────────────────────────


def test_main_dry_run_exits_zero_when_stranded(tmp_path, capsys, monkeypatch):
    """A real stranded bundle in dry-run mode should print the body
    and exit 0 — never block the deploy step on the alerter."""
    _write_bundle(tmp_path, "RUN-Z", visible_count=999, generated_at="2026-06-07T01:00:00Z")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("PULPO_RUN_ID", raising=False)
    rc = csi.main([
        "--data-dir", str(tmp_path),
        "--run-id", "RUN-Z",
        "--dry-run",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "RUN-Z" in out
    assert "999" in out
    assert "promote_candidate.py --run-id RUN-Z" in out


def test_main_dry_run_exits_zero_when_not_stranded(tmp_path, capsys, monkeypatch):
    """Promoted run prints the OK line and exits 0."""
    _write_bundle(tmp_path, "RUN-G", visible_count=10, generated_at="2026-06-07T01:00:00Z")
    (tmp_path / "last_updated.json").write_text(
        json.dumps({"generated_at": "2026-06-07T02:00:00Z"})
    )
    rc = csi.main(["--data-dir", str(tmp_path), "--run-id", "RUN-G", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out
