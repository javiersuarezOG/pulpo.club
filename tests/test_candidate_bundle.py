"""Tests for automation.candidate_bundle — R1 of RESILIENCE-AUDIT-PRD.

These tests cover the recoverability contract: a guard-failed run must
leave a self-contained bundle on disk that promote_candidate.py can
verify and restore. We don't test the run.py wiring here — the bundle
is the unit; the orchestration is its own thing.
"""
from __future__ import annotations

import json
from pathlib import Path

from automation.candidate_bundle import (
    BUNDLE_SCHEMA_VERSION,
    read_candidate_bundle,
    resolve_run_id,
    staging_dir_for,
    verify_bundle,
    write_candidate_bundle,
)


def _write_sidecar(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_resolve_run_id_prefers_github_run_id(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.delenv("PULPO_RUN_ID", raising=False)
    assert resolve_run_id() == "12345"


def test_resolve_run_id_falls_back_to_pulpo_run_id(monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.setenv("PULPO_RUN_ID", "manual-run-1")
    assert resolve_run_id() == "manual-run-1"


def test_resolve_run_id_falls_back_to_timestamp(monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("PULPO_RUN_ID", raising=False)
    rid = resolve_run_id()
    # ISO-like timestamp, 16 chars: YYYYMMDDTHHMMSSZ
    assert len(rid) == 16
    assert rid.endswith("Z")


def test_staging_dir_for_canonical_layout(tmp_path: Path):
    staging = staging_dir_for(tmp_path, run_id="test-run")
    assert staging == tmp_path / ".staging" / "test-run"


def test_write_bundle_produces_manifest_with_hashes(tmp_path: Path):
    staging = tmp_path / ".staging" / "rid"
    ranked = [{"source_id": "a", "title": "A"}, {"source_id": "b", "title": "B"}]
    manifest = write_candidate_bundle(
        staging,
        run_id="rid",
        ranked_dicts=ranked,
        meta={"candidate": True, "visible_count": 2},
    )
    assert manifest.run_id == "rid"
    assert manifest.visible_count == 2
    assert manifest.schema_version == BUNDLE_SCHEMA_VERSION
    paths = {f.path for f in manifest.files}
    assert "ranked.json" in paths
    assert "last_updated.candidate.json" in paths
    # bundle_manifest.json itself is written but NOT in the file list
    # (it's the manifest, not the manifested data).
    assert (staging / "bundle_manifest.json").exists()
    assert "bundle_manifest.json" not in paths
    # SHA256 + bytes are populated for each entry
    for f in manifest.files:
        assert f.bytes > 0
        assert len(f.sha256) == 64


def test_bundle_includes_existing_sidecars(tmp_path: Path):
    staging = tmp_path / ".staging" / "rid"
    sidecar = _write_sidecar(tmp_path / "shelf_audit.json", {"ok": True})
    manifest = write_candidate_bundle(
        staging,
        run_id="rid",
        ranked_dicts=[],
        sidecars={"shelf_audit.json": sidecar},
    )
    paths = {f.path for f in manifest.files}
    assert "shelf_audit.json" in paths
    assert json.loads((staging / "shelf_audit.json").read_text()) == {"ok": True}


def test_bundle_skips_missing_sidecars(tmp_path: Path):
    staging = tmp_path / ".staging" / "rid"
    # Note: sidecar path does not exist on disk.
    manifest = write_candidate_bundle(
        staging,
        run_id="rid",
        ranked_dicts=[],
        sidecars={"shelf_audit.json": tmp_path / "does-not-exist.json"},
    )
    paths = {f.path for f in manifest.files}
    assert "shelf_audit.json" not in paths


def test_read_bundle_round_trip(tmp_path: Path):
    staging = tmp_path / ".staging" / "rid"
    ranked = [{"source_id": "a"}]
    meta = {"candidate": True, "visible_count": 1}
    write_candidate_bundle(
        staging, run_id="rid", ranked_dicts=ranked, meta=meta,
    )
    bundle = read_candidate_bundle(staging)
    assert bundle["manifest"]["run_id"] == "rid"
    assert bundle["ranked"] == ranked
    assert bundle["meta"] == meta


def test_verify_bundle_clean(tmp_path: Path):
    staging = tmp_path / ".staging" / "rid"
    write_candidate_bundle(
        staging, run_id="rid", ranked_dicts=[{"a": 1}],
    )
    assert verify_bundle(staging) == []


def test_verify_bundle_detects_tampering(tmp_path: Path):
    staging = tmp_path / ".staging" / "rid"
    write_candidate_bundle(
        staging, run_id="rid", ranked_dicts=[{"a": 1}],
    )
    # Tamper with ranked.json after the manifest is sealed.
    (staging / "ranked.json").write_text("[]")
    mismatches = verify_bundle(staging)
    assert any("ranked.json" in m for m in mismatches)


def test_read_bundle_raises_when_missing(tmp_path: Path):
    staging = tmp_path / ".staging" / "rid"
    staging.mkdir(parents=True)
    try:
        read_candidate_bundle(staging)
    except FileNotFoundError as e:
        assert "bundle_manifest.json" in str(e)
        return
    raise AssertionError("expected FileNotFoundError")
