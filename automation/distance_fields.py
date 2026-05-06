"""
PRD §FR-5.5 — distance fields per listing + per-run telemetry.

Populates `dist_airport_km` (and, once lat/lng broadly populate via the
LLM single-call, dist_beach_km / dist_highway_km / dist_nearest_town_km).

Telemetry: appends one row per nightly run to
`web/data/distance_fields_history.jsonl`:
    {ts, scored_total, scored_from_latlng, scored_from_zone,
     unscored, median_dist_airport_km, by_zone: {zone: count}}
Same append-only sidecar pattern as source_health_history.jsonl.

Two compute paths:

  1. **Haversine from lat/lng** (preferred). When the listing has both
     lat and lng set, compute great-circle distance to each airport in
     ZONE_AIRPORT_DISTANCES_KM's source list, return the minimum.

  2. **Zone-table fallback** (always available). When lat/lng are None,
     reuse the per-zone distance table in pulpo/airports.py — that's a
     hand-curated lookup mapping each canonical zone slug to nearest
     SAL/AeP airport distance.

Phase 3 will add dist_beach_km / dist_highway_km / dist_nearest_town_km
once SV-wide reference geometry lands. For now those stay None on every
listing — separate follow-up PR will compute them via haversine against
coastline polylines + highway shapefiles + populated-place coordinates.

Public API:

    from automation.distance_fields import apply_distances
    metrics = apply_distances(listings)
    # Each listing now has dist_airport_km populated when computable.
"""
from __future__ import annotations
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pulpo.airports import (   # type: ignore
    ZONE_AIRPORT_DISTANCES_KM,
    _nearest_airport,
)


# Earth radius in km — for haversine.
EARTH_RADIUS_KM = 6371.0


# Source-of-truth airport coordinates from pulpo/airports.py docstring.
# When lat/lng are present, we haversine to these.
AIRPORTS_LAT_LNG: dict[str, tuple[float, float]] = {
    "SAL": (13.4408, -89.0556),  # Monseñor Romero (Comalapa) — main hub
    "AeP": (13.1970, -87.9473),  # Aeropuerto del Pacífico — eastern coast (planned)
}


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two (lat, lng) pairs."""
    a_lat, a_lng = math.radians(lat1), math.radians(lng1)
    b_lat, b_lng = math.radians(lat2), math.radians(lng2)
    dlat = b_lat - a_lat
    dlng = b_lng - a_lng
    h = (math.sin(dlat / 2) ** 2
         + math.cos(a_lat) * math.cos(b_lat) * math.sin(dlng / 2) ** 2)
    # Clamp to handle floating-point edge cases when h is just above 1.0
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, h)))


def _nearest_airport_haversine_km(lat: float, lng: float) -> float:
    """Min km from (lat, lng) to any airport in AIRPORTS_LAT_LNG."""
    return min(
        haversine_km(lat, lng, ap_lat, ap_lng)
        for ap_lat, ap_lng in AIRPORTS_LAT_LNG.values()
    )


def compute_dist_airport_km(li: Any) -> tuple[float | None, str]:
    """Return (km, method) where method ∈ {'haversine', 'zone_table', None}.

    Preferred path: haversine from lat/lng. Fallback: zone-table lookup.
    Returns (None, 'no_zone_no_latlng') when neither is available.
    """
    lat = _g(li, "lat")
    lng = _g(li, "lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return round(_nearest_airport_haversine_km(float(lat), float(lng)), 2), "haversine"

    zone = _g(li, "zone")
    if isinstance(zone, str) and zone in ZONE_AIRPORT_DISTANCES_KM:
        result = _nearest_airport(zone)
        if result is not None:
            _, km = result
            return round(float(km), 2), "zone_table"

    return None, "no_zone_no_latlng"


def apply_distances(listings: list[Any],
                    history_path: Path | None = None) -> dict[str, Any]:
    """Set dist_airport_km on every listing where computable + append run-row
    to history_path (default web/data/distance_fields_history.jsonl).

    Other distance fields (dist_beach_km, dist_highway_km,
    dist_nearest_town_km) stay None — they need geometric SV reference
    data shipping in a follow-up PR once the LLM single-call broadly
    populates lat/lng.

    Returns metrics:
      {
        scored_from_latlng:    int,
        scored_from_zone:      int,
        unscored:              int,
        scored_total:          int,
        median_dist_airport_km: float | None,
        by_zone:               {zone: count},   # which zones contributed
      }
    """
    metrics: dict[str, Any] = {
        "scored_from_latlng":     0,
        "scored_from_zone":       0,
        "unscored":               0,
        "scored_total":           0,
        "median_dist_airport_km": None,
        "by_zone":                {},
    }
    distances: list[float] = []
    by_zone: dict[str, int] = {}
    for li in listings:
        km, method = compute_dist_airport_km(li)
        if km is None:
            metrics["unscored"] += 1
            continue
        _set(li, "dist_airport_km", km)
        distances.append(km)
        zone = _g(li, "zone") or "unknown"
        by_zone[zone] = by_zone.get(zone, 0) + 1
        if method == "haversine":
            metrics["scored_from_latlng"] += 1
        else:
            metrics["scored_from_zone"] += 1
        metrics["scored_total"] += 1
    if distances:
        metrics["median_dist_airport_km"] = round(statistics.median(distances), 2)
    metrics["by_zone"] = dict(sorted(by_zone.items(), key=lambda x: -x[1]))

    # Telemetry sidecar — one row per nightly run. Same append-only pattern
    # as web/data/source_health_history.jsonl.
    if history_path is None:
        history_path = (Path(__file__).resolve().parents[1]
                        / "web" / "data" / "distance_fields_history.jsonl")
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts":                      datetime.now(timezone.utc).isoformat(),
                "scored_total":            metrics["scored_total"],
                "scored_from_latlng":      metrics["scored_from_latlng"],
                "scored_from_zone":        metrics["scored_from_zone"],
                "unscored":                metrics["unscored"],
                "median_dist_airport_km":  metrics["median_dist_airport_km"],
                "by_zone":                 metrics["by_zone"],
            }, ensure_ascii=False) + "\n")
    except OSError:
        # Telemetry write failure should not break the pipeline. Log and continue.
        pass

    return metrics
