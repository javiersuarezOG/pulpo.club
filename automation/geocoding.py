"""
PRD §FR-5 — geocoding pipeline scaffold.

Populates `lat` / `lng` / `geocoding_confidence` on listings via the PRD's
two-tier extraction priority:

  1. HTML extraction (free) — embedded Google Maps URLs, og:latitude /
     og:longitude meta tags, Schema.org GeoCoordinates JSON-LD. Covered
     by automation/geocoding_probe.py for ad-hoc auditing; production
     extraction happens scraper-side once each scraper is upgraded to
     surface lat/lng on the raw record (Phase 2 dependency).

  2. Mapbox Geocoding API (paid, free tier covers 100k req/mo) — fallback
     for listings without scraper-extracted coords.

This module ships the Mapbox path. HTML extraction stays in the probe
until each scraper is migrated.

Graceful degradation:
- MAPBOX_TOKEN missing → skip everything, metrics["skipped_no_token"]=True
- httpx ImportError → skip, metrics["skipped_no_httpx"]=True
- Per-listing error → log, count, continue
- Mapbox returns no result OR coords outside SV bbox → leave listing
  unset rather than risk wrong-country geocoding

Cache shape (web/data/geocoding_cache.json):
    {
      "<source>|<source_id>": {
        "address_md5": "abc123...",
        "lat": 13.501,
        "lng": -89.012,
        "geocoding_confidence": "high|medium|low",
        "source_method": "mapbox|html_og_meta|html_jsonld",
        "ts": "2026-05-06T..."
      }
    }

Public API:

    from automation.geocoding import geocode_listings
    metrics = geocode_listings(listings, cache_path)
    # listings now have li.lat / li.lng / li.geocoding_confidence set
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# El Salvador bounding box — Mapbox results outside this are rejected.
# Same constants as automation/geocoding_probe.py.
SV_BBOX_LAT = (13.0, 14.6)
SV_BBOX_LNG = (-90.6, -87.6)

# Mapbox confidence mapping per PRD §FR-5.4
# Mapbox returns a `relevance` score ∈ [0, 1]; we bucket into high/low.
MAPBOX_HIGH_RELEVANCE_THRESHOLD = 0.8

# Per-call timeout — Mapbox SLO is sub-200ms; allow generous buffer.
MAPBOX_TIMEOUT_S = 8.0

# Polite default delay between Mapbox calls. PRD §10 caps spend at the
# 100k/mo free tier; even at 1 call/listing × 800 listings × daily = 24k/mo,
# we're well under. No real rate limit at this volume but keep a tiny pause.
MAPBOX_DELAY_S = 0.1

# Endpoint
MAPBOX_GEOCODE_URL = (
    "https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"
    "?access_token={token}&country=SV&limit=1"
)


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


def _has_coords(li: Any) -> bool:
    """Listing already has lat AND lng? Skip geocoding."""
    return _g(li, "lat") is not None and _g(li, "lng") is not None


def _build_address(li: Any) -> str | None:
    """Best address string for Mapbox.

    Priority:
      1. location_text (raw broker-supplied address)
      2. zone + department + 'El Salvador' (canonical)
      3. department + 'El Salvador' (coarse)
      4. None — can't geocode
    """
    loc = _g(li, "location_text")
    if isinstance(loc, str) and loc.strip():
        return loc.strip()[:200]

    zone = _g(li, "zone")
    department = _g(li, "department")
    parts = [p for p in (zone, department, "El Salvador") if isinstance(p, str) and p.strip()]
    if len(parts) >= 2:
        return ", ".join(parts).replace("-", " ")

    return None


def _address_md5(addr: str) -> str:
    return hashlib.md5(addr.encode("utf-8")).hexdigest()


def _looks_like_sv(lat: float, lng: float) -> bool:
    return SV_BBOX_LAT[0] <= lat <= SV_BBOX_LAT[1] and SV_BBOX_LNG[0] <= lng <= SV_BBOX_LNG[1]


def _mapbox_relevance_to_confidence(relevance: float) -> str:
    """PRD §FR-5.4 — high (>0.8) / low (≤0.8). 'medium' reserved for
    HTML-extracted coords with partial structure."""
    if relevance > MAPBOX_HIGH_RELEVANCE_THRESHOLD:
        return "high"
    return "low"


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")


def _call_mapbox(address: str, token: str, http_client) -> dict | None:
    """Returns {lat, lng, relevance} or None on failure."""
    from urllib.parse import quote
    url = MAPBOX_GEOCODE_URL.format(query=quote(address), token=token)
    try:
        r = http_client.get(url, timeout=MAPBOX_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None

    features = data.get("features") or []
    if not features:
        return None
    feat = features[0]
    coords = feat.get("center") or []
    if len(coords) < 2:
        return None
    lng, lat = float(coords[0]), float(coords[1])
    if not _looks_like_sv(lat, lng):
        return None
    return {
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "relevance": float(feat.get("relevance") or 0.0),
    }


def geocode_listings(listings: list[Any],
                     cache_path: Path,
                     mapbox_token: str | None = None,
                     max_listings: int | None = None) -> dict:
    """Populate lat/lng/geocoding_confidence on listings.

    Skips listings that already have coords. Cache by `source|source_id` +
    address md5 — re-geocode only when address text changes (broker
    relocates, scraper extracts a more specific address, etc.).

    Args:
        listings: Listing objects or dicts. Mutated in-place.
        cache_path: Path to web/data/geocoding_cache.json
        mapbox_token: API token. If None, read from MAPBOX_TOKEN env.
                       If still None, skip everything.
        max_listings: Cap total Mapbox calls for cost control.

    Returns:
      {
        "skipped_no_token":   bool,
        "skipped_no_httpx":   bool,
        "already_has_coords": int,
        "cache_hits":         int,
        "cache_misses":       int,
        "mapbox_calls":       int,
        "mapbox_succeeded":   int,
        "mapbox_failed":      int,
        "outside_sv_bbox":    int,
        "no_address":         int,
        "populated_total":    int,
      }
    """
    metrics: dict[str, Any] = {
        "skipped_no_token":   False,
        "skipped_no_httpx":   False,
        "already_has_coords": 0,
        "cache_hits":         0,
        "cache_misses":       0,
        "mapbox_calls":       0,
        "mapbox_succeeded":   0,
        "mapbox_failed":      0,
        "outside_sv_bbox":    0,
        "no_address":         0,
        "populated_total":    0,
    }

    token = mapbox_token or os.environ.get("MAPBOX_TOKEN")
    if not token:
        metrics["skipped_no_token"] = True
        return metrics

    try:
        import httpx  # type: ignore
    except ImportError:
        metrics["skipped_no_httpx"] = True
        return metrics

    cache = _load_cache(cache_path)
    client = httpx.Client(headers={"User-Agent": "PulpoClubGeocoder/1.0"})

    n_processed = 0
    try:
        for li in listings:
            # Already has scraper-supplied coords — skip
            if _has_coords(li):
                metrics["already_has_coords"] += 1
                metrics["populated_total"] += 1
                continue

            address = _build_address(li)
            if not address:
                metrics["no_address"] += 1
                continue

            key = f"{_g(li, 'source')}|{_g(li, 'source_id')}"
            current_md5 = _address_md5(address)
            cached = cache.get(key)

            if cached and cached.get("address_md5") == current_md5:
                metrics["cache_hits"] += 1
                _set(li, "lat", cached.get("lat"))
                _set(li, "lng", cached.get("lng"))
                _set(li, "geocoding_confidence", cached.get("geocoding_confidence"))
                metrics["populated_total"] += 1
                continue

            metrics["cache_misses"] += 1

            if max_listings is not None and metrics["mapbox_calls"] >= max_listings:
                continue

            metrics["mapbox_calls"] += 1
            time.sleep(MAPBOX_DELAY_S)
            result = _call_mapbox(address, token, client)
            n_processed += 1

            if not result:
                metrics["mapbox_failed"] += 1
                continue

            confidence = _mapbox_relevance_to_confidence(result["relevance"])
            entry = {
                "address_md5":          current_md5,
                "address":              address[:200],
                "lat":                  result["lat"],
                "lng":                  result["lng"],
                "geocoding_confidence": confidence,
                "source_method":        "mapbox",
                "ts":                   datetime.now(timezone.utc).isoformat(),
            }
            cache[key] = entry
            metrics["mapbox_succeeded"] += 1
            metrics["populated_total"] += 1
            _set(li, "lat", entry["lat"])
            _set(li, "lng", entry["lng"])
            _set(li, "geocoding_confidence", confidence)
    finally:
        client.close()

    _save_cache(cache_path, cache)
    return metrics
