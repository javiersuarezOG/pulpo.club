"""GEO-1 — geospatial due-diligence enrichment from free open APIs.

WHAT THIS IS
------------
Every listing has a lat/lng. That coordinate is a key into a large amount
of free public data nobody in LATAM real estate surfaces: how much sun
the land gets, how high it sits, whether a river floods near it, what the
soil is made of, how far the nearest hospital is. This module turns the
coordinate into those answers and writes them next to the listing.

The PRD for this asked for a database table, a job queue, and a one-off
backfill worker. Pulpo has none of those, and does not need them:

  property_enrichment table  ->  web/data/geo_enrichment.json, keyed
                                 "source|source_id" (the same identity
                                 llm_enrichment.json uses; ~99.7% of keys
                                 survive night-over-night)
  queue + incremental job    ->  a pass in the nightly. New listings only
                                 enter through the nightly anyway, so the
                                 PRD's <24h freshness SLA is automatic.
  backfill worker + control  ->  the cell cache IS the resume state. Night
    table                        one does what the budget allows, the rest
                                 stays "pending", the next night continues.
                                 scripts/backfill_geo_enrichment.py drives
                                 the same function for a controlled run.
  estado pendiente/exitoso/  ->  per-provider status:
    fallido/no_disponible          pending / ok / failed / na

WHY CELLS
---------
95.8% of listings carry ``geocoding_source="estimated"`` — an LLM's
zone-level guess, good to a few km. Fetching per listing would be ~1,900
calls per provider AND would imply a precision we do not have. So each
provider declares the resolution its data actually varies at, and we
fetch once per rounded cell (see ``_cache.cell_id``). Roughly 1,900
listings become a few dozen calls for the coarse providers; a new listing
in a known cell costs nothing.

FAILURE POSTURE
---------------
Nothing here may break a nightly. The caller wraps this in try/except,
and internally: a failed cell is not cached (so tomorrow retries it), a
provider that fails repeatedly is disabled for the rest of the run, the
wall-clock deadline stops new calls, and the assembly pass runs
regardless so partial data still lands.

Assembly is a full recompute from cache every run, not an incremental
patch. That is what makes coordinate changes, geocoding-precision
upgrades, and provider VERSION bumps self-healing rather than a migration.

PUBLIC API
----------
    from automation.geo_enrichment import enrich_listings
    metrics = enrich_listings(listings, cells_path=..., sidecar_path=...)
"""
from __future__ import annotations

import os
import time as _time
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

from automation._atomic import atomic_write_json
from automation._config import env_int
from pulpo.countries import active as _active_country

from . import nasa_power, open_meteo_elevation
from ._cache import (
    STATUS_NA,
    STATUS_OK,
    append_history,
    cell_center,
    cell_id,
    cell_key,
    entry_fresh,
    iso,
    load_cache,
    make_entry,
    parse_iso,
    prune,
    save_cache,
    utcnow,
)
from ._http import default_http_get, default_http_post, with_retry

# Cheapest and most reliable first: if the budget runs out, it should run
# out on the slow throttled providers, not on the ones that would have
# finished. Registry order IS fetch order.
_PROVIDER_MODULES: tuple[ModuleType, ...] = (
    open_meteo_elevation,
    nasa_power,
)

REGISTRY: dict[str, ModuleType] = {m.PROVIDER: m for m in _PROVIDER_MODULES}

# Fail at import, not in production. A duplicate PROVIDER would silently
# drop a module from the registry; a duplicate CATEGORY would have two
# providers overwriting each other's slot in every assembled record. Both
# are invisible at runtime, so they are checked here where adding a
# provider is the only thing that can trigger them.
if len(REGISTRY) != len(_PROVIDER_MODULES):
    raise RuntimeError("geo_enrichment: duplicate PROVIDER name in the registry")
_CATEGORIES = [m.CATEGORY for m in _PROVIDER_MODULES]
if len(set(_CATEGORIES)) != len(_CATEGORIES):
    raise RuntimeError(f"geo_enrichment: duplicate CATEGORY in the registry: {_CATEGORIES}")

# Per-listing status values (PRD's `estado`).
ST_OK = "ok"
ST_NA = "na"
ST_FAILED = "failed"
ST_PENDING = "pending"

# Consecutive failures before a provider is written off for this run. The
# same reasoning as llm_enrichment's global-error short-circuit: an expired
# key or an IP ban fails identically on every cell, so grinding through
# hundreds of them just burns the budget and the goodwill of a free API.
_PROVIDER_FAILURE_LIMIT = 3

# Statuses that mean "stop asking this provider anything" on the first hit.
_GLOBAL_STATUS_CODES = frozenset({401, 403, 429})

_DEFAULT_MAX_CALLS = 400

# Records for listings that have left the catalog stop being re-assembled,
# so their assembled_at freezes and they age out. Deliberately age-based
# rather than "not in this run's listings": the SV and PA passes share this
# file, so presence-based pruning would delete every PA record during the
# SV run and vice versa.
_DEFAULT_SIDECAR_RETENTION_DAYS = 90


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _key(li: Any) -> Optional[str]:
    source = _g(li, "source")
    source_id = _g(li, "source_id")
    if not source or not source_id:
        return None
    return f"{source}|{source_id}"


def _coords(li: Any) -> Optional[tuple[float, float]]:
    lat, lng = _g(li, "lat"), _g(li, "lng")
    if not isinstance(lat, (int, float)) or isinstance(lat, bool):
        return None
    if not isinstance(lng, (int, float)) or isinstance(lng, bool):
        return None
    lat, lng = float(lat), float(lng)
    # A hard sanity gate, not a country gate: (0,0) is the classic
    # "geocoder returned nothing" value and would silently enrich Null
    # Island. Country-specific bounds belong to the geocoders upstream.
    if lat == 0.0 and lng == 0.0:
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        return None
    return lat, lng


def _call_caps(explicit: Optional[dict]) -> dict:
    """Per-provider call ceilings, env-overridable per provider.

    PULPO_GEO_<PROVIDER>_MAX_CALLS, e.g. PULPO_GEO_SOILGRIDS_MAX_CALLS.
    Absent = no per-provider ceiling (the global one still applies).
    """
    caps: dict[str, int] = {}
    for name in REGISTRY:
        env_name = f"PULPO_GEO_{name.upper()}_MAX_CALLS"
        value = env_int(env_name, 0)
        if value > 0:
            caps[name] = value
    if explicit:
        caps.update(explicit)
    return caps


def _resolve_providers(providers: Optional[list[str]]) -> list[ModuleType]:
    """Registry order, filtered by an optional allowlist.

    Unknown names are ignored rather than raising: the allowlist is an
    ops knob (a repo variable, in practice) and a typo in it must not take
    the nightly down.
    """
    if not providers:
        return list(_PROVIDER_MODULES)
    wanted = {p.strip().lower() for p in providers if p and p.strip()}
    return [m for m in _PROVIDER_MODULES if m.PROVIDER in wanted]


def _prune_sidecar(sidecar: dict, *, now: datetime, retention_days: int) -> int:
    """Drop records that stopped being refreshed. Returns rows dropped.

    Age-based on purpose. A listing still in the catalog is re-assembled
    every run, so its `assembled_at` is always today and it never ages out;
    only genuinely delisted ones do. Pruning by "absent from this run's
    listings" would be catastrophic here — the SV and PA passes share this
    file, so each run would delete the other country's records.
    """
    if retention_days <= 0:
        return 0
    cutoff = now - timedelta(days=retention_days)
    dropped = 0
    for key in list(sidecar.keys()):
        rec = sidecar.get(key)
        if not isinstance(rec, dict):
            del sidecar[key]
            dropped += 1
            continue
        ts = parse_iso(rec.get("assembled_at"))
        # An unparseable timestamp is left alone rather than deleted —
        # losing data on a format surprise is worse than carrying it.
        if ts is not None and ts < cutoff:
            del sidecar[key]
            dropped += 1
    return dropped


def enrich_listings(
    listings: list,
    *,
    cells_path: Path,
    sidecar_path: Path,
    history_path: Optional[Path] = None,
    providers: Optional[list[str]] = None,
    deadline: Optional[float] = None,
    max_listings: int = 0,
    max_calls: int = 0,
    call_caps: Optional[dict] = None,
    dry_run: bool = False,
    http_get: Optional[Callable] = None,
    http_post: Optional[Callable] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
    now_fn: Optional[Callable[[], datetime]] = None,
) -> dict:
    """Enrich ``listings`` from the cell cache, fetching what is missing.

    ``deadline`` is an absolute ``time.monotonic()` value; past it, no new
    call is started (in-flight ones finish) and the remainder is left
    pending for the next run. All I/O is skipped entirely when
    ``PULPO_OFFLINE=1`` so the offline pipeline smoke stays hermetic.
    """
    if os.environ.get("PULPO_OFFLINE") == "1":
        return {"offline_skip": True, "listings_seen": len(listings or [])}

    started = _time.monotonic()
    sleep = sleep_fn if sleep_fn is not None else _time.sleep
    # Providers receive an already-retrying transport, so they never carry
    # retry logic themselves and `None` from a fetch stays unambiguous:
    # it means "no data for this cell", never "the request failed".
    get = with_retry(http_get or default_http_get, sleep_fn=sleep)
    post = with_retry(http_post or default_http_post, sleep_fn=sleep)
    now = now_fn or utcnow

    mods = _resolve_providers(providers)
    caps = _call_caps(call_caps)
    global_cap = max_calls if max_calls > 0 else env_int("PULPO_GEO_MAX_CALLS",
                                                         _DEFAULT_MAX_CALLS)

    cells = load_cache(cells_path)
    sidecar = load_cache(sidecar_path)

    # ── Plan ──────────────────────────────────────────────────────────
    # Which listings we can serve, and which cells we are missing.
    candidates: list[tuple[str, Any, float, float]] = []
    listings_no_coords = 0
    for li in listings or []:
        key = _key(li)
        if key is None:
            continue
        coords = _coords(li)
        if coords is None:
            listings_no_coords += 1
            continue
        candidates.append((key, li, coords[0], coords[1]))
    if max_listings > 0:
        candidates = candidates[:max_listings]

    needed: dict[str, list[str]] = {}
    for mod in mods:
        wanted: set[str] = set()
        for _key_, _li, lat, lng in candidates:
            cid = cell_id(lat, lng, mod.CELL_STEP_DEG, mod.CELL_DECIMALS)
            entry = cells.get(cell_key(mod.PROVIDER, cid, mod.VERSION))
            if not entry_fresh(entry, ttl_class=mod.TTL_CLASS,
                               refresh_days=getattr(mod, "REFRESH_DAYS", 0),
                               now=now()):
                wanted.add(cid)
        # Sorted so a budget-truncated run is deterministic and resumable
        # in a stable order rather than however the set happened to hash.
        needed[mod.PROVIDER] = sorted(wanted)

    metrics: dict[str, Any] = {
        "offline_skip": False,
        "listings_seen": len(listings or []),
        "listings_with_coords": len(candidates),
        "listings_no_coords": listings_no_coords,
        "cells_needed": sum(len(v) for v in needed.values()),
        "cache_hits": 0,
        "api_calls": 0,
        "calls_ok": 0,
        "calls_na": 0,
        "calls_failed": 0,
        "assembled": 0,
        "listings_pending": 0,
        "deadline_hit": False,
        "providers_disabled": [],
        "dry_run": bool(dry_run),
        "per_provider": {
            m.PROVIDER: {
                "cells_needed": len(needed[m.PROVIDER]),
                "cache_hits": 0,
                "api_calls": 0,
                "ok": 0,
                "na": 0,
                "failed": 0,
                "disabled": False,
            }
            for m in mods
        },
    }

    if dry_run:
        metrics["duration_s"] = round(_time.monotonic() - started, 1)
        return metrics

    # ── Fetch ─────────────────────────────────────────────────────────
    cache_dirty = False
    disabled: set[str] = set()

    def _budget_left() -> bool:
        if deadline is not None and _time.monotonic() >= deadline:
            metrics["deadline_hit"] = True
            return False
        if global_cap > 0 and metrics["api_calls"] >= global_cap:
            return False
        return True

    for mod in mods:
        pm = metrics["per_provider"][mod.PROVIDER]
        pending_cells = needed[mod.PROVIDER]
        if not pending_cells:
            continue

        cap = caps.get(mod.PROVIDER, 0)
        min_interval = float(getattr(mod, "MIN_INTERVAL_S", 0.0))
        timeout_s = float(getattr(mod, "TIMEOUT_S", 20.0))
        batch_size = int(getattr(mod, "BATCH_SIZE", 0) or 0)
        can_batch = batch_size > 0 and hasattr(mod, "fetch_batch")
        consecutive_failures = 0
        last_call_at: Optional[float] = None

        index = 0
        while index < len(pending_cells):
            if mod.PROVIDER in disabled or not _budget_left():
                break
            if cap > 0 and pm["api_calls"] >= cap:
                break

            chunk = (pending_cells[index:index + batch_size] if can_batch
                     else pending_cells[index:index + 1])
            index += len(chunk)

            if min_interval > 0 and last_call_at is not None:
                wait = min_interval - (_time.monotonic() - last_call_at)
                if wait > 0:
                    sleep(wait)

            centers = [cell_center(cid) for cid in chunk]
            try:
                if can_batch:
                    results = mod.fetch_batch(centers, http_get=get,
                                              timeout_s=timeout_s)
                else:
                    lat, lng = centers[0]
                    results = [mod.fetch(lat, lng, http_get=get, http_post=post,
                                         timeout_s=timeout_s)]
                consecutive_failures = 0
            except Exception as exc:  # noqa: BLE001 — one cell must not end the pass
                metrics["api_calls"] += 1
                pm["api_calls"] += 1
                metrics["calls_failed"] += len(chunk)
                pm["failed"] += len(chunk)
                last_call_at = _time.monotonic()
                consecutive_failures += 1
                status_code = getattr(exc, "status_code", None)
                fatal = (status_code in _GLOBAL_STATUS_CODES
                         or consecutive_failures >= _PROVIDER_FAILURE_LIMIT)
                if fatal:
                    disabled.add(mod.PROVIDER)
                    pm["disabled"] = True
                    pm["disabled_reason"] = (f"http_{status_code}" if status_code
                                             else f"{consecutive_failures}_consecutive_failures")
                    metrics["providers_disabled"].append(mod.PROVIDER)
                continue

            metrics["api_calls"] += 1
            pm["api_calls"] += 1
            last_call_at = _time.monotonic()

            stamped = now()
            # A provider returning a different number of results than it
            # was asked for would silently misalign here — zip() truncates,
            # and we would attach one cell's data to a different cell in a
            # cache that persists for months. Treat it as a failed fetch.
            if not isinstance(results, list) or len(results) != len(chunk):
                metrics["calls_failed"] += len(chunk)
                pm["failed"] += len(chunk)
                consecutive_failures += 1
                if consecutive_failures >= _PROVIDER_FAILURE_LIMIT:
                    disabled.add(mod.PROVIDER)
                    pm["disabled"] = True
                    pm["disabled_reason"] = "result_length_mismatch"
                    metrics["providers_disabled"].append(mod.PROVIDER)
                continue

            for cid, payload in zip(chunk, results):
                status = STATUS_OK if payload else STATUS_NA
                cells[cell_key(mod.PROVIDER, cid, mod.VERSION)] = make_entry(
                    status, payload if payload else None, mod.TTL_CLASS, stamped)
                cache_dirty = True
                if status == STATUS_OK:
                    metrics["calls_ok"] += 1
                    pm["ok"] += 1
                else:
                    metrics["calls_na"] += 1
                    pm["na"] += 1

    # ── Assemble ──────────────────────────────────────────────────────
    # Free (pure dict work), so it runs even when the budget was blown —
    # a listing whose cells were already warm still gets its record today.
    assembled_at = iso(now())
    for key, li, lat, lng in candidates:
        record: dict[str, Any] = {
            "country": _g(li, "country"),
            "coords": {
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                # What the enrichment was computed FROM. ~96% of these say
                # "estimated"; recording it keeps the data honest and makes
                # a later precision upgrade visibly invalidate the record.
                "geocoding_source": _g(li, "geocoding_source"),
                "geocoding_confidence": _g(li, "geocoding_confidence"),
            },
            "assembled_at": assembled_at,
            "providers": {},
        }

        has_pending = False
        for mod in mods:
            cid = cell_id(lat, lng, mod.CELL_STEP_DEG, mod.CELL_DECIMALS)
            entry = cells.get(cell_key(mod.PROVIDER, cid, mod.VERSION))
            fresh = entry_fresh(entry, ttl_class=mod.TTL_CLASS,
                                refresh_days=getattr(mod, "REFRESH_DAYS", 0),
                                now=now())
            if fresh and isinstance(entry, dict):
                status = ST_OK if entry.get("status") == STATUS_OK else ST_NA
                record["providers"][mod.PROVIDER] = {
                    "status": status,
                    "cell": cid,
                    "version": mod.VERSION,
                    "fetched_at": entry.get("fetched_at"),
                }
                record[mod.CATEGORY] = entry.get("payload") if status == ST_OK else None
                metrics["cache_hits"] += 1
                metrics["per_provider"][mod.PROVIDER]["cache_hits"] += 1
            else:
                # Attempted-and-failed this run vs never-attempted. Both
                # retry next run; the distinction is for the operator
                # reading the sidecar, per the PRD's estado split.
                attempted = (cid in needed[mod.PROVIDER]
                             and metrics["per_provider"][mod.PROVIDER]["failed"] > 0)
                record["providers"][mod.PROVIDER] = {
                    "status": ST_FAILED if attempted else ST_PENDING,
                    "cell": cid,
                    "version": mod.VERSION,
                }
                record[mod.CATEGORY] = None
                has_pending = True

        # Preserve categories written by providers not in this run's
        # allowlist — a staged rollout must not delete yesterday's data.
        previous = sidecar.get(key)
        if isinstance(previous, dict):
            for name, prev_status in (previous.get("providers") or {}).items():
                if name not in record["providers"]:
                    record["providers"][name] = prev_status
                    category = getattr(REGISTRY.get(name), "CATEGORY", None)
                    if category and category in previous:
                        record[category] = previous[category]

        sidecar[key] = record
        metrics["assembled"] += 1
        if has_pending:
            metrics["listings_pending"] += 1

    # ── Persist ───────────────────────────────────────────────────────
    if cache_dirty:
        prune(cells, current_versions={m.PROVIDER: m.VERSION for m in mods})
        save_cache(cells_path, cells)
    if candidates:
        metrics["sidecar_pruned"] = _prune_sidecar(
            sidecar,
            now=now(),
            retention_days=env_int("PULPO_GEO_SIDECAR_RETENTION_DAYS",
                                   _DEFAULT_SIDECAR_RETENTION_DAYS),
        )
        atomic_write_json(sidecar_path, sidecar,
                          separators=(",", ":"), sort_keys=True)
        metrics["sidecar_records"] = len(sidecar)

    metrics["cells_cached"] = len(cells)
    metrics["duration_s"] = round(_time.monotonic() - started, 1)

    if history_path is not None:
        coverage = {}
        for mod in mods:
            pm = metrics["per_provider"][mod.PROVIDER]
            total = metrics["listings_with_coords"] or 1
            coverage[mod.PROVIDER] = round(pm["cache_hits"] / total, 3)
        append_history(history_path, {
            "ts": assembled_at,
            "country": _active_country().code,
            "listings_seen": metrics["listings_seen"],
            "listings_with_coords": metrics["listings_with_coords"],
            "assembled": metrics["assembled"],
            "listings_pending": metrics["listings_pending"],
            "cells_needed": metrics["cells_needed"],
            "cells_cached": metrics["cells_cached"],
            "api_calls": metrics["api_calls"],
            "calls_ok": metrics["calls_ok"],
            "calls_na": metrics["calls_na"],
            "calls_failed": metrics["calls_failed"],
            "deadline_hit": metrics["deadline_hit"],
            "providers_disabled": metrics["providers_disabled"],
            "duration_s": metrics["duration_s"],
            "coverage": coverage,
        })

    return metrics
