#!/usr/bin/env python3
"""Move listings that were geocoded ONTO a drifted beach anchor.

Why this exists: the LLM enrichment prompt instructs DeepSeek to use the
*exact* coordinates from the AUTHORITATIVE BEACH COORDINATES block when a
listing names a beach. It obeyed — so when an anchor was wrong, the
listings placed on it inherited the same error verbatim. 217 listings sit
within 200 m of an anchor corrected in Aug 2026.

Correcting the manifest ALONE makes those listings look worse, not better:
the anchor moves to the real beach while the listing stays at the old
position, so a genuinely beachfront listing starts reporting 12-49 km to
the nearest beach. This script closes that gap deterministically — no LLM
call, no cost — by translating each listing that sat on an old anchor onto
the corrected one.

It is intentionally narrow. A listing merely *near* an old anchor is not
touched, because we cannot know whether it was anchor-placed or genuinely
located there; those need the full ``scripts/retrofit_geocoding.py`` pass
(which does cost DeepSeek calls).

    python3 scripts/remap_drifted_beach_anchors.py            # dry run
    python3 scripts/remap_drifted_beach_anchors.py --write

Writes ranked.json AND the llm_enrichment.json sidecar, so the next
nightly does not clobber the remap.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from automation.distance_fields import (  # noqa: E402
    compute_dist_airport_km,
    compute_dist_beach_km,
    haversine_km,
)

RANKED = REPO / "web" / "data" / "ranked.json"
SIDECAR = REPO / "web" / "data" / "llm_enrichment.json"

# Radius within which a listing is considered "placed on the anchor" rather
# than coincidentally nearby. The prompt hands out exact table coordinates,
# so genuine anchor-placed listings land at ~0 m; 200 m absorbs rounding
# without sweeping in real neighbours.
_ON_ANCHOR_KM = 0.20

# (old_lat, old_lng) -> (new_lat, new_lng), Aug 2026 named_beaches correction.
DRIFT_MAP: dict[tuple[float, float], tuple[float, float]] = {
    (13.4843, -89.7163): (13.4710, -89.2628),   # Bocana San Diego
    (13.4900, -89.6594): (13.4919, -89.3649),   # El Majahual
    (13.4844, -89.6322): (13.4942, -89.3949),   # El Sunzal
    (13.4870, -89.6133): (13.4926, -89.3829),   # El Tunco
    (13.4983, -89.5538): (13.4939, -89.4386),   # El Zonte
    (13.4747, -89.4889): (13.4873, -89.3611),   # San Blas
    (13.5300, -89.7000): (13.5105, -89.5964),   # Mizata
    (13.4575, -89.3478): (13.4966, -89.5137),   # Playa La Perla
    (13.1740, -88.5570): (13.1710, -88.2941),   # Playa El Espino
    (13.1761, -88.4836): (13.1601, -87.9711),   # Las Tunas
    (13.1894, -88.3858): (13.1724, -88.1103),   # Playa El Cuco
    (13.1810, -88.3550): (13.1722, -88.1147),   # Playa Las Flores
    (13.1758, -88.2925): (13.1616, -87.9431),   # Playa Negra
    (13.1822, -88.1839): (13.1704, -88.0742),   # Playa Esterón
    (13.2050, -87.8420): (13.1611, -87.9641),   # Playa Torola
}


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _rows(raw):
    return raw if isinstance(raw, list) else (raw.get("listings") or raw.get("items") or [])


def _anchor_for(lat: float, lng: float) -> tuple[float, float] | None:
    for old, new in DRIFT_MAP.items():
        if haversine_km(lat, lng, old[0], old[1]) <= _ON_ANCHOR_KM:
            return new
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="persist changes (default: dry run)")
    args = ap.parse_args(argv)

    raw = _load(RANKED)
    if raw is None:
        print(f"ERROR: {RANKED} not found", file=sys.stderr)
        return 1
    rows = _rows(raw)
    sidecar = _load(SIDECAR) or {}

    moved, beach_before, beach_after = [], [], []
    for li in rows:
        lat, lng = li.get("lat"), li.get("lng")
        if lat is None or lng is None:
            continue
        new = _anchor_for(float(lat), float(lng))
        if new is None:
            continue

        before = li.get("dist_beach_km")
        li["lat"], li["lng"] = new[0], new[1]
        li["geocoding_source"] = "beach_anchor_remap_2026_08"

        # Both helpers RETURN a value rather than mutating the listing, so
        # the results have to be written back explicitly — mirroring what
        # distance_fields.apply_distance_fields does during the nightly.
        after = compute_dist_beach_km(li)
        if after is not None:
            li["dist_beach_km"] = after
        airport_km, _method = compute_dist_airport_km(li)
        if airport_km is not None:
            li["dist_airport_km"] = airport_km

        moved.append((li.get("zone"), before, after))
        if before is not None:
            beach_before.append(before)
        if after is not None:
            beach_after.append(after)

        # Mirror into the sidecar so the nightly does not clobber the remap.
        sid = li.get("source_id")
        if sid and sid in sidecar and isinstance(sidecar[sid], dict):
            sidecar[sid]["lat"], sidecar[sid]["lng"] = new[0], new[1]
            sidecar[sid]["geocoding_source"] = "beach_anchor_remap_2026_08"

    from collections import Counter
    print(f"listings sitting on a drifted anchor: {len(moved)}")
    for z, c in Counter(z for z, _, _ in moved).most_common(12):
        print(f"    {z}: {c}")
    if beach_before and beach_after:
        print(f"\n  mean dist_beach_km  before={sum(beach_before)/len(beach_before):.2f}"
              f"  after={sum(beach_after)/len(beach_after):.2f}")

    if not args.write:
        print("\n[dry run] nothing written — re-run with --write")
        return 0

    RANKED.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if sidecar:
        SIDECAR.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"\nwrote {RANKED.name}" + (f" + {SIDECAR.name}" if sidecar else ""))
    print("Commit this as a DATA-ONLY PR, separate from the manifest change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
