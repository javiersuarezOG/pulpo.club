"""
Audit ranked.json for description/distance inconsistencies on the beach.

Surfaces listings that EITHER:
  * claim walking-distance to the beach in the description, hero blurb,
    or reasons_to_buy, but `dist_beach_km` says otherwise (> 2 km), OR
  * claim "beachfront" / "frente al mar" but `dist_beach_km` > 1 km.

Inverse direction (silent listings ~0 km from the coast) is too noisy
to flag without a corpus signal — most coastal listings just don't
mention it explicitly. Skipped here.

Run:
    python3 scripts/audit_beach_distance_consistency.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RANKED = REPO / "web" / "data" / "ranked.json"

# "near the beach" claims — Spanish + English. Matches:
#   "two-minute walk to the beach"
#   "a 2 minutos de la playa"
#   "a dos minutos caminando de la playa"
#   "a pasos del mar"
#   "walking distance to the beach"
WALK_TO_BEACH_RE = re.compile(
    r"("
    # English: "X-minute walk", "five minute stroll", "walking distance to the beach"
    # "X" capped at 10 because real walking distance maxes out around there;
    # "20-minute walk to the beach" almost always means driving in this market.
    r"(?:\b(?:one|two|three|four|five|six|seven|eight|nine|ten|[1-9]|10)[-\s]minute[s]?\s+(?:walk|stroll)\b[^.]{0,40}?\bbeach\b)"
    r"|(?:\bwalking\s+distance\b[^.]{0,40}?\bbeach\b)"
    # Spanish: "a X minutos caminando de la playa" — walking is explicit
    # (any X up to ~15 is plausible for walking distance).
    r"|(?:\ba\s+\d+\s+min(?:utos?)?\.?\s+caminando\s+(?:de|del|al|a la)\s+(?:la\s+)?(?:playa|mar)\b)"
    # Spanish: bare "a X minutos de la playa" — only count as walking
    # when X ≤ 3. "5 minutos / 10 minutos de la playa" without
    # "caminando" almost always means driving in this market (inland
    # zones where the property is many km from the coast).
    r"|(?:\ba\s+(?:un[oa]s?|dos|tres|[1-3])"
    r"\s+min(?:utos?)?\.?\s+(?:de|del|al|a la)\s+(?:la\s+)?(?:playa|mar)\b)"
    r"|(?:\ba\s+pasos\s+(?:de|del)\s+(?:la\s+)?(?:playa|mar)\b)"
    r"|(?:\ba\s+(?:una\s+)?cuadra\s+(?:de|del)\s+(?:la\s+)?(?:playa|mar)\b)"
    r")",
    re.IGNORECASE,
)

BEACHFRONT_RE = re.compile(
    r"\b(beachfront|ocean[\s-]?front|frente\s+al\s+mar|en\s+(?:la\s+)?playa\s+misma)\b",
    re.IGNORECASE,
)

# Threshold: a description claiming "two-minute walk to the beach" should
# correspond to dist_beach_km <= ~1.5 km. We allow 2.0 km because the
# coastline reference set is point-based at ~5km spacing — a true
# beachfront listing equidistant between two points can read 2.5 km
# even when it's at the water. Above 2.0 km is genuinely wrong.
WALK_THRESHOLD_KM = 2.0
BEACHFRONT_THRESHOLD_KM = 1.0


def _localized_text(value: Any) -> str:
    """LLM bilingual fields are {en, es} dicts; reasons are list of those."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " | ".join(str(v) for v in value.values() if v)
    if isinstance(value, list):
        return " | ".join(_localized_text(v) for v in value)
    return ""


def _gather_claim_text(li: dict) -> str:
    parts = [
        li.get("description") or "",
        li.get("title") or "",
        _localized_text(li.get("title_canonical")),
        _localized_text(li.get("short_description_canonical")),
        _localized_text(li.get("reasons_to_buy")),
    ]
    return " \n ".join(p for p in parts if p)


def audit(records: list[dict]) -> list[dict]:
    findings: list[dict] = []
    for li in records:
        dist = li.get("dist_beach_km")
        if dist is None:
            # Can't compare; skip rather than guess.
            continue
        text = _gather_claim_text(li)
        if not text:
            continue

        walk_match = WALK_TO_BEACH_RE.search(text)
        beachfront_match = BEACHFRONT_RE.search(text)

        flag: str | None = None
        snippet: str | None = None
        if beachfront_match and dist > BEACHFRONT_THRESHOLD_KM:
            flag = "beachfront_claim_vs_distance"
            snippet = beachfront_match.group(0)
        elif walk_match and dist > WALK_THRESHOLD_KM:
            flag = "walking_claim_vs_distance"
            snippet = walk_match.group(0)

        if flag:
            findings.append({
                "source":          li.get("source"),
                "source_id":       li.get("source_id"),
                "url":             li.get("url"),
                "title":           (li.get("title") or "")[:90],
                "zone":            li.get("zone"),
                "geocoding_source":     li.get("geocoding_source"),
                "geocoding_confidence": li.get("geocoding_confidence"),
                "lat": li.get("lat"),
                "lng": li.get("lng"),
                "dist_beach_km":   dist,
                "flag":            flag,
                "claim_snippet":   snippet,
            })
    return findings


def main() -> None:
    records = json.loads(RANKED.read_text(encoding="utf-8"))
    findings = audit(records)
    print(f"Scanned {len(records)} listings; flagged {len(findings)}.")
    by_flag: dict[str, int] = {}
    for f in findings:
        by_flag[f["flag"]] = by_flag.get(f["flag"], 0) + 1
    for flag, n in sorted(by_flag.items(), key=lambda x: -x[1]):
        print(f"  {flag}: {n}")
    print()
    for f in findings:
        print(
            f"[{f['flag']}] dist={f['dist_beach_km']}km "
            f"geocode={f['geocoding_source']}/{f['geocoding_confidence']} "
            f"zone={f['zone']}"
        )
        print(f"    {f['source']}/{f['source_id']}")
        print(f"    title:  {f['title']}")
        print(f"    claim:  {f['claim_snippet']!r}")
        print(f"    url:    {f['url']}")
        print()


if __name__ == "__main__":
    main()
