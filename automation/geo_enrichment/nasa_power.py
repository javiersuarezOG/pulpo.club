"""GEO-1 provider — NASA POWER: solar irradiance + climate normals.

Answers "how much sun does this land get?" and "what is the weather
actually like here?" — the two questions a buyer asks that no broker
listing contains.

We call the *climatology* endpoint, not the daily one: it returns 20-year
monthly and annual means (2001-2020) in a single response. That makes the
payload permanently static — a climate normal does not change between
nightlies — so a cell is fetched once, ever, until VERSION is bumped.

Grid: POWER's native resolution is 0.5° x 0.625°, so a finer cell would
be fetching the same underlying pixel repeatedly. 0.5° collapses a whole
country to a couple of dozen cells.

Response shape (verified live 2026-08-27):
    properties.parameter.<PARAM> = {"JAN": 5.76, ..., "ANN": 5.89}
    header.fill_value = -999.0     # missing data sentinel

KNOWN BIAS — read before rendering precipitation to a user
----------------------------------------------------------
These are 0.5-degree reanalysis cells, and reanalysis smooths orographic
rainfall. Measured against the real catalog on 2026-08-27, POWER returns
1191-1585 mm/yr across El Salvador where station records for the same
areas run roughly 1700-1800 mm/yr — systematically ~20-25% low, because
a half-degree cell averages away the mountain that makes it rain.

So `precip_mm_yr` is sound for COMPARING two locations (the relative
ordering tracks reality) and unsound as an absolute figure. Whatever
renders this must not present it as a measured local rainfall total.
Irradiance and temperature do not have this problem — they vary smoothly
enough that a half-degree cell represents them well.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ._http import headers

PROVIDER = "nasa_power"
VERSION = 1
CATEGORY = "solar_climate"
TTL_CLASS = "static"
REFRESH_DAYS = 0

CELL_STEP_DEG = 0.5
CELL_DECIMALS = 1

# POWER is slow — a climatology point regularly takes several seconds.
MIN_INTERVAL_S = 1.0
TIMEOUT_S = 30.0

BASE_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"

# community=RE (Renewable Energy) is what puts irradiance in kWh/m²/day
# rather than the raw MJ the AG community returns.
_COMMUNITY = "RE"

_PARAMS = (
    "ALLSKY_SFC_SW_DWN",   # GHI, kWh/m²/day
    "ALLSKY_SFC_SW_DNI",   # DNI, kWh/m²/day
    "T2M",                 # mean temp, °C
    "T2M_MAX",
    "T2M_MIN",
    "PRECTOTCORR",         # precipitation, mm/day
    "RH2M",                # relative humidity, %
    "WS2M",                # wind speed at 2m, m/s
)

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

_FILL = -999.0
_DAYS_PER_YEAR = 365.25


def _num(value: Any) -> Optional[float]:
    """Coerce to float, treating POWER's -999 sentinel as absent."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    v = float(value)
    if v <= _FILL + 1.0:
        return None
    return v


def _months(block: dict) -> Optional[list]:
    """The 12 monthly values, or None if any is missing.

    Partial-year data would silently misread as seasonality, so it is all
    or nothing.
    """
    out = []
    for m in _MONTHS:
        v = _num(block.get(m))
        if v is None:
            return None
        out.append(round(v, 2))
    return out


def fetch(lat: float, lng: float, *,
          http_get: Callable,
          http_post: Optional[Callable] = None,
          timeout_s: float = TIMEOUT_S) -> Optional[dict]:
    resp = http_get(
        BASE_URL,
        {
            "parameters": ",".join(_PARAMS),
            "community": _COMMUNITY,
            "latitude": f"{lat:.4f}",
            "longitude": f"{lng:.4f}",
            "format": "JSON",
        },
        headers(),
        timeout_s,
    )
    data = resp.json()
    params = ((data or {}).get("properties") or {}).get("parameter") or {}
    if not isinstance(params, dict) or not params:
        return None

    def ann(name: str) -> Optional[float]:
        block = params.get(name)
        return _num(block.get("ANN")) if isinstance(block, dict) else None

    ghi = ann("ALLSKY_SFC_SW_DWN")
    dni = ann("ALLSKY_SFC_SW_DNI")
    temp = ann("T2M")
    precip_day = ann("PRECTOTCORR")

    out: dict[str, Any] = {}
    if ghi is not None:
        out["ghi_kwh_m2_day"] = round(ghi, 2)
    if dni is not None:
        out["dni_kwh_m2_day"] = round(dni, 2)
    if temp is not None:
        out["temp_mean_c"] = round(temp, 1)
    for key, name in (("temp_max_c", "T2M_MAX"), ("temp_min_c", "T2M_MIN")):
        v = ann(name)
        if v is not None:
            out[key] = round(v, 1)
    if precip_day is not None:
        out["precip_mm_yr"] = round(precip_day * _DAYS_PER_YEAR)
    for key, name in (("humidity_pct", "RH2M"), ("wind_ms", "WS2M")):
        v = ann(name)
        if v is not None:
            out[key] = round(v, 1)

    # Seasonality for the two series a buyer reasons about — a dry-season
    # solar peak and a wet-season rainfall spike. Storing 12 floats twice
    # keeps the payload ~200 bytes; the other six series would not earn it.
    ghi_months = _months(params.get("ALLSKY_SFC_SW_DWN") or {})
    if ghi_months:
        out["ghi_monthly"] = ghi_months
    precip_months = _months(params.get("PRECTOTCORR") or {})
    if precip_months:
        out["precip_monthly_mm_day"] = precip_months

    out["period"] = "2001-2020"
    # Only "period" means we parsed a response but recovered no real values.
    return out if len(out) > 1 else None
