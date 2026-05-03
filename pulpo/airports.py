"""
Static lookup of great-circle distance from each canonical zone slug to the
nearest international airport.

El Salvador has effectively one operational international airport: SAL —
Aeropuerto Internacional Monseñor Óscar Arnulfo Romero y Galdámez (Comalapa,
lat 13.4408, lng -89.0556). A planned Pacific airport in eastern El Salvador
would change this; if/when it opens, refactor the table to {zone: {airport:
km}} and have the location leg pick the minimum.

Distances are great-circle (haversine) from approximate zone centroids,
rounded to the nearest km. Recompute via:

    import math
    R = 6371.0
    sal = (13.4408, -89.0556)
    def haversine(a, b):
        dlat, dlng = math.radians(b[0]-a[0]), math.radians(b[1]-a[1])
        h = (math.sin(dlat/2)**2
             + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0]))
             * math.sin(dlng/2)**2)
        return 2 * R * math.asin(math.sqrt(h))

The location leg consumes this via airport_bonus(zone) below; it returns 0
for zones not in the table (graceful neutral fallback).
"""
from __future__ import annotations

# Distances are km from zone centroid to SAL.
ZONE_TO_AIRPORT_KM: dict[str, float] = {
    # Surf City core — within 60 km of SAL
    "el-tunco":            36.0,
    "el-sunzal":           37.0,
    "el-zonte":            43.0,
    "san-diego":           27.0,
    "la-libertad":         29.0,
    "puerto-la-libertad":  29.0,
    # Next-wave west coast
    "mizata":              66.0,
    # Eastern Pacific — Surf City Phase 2 corridor
    "el-cuco":            103.0,
    "las-flores":         100.0,
    "punta-mango":        105.0,
    "el-espino":           65.0,
    "jiquilisco":          61.0,
    # Gulf of Fonseca
    "conchagua":          130.0,
    "la-union":           132.0,
}


def airport_bonus(zone: str | None) -> tuple[int, str]:
    """Return (bonus_points, reason_string) for a zone's airport accessibility.

    Bonus brackets:
        <60 km     → +5  ("near airport")
        60-120 km  →  0  ("medium")
        120-240 km → -5  ("far airport")
        >240 km    → -10 ("very far")

    Returns (0, "") when the zone is missing from the lookup table —
    graceful neutral fallback rather than an error.
    """
    if not zone:
        return 0, ""
    km = ZONE_TO_AIRPORT_KM.get(zone)
    if km is None:
        return 0, ""
    if km < 60:
        return 5, f"airport {km:.0f}km +5"
    if km < 120:
        return 0, f"airport {km:.0f}km"
    if km < 240:
        return -5, f"airport {km:.0f}km -5"
    return -10, f"airport {km:.0f}km -10"
