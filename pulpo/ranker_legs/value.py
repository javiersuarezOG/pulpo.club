"""
Value leg — "Price vs Comparable Lots" in user-facing terms.

ARCHITECTURE INVARIANT
======================
The comp pools below are keyed on `(property_type, zone)` tuples — NOT bare
zone strings. This is load-bearing. The scrapers pull every real-estate
listing (houses, condos, mansions, raw land, lots), and `property_type` is
populated by the title-first classifier in pulpo/normalize.py. Without the
type segmentation, a 6-bedroom mansion's $/m² lands in the same percentile
distribution as a vacant lot, dragging the lot's value score artificially
high and the mansion's artificially low.

If a future refactor "simplifies" by collapsing the keys back to
`dict[str, list[float]]` keyed only on zone, the leg will silently start
producing wrong percentiles for both property types. The contract is pinned
by tests in tests/agents/test_ranker_legs.py:
- test_value_segments_houses_from_land_in_same_zone
- test_value_macro_cascade_respects_property_type
- test_value_reason_string_includes_property_type_label

Touch _build_pools / _pick_pool below only if those tests still pass after.
"""
from __future__ import annotations
from bisect import bisect_left
from collections import defaultdict
from typing import TYPE_CHECKING
from pulpo.agents import RANKER_LEGS, register

if TYPE_CHECKING:
    from pulpo.models import Listing

MIN_COMPS = 3
NO_PRICE_VALUE_DEFAULT = 35.0

MACRO_ZONE = {
    "el-tunco": "central-pacific", "el-sunzal": "central-pacific",
    "el-zonte": "central-pacific", "san-diego": "central-pacific",
    "mizata": "central-pacific", "puerto-la-libertad": "central-pacific",
    "la-libertad": "central-pacific",
    "el-cuco": "eastern-pacific", "las-flores": "eastern-pacific",
    "punta-mango": "eastern-pacific", "el-espino": "eastern-pacific",
    "conchagua": "gulf-fonseca", "la-union": "gulf-fonseca",
}


def _percentile_in(sorted_values: list[float], v: float) -> float:
    if not sorted_values:
        return 50.0
    return 100.0 * bisect_left(sorted_values, v) / len(sorted_values)


def _build_pools(listings: list["Listing"]):
    """Build per-(metric, type, zone) comp pools.

    Two metrics, kept separate (mixing them would compare e.g. $80/lot-m²
    of land against $1500/built-m² of a house — same number-line, different
    semantics):
      - lot:   price_per_m2   (the lot $/m². Used by land. Fallback for
               house/condo when built_area_m2 is missing — about 80% of
               bienesraices houses today.)
      - built: price_per_built_m2 (the built $/m². Preferred metric for
               house/condo. Computed in normalize.py when both inputs
               exist.)
    """
    pools: dict = {
        "lot":   {"by_zone": defaultdict(list), "by_macro": defaultdict(list),
                  "global":  defaultdict(list)},
        "built": {"by_zone": defaultdict(list), "by_macro": defaultdict(list),
                  "global":  defaultdict(list)},
    }
    for li in listings:
        pt = li.property_type or "land"
        macro = MACRO_ZONE.get(li.zone or "") if li.zone else None
        if li.price_per_m2 is not None:
            p = pools["lot"]
            p["global"][pt].append(li.price_per_m2)
            if li.zone:
                p["by_zone"][(pt, li.zone)].append(li.price_per_m2)
                if macro:
                    p["by_macro"][(pt, macro)].append(li.price_per_m2)
        ppbm = getattr(li, "price_per_built_m2", None)
        if ppbm is not None:
            p = pools["built"]
            p["global"][pt].append(ppbm)
            if li.zone:
                p["by_zone"][(pt, li.zone)].append(ppbm)
                if macro:
                    p["by_macro"][(pt, macro)].append(ppbm)
    # Sort every pool list once
    for metric_pools in pools.values():
        for tier in metric_pools.values():
            for k in tier:
                tier[k].sort()
    return pools


def _pick_pool_for_metric(li, metric_pools):
    """Cascade: zone → macro → global, all keyed on (property_type, …)."""
    pt = li.property_type or "land"
    by_zone, by_macro, global_pool = (
        metric_pools["by_zone"], metric_pools["by_macro"], metric_pools["global"]
    )
    if li.zone and len(by_zone.get((pt, li.zone), [])) >= MIN_COMPS:
        return by_zone[(pt, li.zone)], f"{li.zone} {pt}"
    macro = MACRO_ZONE.get(li.zone or "")
    if macro and len(by_macro.get((pt, macro), [])) >= MIN_COMPS:
        return by_macro[(pt, macro)], f"{macro} {pt} (macro)"
    gpool = global_pool.get(pt, [])
    if len(gpool) >= MIN_COMPS:
        return gpool, f"global {pt}"
    return [], ""


# ── Backwards-compat shims ──────────────────────────────────────────────
# Older tests/external callers used the (by_zone, by_macro, global_pool)
# triple keyed on lot $/m². Keep the shape so existing tests don't break.

def _build_pools_legacy_lot_only(listings: list["Listing"]):
    pools = _build_pools(listings)
    p = pools["lot"]
    return p["by_zone"], p["by_macro"], p["global"]


def _pick_pool(li, by_zone, by_macro, global_pool):
    return _pick_pool_for_metric(li, {
        "by_zone": by_zone, "by_macro": by_macro, "global": global_pool
    })


class ValueLeg:
    slug = "value"
    weight = 0.40
    env_weight_key = "PULPO_W_VALUE"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        # Build pools lazily from comp_pool each call (small N, fast).
        # The full pool shape lives in `pools["lot"]` and `pools["built"]`.
        pools = _build_pools(comp_pool)
        pt = listing.property_type or "land"

        # Pick the metric. House/condo with a built-area metric → use the
        # built pool (the right comp set: a 200 m² built house at $400k is
        # $2,000/built-m², comparable to other built houses in the zone).
        # Land or house-without-built-area → fall through to the lot pool.
        metric_value: float | None = None
        metric_label = "$/m²"
        metric_pools = pools["lot"]
        if pt in ("house", "condo") and listing.price_per_built_m2 is not None:
            metric_value = listing.price_per_built_m2
            metric_label = "$/built-m²"
            metric_pools = pools["built"]
        elif listing.price_per_m2 is not None:
            metric_value = listing.price_per_m2

        if metric_value is None:
            return NO_PRICE_VALUE_DEFAULT, f"value {NO_PRICE_VALUE_DEFAULT:.0f} (no $/m²)"

        pool, label = _pick_pool_for_metric(listing, metric_pools)
        # Fallback chain — built house with no built-comp pool falls back
        # to the lot pool so a house with built area in a sparse zone
        # still gets some signal. Keeps the scoreless fraction tiny.
        if not pool and metric_pools is pools["built"] and listing.price_per_m2 is not None:
            metric_value = listing.price_per_m2
            metric_label = "$/m² (built fallback)"
            pool, label = _pick_pool_for_metric(listing, pools["lot"])

        if not pool:
            return NO_PRICE_VALUE_DEFAULT, f"value {NO_PRICE_VALUE_DEFAULT:.0f} (no comps)"

        pct = _percentile_in(pool, metric_value)
        listing.zone_percentile = round(pct, 1)
        s = max(0.0, min(100.0, 100.0 - pct))
        return s, (
            f"value {s:.0f} (${metric_value:,.2f}/{metric_label.split('/')[1]} = "
            f"{int(pct)}th pct of {label}, {len(pool)} comps)"
        )


register(RANKER_LEGS, "value", ValueLeg())
