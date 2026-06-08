#!/usr/bin/env python3
"""Photo-contract TRUTH canary — does the committed state actually hold?

Why this exists
---------------
`pulpo/photo_contract.py::enforce_photo_contract` nulls stale hero paths
and writes `web/data/photo_contract.json`. But the 2026-06-08 incident
showed the sidecar can describe the WRONG dataset: the multi-country
nightly ran the contract in the PA context (17 listings, 0 missing) and
left `photo_contract.json` reporting `ranked_total=17` while the
committed SV `ranked.json` had 1,590 listings and 1,037 hero paths that
404'd in production. `/api/nightly/health` read the sidecar and reported
"all good." The enforcement was tight but evaluated in the wrong context.

This canary is independent of how/where the contract was computed. It
reads the **committed** files on disk and asserts two things:

  1. PRIMARY (production-truth): every `hero_photo_path` in the committed
     `ranked.json` resolves to an existing file under `web/photos/`.
     This is the exact condition that determines whether production
     serves the image or a 404 — no sidecar trust required.

  2. SECONDARY (sidecar-trust): `photo_contract.json.ranked_total` matches
     `len(ranked.json)`. A mismatch means the sidecar describes a
     different dataset than the one that ships — the PA-overwrite
     fingerprint. Surfaced as a hard failure so `/api/nightly/health`
     can never silently describe the wrong country again.

Run it AFTER the SV/PA restore block in the nightly, before the data
commit, so it sees the SV apex state that actually deploys.

Exit codes
----------
  0  committed state is sound
  1  a hero_photo_path points at a missing file, OR the sidecar's
     ranked_total disagrees with ranked.json
  2  bad input (a required file is missing / unparseable)

Usage
-----
    python3 scripts/check_photo_contract_truth.py
    python3 scripts/check_photo_contract_truth.py --ranked web/data/ranked.json \
        --contract web/data/photo_contract.json --photos-dir web/photos
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RANKED = REPO_ROOT / "web" / "data" / "ranked.json"
DEFAULT_CONTRACT = REPO_ROOT / "web" / "data" / "photo_contract.json"
DEFAULT_PHOTOS = REPO_ROOT / "web" / "photos"

# The committed sidecar can legitimately describe a slightly different
# count than ranked.json if a non-photo step rewrote ranked.json after
# the contract pass. Keep the tolerance tight — the failure we care about
# (PA's 17 vs SV's 1,590) is a ~99% divergence, nothing subtle.
RANKED_TOTAL_DRIFT_TOLERANCE = 5


def _root_file_for(hero_photo_path: str, photos_dir: Path) -> Path:
    """`/photos/<file>.jpg` → `<photos_dir>/<file>.jpg`.

    Mirrors `pulpo.photo_contract._root_file_for` (the producer-side
    resolver) so this canary checks the exact path production serves.
    """
    return photos_dir / hero_photo_path.split("/")[-1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ranked", type=Path, default=DEFAULT_RANKED)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--photos-dir", type=Path, default=DEFAULT_PHOTOS)
    parser.add_argument(
        "--max-examples", type=int, default=15,
        help="How many missing-file examples to print.",
    )
    args = parser.parse_args()

    if not args.ranked.exists():
        print(f"error: ranked.json not found at {args.ranked}", file=sys.stderr)
        return 2
    try:
        ranked = json.loads(args.ranked.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: ranked.json is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(ranked, list):
        print("error: ranked.json is not a list", file=sys.stderr)
        return 2

    violations: list[str] = []

    # ── PRIMARY: every hero_photo_path resolves to a real file ──────────
    with_path = 0
    missing: list[str] = []
    for listing in ranked:
        if not isinstance(listing, dict):
            continue
        hp = listing.get("hero_photo_path")
        if not hp:
            continue
        with_path += 1
        if not _root_file_for(hp, args.photos_dir).exists():
            missing.append(hp)

    print(f"ranked.json listings:        {len(ranked)}")
    print(f"  with hero_photo_path:      {with_path}")
    print(f"  resolving to a real file:  {with_path - len(missing)}")
    print(f"  MISSING on disk:           {len(missing)}")
    if missing:
        violations.append(
            f"{len(missing)} hero_photo_path entries point at files absent "
            f"from {args.photos_dir} — production will 404 on these"
        )
        for hp in missing[: args.max_examples]:
            print(f"    missing: {hp}")

    # ── SECONDARY: sidecar describes the SAME dataset that ships ────────
    if not args.contract.exists():
        violations.append(f"photo_contract.json not found at {args.contract}")
    else:
        try:
            contract = json.loads(args.contract.read_text(encoding="utf-8"))
            sidecar_total = int(contract.get("ranked_total", -1))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            violations.append(f"photo_contract.json unreadable: {e}")
            sidecar_total = -1
        else:
            drift = abs(sidecar_total - len(ranked))
            print(
                f"photo_contract.ranked_total: {sidecar_total} "
                f"(ranked.json={len(ranked)}, drift={drift})"
            )
            if drift > RANKED_TOTAL_DRIFT_TOLERANCE:
                violations.append(
                    f"photo_contract.json describes {sidecar_total} listings "
                    f"but ranked.json has {len(ranked)} (drift {drift} > "
                    f"{RANKED_TOTAL_DRIFT_TOLERANCE}) — the sidecar evaluated a "
                    "different dataset than the one shipping (PA-overwrite "
                    "fingerprint); /api/nightly/health cannot be trusted"
                )

    if violations:
        print("\n[photo_contract_truth] CANARY FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print("\n[photo_contract_truth] OK: committed ranked.json + sidecar agree "
          "and every hero photo resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
