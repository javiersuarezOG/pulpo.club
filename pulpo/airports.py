"""
Static lookup of great-circle distance from each canonical zone slug to
each airport that affects the El Salvador beach-land market.

Currently tracks two airports:

  SAL — Monseñor Óscar Arnulfo Romero y Galdámez (Comalapa). Operational.
        Lat 13.4408, lng -89.0556. The current main hub for tourists and
        property buyers; serves the central-Pacific Surf City corridor.

  AeP — Aeropuerto del Pacífico. Planned, eastern coast, near La Unión /
        Conchagua. Lat 13.1970, lng -87.9473. Not yet operational, but
        already affecting land valuations on the eastern coast — the
        anticipation effect is real and visible in repricing activity.
        Officially announced; construction underway (2026).

The location leg picks the MINIMUM distance across airports per zone, so
the eastern coast (Conchagua, La Unión, El Cuco, Punta Mango, Las Flores)
inherits the +5 "near airport" bonus once AeP is plotted, even though SAL
is 100+ km away. This is a deliberate forward-looking bet: an investor
buying eastern coast land today is paying for accessibility that will
materialize when AeP opens. The Surf City core (Tunco, Sunzal, Zonte) is
still nearer to SAL and stays at +5 either way.

Distances are great-circle (haversine) from approximate zone centroids
to each airport, rounded to the nearest km. Recompute via:

    import math
    R = 6371.0
    def haversine(a, b):
        dlat, dlng = math.radians(b[0]-a[0]), math.radians(b[1]-a[1])
        h = (math.sin(dlat/2)**2
             + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0]))
             * math.sin(dlng/2)**2)
        return 2 * R * math.asin(math.sqrt(h))

The location leg consumes this via airport_bonus(zone) below; it returns
0 for zones not in the table (graceful neutral fallback).
"""
from __future__ import annotations

# Distances per zone to each airport, in km.
ZONE_AIRPORT_DISTANCES_KM: dict[str, dict[str, float]] = {
    # Surf City core — within 60 km of SAL, far from AeP
    "el-tunco":            {"SAL":  36.0, "AeP": 159.0},
    "el-sunzal":           {"SAL":  37.0, "AeP": 160.0},
    "el-zonte":            {"SAL":  43.0, "AeP": 165.0},
    "san-diego":           {"SAL":  27.0, "AeP": 150.0},
    "la-libertad":         {"SAL":  29.0, "AeP": 152.0},
    "puerto-la-libertad":  {"SAL":  29.0, "AeP": 152.0},
    # Next-wave west coast
    "mizata":              {"SAL":  66.0, "AeP": 189.0},
    # Eastern Pacific — Surf City Phase 2 corridor; AeP transforms these
    "el-cuco":             {"SAL": 103.0, "AeP":  21.0},
    "las-flores":          {"SAL": 100.0, "AeP":  27.0},
    "punta-mango":         {"SAL": 105.0, "AeP":  23.0},
    "el-espino":           {"SAL":  65.0, "AeP":  62.0},
    "jiquilisco":          {"SAL":  61.0, "AeP":  62.0},
    # Gulf of Fonseca — closest to AeP, far from SAL
    "conchagua":           {"SAL": 130.0, "AeP":  15.0},
    "la-union":            {"SAL": 132.0, "AeP":  19.0},
}

# Backward-compat shim: the old single-airport table. Some downstream
# consumers (tests, audit scripts, prior commits in flight) may still
# import ZONE_TO_AIRPORT_KM. It exposes the SAL-only distances unchanged
# from before the AeP addition. Drop this in a follow-up cleanup once
# nothing references it.
ZONE_TO_AIRPORT_KM: dict[str, float] = {
    zone: dists["SAL"] for zone, dists in ZONE_AIRPORT_DISTANCES_KM.items()
}


def _nearest_airport(zone: str) -> tuple[str, float] | None:
    """Return (airport_code, km) for the closest airport to `zone`, or None
    when the zone isn't in the lookup table."""
    distances = ZONE_AIRPORT_DISTANCES_KM.get(zone)
    if not distances:
        return None
    code, km = min(distances.items(), key=lambda x: x[1])
    return code, km


def airport_bonus(zone: str | None) -> tuple[int, str]:
    """Return (bonus_points, reason_string) for a zone's airport accessibility.

    Picks the NEAREST airport (across SAL and AeP) and applies the bonus
    based on great-circle distance to that one. The eastern coast's AeP
    proximity flips its bonus from "far" to "near" even though SAL is still
    100+ km away.

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
    nearest = _nearest_airport(zone)
    if nearest is None:
        return 0, ""
    code, km = nearest
    if km < 60:
        return 5, f"airport {km:.0f}km +5 ({code})"
    if km < 120:
        return 0, f"airport {km:.0f}km ({code})"
    if km < 240:
        return -5, f"airport {km:.0f}km -5 ({code})"
    return -10, f"airport {km:.0f}km -10 ({code})"
