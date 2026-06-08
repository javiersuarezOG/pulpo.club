"""Tests for the photo-contract TRUTH canary (PR-P1).

The canary reads committed files on disk and asserts (1) every
hero_photo_path resolves to a real file and (2) photo_contract.json's
ranked_total matches ranked.json. Both are the exact signals that were
silently wrong in the 2026-06-08 PA-overwrite incident.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _load():
    path = REPO / "scripts" / "check_photo_contract_truth.py"
    spec = importlib.util.spec_from_file_location("check_photo_contract_truth", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scaffold(tmp_path, *, basenames, contract_total, create_files=True):
    """Build a fake repo: ranked.json + photo_contract.json + web/photos/."""
    photos = tmp_path / "web" / "photos"
    data = tmp_path / "web" / "data"
    photos.mkdir(parents=True)
    data.mkdir(parents=True)
    ranked = [{"source": b.split("_")[0], "hero_photo_path": f"/photos/{b}.jpg"}
              for b in basenames]
    (data / "ranked.json").write_text(json.dumps(ranked))
    (data / "photo_contract.json").write_text(json.dumps({"ranked_total": contract_total}))
    if create_files:
        for b in basenames:
            (photos / f"{b}.jpg").write_bytes(b"jpg")
    return data / "ranked.json", data / "photo_contract.json", photos


def _invoke(mod, ranked, contract, photos):
    old = sys.argv
    sys.argv = ["truth", "--ranked", str(ranked),
                "--contract", str(contract), "--photos-dir", str(photos)]
    try:
        return mod.main()
    finally:
        sys.argv = old


def test_passes_when_all_resolve_and_counts_match(tmp_path):
    mod = _load()
    ranked, contract, photos = _scaffold(
        tmp_path, basenames=["remax_1", "goodlife_2"], contract_total=2)
    assert _invoke(mod, ranked, contract, photos) == 0


def test_fails_on_missing_root_file(tmp_path):
    mod = _load()
    ranked, contract, photos = _scaffold(
        tmp_path, basenames=["remax_1", "essurf_2"], contract_total=2,
        create_files=False)  # no files on disk
    assert _invoke(mod, ranked, contract, photos) == 1


def test_fails_on_ranked_total_drift(tmp_path):
    """The PA-overwrite fingerprint: sidecar says 17, ranked.json has 2."""
    mod = _load()
    ranked, contract, photos = _scaffold(
        tmp_path, basenames=["remax_1", "goodlife_2"], contract_total=17)
    assert _invoke(mod, ranked, contract, photos) == 1


def test_passes_within_drift_tolerance(tmp_path):
    """A small post-contract rewrite of ranked.json is tolerated."""
    mod = _load()
    # 3 listings, sidecar says 1 (drift 2 <= tolerance 5) — but all files
    # must resolve for the primary check to pass.
    ranked, contract, photos = _scaffold(
        tmp_path, basenames=["a_1", "b_2", "c_3"], contract_total=1)
    assert _invoke(mod, ranked, contract, photos) == 0


def test_missing_contract_file_fails(tmp_path):
    mod = _load()
    ranked, contract, photos = _scaffold(
        tmp_path, basenames=["remax_1"], contract_total=1)
    contract.unlink()  # remove photo_contract.json
    assert _invoke(mod, ranked, contract, photos) == 1
