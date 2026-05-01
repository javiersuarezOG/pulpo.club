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
    by_zone: dict[str, list[float]] = defaultdict(list)
    by_macro: dict[str, list[float]] = defaultdict(list)
    global_pool: list[float] = []
    for li in listings:
        if li.price_per_m2 is None:
            continue
        global_pool.append(li.price_per_m2)
        if li.zone:
            by_zone[li.zone].append(li.price_per_m2)
            macro = MACRO_ZONE.get(li.zone)
            if macro:
                by_macro[macro].append(li.price_per_m2)
    for z in by_zone:
        by_zone[z].sort()
    for m in by_macro:
        by_macro[m].sort()
    global_pool.sort()
    return by_zone, by_macro, global_pool


def _pick_pool(li, by_zone, by_macro, global_pool):
    if li.zone and len(by_zone.get(li.zone, [])) >= MIN_COMPS:
        return by_zone[li.zone], li.zone
    macro = MACRO_ZONE.get(li.zone or "")
    if macro and len(by_macro.get(macro, [])) >= MIN_COMPS:
        return by_macro[macro], f"{macro} (macro)"
    if len(global_pool) >= MIN_COMPS:
        return global_pool, "global"
    return [], ""


class ValueLeg:
    slug = "value"
    weight = 0.35
    env_weight_key = "PULPO_W_VALUE"
    _pools_cache: dict = {}  # keyed by id(listings_tuple) — rebuilt per rank() call

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
