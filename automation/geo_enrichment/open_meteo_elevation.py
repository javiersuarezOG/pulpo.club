"""GEO-1 provider — Open-Meteo elevation (Copernicus DEM GLO-90).

Elevation is the cheapest genuinely useful fact we can attach: it
separates a highland coffee plot from a coastal lot, and it is the input
a buyer needs before asking about flooding or sea level.

This is the one provider that batches — the endpoint accepts up to 100
coordinate pairs per request (verified live: 105 returns HTTP 400
"must not exceed 100 coordinates"). So several hundred cells cost a
handful of calls, and the orchestrator prefers ``fetch_batch`` when a
provider exposes it.

A 90m DEM under a coordinate that is itself accurate to a few km is
already more precision than our input deserves, so the cell is 0.01°
(~1.1km) purely to keep the call count sane.

Note ocean returns ``0.0``, not null — so zero is a legitimate value
(coastal lots really are near sea level) and only a non-numeric response
counts as "no data".
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ._http import headers

PROVIDER = "open_meteo_elevation"
VERSION = 1
CATEGORY = "elevation"
TTL_CLASS = "static"
REFRESH_DAYS = 0

CELL_STEP_DEG = 0.01
CELL_DECIMALS = 2

MIN_INTERVAL_S = 0.5
TIMEOUT_S = 20.0

BASE_URL = "https://api.open-meteo.com/v1/elevation"

# Hard API limit, not a tuning knob.
BATCH_SIZE = 100


def _parse(value: Any) -> Optional[dict]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return {"elevation_m": round(float(value))}


def fetch_batch(cells: list[tuple[float, float]], *,
                http_get: Callable,
                timeout_s: float = TIMEOUT_S) -> list[Optional[dict]]:
    """Resolve up to ``BATCH_SIZE`` coordinates in one request.

    Returns one result per input cell, positionally aligned. A short or
    malformed ``elevation`` array yields ``None`` for the missing tail
    rather than silently shifting values onto the wrong cells.
    """
    if not cells:
        return []
    if len(cells) > BATCH_SIZE:
        raise ValueError(f"batch of {len(cells)} exceeds API limit {BATCH_SIZE}")

    resp = http_get(
        BASE_URL,
        {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in cells),
            "longitude": ",".join(f"{lng:.4f}" for _, lng in cells),
        },
        headers(),
        timeout_s,
    )
    data = resp.json()
    values = (data or {}).get("elevation")
    if not isinstance(values, list):
        return [None] * len(cells)
    return [
        _parse(values[i]) if i < len(values) else None
        for i in range(len(cells))
    ]


def fetch(lat: float, lng: float, *,
          http_get: Callable,
          http_post: Optional[Callable] = None,
          timeout_s: float = TIMEOUT_S) -> Optional[dict]:
    """Single-cell path — kept so every provider honors the same contract."""
    return fetch_batch([(lat, lng)], http_get=http_get, timeout_s=timeout_s)[0]
