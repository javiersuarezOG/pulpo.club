"""Tests for pulpo.photo_contract.enforce_photo_contract (PRD P1-2).

Audit 2026-06-02 found 884/959 ranked rows pointed at root-photo files
that didn't exist. The canary's invariant: every `hero_photo_path` must
resolve to a present root file OR be nulled in the ranked output. Stats
land on `web/data/photo_contract.json`; misses on
`web/data/photo_contract_log.jsonl` (append-only audit trail).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pulpo.photo_contract import (
    GLOBAL_MISSING_RATE_THRESHOLD,
    TOP_BROWSE_N,
    TOP_HERO_N,
    enforce_photo_contract,
)


@dataclass
class _FakeListing:
    """Minimal Listing-like for the contract test. Mirrors what
    pulpo.models.Listing exposes — only the fields the canary reads."""

    source: str = "essurf"
    source_id: str = "1"
    hero_photo_path: Optional[str] = None


def _seed(photos_dir: Path, filename: str) -> None:
    """Drop a 1-byte file so `Path.exists()` returns True."""
    (photos_dir / filename).write_bytes(b"\x00")


def test_nulls_hero_path_when_root_file_missing(tmp_path):
    """The smoking gun: a listing carrying `/photos/foo.jpg` but no
    file at `web/photos/foo.jpg` must have the path nulled so the
    frontend falls back gracefully instead of firing a 404."""
    photos_dir = tmp_path / "photos"
    data_dir = tmp_path / "data"
    photos_dir.mkdir()

    l1 = _FakeListing(source_id="present", hero_photo_path="/photos/essurf_present.jpg")
    l2 = _FakeListing(source_id="missing", hero_photo_path="/photos/essurf_missing.jpg")
    _seed(photos_dir, "essurf_present.jpg")

    stats = enforce_photo_contract([l1, l2], photos_dir, data_dir=data_dir)

    assert l1.hero_photo_path == "/photos/essurf_present.jpg"
    assert l2.hero_photo_path is None
    assert stats.ranked_total == 2
    assert stats.with_local_path == 2
    assert stats.local_path_exists == 1
    assert stats.local_path_missing == 1
    assert stats.nulled == 1


def test_writes_sidecar_and_audit_log(tmp_path):
    photos_dir = tmp_path / "photos"
    data_dir = tmp_path / "data"
    photos_dir.mkdir()

    l1 = _FakeListing(source_id="x", hero_photo_path="/photos/essurf_x.jpg")
    enforce_photo_contract([l1], photos_dir, data_dir=data_dir)

    sidecar = data_dir / "photo_contract.json"
    log = data_dir / "photo_contract_log.jsonl"
    assert sidecar.exists()
    assert log.exists()

    snapshot = json.loads(sidecar.read_text())
    assert snapshot["ranked_total"] == 1
    assert snapshot["with_local_path"] == 1
    assert snapshot["local_path_missing"] == 1

    log_rows = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert log_rows and log_rows[0]["hero_photo_path"] == "/photos/essurf_x.jpg"
    assert log_rows[0]["source"] == "essurf"
    assert log_rows[0]["source_id"] == "x"


def test_writes_country_specific_photo_contract_sidecar(tmp_path):
    photos_dir = tmp_path / "photos"
    data_dir = tmp_path / "data"
    photos_dir.mkdir()

    l1 = _FakeListing(source_id="x", hero_photo_path="/photos/essurf_x.jpg")
    enforce_photo_contract([l1], photos_dir, data_dir=data_dir)

    legacy = data_dir / "photo_contract.json"
    country = data_dir / "photo_contract.SV.json"
    assert legacy.exists()
    assert country.exists()
    assert json.loads(legacy.read_text()) == json.loads(country.read_text())


def test_audit_log_is_append_only(tmp_path):
    """Two consecutive nightlies must keep both rows so dashboards can
    bucket by run."""
    photos_dir = tmp_path / "photos"
    data_dir = tmp_path / "data"
    photos_dir.mkdir()

    li = _FakeListing(source_id="x", hero_photo_path="/photos/essurf_x.jpg")
    enforce_photo_contract([li], photos_dir, data_dir=data_dir)
    # Round 2: same fixture, restored path so we test idempotent merging.
    l2 = _FakeListing(source_id="y", hero_photo_path="/photos/essurf_y.jpg")
    enforce_photo_contract([l2], photos_dir, data_dir=data_dir)

    rows = [json.loads(line)
            for line in (data_dir / "photo_contract_log.jsonl").read_text().splitlines()
            if line]
    assert len(rows) == 2


def test_top_shelf_counts_use_rank_index(tmp_path):
    """Listings 0..TOP_HERO_N-1 contribute to top_hero; 0..TOP_BROWSE_N-1
    contribute to top_browse. Stale row at index 0 must mark BOTH as
    missing — the most expensive class of failure."""
    photos_dir = tmp_path / "photos"
    data_dir = tmp_path / "data"
    photos_dir.mkdir()

    listings = [
        _FakeListing(source_id=str(i), hero_photo_path=f"/photos/x_{i}.jpg")
        for i in range(TOP_BROWSE_N + 5)
    ]
    # First TOP_HERO_N - 1 land present; one position-0 missing.
    for i in range(1, TOP_HERO_N):
        _seed(photos_dir, f"x_{i}.jpg")
    # Browseable 10..49 also present.
    for i in range(TOP_HERO_N, TOP_BROWSE_N):
        _seed(photos_dir, f"x_{i}.jpg")
    # Tail ranks 50+ also present so the global rate doesn't dominate.
    for i in range(TOP_BROWSE_N, TOP_BROWSE_N + 5):
        _seed(photos_dir, f"x_{i}.jpg")

    stats = enforce_photo_contract(listings, photos_dir, data_dir=data_dir)
    assert stats.top_hero_present == TOP_HERO_N - 1
    assert stats.top_hero_missing == 1
    assert stats.top_browse_present == TOP_BROWSE_N - 1
    assert stats.top_browse_missing == 1


def test_canary_fails_on_global_missing_rate(tmp_path):
    """>5% global missing trips the threshold rule. Caller decides
    whether to fail nightly; this just centralises the rule."""
    photos_dir = tmp_path / "photos"
    data_dir = tmp_path / "data"
    photos_dir.mkdir()

    # 20% missing > 5% threshold.
    listings = [
        _FakeListing(source_id=str(i), hero_photo_path=f"/photos/x_{i}.jpg")
        for i in range(10)
    ]
    for i in range(8):
        _seed(photos_dir, f"x_{i}.jpg")

    stats = enforce_photo_contract(listings, photos_dir, data_dir=data_dir)
    violations = stats.fails_threshold()
    assert violations
    assert any("global missing rate" in v for v in violations)


def test_no_threshold_failures_when_clean(tmp_path):
    photos_dir = tmp_path / "photos"
    data_dir = tmp_path / "data"
    photos_dir.mkdir()

    listings = [
        _FakeListing(source_id=str(i), hero_photo_path=f"/photos/x_{i}.jpg")
        for i in range(20)
    ]
    for i in range(20):
        _seed(photos_dir, f"x_{i}.jpg")

    stats = enforce_photo_contract(listings, photos_dir, data_dir=data_dir)
    assert stats.fails_threshold() == []


def test_listings_without_hero_path_are_skipped(tmp_path):
    """A listing whose `hero_photo_path` is already None contributes
    only to `ranked_total` — the contract is permissive about missing
    paths; it just guards stale ones."""
    photos_dir = tmp_path / "photos"
    data_dir = tmp_path / "data"
    photos_dir.mkdir()

    listings = [
        _FakeListing(hero_photo_path=None),
        _FakeListing(hero_photo_path=""),
    ]
    stats = enforce_photo_contract(listings, photos_dir, data_dir=data_dir)
    assert stats.ranked_total == 2
    assert stats.with_local_path == 0
    assert stats.local_path_missing == 0


def test_write_sidecars_false_skips_disk_writes(tmp_path):
    """In-memory mode for tests / dry runs — never touch disk."""
    photos_dir = tmp_path / "photos"
    data_dir = tmp_path / "data"
    photos_dir.mkdir()

    li = _FakeListing(source_id="x", hero_photo_path="/photos/x.jpg")
    enforce_photo_contract([li], photos_dir, data_dir=data_dir, write_sidecars=False)
    assert not (data_dir / "photo_contract.json").exists()
    assert not (data_dir / "photo_contract_log.jsonl").exists()


def test_threshold_constants_match_prd():
    """Constants are public contract — guard against unintended loosening."""
    assert GLOBAL_MISSING_RATE_THRESHOLD == 0.05
    assert TOP_BROWSE_N == 50
    assert TOP_HERO_N == 10
