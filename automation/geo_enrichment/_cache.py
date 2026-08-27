"""GEO-1 — the cell cache: what makes night two nearly free.

Why cells and not listings
--------------------------
95.8% of listings carry ``geocoding_source="estimated"`` — a DeepSeek
guess at zone level, accurate to a few km, not to the metre. Asking an
API for a 250m soil sample under such a coordinate is false precision AND
1,893 HTTP calls. So every provider declares the resolution its data
actually varies at (NASA POWER's native grid is 0.5°; CAMS air quality is
~0.4°), we round the listing's coordinate to that grid, and we fetch once
per *cell*. ~1,900 listings collapse to a few dozen calls for the coarse
providers, and new listings that land in an already-known cell cost zero.

Key shape: ``provider|cell|vN``. The version lives in the key on purpose —
bumping a provider's ``VERSION`` is then automatically a cache miss, and
``prune()`` garbage-collects the superseded keys on the next save. No
migration step, no stale payload silently surviving a parser change.

Freshness has two classes. ``static`` data (elevation, soil, climate
normals, historical seismicity) never expires: only a VERSION bump
refetches it. ``slow`` data (air quality, river discharge) expires after
``REFRESH_DAYS``.

The history JSONL is capped from day one. ``type_classifier_log.jsonl``
reached 38MB by growing forever; there is no reason to repeat that for an
aggregate one row per run.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from automation._atomic import atomic_write_json, atomic_write_text


# Steady-state cell count is bounded by geography (a country only has so
# many 0.01° cells with listings in them), so this cap is a runaway guard,
# not an expected eviction path.
CACHE_MAX_ROWS = 20_000

# One aggregate row per nightly run — 500 rows is ~8 months of history.
HISTORY_MAX_ROWS = 500

STATUS_OK = "ok"
STATUS_NA = "na"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def cell_id(lat: float, lng: float, step: float, decimals: int) -> str:
    """Snap a coordinate to the provider's grid.

    Formatting with fixed decimals (rather than repr of the float) keeps
    the key stable: ``round(13.47 / 0.05) * 0.05`` is 13.450000000000001
    on this hardware, and that artifact must never reach a cache key.
    """
    snapped_lat = round(lat / step) * step
    snapped_lng = round(lng / step) * step
    # ``+ 0.0`` normalizes -0.0 (which formats as "-0.00") to 0.0.
    return f"{snapped_lat + 0.0:.{decimals}f},{snapped_lng + 0.0:.{decimals}f}"


def cell_center(cid: str) -> tuple[float, float]:
    lat_s, lng_s = cid.split(",", 1)
    return float(lat_s), float(lng_s)


def cell_key(provider: str, cid: str, version: int) -> str:
    return f"{provider}|{cid}|v{version}"


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(path: Path, cache: dict) -> None:
    # Compact: this file carries thousands of payloads and is committed to
    # the repo every night. Indentation would roughly double the diff.
    atomic_write_json(path, cache, separators=(",", ":"), sort_keys=True)


def make_entry(status: str, payload: Optional[dict], ttl_class: str,
               now: Optional[datetime] = None) -> dict:
    return {
        "status": status,
        "payload": payload,
        "fetched_at": iso(now or utcnow()),
        "ttl_class": ttl_class,
    }


def entry_fresh(entry: Any, *, ttl_class: str, refresh_days: int,
                now: Optional[datetime] = None) -> bool:
    """True when a cached entry can be served without refetching."""
    if not isinstance(entry, dict) or entry.get("status") not in (STATUS_OK, STATUS_NA):
        return False
    if ttl_class == "static" or refresh_days <= 0:
        return True
    fetched = parse_iso(entry.get("fetched_at"))
    if fetched is None:
        return False
    return (now or utcnow()) - fetched < timedelta(days=refresh_days)


def prune(cache: dict, *, current_versions: dict[str, int],
          max_rows: int = CACHE_MAX_ROWS) -> int:
    """Drop superseded-version keys, then row-cap by age. Returns rows dropped.

    A provider absent from ``current_versions`` (not registered this run —
    e.g. an env allowlist narrowed the set) is left alone: its entries are
    still valid and re-registering shouldn't cost a refetch.
    """
    dropped = 0
    for key in list(cache.keys()):
        parts = key.split("|")
        if len(parts) != 3:
            del cache[key]
            dropped += 1
            continue
        provider, _cid, vtag = parts
        current = current_versions.get(provider)
        if current is not None and vtag != f"v{current}":
            del cache[key]
            dropped += 1

    if len(cache) > max_rows:
        # Evict 10% past the cap so this is a rare batch operation rather
        # than a per-write eviction (aesthetic_vision.py precedent).
        target = max(0, len(cache) - max_rows) + max_rows // 10
        ordered = sorted(cache.items(),
                         key=lambda kv: (kv[1] or {}).get("fetched_at") or "")
        for key, _ in ordered[:target]:
            del cache[key]
            dropped += 1
    return dropped


def append_history(path: Path, row: dict,
                   max_rows: int = HISTORY_MAX_ROWS) -> None:
    """Append one aggregate row, rewriting to the cap when it overflows.

    Telemetry must never break the pipeline, so every failure here is
    swallowed (distance_fields_history.jsonl precedent).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

        existing = path.read_text(encoding="utf-8").splitlines()
        if len(existing) > max_rows:
            atomic_write_text(path, "\n".join(existing[-max_rows:]) + "\n")
    except OSError:
        pass
