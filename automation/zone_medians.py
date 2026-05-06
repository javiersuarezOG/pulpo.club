"""
PRD §FR-7.5 — zone median price batch.

Computes the median price_per_m2 per (zone_name, property_type) bucket
across all active listings, then writes price_vs_zone_median and
price_vs_zone_pct on every listing whose bucket has ≥ MIN_LISTINGS_PER_ZONE
comparable peers.

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
    # Each listing now has price_vs_zone_median and price_vs_zone_pct
    # set when eligible.

Idempotent: pure function of (current listings) → fields. No sidecar.
The medians are recomputed every run from the current catalog state.
"""
from __future__ import annotations
import statistics
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


def compute_zone_medians(listings: list[Any]) -> dict[tuple[str, str], float]:
    """Per-bucket median price_per_m2. Buckets below MIN_LISTINGS_PER_ZONE excluded.

    Returns:
        {(zone, property_type): median_price_per_m2}
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
        key: round(statistics.median(values), 2)
        for key, values in by_bucket.items()
        if len(values) >= MIN_LISTINGS_PER_ZONE
    }


def apply_zone_metrics(listings: list[Any],
                       medians: dict[tuple[str, str], float]) -> dict:
    """Set price_vs_zone_median + price_vs_zone_pct on each eligible listing.

    Eligibility: listing must be active AND its bucket must be in medians
    (i.e. ≥ MIN_LISTINGS_PER_ZONE peers). Listings that don't qualify
    leave both fields untouched (default None).

    Returns metrics dict with bucket counts + how many listings were scored.
    """
    metrics: dict[str, Any] = {
        "buckets_computed":      len(medians),
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
        median = medians.get(key)
        if median is None:
            metrics["listings_skipped_no_bucket_median"] += 1
            continue

        ppm = _g(li, "price_per_m2")
        # Signed % difference: negative = below median (cheaper), positive = above.
        # Rounded to 1 decimal — sufficient resolution for chip display.
        pct = round(((ppm - median) / median) * 100, 1)
        _set(li, "price_vs_zone_median", median)
        _set(li, "price_vs_zone_pct", pct)
        metrics["listings_scored"] += 1

    metrics["buckets_below_min"] = (
        metrics["listings_skipped_no_bucket_median"]
    )
    return metrics


def compute_and_apply(listings: list[Any]) -> dict:
    """Top-level entry point — compute medians from `listings` and apply
    them in-place. Returns metrics dict.

    Common case: called once per nightly run after enrichment / derived
    rules / etc. — listings is the validated set, not raw scraper output.
    """
    medians = compute_zone_medians(listings)
    return apply_zone_metrics(listings, medians)
