"""
Multi-factor investment ranker for raw beach + recreational land in El Salvador.

Why a multi-factor model?  A pure "cheap-for-zone" scorer (which is what we
shipped first) tells you which listings are mispriced low against their comp
pool — but it punishes prime-location plays at fair price and rewards cheap
parcels in zones nobody is buying. The classic real-estate trap: you get a
nominal "discount" on something with no liquidity and no exit.

Institutional underwriting decomposes asset attractiveness into four legs:

    1. VALUE       — entry price vs comparable sales (your ranker bread-and-butter)
    2. QUALITY     — locational tier + physical attributes (the "A-location premium")
    3. LIQUIDITY   — exit-risk proxy: how fast does this zone turn over?
    4. UPSIDE      — path-of-progress: where is capital flowing next?

We compute each on a 0..100 scale, then combine with editor-tunable weights:

    composite = 0.35*value + 0.25*quality + 0.20*liquidity + 0.20*upside

…and convert the composite to a 1-based position rank (1 = best opportunity).

This intentionally maps to the way a sophisticated SV beach-land investor
would actually frame the trade: a single $1.5M Tunco oceanfront at fair price
can beat five $200k Conchagua interior parcels that LOOK cheap, because the
Tunco asset has lower liquidity risk + a bigger growth multiple — even if
the value-leg score is identical or worse. The composite makes that visible
instead of letting the value leg dominate.

A user who wants the old behavior can re-weight via env vars:
    PULPO_W_VALUE / PULPO_W_QUALITY / PULPO_W_LIQUIDITY / PULPO_W_UPSIDE

(weights renormalize so they don't have to sum to 1.0).
"""
from __future__ import annotations
import os
from bisect import bisect_left
from collections import defaultdict
from typing import Iterable
from .models import Listing


# --- VALUE leg --------------------------------------------------------------
MIN_COMPS = 3
NO_PRICE_VALUE_DEFAULT = 35.0   # neutral-ish if we can't compute $/m² percentile

# --- QUALITY leg ------------------------------------------------------------
# Zone tiers reflect today's market reality, not aspirations.
# A: established, deep buyer pool, premium $/m², resilient through cycles.
# B: secondary but proven; thicker discounts to A but real exit demand.
# C: frontier; cheap but liquidity risk dominates for non-strategic buyers.
ZONE_TIER = {
    # A — Surf City core
    "el-tunco":  "A",
    "el-sunzal": "A",
    "el-zonte":  "A",
    # B — established secondary
    "san-diego":          "B",
    "la-libertad":        "B",
    "puerto-la-libertad": "B",
    "el-cuco":            "B",
    "las-flores":         "B",
    "mizata":             "B",
    # C — frontier / interior / Gulf
    "punta-mango": "C",
    "el-espino":   "C",
    "conchagua":   "C",
    "la-union":    "C",
}
TIER_BASE = {"A": 85, "B": 65, "C": 45}

# --- LIQUIDITY leg ----------------------------------------------------------
# Zones with deeper buyer pools -> faster exit -> higher liquidity score.
# These weights are SV-market judgment calls; tune with real DOM data when
# we have it (Phase 2: track listing -> sold transitions).
ZONE_LIQUIDITY = {
    "el-tunco": 90, "el-sunzal": 88, "el-zonte": 85,
    "san-diego": 75, "la-libertad": 72, "puerto-la-libertad": 72,
    "mizata": 65,
    "el-cuco": 70, "las-flores": 68, "punta-mango": 55,
    "el-espino": 50,
    "conchagua": 45, "la-union": 50,
}

# --- UPSIDE leg -------------------------------------------------------------
# Path-of-progress mapping. Higher = more headroom for $/m² to expand over a
# 5–10 year hold. Calibrated against:
#   * Surf City Phase 2 narrative (eastern coast)
#   * La Unión deep-water port + Bitcoin City discussion (gulf-fonseca)
#   * Already-priced-in core (Tunco/Sunzal/Zonte appreciation slowing)
#   * El Espino still slow vs adjacent corridors
ZONE_UPSIDE = {
    "el-tunco": 60, "el-sunzal": 60, "el-zonte": 65,    # priced-in core
    "san-diego": 75, "la-libertad": 70, "puerto-la-libertad": 70,
    "mizata": 80,                                         # next wave west
    "el-cuco": 85, "las-flores": 88, "punta-mango": 85,   # Surf City Phase 2
    "el-espino": 65,
    "conchagua": 90, "la-union": 92,                      # gulf-fonseca thesis
}

# --- Composite weights ------------------------------------------------------
def _weights() -> tuple[float, float, float, float]:
    def f(name: str, default: float) -> float:
        try: return float(os.environ.get(name, default))
        except ValueError: return default
    wv = f("PULPO_W_VALUE",     0.35)
    wq = f("PULPO_W_QUALITY",   0.25)
    wl = f("PULPO_W_LIQUIDITY", 0.20)
    wu = f("PULPO_W_UPSIDE",    0.20)
    s = wv + wq + wl + wu
    if s <= 0: return 0.35, 0.25, 0.20, 0.20
    return wv / s, wq / s, wl / s, wu / s


# --- helpers ----------------------------------------------------------------
def _percentile_in(sorted_values: list[float], v: float) -> float:
    if not sorted_values: return 50.0
    idx = bisect_left(sorted_values, v)
    return 100.0 * idx / len(sorted_values)


def _value_leg(li: Listing, by_zone, by_macro, global_pool) -> tuple[float, str]:
    """0..100 value score + reason string. Cheaper-for-pool = higher."""
    if li.price_per_m2 is None:
        return NO_PRICE_VALUE_DEFAULT, f"value {NO_PRICE_VALUE_DEFAULT:.0f} (no $/m²)"
    pool, label = _pick_pool(li, by_zone, by_macro, global_pool)
    if not pool:
        return NO_PRICE_VALUE_DEFAULT, f"value {NO_PRICE_VALUE_DEFAULT:.0f} (no comps)"
    pct = _percentile_in(pool, li.price_per_m2)
    li.zone_percentile = round(pct, 1)
    score = max(0.0, min(100.0, 100.0 - pct))
    return score, (
        f"value {score:.0f} (${li.price_per_m2:,.2f}/m² = "
        f"{int(pct)}th pct of {label}, {len(pool)} comps)"
    )


def _quality_leg(li: Listing) -> tuple[float, str]:
    """Zone tier + physical attributes."""
    tier = ZONE_TIER.get(li.zone or "", None)
    base = TIER_BASE.get(tier, 30)   # 30 for unknown
    bonuses = 0
    parts = [f"tier-{tier or '?'} {base}"]
    if li.is_beachfront: bonuses += 10; parts.append("beachfront +10")
    if li.has_paved_access: bonuses += 4; parts.append("paved +4")
    if li.has_water: bonuses += 3; parts.append("water +3")
    if li.has_power: bonuses += 3; parts.append("power +3")
    score = max(0.0, min(100.0, base + bonuses))
    return score, "quality " + str(int(score)) + " (" + ", ".join(parts) + ")"


def _liquidity_leg(li: Listing) -> tuple[float, str]:
    """Zone exit-risk proxy + freshness penalty."""
    base = ZONE_LIQUIDITY.get(li.zone or "", 35)   # unknown zone is illiquid
    parts = [f"zone-base {base}"]
    # Long DOM is a yellow flag — listing has been seen and passed on.
    if li.days_listed is not None:
        if li.days_listed > 180:
            base -= 20; parts.append(f"DOM {li.days_listed}d -20")
        elif li.days_listed > 90:
            base -= 10; parts.append(f"DOM {li.days_listed}d -10")
        elif li.days_listed <= 14:
            base += 5; parts.append(f"DOM {li.days_listed}d +5 fresh")
    # Repriced means seller is motivated -> shorter time to clearing price.
    if li.is_repriced:
        base += 5; parts.append("repriced +5")
    score = max(0.0, min(100.0, base))
    return score, "liquidity " + str(int(score)) + " (" + ", ".join(parts) + ")"


def _upside_leg(li: Listing) -> tuple[float, str]:
    """Path-of-progress / growth-corridor headroom."""
    base = ZONE_UPSIDE.get(li.zone or "", 50)
    parts = [f"zone-upside {base}"]
    # Beachfront in any tier gets a small upside bump (development premium scales).
    bonus = 0
    if li.is_beachfront: bonus += 5; parts.append("beachfront +5")
    # Large parcels in growth zones offer subdivision optionality.
    if li.area_m2 and li.area_m2 >= 50_000 and base >= 75:
        bonus += 5; parts.append("scale +5 (subdividable in growth zone)")
    score = max(0.0, min(100.0, base + bonus))
    return score, "upside " + str(int(score)) + " (" + ", ".join(parts) + ")"


def _pick_pool(li, by_zone, by_macro, global_pool):
    if li.zone and len(by_zone.get(li.zone, [])) >= MIN_COMPS:
        return by_zone[li.zone], li.zone
    macro = MACRO_ZONE.get(li.zone or "")
    if macro and len(by_macro.get(macro, [])) >= MIN_COMPS:
        return by_macro[macro], f"{macro} (macro)"
    if len(global_pool) >= MIN_COMPS:
        return global_pool, "global"
    return [], ""


# Macro-zone groups for value-leg comp-pool fallback.
MACRO_ZONE = {
    "el-tunco": "central-pacific", "el-sunzal": "central-pacific",
    "el-zonte": "central-pacific", "san-diego": "central-pacific",
    "mizata": "central-pacific", "puerto-la-libertad": "central-pacific",
    "la-libertad": "central-pacific",
    "el-cuco": "eastern-pacific", "las-flores": "eastern-pacific",
    "punta-mango": "eastern-pacific", "el-espino": "eastern-pacific",
    "conchagua": "gulf-fonseca", "la-union": "gulf-fonseca",
}


def rank(listings: Iterable[Listing]) -> list[Listing]:
    """Compute composite investment score + 1-based rank, sort, return."""
    items = list(listings)

    # Build comp pools for the value leg.
    by_zone: dict[str, list[float]] = defaultdict(list)
    by_macro: dict[str, list[float]] = defaultdict(list)
    global_pool: list[float] = []
    for li in items:
        if li.price_per_m2 is None: continue
        global_pool.append(li.price_per_m2)
        if li.zone:
            by_zone[li.zone].append(li.price_per_m2)
            macro = MACRO_ZONE.get(li.zone)
            if macro: by_macro[macro].append(li.price_per_m2)
    for z in by_zone: by_zone[z].sort()
    for m in by_macro: by_macro[m].sort()
    global_pool.sort()

    wv, wq, wl, wu = _weights()

    for li in items:
        v, v_reason = _value_leg(li, by_zone, by_macro, global_pool)
        q, q_reason = _quality_leg(li)
        l, l_reason = _liquidity_leg(li)
        u, u_reason = _upside_leg(li)

        composite = wv * v + wq * q + wl * l + wu * u
        composite = round(composite, 2)

        li.rank_score = composite
        li.rank_reasons = [
            v_reason, q_reason, l_reason, u_reason,
            f"weights V{wv:.2f} Q{wq:.2f} L{wl:.2f} U{wu:.2f} → {composite:.1f}",
        ]
        # Component breakdown for downstream UI / sorting flexibility.
        li.value_score     = round(v, 1)
        li.quality_score   = round(q, 1)
        li.liquidity_score = round(l, 1)
        li.upside_score    = round(u, 1)

    items.sort(key=lambda x: (x.rank_score or 0), reverse=True)

    # Assign 1-based position rank after the sort.
    for i, li in enumerate(items, start=1):
        li.rank = i

    return items
