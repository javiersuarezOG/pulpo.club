#!/usr/bin/env python3
"""Reconstruct web/data/listings_history.json from git history.

Why this exists
---------------
``automation/run.py`` writes ``web/data/listings_history.json`` (the
``{"<source>|<source_id>": "<iso first_seen_at>"}`` sidecar) on every
nightly, and reads it back at the top of the next run so a listing keeps
the timestamp of the first nightly that ever saw it. That read-back never
happened in production: the nightly's commit step never staged the file,
so every run checked out a fresh repo, found nothing on disk, and stamped
``first_seen_at = <this run's start>`` on the entire catalog. Downstream,
``days_listed`` is derived as ``now - first_seen_at``, so ~98% of listings
rendered "0d" in the browse table and tripped the "New" badge.

The commit-step fix makes the file persist *going forward*. Without a seed
it starts empty, which means the whole catalog would still read "0d" on
the first post-fix nightly and only accumulate real ages from that day.

But the history is recoverable: ``web/data/ranked.json`` has been
committed by every nightly since 2026-04-29. Walking those blobs in
chronological order and recording the first commit in which each
``source|source_id`` appears reconstructs a genuine first-seen date for
every listing Pulpo has ever ranked.

Accuracy caveats (deliberately conservative)
--------------------------------------------
- The floor is the oldest ``ranked.json`` commit. A listing present in
  that first snapshot gets that commit's date, which is a LOWER bound on
  its true age — it may have been live on the broker's site long before.
  Such entries are marked in the ``--report`` output so the floor effect
  is visible rather than silently baked in.
- ``ranked.json`` is post-ranking, so a listing dropped by the ranker for
  a stretch of nightlies and later re-admitted still keeps its earliest
  appearance. That is the desired semantic (first seen, not continuously
  seen).
- ``days_listed`` parsed directly from a broker's ``mod_dt`` by the
  scraper always wins over this reconstruction: ``run.py`` only derives
  from ``first_seen_at`` when ``days_listed is None``.

Usage
-----
    python3 scripts/backfill_first_seen.py --report
    python3 scripts/backfill_first_seen.py --write
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RANKED = "web/data/ranked.json"
OUT = REPO / "web" / "data" / "listings_history.json"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout


def _norm_iso(iso: str) -> str:
    """Normalize to a form ``datetime.fromisoformat`` accepts on 3.10.

    ``git log %cI`` emits ``+00:00`` for locally-created commits but a
    bare ``Z`` for commits authored through the GitHub API (squash
    merges), and 3.10's parser rejects ``Z``. run.py does the same
    replace when it reads this file back."""
    return iso.replace("Z", "+00:00")


def commits_oldest_first() -> list[tuple[str, str]]:
    """[(sha, iso_committer_date)] for every commit touching ranked.json."""
    raw = _git("log", "--format=%H|%cI", "--reverse", "--", RANKED)
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        sha, _, iso = line.partition("|")
        if sha and iso:
            out.append((sha, _norm_iso(iso)))
    return out


def keys_at(sha: str) -> set[str]:
    """The set of '<source>|<source_id>' keys in ranked.json at `sha`."""
    try:
        blob = _git("show", f"{sha}:{RANKED}")
    except subprocess.CalledProcessError:
        return set()
    try:
        rows = json.loads(blob)
    except json.JSONDecodeError:
        return set()
    if not isinstance(rows, list):
        return set()
    keys = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        source, source_id = r.get("source"), r.get("source_id")
        if source and source_id is not None:
            keys.add(f"{source}|{source_id}")
    return keys


def build() -> tuple[dict[str, str], str, int]:
    """Returns (first_seen map, floor_iso, n_commits_walked)."""
    commits = commits_oldest_first()
    if not commits:
        sys.exit(f"no commits found touching {RANKED}")
    first_seen: dict[str, str] = {}
    for i, (sha, iso) in enumerate(commits, 1):
        for key in keys_at(sha):
            first_seen.setdefault(key, iso)
        print(f"  [{i}/{len(commits)}] {iso[:10]} {sha[:8]} "
              f"cumulative_keys={len(first_seen)}", file=sys.stderr)
    return first_seen, commits[0][1], len(commits)


def report(first_seen: dict[str, str], floor_iso: str, n_commits: int) -> None:
    by_month = collections.Counter(v[:7] for v in first_seen.values())
    at_floor = sum(1 for v in first_seen.values() if v == floor_iso)
    print(f"\ncommits walked      : {n_commits}")
    print(f"history floor       : {floor_iso[:10]} (oldest ranked.json commit)")
    print(f"keys reconstructed  : {len(first_seen)}")
    print(f"pinned at the floor : {at_floor}  "
          f"(LOWER bound on true age — listing predates our history)")
    print("\nfirst-seen by month:")
    for month, n in sorted(by_month.items()):
        print(f"  {month}  {n:5d}  {'#' * min(60, n // 12)}")

    # How the CURRENT catalog would render once this seed is in place.
    ranked_path = REPO / RANKED
    if ranked_path.exists():
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        rows = json.loads(ranked_path.read_text())
        ages, unmatched = [], 0
        for r in rows:
            key = f"{r.get('source')}|{r.get('source_id')}"
            iso = first_seen.get(key)
            if not iso:
                unmatched += 1
                continue
            ts = dt.datetime.fromisoformat(iso)
            ages.append(max(0, (now - ts).days))
        if ages:
            ages.sort()
            buckets = collections.Counter(
                "0d" if a == 0 else "1-7d" if a <= 7 else "8-30d"
                if a <= 30 else "31-90d" if a <= 90 else "90d+"
                for a in ages
            )
            print(f"\ncurrent catalog ({len(rows)} listings) would render:")
            for b in ("0d", "1-7d", "8-30d", "31-90d", "90d+"):
                n = buckets.get(b, 0)
                print(f"  {b:>7}  {n:5d}  ({100 * n / len(ages):.1f}%)")
            print(f"  median age: {ages[len(ages) // 2]}d")
            print(f"  no history match (genuinely new): {unmatched}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help=f"write the reconstructed map to {OUT}")
    ap.add_argument("--report", action="store_true",
                    help="print the distribution without writing")
    args = ap.parse_args()
    if not (args.write or args.report):
        ap.error("pass --report and/or --write")

    print(f"walking git history of {RANKED} ...", file=sys.stderr)
    first_seen, floor_iso, n_commits = build()

    if args.report:
        report(first_seen, floor_iso, n_commits)

    if args.write:
        # Merge rather than clobber: if a history file already exists
        # (a later run of this script, or a nightly that has since
        # persisted one), its entries are authoritative — they were
        # observed live, not reconstructed. Only fill gaps, and only
        # when the reconstruction is OLDER.
        existing = {}
        if OUT.exists():
            try:
                loaded = json.loads(OUT.read_text())
                if isinstance(loaded, dict):
                    existing = {k: v for k, v in loaded.items()
                                if isinstance(v, str)}
            except (json.JSONDecodeError, OSError):
                existing = {}
        merged = dict(first_seen)
        for k, v in existing.items():
            merged[k] = min(v, merged[k]) if k in merged else v
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
        print(f"\nwrote {OUT} ({len(merged)} keys, "
              f"{len(existing)} pre-existing preserved)")


if __name__ == "__main__":
    main()
