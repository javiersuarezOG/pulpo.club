#!/usr/bin/env python3
"""Cross-check the manifest's ``named_beaches`` against an independent gazetteer.

Motivation: ``named_beaches`` is asserted, never verified. The same tuple
feeds BOTH the ``dist_beach_km`` haversine grid AND the LLM enrichment
prompt's AUTHORITATIVE BEACH COORDINATES block, so a wrong entry is wrong
twice — it inflates beach distance for genuinely beachfront listings and
anchors newly geocoded listings to the wrong spot. Nothing in the pipeline
would notice, because every consumer trusts the table by construction.

This audit is a DEVELOPMENT tool, run on demand — not a CI gate and not a
nightly step. It hits the public Nominatim endpoint at 1 request/sec per
their usage policy, so a full 36-beach sweep takes ~40s.

    python3 scripts/audit_named_beach_coords.py
    python3 scripts/audit_named_beach_coords.py --threshold-km 2 --json out.json

Read ``docs/named-beach-reference.md`` before acting on the output. A large
delta is a prompt to investigate, NOT a licence to bulk-overwrite the table:
Nominatim frequently returns a town centroid where we want the coastline
point, and the table's own rule is to omit any beach we cannot pin to
within ~500 m.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.distance_fields import haversine_km  # noqa: E402
from pulpo.countries import active as _active_country  # noqa: E402

_UA = "pulpo.club-beach-audit/1.0 (+https://pulpo.club; contact: javier@suarez.ventures)"
_ENDPOINT = "https://nominatim.openstreetmap.org/search"
_RATE_LIMIT_S = 1.1


def _lookup(name: str, country_code: str) -> dict | None:
    """Best gazetteer hit for ``name`` restricted to the active country."""
    q = urllib.parse.urlencode({
        "q": name,
        "format": "json",
        "limit": 1,
        "countrycodes": country_code.lower(),
        "addressdetails": 1,
    })
    req = urllib.request.Request(f"{_ENDPOINT}?{q}", headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:  # noqa: S310 - fixed https host
            hits = json.load(r)
    except Exception as e:  # noqa: BLE001 - a lookup failure must not abort the sweep
        return {"error": str(e)}
    if not hits:
        return None
    h = hits[0]
    return {
        "lat": float(h["lat"]),
        "lng": float(h["lon"]),
        "display_name": h.get("display_name", ""),
        "class": h.get("class", ""),
        "type": h.get("type", ""),
    }


def audit(threshold_km: float) -> list[dict]:
    m = _active_country()
    rows: list[dict] = []
    beaches = m.named_beaches()
    for i, (name, lat, lng) in enumerate(beaches, 1):
        hit = _lookup(f"{name}, {m.name_en}", m.code)
        time.sleep(_RATE_LIMIT_S)
        row: dict = {"name": name, "manifest_lat": lat, "manifest_lng": lng}
        if hit is None:
            row["status"] = "not_found"
        elif "error" in hit:
            row["status"] = "lookup_error"
            row["error"] = hit["error"]
        else:
            d = haversine_km(lat, lng, hit["lat"], hit["lng"])
            row.update({
                "status": "drift" if d > threshold_km else "ok",
                "osm_lat": round(hit["lat"], 5),
                "osm_lng": round(hit["lng"], 5),
                "delta_km": round(d, 2),
                "osm_match": hit["display_name"][:80],
                "osm_kind": f"{hit['class']}/{hit['type']}",
            })
        rows.append(row)
        print(f"  [{i:2d}/{len(beaches)}] {name:24} {row['status']}"
              + (f"  {row.get('delta_km')} km" if "delta_km" in row else ""),
              file=sys.stderr)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold-km", type=float, default=2.0,
                    help="flag entries further than this from the gazetteer (default 2)")
    ap.add_argument("--json", help="also write the full result set here")
    args = ap.parse_args(argv)

    m = _active_country()
    print(f"[beach-audit] {m.name_en} ({m.code}) — {len(m.named_beaches())} entries, "
          f"threshold {args.threshold_km} km\n", file=sys.stderr)

    rows = audit(args.threshold_km)
    drift = [r for r in rows if r["status"] == "drift"]
    other = [r for r in rows if r["status"] in ("not_found", "lookup_error")]

    print(f"\n{'beach':26} {'manifest':>19} {'gazetteer':>19} {'delta':>8}")
    print("-" * 76)
    for r in sorted(drift, key=lambda x: -x["delta_km"]):
        print(f"{r['name']:26} {r['manifest_lat']:8.4f},{r['manifest_lng']:9.4f} "
              f"{r['osm_lat']:8.4f},{r['osm_lng']:9.4f} {r['delta_km']:7.1f}")
    for r in other:
        print(f"{r['name']:26} {r['status']}")

    print(f"\n[beach-audit] {len(drift)} drifted / {len(other)} unresolved "
          f"/ {len(rows) - len(drift) - len(other)} ok")
    if drift:
        print("[beach-audit] Investigate each before editing the manifest — the "
              "gazetteer may return a town centroid where the table wants the "
              "coastline point. See docs/named-beach-reference.md.")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
        print(f"[beach-audit] full results -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
