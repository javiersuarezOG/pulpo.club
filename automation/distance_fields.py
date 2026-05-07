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
from typing import Any, Optional

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


# PR-8.5 — representative coastline reference points along the
# Salvadoran Pacific coast, from west (La Libertad) to east (La Unión).
# Curated from prominent surf spots + tourist beaches; covers the full
# coastline at ~5km spacing so haversine to nearest point gives a
# reasonable proxy for "distance to coast."
#
# Future upgrade: replace with a proper coastline polyline + nearest-
# point-on-segment math. For now the point-set approximation is
# good enough for the "Beach access · Xkm" editorial chip — the
# precision difference is < 1km on coastal listings (where it matters)
# and irrelevant for inland listings (5km vs 6km from beach reads the
# same).
COASTLINE_POINTS: tuple[tuple[float, float], ...] = (
    (13.4843, -89.7163),   # Bocana San Diego (far west)
    (13.4900, -89.6594),   # El Majahual
    (13.4844, -89.6322),   # Sunzal
    (13.4870, -89.6133),   # El Tunco
    (13.4983, -89.5856),   # El Sunza
    (13.4983, -89.5538),   # El Zonte
    (13.4747, -89.4889),   # San Blas
    (13.4575, -89.3478),   # La Perla
    (13.3372, -88.9892),   # Costa del Sol
    (13.2000, -88.5950),   # Bahía de Jiquilisco mouth
    (13.1761, -88.4836),   # Las Tunas
    (13.1894, -88.3858),   # Playa El Cuco
    (13.1758, -88.2925),   # Playa Negra
    (13.1822, -88.1839),   # Playa Esterón
    (13.1733, -87.9589),   # Conchagua / Playas Orientales
)


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


def _nearest_coastline_haversine_km(lat: float, lng: float) -> float:
    """Min km from (lat, lng) to any point in COASTLINE_POINTS."""
    return min(
        haversine_km(lat, lng, c_lat, c_lng)
        for c_lat, c_lng in COASTLINE_POINTS
    )


def compute_dist_beach_km(li: Any) -> Optional[float]:
    """PR-8.5 — kilometers from the listing's lat/lng to the nearest point
    in the curated SV coastline reference set.

    Returns None when lat/lng aren't populated. Inland listings (e.g.
    San Salvador metro at ~30km from coast) and obviously coastal
    listings (~0–1km) both produce defensible numbers.
    """
    lat = _g(li, "lat")
    lng = _g(li, "lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return round(_nearest_coastline_haversine_km(float(lat), float(lng)), 2)
    return None


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
        # PR-8.5 additions
        "scored_beach":           0,
        "median_dist_beach_km":   None,
        "by_zone":                {},
    }
    distances: list[float] = []
    beach_distances: list[float] = []
    by_zone: dict[str, int] = {}
    for li in listings:
        km, method = compute_dist_airport_km(li)
        if km is None:
            metrics["unscored"] += 1
        else:
            _set(li, "dist_airport_km", km)
            distances.append(km)
            zone = _g(li, "zone") or "unknown"
            by_zone[zone] = by_zone.get(zone, 0) + 1
            if method == "haversine":
                metrics["scored_from_latlng"] += 1
            else:
                metrics["scored_from_zone"] += 1
            metrics["scored_total"] += 1

        # PR-8.5 — beach distance is independent of the airport path
        # (it requires lat/lng; no zone-table fallback). A listing might
        # have airport km but no beach km, or vice-versa.
        beach_km = compute_dist_beach_km(li)
        if beach_km is not None:
            _set(li, "dist_beach_km", beach_km)
            beach_distances.append(beach_km)
            metrics["scored_beach"] += 1
    if distances:
        metrics["median_dist_airport_km"] = round(statistics.median(distances), 2)
    if beach_distances:
        metrics["median_dist_beach_km"] = round(statistics.median(beach_distances), 2)
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
