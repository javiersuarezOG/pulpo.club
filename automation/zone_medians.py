"""
PRD §FR-7.5 — zone median price batch + per-run telemetry.

Computes the median price_per_m2 per (zone_name, property_type) bucket
across all active listings, then writes price_vs_zone_median and
price_vs_zone_pct on every listing whose bucket has ≥ MIN_LISTINGS_PER_ZONE
comparable peers.

Telemetry: appends one row per (zone, property_type, ts) to
web/data/zone_medians_history.jsonl per nightly. Lets us spot
week-over-week shifts in zone medians (zone heating up, supply collapse,
etc.) without parsing ranked.json. Same append-only pattern as
source_health_history.jsonl.

This is the dependency that unlocks:
  - PRD §FR-7.2 investment_signal=deal     (is_repriced AND price_vs_zone_pct ≤ -10)
  - WS3 'X% below zone average' display
  - Sorting by price-vs-zone

Bucketing decision: per (zone, property_type) rather than just zone.
Today the catalog is 94% land but bienesraices Phase A (PR #65) is starting
to surface houses + condos — segmenting by type now keeps house $/m²
from polluting the land $/m² distribution as inventory mix shifts.

Listings that can't be scored leave both fields as None:
  - price_per_m2 is missing or non-positive
  - zone is missing or "unresolved"
  - days_listed > 365 (per PRD §FR-7.5 — stale comp pool)
  - bucket has fewer than MIN_LISTINGS_PER_ZONE peers

Public API:

    from automation.zone_medians import compute_and_apply
    metrics = compute_and_apply(listings)
    # Each listing now has price_vs_zone_median, price_vs_zone_pct,
    # zone_price_per_m2_min, zone_price_per_m2_max, and zone_comp_count
    # set when eligible.

Idempotent: pure function of (current listings) → fields. No sidecar.
The medians are recomputed every run from the current catalog state.
"""
from __future__ import annotations
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# PRD §FR-7.5 — at least 10 active listings per zone to compute a median.
MIN_LISTINGS_PER_ZONE = 10

# PRD §FR-7.5 — max days_listed before excluding from comp pool.
MAX_DAYS_LISTED_FOR_COMPS = 365


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


def _bucket_key(li: Any) -> tuple[str, str] | None:
    """(zone, property_type) bucket key. None if unbucketable."""
    zone = _g(li, "zone")
    if not isinstance(zone, str) or not zone or zone == "unresolved":
        return None
    ptype = _g(li, "property_type") or "land"
    return (zone, ptype)


def _is_active(li: Any) -> bool:
    """Active = not sold + has positive price_per_m2 + days_listed within window."""
    if _g(li, "is_sold") is True:
        return False
    ppm = _g(li, "price_per_m2")
    if not isinstance(ppm, (int, float)) or ppm <= 0:
        return False
    days = _g(li, "days_listed")
    if isinstance(days, (int, float)) and days > MAX_DAYS_LISTED_FOR_COMPS:
        return False
    return True


def compute_zone_medians(listings: list[Any]) -> dict[tuple[str, str], dict]:
    """Per-bucket distribution stats over price_per_m2. Buckets below
    MIN_LISTINGS_PER_ZONE are excluded.

    Returns:
        {(zone, property_type): {"median": float, "min": float,
                                 "max": float, "n": int}}

    `median` is the existing signal driving price_vs_zone_pct. `min`/`max`/`n`
    feed the detail-page PriceContextBlock — `n` shows up in the "Based on N
    listings" caption; `min`/`max` are kept for a future visualization that
    isn't shipped in this PR (computed silently so the pipeline doesn't need
    a second pass when the viz lands).
    """
    by_bucket: dict[tuple[str, str], list[float]] = {}
    for li in listings:
        if not _is_active(li):
            continue
        key = _bucket_key(li)
        if key is None:
            continue
        ppm = _g(li, "price_per_m2")
        by_bucket.setdefault(key, []).append(float(ppm))

    return {
        key: {
            "median": round(statistics.median(values), 2),
            "min":    round(min(values), 2),
            "max":    round(max(values), 2),
            "n":      len(values),
        }
        for key, values in by_bucket.items()
        if len(values) >= MIN_LISTINGS_PER_ZONE
    }


def apply_zone_metrics(listings: list[Any],
                       stats: dict[tuple[str, str], dict]) -> dict:
    """Set zone-comparison fields on each eligible listing:
        - price_vs_zone_median   (USD/m² median of bucket peers)
        - price_vs_zone_pct      (signed % vs. median; negative = below)
        - zone_price_per_m2_min  (lowest $/m² in bucket; not displayed yet)
        - zone_price_per_m2_max  (highest $/m² in bucket; not displayed yet)
        - zone_comp_count        (n peers; powers "Based on N" caption)

    Eligibility: listing must be active AND its bucket must be in `stats`
    (i.e. ≥ MIN_LISTINGS_PER_ZONE peers). Listings that don't qualify
    leave all fields untouched (default None).

    Returns metrics dict with bucket counts + how many listings were scored.
    """
    metrics: dict[str, Any] = {
        "buckets_computed":      len(stats),
        "buckets_below_min":     0,
        "listings_scored":       0,
        "listings_skipped_no_zone":  0,
        "listings_skipped_inactive": 0,
        "listings_skipped_no_bucket_median": 0,
    }
    for li in listings:
        if not _is_active(li):
            metrics["listings_skipped_inactive"] += 1
            continue
        key = _bucket_key(li)
        if key is None:
            metrics["listings_skipped_no_zone"] += 1
            continue
        bucket = stats.get(key)
        if bucket is None:
            metrics["listings_skipped_no_bucket_median"] += 1
            continue

        ppm = _g(li, "price_per_m2")
        median = bucket["median"]
        # Signed % difference: negative = below median (cheaper), positive = above.
        # Rounded to 1 decimal — sufficient resolution for chip display.
        pct = round(((ppm - median) / median) * 100, 1)
        _set(li, "price_vs_zone_median", median)
        _set(li, "price_vs_zone_pct", pct)
        _set(li, "zone_price_per_m2_min", bucket["min"])
        _set(li, "zone_price_per_m2_max", bucket["max"])
        _set(li, "zone_comp_count", bucket["n"])
        metrics["listings_scored"] += 1

    metrics["buckets_below_min"] = (
        metrics["listings_skipped_no_bucket_median"]
    )
    return metrics


def _write_history(stats: dict[tuple[str, str], dict],
                   bucket_sizes: dict[tuple[str, str], int],
                   history_path: Path) -> None:
    """Append one row per eligible (zone, type) bucket to the history JSONL."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as f:
            for (zone, ptype), bucket in stats.items():
                f.write(json.dumps({
                    "ts":              ts,
                    "zone":            zone,
                    "property_type":   ptype,
                    "n_listings":      bucket_sizes.get((zone, ptype), 0),
                    "median_ppm_usd":  bucket["median"],
                }, ensure_ascii=False) + "\n")
    except OSError:
        # Telemetry write failure should not break the pipeline.
        pass


def compute_and_apply(listings: list[Any], history_path: Path | None = None) -> dict:
    """Top-level entry point — compute zone stats from `listings` and apply
    them in-place. Returns metrics dict.

    Common case: called once per nightly run after enrichment / derived
    rules / etc. — listings is the validated set, not raw scraper output.

    Side effect: appends one row per eligible bucket to history_path
    (default web/data/zone_medians_history.jsonl) for trend tracking.
    """
    stats = compute_zone_medians(listings)
    metrics = apply_zone_metrics(listings, stats)

    # Compute per-bucket sizes for telemetry (separately from stats,
    # which already filtered to only eligible buckets).
    bucket_sizes: dict[tuple[str, str], int] = {}
    for li in listings:
        if not _is_active(li):
            continue
        key = _bucket_key(li)
        if key is None:
            continue
        bucket_sizes[key] = bucket_sizes.get(key, 0) + 1

    if history_path is None:
        history_path = (Path(__file__).resolve().parents[1]
                        / "web" / "data" / "zone_medians_history.jsonl")
    _write_history(stats, bucket_sizes, history_path)
    return metrics
