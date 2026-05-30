"""Tests for `pulpo check-hero-variants`.

The canary's job: catch /api/img regressions where the pipeline stops
writing `.hero.jpg` derivatives. Before the 2026-05-30 patch the check
ran strictly against the runner's working tree, which produced a
4-day false-alarm run when the runner's working-tree drifted away
from main mid-pipeline (cause never root-caused; the variants existed
on `main`, served fine via /api/img, but the canary failed and
blocked the data commit — see commit message). The patch adds an
``origin/main`` fallback: a file is "present" if it's in the working
tree OR in main, since `git add` is additive and committed files
survive.

These tests cover:

  * the strict path (--no-main-fallback) still fires when a variant is
    missing — the original regression guard's behaviour is preserved
    bit-for-bit when the operator wants it;
  * the fallback path rescues a working-tree-missing variant when
    main carries it — fixing the 2026-05-30 false-alarm class;
  * `_list_origin_main_photos` returns empty when git is missing or
    origin/main isn't fetched — degrades cleanly to strict mode rather
    than crashing the nightly.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.cli import _list_origin_main_photos, _run_check_hero_variants  # noqa: E402


def _init_git_repo(root: Path) -> None:
    """Initialise a git repo at root and stage a remote-named 'origin' that
    points to itself, so `git ls-tree origin/main` resolves locally.

    We don't actually need a real remote — just a ref called
    ``refs/remotes/origin/main`` that points at the commit we want to
    treat as production. Easiest path: create the commit on a local
    branch then fetch it under the origin/main name from the local clone.
    """
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)


def _commit_as_main(root: Path) -> None:
    """Stage everything currently in `root`, commit it, and create the
    ``refs/remotes/origin/main`` ref pointing at that commit.

    Bypasses the need for a separate remote URL — `update-ref` lets us
    register a local commit under the remote-tracking name directly.
    """
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=root, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", head],
        cwd=root, check=True,
    )


def _write_ranked(root: Path, hero_paths: list[str]) -> Path:
    """Write a minimal ranked.json with one record per hero_path."""
    ranked = [
        {
            "source": "test",
            "source_id": str(i),
            "rank_score": 90.0 - i,
            "hero_photo_path": hp,
        }
        for i, hp in enumerate(hero_paths)
    ]
    ranked_path = root / "web" / "data" / "ranked.json"
    ranked_path.parent.mkdir(parents=True, exist_ok=True)
    ranked_path.write_text(json.dumps(ranked))
    return ranked_path


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """A minimal repo layout the canary can run against."""
    (tmp_path / "web" / "data").mkdir(parents=True)
    (tmp_path / "web" / "photos").mkdir(parents=True)
    return tmp_path


# ── strict (no-main-fallback) mode ────────────────────────────────────


def test_strict_passes_when_all_heroes_in_working_tree(temp_repo, capsys):
    """Pre-2026-05-30 behaviour: working-tree-only check passes when
    every ranked listing has its `.hero.jpg` next to its thumbnail."""
    photos = temp_repo / "web" / "photos"
    (photos / "test_0.jpg").write_bytes(b"thumb")
    (photos / "test_0.hero.jpg").write_bytes(b"hero")
    ranked = _write_ranked(temp_repo, ["/photos/test_0.jpg"])

    rc = _run_check_hero_variants([
        "--repo-root", str(temp_repo),
        "--ranked-path", str(ranked),
        "--no-main-fallback",
    ])
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_strict_fails_when_hero_missing_from_working_tree(temp_repo, capsys):
    """Pre-2026-05-30 behaviour preserved: missing `.hero.jpg` triggers
    a hard failure even if it exists somewhere else (we just don't check
    elsewhere in strict mode)."""
    photos = temp_repo / "web" / "photos"
    (photos / "test_0.jpg").write_bytes(b"thumb")
    # .hero.jpg deliberately absent
    ranked = _write_ranked(temp_repo, ["/photos/test_0.jpg"])

    rc = _run_check_hero_variants([
        "--repo-root", str(temp_repo),
        "--ranked-path", str(ranked),
        "--no-main-fallback",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "missing .hero.jpg" in err
    # The strict failure message must NOT mention origin/main — the
    # operator opted out of the fallback and shouldn't see misleading
    # copy about it.
    assert "origin/main" not in err.split("FAIL")[1] if "FAIL" in err else True


# ── main fallback (default mode, post-2026-05-30) ─────────────────────


def test_fallback_rescues_when_hero_only_in_origin_main(temp_repo, capsys):
    """The 2026-05-30 fix in action: a hero file missing from the
    working tree but present in origin/main is treated as present,
    because Vercel serves from main and `git add` is additive."""
    photos = temp_repo / "web" / "photos"
    (photos / "test_0.jpg").write_bytes(b"thumb")
    (photos / "test_0.hero.jpg").write_bytes(b"hero")

    # Seed main with both files via git, then DELETE the hero from the
    # working tree (mimicking the runner's pre-canary state).
    _init_git_repo(temp_repo)
    _commit_as_main(temp_repo)
    (photos / "test_0.hero.jpg").unlink()
    assert not (photos / "test_0.hero.jpg").exists()

    ranked = _write_ranked(temp_repo, ["/photos/test_0.jpg"])

    rc = _run_check_hero_variants([
        "--repo-root", str(temp_repo),
        "--ranked-path", str(ranked),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    # The "rescued from main" counter is the operator-facing signal that
    # the working tree diverged from main — must be surfaced so a
    # sustained non-zero value is visible without parsing JSON.
    assert "rescued from main:    1" in out
    assert "PASS" in out


def test_fallback_still_fails_when_missing_from_both(temp_repo, capsys):
    """The fallback is a rescue, not a free pass: if a hero file is
    missing from BOTH the working tree AND origin/main, the canary still
    hard-fails. This is the only state a hero variant can be genuinely
    "broken" in production (Vercel serves from main; main lacks it →
    /api/img 404 → broker-URL fallback → LCP regression)."""
    photos = temp_repo / "web" / "photos"
    (photos / "test_0.jpg").write_bytes(b"thumb")
    # No hero anywhere
    _init_git_repo(temp_repo)
    _commit_as_main(temp_repo)

    ranked = _write_ranked(temp_repo, ["/photos/test_0.jpg"])

    rc = _run_check_hero_variants([
        "--repo-root", str(temp_repo),
        "--ranked-path", str(ranked),
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "missing .hero.jpg" in err
    # The error message must mention that origin/main was consulted —
    # operator should be able to tell at a glance whether the fallback
    # was checked. "not in working tree AND not in origin/main" is the
    # current wording.
    assert "origin/main" in err


def test_fallback_does_not_rescue_listings_with_no_hero_path(temp_repo, capsys):
    """A listing without a usable hero_photo_path is silently SKIPPED
    (counted under 'skipped (no path)'), not rescued. The fallback only
    applies to listings whose path is well-formed but whose file is
    absent from the working tree — it doesn't paper over schema bugs
    where hero_photo_path is null."""
    photos = temp_repo / "web" / "photos"
    (photos / "test_0.jpg").write_bytes(b"thumb")
    (photos / "test_0.hero.jpg").write_bytes(b"hero")
    _init_git_repo(temp_repo)
    _commit_as_main(temp_repo)

    # Two records: one with a real hero_photo_path, one with null
    ranked_path = temp_repo / "web" / "data" / "ranked.json"
    ranked_path.write_text(json.dumps([
        {"source": "test", "source_id": "0", "rank_score": 90.0, "hero_photo_path": "/photos/test_0.jpg"},
        {"source": "test", "source_id": "1", "rank_score": 89.0, "hero_photo_path": None},
    ]))

    rc = _run_check_hero_variants([
        "--repo-root", str(temp_repo),
        "--ranked-path", str(ranked_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped (no path):    1" in out
    assert "checked (have path):  1" in out


# ── degradation when git is unavailable ───────────────────────────────


def test_list_origin_main_photos_returns_empty_when_not_a_git_repo(tmp_path):
    """A tmp dir that isn't a git repo must yield an empty set rather
    than crashing. Keeps the canary working under pytest in tarball-
    installed environments and in CI sandboxes that strip .git."""
    assert _list_origin_main_photos(tmp_path) == set()


def test_list_origin_main_photos_returns_empty_when_git_binary_missing(tmp_path):
    """Even if the `git` binary itself is absent (some minimal container
    images), the helper degrades silently rather than tracebacking."""
    with patch(
        "subprocess.run",
        side_effect=FileNotFoundError("git: command not found"),
    ):
        assert _list_origin_main_photos(tmp_path) == set()


def test_fallback_silently_degrades_to_strict_when_no_main_ref(temp_repo, capsys):
    """If git is present but origin/main isn't fetched (e.g. local-only
    smoke run, sandbox without remotes), the fallback set is empty and
    the canary behaves like --no-main-fallback. Existing working-tree
    files still PASS; truly missing ones still FAIL. No tracebacks."""
    photos = temp_repo / "web" / "photos"
    (photos / "test_0.jpg").write_bytes(b"thumb")
    (photos / "test_0.hero.jpg").write_bytes(b"hero")
    # git init but DON'T set origin/main — degraded-fallback case
    _init_git_repo(temp_repo)
    subprocess.run(["git", "add", "-A"], cwd=temp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=temp_repo, check=True)

    ranked = _write_ranked(temp_repo, ["/photos/test_0.jpg"])

    rc = _run_check_hero_variants([
        "--repo-root", str(temp_repo),
        "--ranked-path", str(ranked),
    ])
    assert rc == 0
    # File is in the working tree, so it passes regardless of fallback.
    # The "rescued from main" line is NOT printed when the rescue count is 0.
    out = capsys.readouterr().out
    assert "rescued from main" not in out
