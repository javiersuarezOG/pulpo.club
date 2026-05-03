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
    # Segment by (property_type, zone) so houses don't pollute the land $/m²
    # distribution — a 6-bed mansion skews the percentile for raw lots.
    by_zone: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_macro: dict[tuple[str, str], list[float]] = defaultdict(list)
    global_pool: dict[str, list[float]] = defaultdict(list)
    for li in listings:
        if li.price_per_m2 is None:
            continue
        pt = li.property_type or "land"
        global_pool[pt].append(li.price_per_m2)
        if li.zone:
            by_zone[(pt, li.zone)].append(li.price_per_m2)
            macro = MACRO_ZONE.get(li.zone)
            if macro:
                by_macro[(pt, macro)].append(li.price_per_m2)
    for k in by_zone:
        by_zone[k].sort()
    for k in by_macro:
        by_macro[k].sort()
    for k in global_pool:
        global_pool[k].sort()
    return by_zone, by_macro, global_pool


def _pick_pool(li, by_zone, by_macro, global_pool):
    pt = li.property_type or "land"
    if li.zone and len(by_zone.get((pt, li.zone), [])) >= MIN_COMPS:
        return by_zone[(pt, li.zone)], f"{li.zone} {pt}"
    macro = MACRO_ZONE.get(li.zone or "")
    if macro and len(by_macro.get((pt, macro), [])) >= MIN_COMPS:
        return by_macro[(pt, macro)], f"{macro} {pt} (macro)"
    gpool = global_pool.get(pt, [])
    if len(gpool) >= MIN_COMPS:
        return gpool, f"global {pt}"
    return [], ""


class ValueLeg:
    slug = "value"
    weight = 0.40
    env_weight_key = "PULPO_W_VALUE"

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        # Build pools lazily from comp_pool each call (small N, fast)
        by_zone, by_macro, global_pool = _build_pools(comp_pool)
        if listing.price_per_m2 is None:
            return NO_PRICE_VALUE_DEFAULT, f"value {NO_PRICE_VALUE_DEFAULT:.0f} (no $/m²)"
        pool, label = _pick_pool(listing, by_zone, by_macro, global_pool)
        if not pool:
            return NO_PRICE_VALUE_DEFAULT, f"value {NO_PRICE_VALUE_DEFAULT:.0f} (no comps)"
        pct = _percentile_in(pool, listing.price_per_m2)
        listing.zone_percentile = round(pct, 1)
        s = max(0.0, min(100.0, 100.0 - pct))
        return s, (
            f"value {s:.0f} (${listing.price_per_m2:,.2f}/m² = "
            f"{int(pct)}th pct of {label}, {len(pool)} comps)"
        )


register(RANKER_LEGS, "value", ValueLeg())
