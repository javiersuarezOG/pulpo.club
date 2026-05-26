"""
PRD §FR-7.5 — zone median price batch + per-run telemetry.

Computes median price_per_m2 across three tiers — (zone, property_type),
then (macro_zone, property_type), then (country, property_type) — and
writes price_vs_zone_median + price_vs_zone_pct + zone_price_per_m2_min/max
+ zone_comp_count + zone_comparison_scope on every listing whose pool
qualifies at the most-specific tier reachable.

Cascade rationale: a strict per-zone gate (≥10 comps) stranded ~30% of
active listings on a 879-listing catalog. Mirroring the proven pattern
in pulpo/ranker_legs/value.py (zone → macro → global, keyed on
property_type) recovers most of those into a meaningful comparison
without polluting types (a house's $/m² never lands in a land pool).

Gate: the same ≥ MIN_LISTINGS_PER_ZONE threshold applies at each tier.
Medians need more samples than the value leg's MIN_COMPS=3 to stay
stable for user-visible display.

Telemetry: appends one row per (zone, property_type, ts) to
web/data/zone_medians_history.jsonl per nightly. Only zone-tier rows are
recorded — macro/country are roll-ups derivable from the zone rows.

This is the dependency that unlocks:
  - PRD §FR-7.2 investment_signal=deal     (is_repriced AND price_vs_zone_pct ≤ -10)
  - WS3 'X% below zone average' display
  - Detail-page PriceContextBlock (PR #476 + this PR's cascade)
  - Sorting by price-vs-zone

Listings leave all zone fields as None when no pool qualifies at any tier:
  - price_per_m2 is missing or non-positive
  - listing is sold or stale (days_listed > MAX_DAYS_LISTED_FOR_COMPS)
  - no (zone, ptype) / (macro, ptype) / (country, ptype) bucket has ≥
    MIN_LISTINGS_PER_ZONE peers

Public API:

    from automation.zone_medians import compute_and_apply
    metrics = compute_and_apply(listings)
    # Each listing now has the six zone fields set when the cascade
    # found a qualifying pool.

Idempotent: pure function of (current listings) → fields. No sidecar.
"""
from __future__ import annotations
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Single source of truth for the macro-region mapping. Lives in value.py
# because it was the first leg to need it; we read it here to keep the
# cascade taxonomies in lockstep.
from pulpo.ranker_legs.value import MACRO_ZONE

# PRD §FR-7.5 — at least 10 active listings per pool to compute a median.
MIN_LISTINGS_PER_ZONE = 10

# PRD §FR-7.5 — max days_listed before excluding from comp pool.
MAX_DAYS_LISTED_FOR_COMPS = 365

# Fallback country code when a listing lacks an explicit country. Today
# the pipeline runs SV-only; MC-3+ tags every listing with `country` so
# this default is increasingly defensive.
DEFAULT_COUNTRY = "SV"


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


def _bucket_key(li: Any) -> tuple[str, str] | None:
    """(zone, property_type) bucket key for the zone tier.
    None if the listing has no resolved zone."""
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


def _stats_for(values: list[float]) -> dict:
    """Compute the distribution stats for a comp pool."""
    return {
        "median": round(statistics.median(values), 2),
        "min":    round(min(values), 2),
        "max":    round(max(values), 2),
        "n":      len(values),
    }


def compute_zone_medians(listings: list[Any]) -> dict[tuple[str, str, str], dict]:
    """Per-tier distribution stats over price_per_m2.

    Returns a dict keyed by (tier, scope_slug, property_type) where tier
    is one of "zone" / "macro" / "country" and scope_slug is the zone
    slug / macro-region slug / ISO-3166 alpha-2 country code respectively.
    Buckets below MIN_LISTINGS_PER_ZONE at any tier are excluded.

    Example keys:
      ("zone",    "el-tunco",         "land")
      ("macro",   "central-pacific",  "land")
      ("country", "SV",               "land")

    Listings contribute to every applicable tier — a listing in El Tunco
    fills the zone pool, the central-pacific macro pool, AND the SV
    country pool. apply_zone_metrics picks the most-specific qualifying
    tier per-listing on the read side.
    """
    by_zone:    dict[tuple[str, str], list[float]] = {}
    by_macro:   dict[tuple[str, str], list[float]] = {}
    by_country: dict[tuple[str, str], list[float]] = {}

    for li in listings:
        if not _is_active(li):
            continue
        ppm = float(_g(li, "price_per_m2"))
        ptype = _g(li, "property_type") or "land"
        country = _g(li, "country") or DEFAULT_COUNTRY

        zone = _g(li, "zone")
        if isinstance(zone, str) and zone and zone != "unresolved":
            by_zone.setdefault((zone, ptype), []).append(ppm)
            macro = MACRO_ZONE.get(zone)
            if macro:
                by_macro.setdefault((macro, ptype), []).append(ppm)

        # Country tier accepts every active listing with a $/m², even
        # zone-less ones. That makes the country fallback the broadest
        # safety net so a listing in `unresolved` still gets context.
        by_country.setdefault((country, ptype), []).append(ppm)

    out: dict[tuple[str, str, str], dict] = {}
    for (zone, ptype), vals in by_zone.items():
        if len(vals) >= MIN_LISTINGS_PER_ZONE:
            out[("zone", zone, ptype)] = _stats_for(vals)
    for (macro, ptype), vals in by_macro.items():
        if len(vals) >= MIN_LISTINGS_PER_ZONE:
            out[("macro", macro, ptype)] = _stats_for(vals)
    for (country, ptype), vals in by_country.items():
        if len(vals) >= MIN_LISTINGS_PER_ZONE:
            out[("country", country, ptype)] = _stats_for(vals)
    return out


def _pick_bucket(
    li: Any,
    stats: dict[tuple[str, str, str], dict],
) -> tuple[dict | None, str | None]:
    """Cascade-pick the most-specific qualifying pool for a listing.

    Returns (bucket_stats, scope) where scope is "zone" / "macro" /
    "country" — or (None, None) if no tier qualified.
    """
    ptype = _g(li, "property_type") or "land"
    zone = _g(li, "zone")
    country = _g(li, "country") or DEFAULT_COUNTRY

    if isinstance(zone, str) and zone and zone != "unresolved":
        bucket = stats.get(("zone", zone, ptype))
        if bucket is not None:
            return bucket, "zone"
        macro = MACRO_ZONE.get(zone)
        if macro:
            bucket = stats.get(("macro", macro, ptype))
            if bucket is not None:
                return bucket, "macro"

    bucket = stats.get(("country", country, ptype))
    if bucket is not None:
        return bucket, "country"

    return None, None


def apply_zone_metrics(
    listings: list[Any],
    stats: dict[tuple[str, str, str], dict],
) -> dict:
    """Set zone-comparison fields on each eligible listing:
        - price_vs_zone_median     (USD/m² median of the chosen pool)
        - price_vs_zone_pct        (signed % vs. median; negative = below)
        - zone_price_per_m2_min    (lowest $/m² in the chosen pool)
        - zone_price_per_m2_max    (highest $/m² in the chosen pool)
        - zone_comp_count          (n peers in the chosen pool)
        - zone_comparison_scope    ("zone" | "macro" | "country")

    The cascade picks the most-specific tier whose bucket has ≥
    MIN_LISTINGS_PER_ZONE peers. Listings that don't qualify at any tier
    leave all fields untouched (default None).

    Returns metrics dict with tier-by-tier scoring counts.
    """
    metrics: dict[str, Any] = {
        "buckets_computed":              len(stats),
        "listings_scored":               0,
        "listings_scored_zone":          0,
        "listings_scored_macro":         0,
        "listings_scored_country":       0,
        "listings_skipped_inactive":     0,
        "listings_skipped_no_pool":      0,
    }
    for li in listings:
        if not _is_active(li):
            metrics["listings_skipped_inactive"] += 1
            continue
        bucket, scope = _pick_bucket(li, stats)
        if bucket is None:
            metrics["listings_skipped_no_pool"] += 1
            continue

        ppm = _g(li, "price_per_m2")
        median = bucket["median"]
        # Signed % difference: negative = below median (cheaper), positive = above.
        # Rounded to 1 decimal — sufficient resolution for chip display.
        pct = round(((ppm - median) / median) * 100, 1)
        _set(li, "price_vs_zone_median",     median)
        _set(li, "price_vs_zone_pct",        pct)
        _set(li, "zone_price_per_m2_min",    bucket["min"])
        _set(li, "zone_price_per_m2_max",    bucket["max"])
        _set(li, "zone_comp_count",          bucket["n"])
        _set(li, "zone_comparison_scope",    scope)
        metrics["listings_scored"] += 1
        metrics[f"listings_scored_{scope}"] += 1

    return metrics


def _write_history(
    stats: dict[tuple[str, str, str], dict],
    zone_bucket_sizes: dict[tuple[str, str], int],
    history_path: Path,
) -> None:
    """Append one row per eligible zone-tier bucket to the history JSONL.

    Macro and country tiers are derivable from zone-level rolls, so we
    only telemeter the zone tier — keeps the history file's shape stable
    across the cascade refactor.
    """
    ts = datetime.now(timezone.utc).isoformat()
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as f:
            for (tier, zone, ptype), bucket in stats.items():
                if tier != "zone":
                    continue
                f.write(json.dumps({
                    "ts":              ts,
                    "zone":            zone,
                    "property_type":   ptype,
                    "n_listings":      zone_bucket_sizes.get((zone, ptype), 0),
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

    Side effect: appends one row per eligible zone-tier bucket to
    history_path (default web/data/zone_medians_history.jsonl) for
    trend tracking.
    """
    stats = compute_zone_medians(listings)
    metrics = apply_zone_metrics(listings, stats)

    # Pre-cascade zone bucket sizes (i.e., how many comps each zone
    # bucket has BEFORE the gate is applied). Used for telemetry only.
    zone_bucket_sizes: dict[tuple[str, str], int] = {}
    for li in listings:
        if not _is_active(li):
            continue
        key = _bucket_key(li)
        if key is None:
            continue
        zone_bucket_sizes[key] = zone_bucket_sizes.get(key, 0) + 1

    if history_path is None:
        history_path = (Path(__file__).resolve().parents[1]
                        / "web" / "data" / "zone_medians_history.jsonl")
    _write_history(stats, zone_bucket_sizes, history_path)
    return metrics
