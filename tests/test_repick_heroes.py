"""Tests for automation/repick_heroes.py — the one-off retroactive
picker CLI.

Strategy: build a tiny fake ``ranked.json``, mock the HTTP layer via
monkeypatching ``httpx.get`` inside ``_score_candidates_cheap``, and
assert:
  - dry-run does not write
  - --execute writes hero + sidecar + mutates ranked.json
  - --booster-only-cached passes empty eligible_urls
  - --source / --limit filters work
  - --floor overrides HERO_PICKER_MIN_CHEAP_SCORE for the run
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _png_bytes(w: int = 1920, h: int = 1080, color: tuple = (200, 200, 200)) -> bytes:
    """Synthetic PIL-decodable JPEG bytes large enough to pass the
    resolution gate in compute_score."""
    from PIL import Image  # type: ignore

    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


def _fake_response(content: bytes, status_code: int = 200):
    class _R:
        def __init__(self) -> None:
            self.content = content
            self.status_code = status_code

        def raise_for_status(self) -> None:
            if not (200 <= self.status_code < 300):
                raise RuntimeError(f"HTTP {self.status_code}")

    return _R()


def _stub_listing(source: str, source_id: str, photo_urls: list[str]) -> dict:
    return {
        "source": source,
        "source_id": source_id,
        "photo_urls": photo_urls,
        "photos_count": len(photo_urls),
        "hero_photo_path": None,
        "hero_photo_quality_score": None,
        "has_text_overlay": None,
    }


@pytest.fixture
def fake_ranked(tmp_path: Path) -> Path:
    data = [
        _stub_listing("remax", "abc123", ["https://x/a.jpg", "https://x/b.jpg"]),
        _stub_listing("bienesraices", "def456", ["https://x/c.jpg"]),
        _stub_listing("remax", "ghi789", []),  # no photos → no_photo_urls
    ]
    p = tmp_path / "ranked.json"
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def _run_cli(argv: list[str], photos_dir: Path) -> int:
    """Invoke the CLI's main() in-process with a fake REPO photos dir."""
    from automation import repick_heroes
    # Redirect the photos write dir into tmp.
    with mock.patch.object(repick_heroes, "REPO", photos_dir.parent.parent):
        # Ensure DEFAULT_INPUT / DEFAULT_SUMMARY aren't used; we pass explicit args.
        with mock.patch.object(sys, "argv", ["repick_heroes.py"] + argv):
            return repick_heroes.main()


def test_dry_run_does_not_write(fake_ranked: Path, tmp_path: Path, monkeypatch):
    summary = tmp_path / "summary.jsonl"
    photos_dir = tmp_path / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    # No HTTP mock needed — dry-run shouldn't call _score_candidates_cheap.
    rc = _run_cli(
        ["--input", str(fake_ranked), "--summary-out", str(summary)],
        photos_dir=photos_dir,
    )
    assert rc == 0
    # No files written.
    assert not summary.exists()
    assert list(photos_dir.iterdir()) == []
    # ranked.json unchanged.
    data = json.loads(fake_ranked.read_text())
    for li in data:
        assert li["hero_photo_path"] in (None, "")
        assert li["hero_photo_quality_score"] is None


def test_execute_writes_hero_and_mutates_ranked(fake_ranked: Path, tmp_path: Path, monkeypatch):
    summary = tmp_path / "summary.jsonl"
    photos_dir = tmp_path / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    # Mock all httpx.get inside _score_candidates_cheap with synthetic
    # large gray JPEGs (clears the 800×600 resolution gate).
    bytes_a = _png_bytes(1920, 1080, color=(180, 180, 180))
    bytes_b = _png_bytes(1920, 1080, color=(150, 150, 150))
    bytes_c = _png_bytes(1920, 1080, color=(120, 120, 120))
    url_to_bytes = {
        "https://x/a.jpg": bytes_a,
        "https://x/b.jpg": bytes_b,
        "https://x/c.jpg": bytes_c,
    }

    def _fake_get(url, **_kw):
        return _fake_response(url_to_bytes[url])

    from automation import run as run_module
    import httpx

    with mock.patch.object(httpx, "get", side_effect=_fake_get):
        rc = _run_cli(
            ["--input", str(fake_ranked), "--summary-out", str(summary),
             "--execute"],
            photos_dir=photos_dir,
        )
    assert rc == 0

    # Hero files written for listings with photos (2 of 3).
    assert (photos_dir / "remax_abc123.jpg").exists()
    assert (photos_dir / "remax_abc123.hero.jpg").exists()
    assert (photos_dir / "bienesraices_def456.jpg").exists()
    assert (photos_dir / "bienesraices_def456.hero.jpg").exists()
    # Listing with no photos got no hero.
    assert not (photos_dir / "remax_ghi789.jpg").exists()

    # Sidecars present.
    assert (photos_dir / "remax_abc123.hero.jpg.meta.json").exists()
    hero_meta = json.loads(
        (photos_dir / "remax_abc123.hero.jpg.meta.json").read_text()
    )
    assert "winning_url" in hero_meta
    assert hero_meta["winning_url"] in ("https://x/a.jpg", "https://x/b.jpg")
    assert "repicked_at" in hero_meta  # repick-specific marker

    # ranked.json was atomically rewritten with new fields.
    data = json.loads(fake_ranked.read_text())
    remax_abc = next(li for li in data if li["source_id"] == "abc123")
    assert remax_abc["hero_photo_path"] == "/photos/remax_abc123.jpg"
    assert remax_abc["hero_photo_quality_score"] is not None

    # Summary log written.
    lines = summary.read_text().strip().splitlines()
    assert len(lines) == 3  # one per filtered listing
    rows = [json.loads(ln) for ln in lines]
    actions = {r["action"] for r in rows}
    assert "winner_picked" in actions
    assert "no_photo_urls" in actions


def test_source_filter(fake_ranked: Path, tmp_path: Path, monkeypatch):
    summary = tmp_path / "summary.jsonl"
    photos_dir = tmp_path / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    bytes_c = _png_bytes(1920, 1080)

    def _fake_get(url, **_kw):
        return _fake_response(bytes_c)

    import httpx

    with mock.patch.object(httpx, "get", side_effect=_fake_get):
        rc = _run_cli(
            ["--input", str(fake_ranked), "--summary-out", str(summary),
             "--execute", "--source", "bienesraices"],
            photos_dir=photos_dir,
        )
    assert rc == 0

    # Only one bienesraices listing → only one summary row, only one hero.
    lines = summary.read_text().strip().splitlines()
    assert len(lines) == 1
    assert (photos_dir / "bienesraices_def456.hero.jpg").exists()
    assert not (photos_dir / "remax_abc123.hero.jpg").exists()


def test_limit(fake_ranked: Path, tmp_path: Path):
    summary = tmp_path / "summary.jsonl"
    photos_dir = tmp_path / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    bytes_x = _png_bytes(1920, 1080)

    import httpx

    with mock.patch.object(httpx, "get", side_effect=lambda *a, **k: _fake_response(bytes_x)):
        rc = _run_cli(
            ["--input", str(fake_ranked), "--summary-out", str(summary),
             "--execute", "--limit", "1"],
            photos_dir=photos_dir,
        )
    assert rc == 0

    lines = summary.read_text().strip().splitlines()
    assert len(lines) == 1  # only first listing


def test_floor_override_env_var(fake_ranked: Path, tmp_path: Path, monkeypatch):
    """--floor sets HERO_PICKER_MIN_CHEAP_SCORE for the duration of main()."""
    monkeypatch.delenv("HERO_PICKER_MIN_CHEAP_SCORE", raising=False)

    summary = tmp_path / "summary.jsonl"
    photos_dir = tmp_path / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    # Dry-run so we don't need httpx mocks.
    rc = _run_cli(
        ["--input", str(fake_ranked), "--summary-out", str(summary),
         "--floor", "55"],
        photos_dir=photos_dir,
    )
    assert rc == 0
    assert os.environ.get("HERO_PICKER_MIN_CHEAP_SCORE") == "55"


def test_floor_rejects_out_of_range(fake_ranked: Path, tmp_path: Path, capsys):
    photos_dir = tmp_path / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    rc = _run_cli(
        ["--input", str(fake_ranked), "--floor", "150"],
        photos_dir=photos_dir,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "must be 0..100" in err


def test_missing_input(tmp_path: Path, capsys):
    photos_dir = tmp_path / "web" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    rc = _run_cli(
        ["--input", str(tmp_path / "nope.json")],
        photos_dir=photos_dir,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err
