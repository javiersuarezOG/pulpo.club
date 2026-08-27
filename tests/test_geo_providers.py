"""
Tests for the GEO-1 provider modules — payload extraction, unit
conversion, and the not-available-here semantics.

Every response body here mirrors a real one captured live on 2026-08-27.
No network: each test injects a stub `http_get`.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.geo_enrichment import nasa_power, open_meteo_elevation  # noqa: E402
from automation.geo_enrichment._http import HttpError, with_retry       # noqa: E402


class _StubResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        return self._payload


class _StubGet:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, params, headers, timeout_s):
        self.calls.append({"url": url, "params": params, "headers": headers,
                           "timeout_s": timeout_s})
        r = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(r, Exception):
            raise r
        return r


# ── NASA POWER ────────────────────────────────────────────────────────

def _power_block(ann, monthly=None):
    months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    block = {m: (monthly if monthly is not None else ann) for m in months}
    block["ANN"] = ann
    return block


def _power_payload(**overrides):
    params = {
        "ALLSKY_SFC_SW_DWN": _power_block(5.89),
        "ALLSKY_SFC_SW_DNI": _power_block(5.35),
        "T2M": _power_block(27.3),
        "T2M_MAX": _power_block(39.3),
        "T2M_MIN": _power_block(15.5),
        "PRECTOTCORR": _power_block(4.08),
        "RH2M": _power_block(70.4),
        "WS2M": _power_block(1.9),
    }
    params.update(overrides)
    return {"properties": {"parameter": params},
            "header": {"fill_value": -999.0}}


def test_nasa_power_extracts_annual_scalars():
    get = _StubGet(_StubResponse(_power_payload()))
    out = nasa_power.fetch(13.5, -89.5, http_get=get)
    assert out["ghi_kwh_m2_day"] == 5.89
    assert out["dni_kwh_m2_day"] == 5.35
    assert out["temp_mean_c"] == 27.3
    assert out["humidity_pct"] == 70.4
    assert out["wind_ms"] == 1.9
    assert out["period"] == "2001-2020"


def test_nasa_power_converts_precip_to_mm_per_year():
    get = _StubGet(_StubResponse(_power_payload()))
    out = nasa_power.fetch(13.5, -89.5, http_get=get)
    assert out["precip_mm_yr"] == round(4.08 * 365.25)   # 1490


def test_nasa_power_keeps_monthly_series_for_ghi_and_precip_only():
    get = _StubGet(_StubResponse(_power_payload()))
    out = nasa_power.fetch(13.5, -89.5, http_get=get)
    assert len(out["ghi_monthly"]) == 12
    assert len(out["precip_monthly_mm_day"]) == 12
    assert "temp_monthly" not in out


def test_nasa_power_treats_fill_value_as_absent():
    """-999 is POWER's 'no data', not a temperature."""
    get = _StubGet(_StubResponse(_power_payload(T2M=_power_block(-999.0))))
    out = nasa_power.fetch(13.5, -89.5, http_get=get)
    assert "temp_mean_c" not in out
    assert out["ghi_kwh_m2_day"] == 5.89   # siblings unaffected


def test_nasa_power_drops_partial_monthly_series():
    """A partial year would misread as seasonality — all or nothing."""
    block = _power_block(5.89)
    block["JUL"] = -999.0
    get = _StubGet(_StubResponse(_power_payload(ALLSKY_SFC_SW_DWN=block)))
    out = nasa_power.fetch(13.5, -89.5, http_get=get)
    assert "ghi_monthly" not in out
    assert out["ghi_kwh_m2_day"] == 5.89


def test_nasa_power_returns_none_when_no_values_survive():
    empty = {k: _power_block(-999.0) for k in
             ("ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_SW_DNI", "T2M", "T2M_MAX",
              "T2M_MIN", "PRECTOTCORR", "RH2M", "WS2M")}
    get = _StubGet(_StubResponse(_power_payload(**empty)))
    assert nasa_power.fetch(13.5, -89.5, http_get=get) is None


def test_nasa_power_returns_none_on_empty_parameter_block():
    get = _StubGet(_StubResponse({"properties": {"parameter": {}}}))
    assert nasa_power.fetch(13.5, -89.5, http_get=get) is None


def test_nasa_power_requests_renewable_energy_community():
    """community=RE is what puts irradiance in kWh/m2/day rather than MJ."""
    get = _StubGet(_StubResponse(_power_payload()))
    nasa_power.fetch(13.5, -89.5, http_get=get)
    assert get.calls[0]["params"]["community"] == "RE"
    assert get.calls[0]["headers"]["User-Agent"].startswith("pulpo.club/")


# ── Open-Meteo elevation ──────────────────────────────────────────────

def test_elevation_batch_aligns_results_to_inputs():
    get = _StubGet(_StubResponse({"elevation": [651.0, 0.0, 1204.0]}))
    cells = [(13.70, -89.19), (13.49, -89.38), (14.05, -89.71)]
    out = open_meteo_elevation.fetch_batch(cells, http_get=get)
    assert out == [{"elevation_m": 651}, {"elevation_m": 0}, {"elevation_m": 1204}]
    assert len(get.calls) == 1


def test_elevation_zero_is_a_real_value_not_missing():
    """Ocean and sea-level coast both return 0.0 — coastal lots are real."""
    get = _StubGet(_StubResponse({"elevation": [0.0]}))
    assert open_meteo_elevation.fetch(13.49, -89.38, http_get=get) == {"elevation_m": 0}


def test_elevation_short_response_yields_none_not_shifted_values():
    """A truncated array must not slide values onto the wrong cells."""
    get = _StubGet(_StubResponse({"elevation": [651.0]}))
    out = open_meteo_elevation.fetch_batch(
        [(13.70, -89.19), (13.49, -89.38)], http_get=get)
    assert out == [{"elevation_m": 651}, None]


def test_elevation_malformed_response_yields_all_none():
    get = _StubGet(_StubResponse({"error": True, "reason": "nope"}))
    assert open_meteo_elevation.fetch_batch([(1.0, 1.0)], http_get=get) == [None]


def test_elevation_refuses_oversized_batch():
    """The API caps at 100; failing loudly beats a silent 400."""
    cells = [(13.5, -89.5)] * 101
    with pytest.raises(ValueError, match="exceeds API limit"):
        open_meteo_elevation.fetch_batch(cells, http_get=_StubGet(_StubResponse({})))


def test_elevation_empty_batch_makes_no_call():
    get = _StubGet(_StubResponse({}))
    assert open_meteo_elevation.fetch_batch([], http_get=get) == []
    assert get.calls == []


# ── retry seam ────────────────────────────────────────────────────────

def test_with_retry_retries_500_then_succeeds():
    get = _StubGet(_StubResponse({}, status_code=500),
                   _StubResponse({"elevation": [7.0]}))
    slept = []
    wrapped = with_retry(get, sleep_fn=slept.append)
    out = open_meteo_elevation.fetch(1.0, 1.0, http_get=wrapped)
    assert out == {"elevation_m": 7}
    assert len(slept) == 1


def test_with_retry_honors_retry_after():
    get = _StubGet(_StubResponse({}, status_code=429, headers={"Retry-After": "12"}),
                   _StubResponse({"elevation": [7.0]}))
    slept = []
    with_retry(get, sleep_fn=slept.append)("u", {}, {}, 1.0)
    assert slept == [12.0]


def test_with_retry_does_not_retry_404():
    get = _StubGet(_StubResponse({}, status_code=404))
    slept = []
    with pytest.raises(HttpError) as exc:
        with_retry(get, sleep_fn=slept.append)("u", {}, {}, 1.0)
    assert exc.value.status_code == 404
    assert slept == []
    assert len(get.calls) == 1


def test_with_retry_reraises_transport_exception_after_budget():
    get = _StubGet(RuntimeError("connection reset"))
    with pytest.raises(RuntimeError, match="connection reset"):
        with_retry(get, sleep_fn=lambda _s: None)("u", {}, {}, 1.0)
    assert len(get.calls) == 3   # policy retry_max
