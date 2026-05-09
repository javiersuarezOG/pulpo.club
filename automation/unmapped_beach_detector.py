"""
Detect listings whose description claims walking distance to a beach but
whose stored dist_beach_km says they're far from any point in the
authoritative NAMED_BEACHES reference table.

Two failure modes this surfaces:
  1. The LLM placed lat/lng at an inland centroid even though the source
     contained a coastal cue (prompt regression / new edge case).
  2. The LLM placed lat/lng correctly at a coastal point that is NOT in
     NAMED_BEACHES (a beach we haven't mapped yet, e.g. when a new
     country / new SV stretch is added). Cluster these by approximate
     region so the operator can see "12 listings around (13.7, -89.97)
     claim beachfront but no mapped beach within 5km — add a
     NAMED_BEACHES entry for La Barra de Santiago".

Wired into automation/run.py after the final apply_distances pass.
Telemetry rows append to web/data/unmapped_beaches_history.jsonl.

Public API:

    from automation.unmapped_beach_detector import detect_unmapped_beach_clusters
    metrics = detect_unmapped_beach_clusters(listings)

Returns a metrics dict; also writes one row to the history sidecar.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Same regexes as scripts/audit_beach_distance_consistency.py — keep the
# pipeline-side detector and the offline audit aligned. If the audit
# heuristic changes, change both.
_WALK_TO_BEACH_RE = re.compile(
    r"("
    r"(?:\b(?:one|two|three|four|five|six|seven|eight|nine|ten|[1-9]|10)[-\s]minute[s]?\s+(?:walk|stroll)\b[^.]{0,40}?\bbeach\b)"
    r"|(?:\bwalking\s+distance\b[^.]{0,40}?\bbeach\b)"
    r"|(?:\ba\s+\d+\s+min(?:utos?)?\.?\s+caminando\s+(?:de|del|al|a la)\s+(?:la\s+)?(?:playa|mar)\b)"
    r"|(?:\ba\s+(?:un[oa]s?|dos|tres|[1-3])"
    r"\s+min(?:utos?)?\.?\s+(?:de|del|al|a la)\s+(?:la\s+)?(?:playa|mar)\b)"
    r"|(?:\ba\s+pasos\s+(?:de|del)\s+(?:la\s+)?(?:playa|mar)\b)"
    r"|(?:\ba\s+(?:una\s+)?cuadra\s+(?:de|del)\s+(?:la\s+)?(?:playa|mar)\b)"
    r")",
    re.IGNORECASE,
)
_BEACHFRONT_RE = re.compile(
    r"\b(beachfront|ocean[\s-]?front|frente\s+al\s+mar|en\s+(?:la\s+)?playa\s+misma)\b",
    re.IGNORECASE,
)

# Distance threshold above which a coastal-claim listing is suspect.
# 5 km matches the spacing of NAMED_BEACHES — a listing at >5km from any
# named beach is either at an unmapped beach or has a wrong lat/lng.
SUSPECT_DIST_KM = 5.0

# Cluster grid resolution — 0.1° ≈ 11 km. Listings rounded to the same
# grid cell get aggregated into one "potential unmapped zone" alert.
CLUSTER_GRID = 0.1


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _localized_text(value: Any) -> str:
    """Bilingual {en, es} dict OR list of those — flatten for keyword search."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " | ".join(str(v) for v in value.values() if v)
    if isinstance(value, list):
        return " | ".join(_localized_text(v) for v in value)
    return ""


def _has_coastal_claim(li: Any) -> bool:
    text = " ".join(filter(None, [
        _g(li, "description") or "",
        _g(li, "title") or "",
        _localized_text(_g(li, "title_canonical")),
        _localized_text(_g(li, "short_description_canonical")),
        _localized_text(_g(li, "reasons_to_buy")),
    ]))
    if not text:
        return False
    return bool(_WALK_TO_BEACH_RE.search(text) or _BEACHFRONT_RE.search(text))


def detect_unmapped_beach_clusters(
    listings: Iterable[Any],
    *,
    history_path: Path | None = None,
    threshold_km: float = SUSPECT_DIST_KM,
) -> dict[str, Any]:
    """Identify listings that look like they're at an unmapped beach.

    Returns a metrics dict with:
      suspect_count:       int  — total listings flagged
      cluster_count:       int  — distinct (lat_grid, lng_grid) clusters
      top_clusters:        list — [{lat, lng, count, sample_titles}, ...]

    Also appends one telemetry row to history_path (default
    web/data/unmapped_beaches_history.jsonl).
    """
    suspects: list[dict[str, Any]] = []
    for li in listings:
        dist = _g(li, "dist_beach_km")
        if dist is None or dist <= threshold_km:
            continue
        if not _has_coastal_claim(li):
            continue
        lat = _g(li, "lat")
        lng = _g(li, "lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        suspects.append({
            "source":    _g(li, "source"),
            "source_id": _g(li, "source_id"),
            "title":     (_g(li, "title") or "")[:80],
            "lat":       float(lat),
            "lng":       float(lng),
            "dist_beach_km": float(dist),
            "zone":      _g(li, "zone"),
        })

    # Cluster by 0.1° grid — round AWAY from zero so symmetric grid cells
    # for negative lng don't collapse with positive ones (irrelevant in
    # SV but defensive). Sort clusters by size descending.
    by_cell: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for s in suspects:
        cell = (
            round(s["lat"] / CLUSTER_GRID) * CLUSTER_GRID,
            round(s["lng"] / CLUSTER_GRID) * CLUSTER_GRID,
        )
        by_cell[cell].append(s)

    clusters: list[dict[str, Any]] = sorted(
        (
            {
                "lat":     round(cell[0], 2),
                "lng":     round(cell[1], 2),
                "count":   len(items),
                "median_dist_beach_km": round(
                    sorted(i["dist_beach_km"] for i in items)[len(items) // 2], 2
                ),
                "sample_titles": [i["title"] for i in items[:3]],
                "sample_ids":    [f"{i['source']}/{i['source_id']}" for i in items[:3]],
            }
            for cell, items in by_cell.items()
        ),
        key=lambda c: -int(c["count"]),
    )

    metrics: dict[str, Any] = {
        "suspect_count": len(suspects),
        "cluster_count": len(clusters),
        "top_clusters":  clusters[:10],
    }

    # Telemetry append — append-only pattern, never a hard fail.
    if history_path is None:
        history_path = (Path(__file__).resolve().parents[1]
                        / "web" / "data" / "unmapped_beaches_history.jsonl")
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts":             datetime.now(timezone.utc).isoformat(),
                "threshold_km":   threshold_km,
                "suspect_count":  metrics["suspect_count"],
                "cluster_count":  metrics["cluster_count"],
                "top_clusters":   metrics["top_clusters"],
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass

    return metrics
