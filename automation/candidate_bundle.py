"""Candidate bundle — R1 of docs/RESILIENCE-AUDIT-PRD.md.

The nightly used to lose a perfectly good catalogue every time one
downstream guard exited non-zero. The 2026-06-06 incident produced 2107
ranked listings and then the population-regression guard fired on a
mix-shift — `phase_write_outputs` never ran, the data PR never opened,
the site stayed stale.

R1's fix is the simplest possible one: write a recoverable bundle of
the candidate to ``web/data/.staging/<run_id>/`` BEFORE the guards
run. If the guards block promotion, the bundle still exists on disk
and the workflow uploads it as ``candidate_bundle_<run_id>`` so a
human can inspect the data and (optionally) promote it manually with
``scripts/promote_candidate.py``.

Promotion semantics in R1 are intentionally thin: a guard pass means
the existing ``phase_write_outputs`` keeps doing what it already does
(writes the canonical ``web/data/*.json``). R4 will add the proper
promotion / quarantine state machine; R5 will rewrite the nightly
summary against the bundle manifest.

Public surface:

    write_candidate_bundle(staging_dir, ranked_dicts, meta, sidecars)
    read_candidate_bundle(staging_dir)
    BundleManifest

`ranked_dicts` is the list of Listing.to_dict() outputs (the same
shape that lands in `web/data/ranked.json`). `meta` is the meta-dict
returned by `_build_meta` in `automation/pipeline_steps.py`; we save
it as `last_updated.candidate.json` to keep the canonical file name
free for the post-guard write. `sidecars` is a mapping of
``filename → existing path on disk`` for the audit JSON files that
were already written by their respective phases (`shelf_audit.json`,
`kpi_dashboard.json`, etc.); the bundle copies them in so the
artifact is self-contained.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from automation._atomic import atomic_write_json, atomic_write_text

BUNDLE_SCHEMA_VERSION = 1

CANDIDATE_SUFFIX = ".candidate.json"


@dataclass
class BundleFile:
    path: str          # relative to staging_dir
    bytes: int
    sha256: str


@dataclass
class BundleManifest:
    schema_version: int = BUNDLE_SCHEMA_VERSION
    run_id: str = ""
    generated_at: str = ""
    visible_count: int = 0
    files: list[BundleFile] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "visible_count": self.visible_count,
            "files": [asdict(f) for f in self.files],
        }


def _sha256_of(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while True:
            block = fh.read(65536)
            if not block:
                break
            h.update(block)
            size += len(block)
    return size, h.hexdigest()


def resolve_run_id() -> str:
    """Pick the most stable run identifier available.

    Priority: ``GITHUB_RUN_ID`` (set by Actions); then
    ``PULPO_RUN_ID`` (manual override for local repro); then a
    UTC ISO-8601 stamp. The stamp is fine for dev — no collision risk
    on a single workstation.
    """
    rid = os.environ.get("GITHUB_RUN_ID") or os.environ.get("PULPO_RUN_ID")
    if rid:
        return str(rid)
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def staging_dir_for(repo_data_dir: Path, run_id: Optional[str] = None) -> Path:
    """Return the canonical staging path for a candidate bundle."""
    rid = run_id or resolve_run_id()
    return repo_data_dir / ".staging" / rid


def write_candidate_bundle(
    staging_dir: Path,
    *,
    run_id: str,
    ranked_dicts: list[dict],
    ranked_list_slim: Optional[list[dict]] = None,
    meta: Optional[dict] = None,
    sidecars: Optional[dict[str, Path]] = None,
) -> BundleManifest:
    """Write a candidate bundle to ``staging_dir``.

    ``ranked_dicts`` and (optionally) ``ranked_list_slim`` are the
    in-memory state; ``meta`` is the candidate's ``last_updated.json``
    payload (saved as ``last_updated.candidate.json``); ``sidecars`` is
    a mapping of bundle-relative-name → on-disk-path for the audit
    JSON files already produced by their respective phases.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    files: list[BundleFile] = []

    ranked_path = staging_dir / "ranked.json"
    atomic_write_json(ranked_path, ranked_dicts, indent=2, default=str)
    size, digest = _sha256_of(ranked_path)
    files.append(BundleFile(path="ranked.json", bytes=size, sha256=digest))

    if ranked_list_slim is not None:
        slim_path = staging_dir / "ranked.list.json"
        atomic_write_json(slim_path, ranked_list_slim, separators=(",", ":"), default=str)
        size, digest = _sha256_of(slim_path)
        files.append(BundleFile(path="ranked.list.json", bytes=size, sha256=digest))

    if meta is not None:
        meta_path = staging_dir / "last_updated.candidate.json"
        atomic_write_json(meta_path, meta, indent=2)
        size, digest = _sha256_of(meta_path)
        files.append(BundleFile(path="last_updated.candidate.json", bytes=size, sha256=digest))

    for bundle_name, source_path in (sidecars or {}).items():
        if source_path is None or not source_path.exists():
            continue
        dest = staging_dir / bundle_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, dest)
        size, digest = _sha256_of(dest)
        files.append(BundleFile(path=bundle_name, bytes=size, sha256=digest))

    manifest = BundleManifest(
        run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        visible_count=len(ranked_dicts),
        files=files,
    )
    atomic_write_text(
        staging_dir / "bundle_manifest.json",
        json.dumps(manifest.to_json(), indent=2),
    )
    return manifest


def read_candidate_bundle(staging_dir: Path) -> dict[str, Any]:
    """Return ``{manifest, ranked, meta}`` for the bundle at ``staging_dir``.

    Used by ``scripts/promote_candidate.py``. Does NOT verify hashes
    here — the caller (promote_candidate) checks them so the verify
    step is observable in the recovery flow.
    """
    manifest_path = staging_dir / "bundle_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no bundle_manifest.json in {staging_dir}")
    manifest = json.loads(manifest_path.read_text())
    out: dict[str, Any] = {"manifest": manifest}

    ranked_path = staging_dir / "ranked.json"
    if ranked_path.exists():
        out["ranked"] = json.loads(ranked_path.read_text())

    meta_path = staging_dir / "last_updated.candidate.json"
    if meta_path.exists():
        out["meta"] = json.loads(meta_path.read_text())

    return out


def verify_bundle(staging_dir: Path) -> list[str]:
    """Recompute SHA256 for every file in the manifest. Return list of mismatches.

    Empty list means every file matches its manifest entry. Used by
    ``scripts/promote_candidate.py`` to refuse a tampered bundle.
    """
    manifest = json.loads((staging_dir / "bundle_manifest.json").read_text())
    mismatches: list[str] = []
    for entry in manifest.get("files", []):
        rel = entry["path"]
        target = staging_dir / rel
        if not target.exists():
            mismatches.append(f"missing: {rel}")
            continue
        size, digest = _sha256_of(target)
        if digest != entry["sha256"]:
            mismatches.append(
                f"sha256 mismatch on {rel}: manifest={entry['sha256']} actual={digest}"
            )
        if size != entry["bytes"]:
            mismatches.append(
                f"size mismatch on {rel}: manifest={entry['bytes']} actual={size}"
            )
    return mismatches
