#!/usr/bin/env python3
"""Emergency restore of archived hero photos referenced by ranked.json.

Why this exists
---------------
The nightly's orphan-pruner (``automation/run.py::_prune_orphan_photos``)
moves photos not present in the *current run's* listing set into
``web/photos/_archive/<YYYY-MM-DD>/``. Because SV and PA share one
un-scoped ``web/photos/`` directory, the PA-country nightly run sees
every SV photo as an orphan and archives it — while the SV
``ranked.json`` (restored afterwards) still points at those now-archived
paths. The result: ``hero_photo_path`` entries resolve to files that
exist only under ``_archive``, so production serves HTTP 404 on every
card and hero image.

This script restores the referenced files from the archive back to the
served root. It is the emergency half of the fix; the structural half
(stop the PA run re-archiving SV photos) lands separately in the nightly
workflow.

What it does
------------
For every ``hero_photo_path`` in ``ranked.json``:
  * If the root file already exists in ``web/photos/``, skip (idempotent).
  * Otherwise locate the copy under the NEWEST dated ``_archive`` subdir
    and copy the full sibling set back to ``web/photos/``:
        <file>.jpg              (thumbnail / card image)
        <file>.hero.jpg         (1920x1080 hero derivative)
        <file>.jpg.meta.json    (thumbnail metadata sidecar)
        <file>.hero.jpg.meta.json (hero metadata sidecar — carries winning_url)
        <file>.jpg.hash         (URL-dedup cache key)

The sibling set mirrors ``_prune_orphan_photos`` in
``automation/run.py`` (the canonical mover) so restore is the exact
inverse of archive. The archive is left intact (copy, not move) so a
second run is safe and the archive remains a backup.

Exit codes
----------
  0  every referenced file is now present (or was already present)
  1  one or more TOP-N ranked listings could not be restored (no archive
     copy found) — a production-visible gap
  2  bad input (ranked.json missing / not a list)

Usage
-----
    python3 scripts/restore_archived_photos.py            # restore + verify
    python3 scripts/restore_archived_photos.py --dry-run  # report only
    python3 scripts/restore_archived_photos.py --top-required 50
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RANKED = REPO_ROOT / "web" / "data" / "ranked.json"
DEFAULT_PHOTOS = REPO_ROOT / "web" / "photos"

# Sibling suffixes per listing. Derived from a `<base>.jpg` thumbnail name.
# Canonical source: automation/run.py::_prune_orphan_photos (the mover).
_SIBLING_SUFFIXES = (
    ".jpg",
    ".hero.jpg",
    ".jpg.meta.json",
    ".hero.jpg.meta.json",
    ".jpg.hash",
)


def _rel(p: Path) -> str:
    """Path relative to the repo root for display; falls back to the raw
    path when ``p`` lives outside the repo (e.g. a tmp dir under test)."""
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _index_archive(archive_root: Path) -> dict[str, list[tuple[str, Path]]]:
    """basename(``<base>.jpg``) -> [(date_dir_name, full_path), ...] sorted.

    Only thumbnail ``.jpg`` files are indexed (not ``.hero.jpg`` — those
    are restored as siblings of their thumbnail). Date dirs are named
    ``YYYY-MM-DD`` so lexicographic sort == chronological sort.
    """
    index: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    if not archive_root.exists():
        return index
    for date_dir in sorted(archive_root.iterdir()):
        if not date_dir.is_dir():
            continue
        for f in date_dir.iterdir():
            name = f.name
            if name.endswith(".jpg") and not name.endswith(".hero.jpg"):
                index[name].append((date_dir.name, f))
    for name in index:
        index[name].sort()  # oldest -> newest by date dir name
    return index


def _restore_one(base_name: str, newest_dir: Path, photos_dir: Path,
                 dry_run: bool) -> list[str]:
    """Copy the sibling set for ``base_name`` from ``newest_dir`` into
    ``photos_dir``. Returns the list of relative paths actually written
    (for the git-add list)."""
    stem = base_name[: -len(".jpg")]  # strip trailing .jpg
    written: list[str] = []
    for suffix in _SIBLING_SUFFIXES:
        src = newest_dir / f"{stem}{suffix}"
        if not src.exists():
            continue  # sidecar/hero may legitimately be absent for some files
        dst = photos_dir / f"{stem}{suffix}"
        if dst.exists():
            continue
        if not dry_run:
            shutil.copy2(src, dst)
        written.append(_rel(dst))
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ranked", type=Path, default=DEFAULT_RANKED)
    parser.add_argument("--photos-dir", type=Path, default=DEFAULT_PHOTOS)
    parser.add_argument("--archive", type=Path, default=None,
                        help="Archive root (default <photos-dir>/_archive).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be restored; write nothing.")
    parser.add_argument("--top-required", type=int, default=50,
                        help="Fail (exit 1) if any of the top-N ranked "
                             "listings cannot be restored. Default 50.")
    args = parser.parse_args()

    if not args.ranked.exists():
        print(f"error: ranked.json not found at {args.ranked}", file=sys.stderr)
        return 2
    data = json.loads(args.ranked.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("error: ranked.json is not a list", file=sys.stderr)
        return 2

    photos_dir = args.photos_dir
    archive_root = args.archive or (photos_dir / "_archive")
    photos_dir.mkdir(parents=True, exist_ok=True)

    index = _index_archive(archive_root)
    print(f"Archive indexed: {len(index)} distinct basenames under {archive_root}")

    referenced: list[tuple[int, str]] = []  # (rank_index, basename)
    for rank_idx, listing in enumerate(data):
        if not isinstance(listing, dict):
            continue
        hp = listing.get("hero_photo_path")
        if hp:
            referenced.append((rank_idx, hp.split("/")[-1]))

    already_present = 0
    restored = 0
    written_paths: list[str] = []
    missing: list[tuple[int, str]] = []  # (rank_index, basename) with no archive copy

    for rank_idx, base_name in referenced:
        root_file = photos_dir / base_name
        if root_file.exists():
            already_present += 1
            continue
        copies = index.get(base_name)
        if not copies:
            missing.append((rank_idx, base_name))
            continue
        newest_path = copies[-1][1]
        files = _restore_one(base_name, newest_path.parent, photos_dir, args.dry_run)
        if files:
            restored += 1
            written_paths.extend(files)
        else:
            # archive had the basename but no copyable thumbnail — treat as missing
            missing.append((rank_idx, base_name))

    print()
    print(f"Referenced hero_photo_path: {len(referenced)}")
    print(f"  already present:          {already_present}")
    print(f"  restored {'(dry-run) ' if args.dry_run else ''}this run: {restored}")
    print(f"  files {'would be ' if args.dry_run else ''}written:    {len(written_paths)}")
    print(f"  STILL MISSING (no archive copy): {len(missing)}")

    top_missing = [(r, b) for (r, b) in missing if r < args.top_required]
    if missing:
        print("\nStill-missing sample (rank, basename):")
        for r, b in missing[:15]:
            print(f"  rank={r} {b}")

    if written_paths and not args.dry_run:
        # Emit an explicit git-add list (CLAUDE.md: never `git add .` on
        # the sensitive web/photos/ tree). Grouped to keep the command short.
        print("\n# git add list (explicit — restored files only):")
        print(f"#   {len(written_paths)} files under {_rel(photos_dir)}/")

    if top_missing:
        print(
            f"\n[restore_photos] FAILED: {len(top_missing)} of the top "
            f"{args.top_required} ranked listings have no archive copy to "
            "restore — production will 404 on these.",
            file=sys.stderr,
        )
        return 1
    print("\n[restore_photos] OK: every top-ranked referenced photo is present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
