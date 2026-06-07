#!/usr/bin/env python3
"""Promote a candidate bundle to web/data/.

R1 of docs/RESILIENCE-AUDIT-PRD.md. When a guard blocked a nightly
candidate from auto-promoting, the workflow uploaded the bundle as
``candidate_bundle_<run_id>``. This CLI fetches that artifact, verifies
the manifest's SHA256s, and (optionally) writes the bundle's ranked.json
into web/data/ so the data PR can land.

Usage:

    # See what would happen — no writes
    python scripts/promote_candidate.py --run-id 27050642483 --dry-run

    # Apply the promote
    python scripts/promote_candidate.py --run-id 27050642483 --apply

    # Promote a locally-staged bundle (skip the GH artifact download)
    python scripts/promote_candidate.py --staging web/data/.staging/<rid> --apply

In R1 the CLI is intentionally thin — it copies ranked.json into
web/data/ and prints a manual checklist for the rest. R4 will add
the proper promotion/quarantine state machine; R9 will round out
list_candidates / explain_run / etc.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from automation.candidate_bundle import (  # noqa: E402
    read_candidate_bundle,
    verify_bundle,
)


def _download_artifact(run_id: str, dest: Path) -> Path:
    """Use gh CLI to download the candidate_bundle_<run_id> artifact.

    Returns the staging directory inside `dest` containing the bundle.
    Raises CalledProcessError if gh isn't installed / not authed / the
    artifact doesn't exist.
    """
    artifact_name = f"candidate_bundle_{run_id}"
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["gh", "run", "download", run_id, "--name", artifact_name, "--dir", str(dest)],
        check=True,
    )
    return dest


def _diff_summary(bundle: dict, target_dir: Path) -> list[str]:
    """One-line per-file summary of what would change on apply."""
    lines = []
    ranked = bundle.get("ranked", [])
    target_ranked = target_dir / "ranked.json"
    if target_ranked.exists():
        old = json.loads(target_ranked.read_text())
        lines.append(f"ranked.json: {len(old)} → {len(ranked)} listings")
    else:
        lines.append(f"ranked.json: <missing> → {len(ranked)} listings")
    return lines


def main() -> int:
    p = argparse.ArgumentParser(prog="promote_candidate")
    p.add_argument("--run-id", help="GitHub Actions run id (used to download the artifact).")
    p.add_argument("--staging", help="Path to an already-extracted bundle directory. "
                                     "Skips the gh artifact download.")
    p.add_argument("--target", default=str(REPO / "web" / "data"),
                   help="Directory to promote into (default: web/data).")
    p.add_argument("--dry-run", action="store_true",
                   help="Show diff, do not write.")
    p.add_argument("--apply", action="store_true",
                   help="Write the bundle's ranked.json into the target directory.")
    p.add_argument("--allow-degraded", action="store_true",
                   help="Placeholder for R4 — accepted but unused in R1.")
    args = p.parse_args()

    if not args.run_id and not args.staging:
        print("error: must provide --run-id or --staging", file=sys.stderr)
        return 2
    if args.dry_run and args.apply:
        print("error: --dry-run and --apply are mutually exclusive", file=sys.stderr)
        return 2
    if not args.dry_run and not args.apply:
        # Sensible default: read-only.
        args.dry_run = True

    if args.staging:
        staging = Path(args.staging).resolve()
        if not staging.exists():
            print(f"error: staging dir does not exist: {staging}", file=sys.stderr)
            return 2
    else:
        staging = REPO / ".artifacts" / args.run_id
        try:
            _download_artifact(args.run_id, staging)
        except subprocess.CalledProcessError as e:
            print(f"error: gh artifact download failed (exit {e.returncode})", file=sys.stderr)
            return 3

    mismatches = verify_bundle(staging)
    if mismatches:
        print("error: bundle integrity check failed:", file=sys.stderr)
        for m in mismatches:
            print(f"  {m}", file=sys.stderr)
        return 4

    bundle = read_candidate_bundle(staging)
    manifest = bundle["manifest"]
    target_dir = Path(args.target).resolve()

    print(f"bundle run_id: {manifest['run_id']}")
    print(f"generated_at:  {manifest['generated_at']}")
    print(f"visible_count: {manifest['visible_count']}")
    print(f"files:         {len(manifest['files'])}")
    print(f"target_dir:    {target_dir}")
    print()
    print("Would change:")
    for line in _diff_summary(bundle, target_dir):
        print(f"  {line}")

    if args.dry_run:
        print()
        print("DRY-RUN — no writes performed. Pass --apply to commit the promote.")
        return 0

    # Apply: copy ranked.json (the canonical data file).
    src_ranked = staging / "ranked.json"
    if not src_ranked.exists():
        print(f"error: bundle missing ranked.json at {src_ranked}", file=sys.stderr)
        return 5
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_ranked, target_dir / "ranked.json")
    print()
    print(f"WROTE: {target_dir / 'ranked.json'}")
    print()
    print("Next manual steps:")
    print("  1. Inspect the diff:  git diff web/data/ranked.json")
    print("  2. Run the next nightly to refresh last_updated.json + run_history.json")
    print("  3. Or open a data PR explicitly: git add web/data/ranked.json && git commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
