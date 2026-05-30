"""Read-side helper for the scrape-cache fallback path.

When a scraper's host is WAF-blocked from the runner's IP, the main
nightly can read records from a cache file the GCP self-hosted runner
wrote out earlier (see ``pulpo.cli._run_scrape_external``). This module
is the read side — scrapers call ``load_fresh_cache(slug)`` before
attempting a live fetch and use the returned records if any are present
and recent enough.

Why this layer exists
---------------------
Pre-2026-05-30 the realtyelsalvador + elagente scrapers tried live
HTTP from the Azure GH-runner IP every nightly, got 403, and wrote
zero records to ranked.json. The /admin/sources tile stayed red. With
the cache fallback, the scraper consumes pre-written records when the
live path fails, and the tile stays green as long as the GCP shim
produced fresh data within the freshness window.

Failure modes (intentional)
---------------------------
- Cache file missing → returns None → caller falls through to live.
- Cache file unparseable → returns None → caller falls through to live;
  the corrupt file is logged but not raised. A bad cache shouldn't
  poison the live fetch's failure mode (which the existing watchdog
  understands).
- Cache file older than the freshness window → returns None → caller
  falls through. Visibility into "the GCP shim hasn't run in a while"
  comes from the source_health_history row, not from this layer.
- ``records`` field missing or empty → returns None. Empty caches are
  not yielded — that would mask the failure the caller is trying to
  detect.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Default freshness window: 25 hours. The GCP shim runs daily at 01:30
# UTC, the main nightly at 02:00 — one nightly + slack. A cache older
# than 25h means the shim hasn't run in over a day, which is a real
# operator-actionable problem rather than a "use stale data anyway"
# scenario.
DEFAULT_FRESHNESS_HOURS = 25


def _cache_path(slug: str, *, base_dir: Optional[Path] = None) -> Path:
    """Resolve the on-disk cache path for ``slug``.

    ``base_dir`` override is for tests; production code passes None and
    gets the canonical ``<repo>/web/data/scrape_cache/<slug>.json``.
    """
    if base_dir is None:
        # __file__ → pulpo/scrapers/_scrape_cache.py → parents[2] = repo root.
        base_dir = Path(__file__).resolve().parents[2] / "web" / "data" / "scrape_cache"
    return base_dir / f"{slug}.json"


def _parse_ts(s: str) -> Optional[datetime]:
    """Tolerantly parse the cache envelope's ``ts`` field.

    Accepts both the Z-suffix form the writer produces today
    (``2026-05-30T01:34:12Z``) and the ISO-offset form Python's
    ``datetime.isoformat()`` defaults to (``2026-05-30T01:34:12+00:00``).
    A future writer change won't silently break the reader.
    """
    if not isinstance(s, str):
        return None
    try:
        # fromisoformat doesn't accept the Z suffix in Python <3.11;
        # normalize it ourselves so the reader works on the same Python
        # versions Pulpo's pipeline supports.
        normalized = s.rstrip("Z") + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_fresh_cache(
    slug: str,
    *,
    base_dir: Optional[Path] = None,
    freshness_hours: Optional[float] = None,
    now: Optional[datetime] = None,
) -> Optional[list[dict]]:
    """Return cached records for ``slug`` if a fresh envelope exists.

    Returns None — and the caller proceeds with its normal live-fetch
    path — when any of these is true:
      - the cache file doesn't exist
      - the cache file is unparseable JSON
      - the envelope's ``ts`` is missing, malformed, or older than
        ``freshness_hours`` (default 25h, overridable via the env var
        ``PULPO_SCRAPE_CACHE_FRESHNESS_HOURS`` for ops experiments)
      - the envelope has no records

    A returned list is always non-empty.
    """
    path = _cache_path(slug, base_dir=base_dir)
    if not path.exists():
        return None

    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # A corrupted cache file shouldn't crash the scraper. Log to
        # stdout (the pipeline's log path) and fall through.
        print(f"[scrape-cache] {slug}: cache parse failed ({e!r}); using live path")
        return None

    if not isinstance(envelope, dict):
        print(f"[scrape-cache] {slug}: envelope is not a dict; using live path")
        return None

    ts = _parse_ts(envelope.get("ts") or "")
    if ts is None:
        print(f"[scrape-cache] {slug}: envelope has no usable ts; using live path")
        return None

    if freshness_hours is None:
        try:
            freshness_hours = float(
                os.environ.get("PULPO_SCRAPE_CACHE_FRESHNESS_HOURS")
                or DEFAULT_FRESHNESS_HOURS,
            )
        except (TypeError, ValueError):
            freshness_hours = DEFAULT_FRESHNESS_HOURS

    current = now or datetime.now(timezone.utc)
    age_h = (current - ts).total_seconds() / 3600.0
    if age_h > freshness_hours:
        print(f"[scrape-cache] {slug}: cache is {age_h:.1f}h old "
              f"(>{freshness_hours:.0f}h); using live path")
        return None

    records = envelope.get("records")
    if not isinstance(records, list) or not records:
        print(f"[scrape-cache] {slug}: envelope has no records; using live path")
        return None

    print(f"[scrape-cache] {slug}: hit — {len(records)} records, age={age_h:.1f}h")
    return records
