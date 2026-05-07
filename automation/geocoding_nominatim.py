"""
PR-8.5 — OSM Nominatim geocoding fallback for listings with no lat/lng.

Order of geocoding signals (most → least specific):
  1. Scraper extracted explicit coords from listing text
  2. DeepSeek LLM enrichment estimated from context
  3. **THIS MODULE** — Nominatim lookup of "{zone}, {municipality}, El Salvador"
  4. (Manual coords for top-N listings — not yet wired)

Nominatim usage policy:
  - 1 request/second hard limit
  - Required: descriptive User-Agent header
  - Required: results are CACHED so we don't re-query

We satisfy all three:
  - 1.1s sleep between API calls (above the 1s minimum, with margin)
  - User-Agent: "pulpo.club/0.1 (sebastian@pulpo.club)"
  - Sidecar at web/data/geocoding_nominatim.json keyed by query string
    so identical queries skip the API entirely

Failure modes (each fails the listing's geocode but not the run):
  - HTTP error / network timeout → log and continue
  - Empty response → log and continue
  - Result outside SV bounding box → reject (Nominatim sometimes returns
    a Salvadoran zone in another country; defensive)

The module is pure-functions-plus-file-I/O: no global state, no
network calls when the cache is hit. Used both by the nightly pipeline
and by ad-hoc backfill scripts.

Public API:

    from automation.geocoding_nominatim import (
        geocode_listings, geocode_one, load_cache, save_cache,
    )
    metrics = geocode_listings(listings, sidecar_path)
    # listings now have lat/lng populated where Nominatim returned a hit
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "pulpo.club/0.1 (sebastian@pulpo.club)"
RATE_LIMIT_SLEEP_S = 1.1   # Nominatim's policy is 1 req/sec; 1.1s adds margin

# El Salvador bounding box (same as automation/llm_enrichment_schema.py).
# Reject Nominatim results that fall outside — defensive against
# geocoder picking a same-named place in another country.
SV_BBOX_LAT = (13.0, 14.6)
SV_BBOX_LNG = (-90.6, -87.6)


@dataclass(frozen=True)
class GeocodeResult:
    """Output of a single Nominatim lookup."""
    lat:           float
    lng:           float
    display_name:  str          # e.g. "El Tunco, La Libertad, El Salvador"
    query:         str          # what we asked Nominatim


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


def build_query(li: Any) -> Optional[str]:
    """Compose a Nominatim search query from the listing's location fields.

    Priority: zone → municipality → department. Returns None when there
    isn't enough signal to query (e.g. a listing with only `country=SV`).
    """
    zone = _g(li, "zone")
    municipality = _g(li, "municipality")
    department = _g(li, "department")
    parts: list[str] = []
    # Pretty zone slug ("el-tunco" → "El Tunco") — Nominatim handles this OK
    # without further normalization, but the cleaner the query the better
    # the hit rate.
    if isinstance(zone, str) and zone.strip():
        pretty = zone.replace("-", " ").replace("_", " ").strip()
        parts.append(pretty.title())
    if isinstance(municipality, str) and municipality.strip():
        parts.append(municipality.strip())
    if isinstance(department, str) and department.strip():
        parts.append(department.strip())
    if not parts:
        return None
    parts.append("El Salvador")
    return ", ".join(parts)


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _result_in_sv_bbox(lat: float, lng: float) -> bool:
    return (SV_BBOX_LAT[0] <= lat <= SV_BBOX_LAT[1]
            and SV_BBOX_LNG[0] <= lng <= SV_BBOX_LNG[1])


def _default_http_get(url: str, params: dict, headers: dict, timeout: float):
    """Real httpx.get — separated so tests can pass a stub."""
    import httpx
    return httpx.get(url, params=params, headers=headers, timeout=timeout)


def geocode_one(query: str,
                http_get: Callable | None = None) -> Optional[GeocodeResult]:
    """One Nominatim API call, no rate-limit handling. Caller owns the
    pacing (see geocode_listings) and the cache.

    Returns None on any failure path: HTTP error, empty response,
    out-of-SV result. Each failure is silent here — the caller logs.
    """
    http_get = http_get or _default_http_get
    try:
        r = http_get(
            NOMINATIM_BASE_URL,
            params={
                "q":             query,
                "format":        "json",
                "limit":         1,
                "countrycodes":  "sv",     # restrict to El Salvador
            },
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        results = r.json()
        if not isinstance(results, list) or not results:
            return None
        first = results[0]
        lat_s = first.get("lat")
        lng_s = first.get("lon")
        try:
            lat = float(lat_s)
            lng = float(lng_s)
        except (TypeError, ValueError):
            return None
        if not _result_in_sv_bbox(lat, lng):
            return None
        return GeocodeResult(
            lat          = round(lat, 6),
            lng          = round(lng, 6),
            display_name = str(first.get("display_name") or "").strip(),
            query        = query,
        )
    except Exception:
        return None


def geocode_listings(listings: list,
                     cache_path: Path,
                     http_get: Callable | None = None,
                     sleep_fn: Callable[[float], None] | None = None,
                     ) -> dict:
    """Backfill lat/lng on listings that don't have them.

    Per-listing flow:
      - skip if lat & lng already populated (LLM did the job)
      - build_query(li): zone + municipality + department + "El Salvador"
      - cache hit: write coords, no API call
      - cache miss: rate-limited Nominatim call → cache → write coords

    cache_path: typically web/data/geocoding_nominatim.json. Schema:
        { "<query>": {"lat", "lng", "display_name", "ts"} }

    Returns metrics for the run telemetry log:
        {scanned, skipped_already_geocoded, skipped_no_query,
         cache_hits, api_calls, api_hits, api_misses}
    """
    sleep_fn = sleep_fn or time.sleep
    cache = load_cache(cache_path)
    metrics = {
        "scanned":                  0,
        "skipped_already_geocoded": 0,
        "skipped_no_query":         0,
        "cache_hits":               0,
        "api_calls":                0,
        "api_hits":                 0,
        "api_misses":               0,
    }
    cache_dirty = False
    last_api_call_t: Optional[float] = None

    for li in listings:
        metrics["scanned"] += 1
        lat = _g(li, "lat")
        lng = _g(li, "lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            metrics["skipped_already_geocoded"] += 1
            continue
        query = build_query(li)
        if query is None:
            metrics["skipped_no_query"] += 1
            continue

        # Cache hit
        if query in cache:
            entry = cache[query]
            if (isinstance(entry, dict)
                and isinstance(entry.get("lat"), (int, float))
                and isinstance(entry.get("lng"), (int, float))):
                _set(li, "lat", float(entry["lat"]))
                _set(li, "lng", float(entry["lng"]))
                if _g(li, "geocoding_source") is None:
                    _set(li, "geocoding_source", "nominatim")
                if _g(li, "geocoding_confidence") is None:
                    _set(li, "geocoding_confidence", "medium")
                metrics["cache_hits"] += 1
                continue
            elif entry == "miss":
                # Previously failed lookup — don't retry on the same run
                continue

        # Cache miss → API call
        # Pace: ensure ≥ RATE_LIMIT_SLEEP_S since the last live request
        now = time.monotonic()
        if last_api_call_t is not None:
            elapsed = now - last_api_call_t
            if elapsed < RATE_LIMIT_SLEEP_S:
                sleep_fn(RATE_LIMIT_SLEEP_S - elapsed)
        result = geocode_one(query, http_get=http_get)
        last_api_call_t = time.monotonic()
        metrics["api_calls"] += 1
        if result is not None:
            cache[query] = {
                "lat":          result.lat,
                "lng":          result.lng,
                "display_name": result.display_name,
                "ts":           datetime.now(timezone.utc).isoformat(),
            }
            cache_dirty = True
            _set(li, "lat", result.lat)
            _set(li, "lng", result.lng)
            if _g(li, "geocoding_source") is None:
                _set(li, "geocoding_source", "nominatim")
            if _g(li, "geocoding_confidence") is None:
                _set(li, "geocoding_confidence", "medium")
            metrics["api_hits"] += 1
        else:
            cache[query] = "miss"
            cache_dirty = True
            metrics["api_misses"] += 1

    if cache_dirty:
        save_cache(cache_path, cache)
    return metrics
