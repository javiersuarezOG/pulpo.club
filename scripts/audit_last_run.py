"""
Post-crawl audit. Reads web/data/ranked.json + last_updated.json and writes a
human-readable summary to samples/last_run_audit.txt covering:

  - record count, source split, dropped count
  - dedup confirmation (unique URLs vs total records)
  - SOLD bleed-through check (any record with sold/vendido/reservado markers
    in any text field — should be zero)
  - field coverage (% of records with price / area / $/m² / zone)
  - $/m² distribution (min / median / max / outliers below $5 or above $1k)
  - per-zone counts and median $/m²
  - any unknown-zone records flagged for ZONE_PATTERNS expansion

Exits non-zero if any hard invariants fail (dedup not enforced, SOLD leaks,
fixture_fallback_active true on a live run).
"""
from __future__ import annotations
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RANKED = REPO / "web" / "data" / "ranked.json"
META = REPO / "web" / "data" / "last_updated.json"
OUT = REPO / "samples" / "last_run_audit.txt"

# Mirror the relaxed pattern from pulpo.normalize._SOLD_RE — see comment there.
# No trailing \b, because DOM-blob text often runs words together.
SOLD_RE = re.compile(
    r"(?:^|[\s\W])(?:\*?\s*sold|vendido|vendida|under\s+contract|reservado|reservada|pending\s+sale)",
    re.IGNORECASE,
)


def main() -> int:
    if not RANKED.exists():
        print(f"FAIL: {RANKED} missing", file=sys.stderr)
        return 1

    data = json.loads(RANKED.read_text())
    meta = json.loads(META.read_text()) if META.exists() else {}

    lines: list[str] = []
    failures: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w(f"pulpo audit — generated {datetime.now(timezone.utc).isoformat()}")
    w("=" * 72)
    w()

    # ---- Run metadata ----
    w("RUN METADATA")
    w(f"  last_updated:            {meta.get('last_updated')}")
    w(f"  duration_seconds:        {meta.get('duration_seconds')}")
    w(f"  offline (intent):        {meta.get('offline')}")
    w(f"  fixture_fallback_active: {meta.get('fixture_fallback_active')}")
    w(f"  raw per source:          {meta.get('per_source_raw')}")
    w(f"  dropped:                 {meta.get('dropped')}")
    w(f"  errors:                  {meta.get('errors')}")
    w()
    if meta.get("offline") is False and meta.get("fixture_fallback_active") is True:
        failures.append("fixture fallback active on a live run — dependency missing")

    # ---- Dedup ----
    urls = Counter(r["url"] for r in data)
    dup_urls = [(u, n) for u, n in urls.items() if n > 1]
    w("DEDUP")
    w(f"  total records:  {len(data)}")
    w(f"  unique URLs:    {len(urls)}")
    w(f"  duplicates:     {len(dup_urls)}")
    if dup_urls:
        for u, n in dup_urls[:5]:
            w(f"    ×{n}  {u}")
        failures.append(f"{len(dup_urls)} URLs duplicated in ranked.json")
    w()

    # ---- SOLD leak ----
    leaks = []
    for r in data:
        blob = " ".join(
            str(r.get(k, "")) for k in
            ("title", "description", "raw_price_text", "raw_size_text", "location_text")
        )
        if SOLD_RE.search(blob):
            leaks.append(r)
    w("SOLD BLEED-THROUGH")
    w(f"  records carrying SOLD markers anywhere: {len(leaks)}")
    for r in leaks[:5]:
        w(f"    [{r['source']}] {r['title'][:60]!r}")
    if leaks:
        failures.append(f"{len(leaks)} SOLD-marked records leaked into ranked.json")
    w()

    # ---- Source / zone breakdown ----
    sources = Counter(r["source"] for r in data)
    zones = Counter(r.get("zone") or "<unknown>" for r in data)
    w("SOURCE SPLIT")
    for s, n in sources.most_common():
        w(f"  {s:12}  {n}")
    w()
    w("ZONE BREAKDOWN")
    for z, n in zones.most_common():
        w(f"  {z:14}  {n}")
    w()

    # ---- Field coverage ----
    n = max(len(data), 1)
    has_price = sum(1 for r in data if r.get("price_usd"))
    has_area = sum(1 for r in data if r.get("area_m2"))
    has_ppm2 = sum(1 for r in data if r.get("price_per_m2"))
    has_zone = sum(1 for r in data if r.get("zone"))
    w("FIELD COVERAGE")
    w(f"  price_usd:     {has_price}/{n}  ({100*has_price/n:.0f}%)")
    w(f"  area_m2:       {has_area}/{n}  ({100*has_area/n:.0f}%)")
    w(f"  price_per_m2:  {has_ppm2}/{n}  ({100*has_ppm2/n:.0f}%)")
    w(f"  zone:          {has_zone}/{n}  ({100*has_zone/n:.0f}%)")
    w()

    # ---- $/m² distribution ----
    ppm2_vals = sorted(r["price_per_m2"] for r in data if r.get("price_per_m2"))
    w("$/m² DISTRIBUTION")
    if ppm2_vals:
        w(f"  count:   {len(ppm2_vals)}")
        w(f"  min:     ${ppm2_vals[0]:,.2f}")
        w(f"  median:  ${statistics.median(ppm2_vals):,.2f}")
        w(f"  mean:    ${statistics.mean(ppm2_vals):,.2f}")
        w(f"  max:     ${ppm2_vals[-1]:,.2f}")
        # Outliers worth a human eye
        low = [r for r in data if r.get("price_per_m2") and r["price_per_m2"] < 5]
        high = [r for r in data if r.get("price_per_m2") and r["price_per_m2"] > 1000]
        if low:
            w(f"  outliers <$5/m² ({len(low)}):")
            for r in low[:5]:
                w(f"    ${r['price_per_m2']:.2f}  area={r.get('area_m2')}  {r['title'][:50]!r}")
        if high:
            w(f"  outliers >$1k/m² ({len(high)}):")
            for r in high[:5]:
                w(f"    ${r['price_per_m2']:.2f}  area={r.get('area_m2')}  {r['title'][:50]!r}")
    else:
        w("  (no records with $/m²)")
    w()

    # ---- Per-zone median $/m² ----
    by_zone: dict[str, list[float]] = defaultdict(list)
    for r in data:
        if r.get("zone") and r.get("price_per_m2"):
            by_zone[r["zone"]].append(r["price_per_m2"])
    w("MEDIAN $/m² BY ZONE")
    for z, vals in sorted(by_zone.items(), key=lambda kv: -statistics.median(kv[1])):
        w(f"  {z:14}  ${statistics.median(vals):>8,.2f}   (n={len(vals)})")
    w()

    # ---- Unknown zones (candidates to add to ZONE_PATTERNS) ----
    unknowns = [r for r in data if not r.get("zone")]
    if unknowns:
        w("UNKNOWN ZONES (candidates for ZONE_PATTERNS expansion)")
        for r in unknowns[:10]:
            w(f"  {r['title'][:55]!r}  loc={r.get('location_text','')[:60]!r}")
        w()

    # ---- Verdict ----
    w("=" * 72)
    if failures:
        w("VERDICT: FAIL")
        for f in failures:
            w(f"  ✗ {f}")
    else:
        w("VERDICT: OK")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"audit written to {OUT}")
    print("\n".join(lines[-12:]))  # echo verdict block

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
