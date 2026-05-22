"""Filter a global ranked.json list down to the slice that matches a Preference.

Keeps the ranker stateless (pulpo/ranker.py): the global rank is computed once,
this module slices. Per-user re-ranking would be a future optimisation; for the
fortnightly newsletter, slice + cap is enough.

The contract: input is ranked listings (dicts as written by automation/run.py),
already sorted ascending by `rank` (1 = best). Output is the same list filtered
by Preference, preserving rank order. Cap is applied by the caller.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .types import Preference


CATEGORY_PREDICATES = {
    # Mirrors the keys in web/app/lib/categories.ts. Kept lean — only what
    # makes sense as a newsletter filter (UX-side "new_this_week" becomes
    # "new_in_window" here because the newsletter window is the issue's
    # eligibility window, not a fixed 7 days).
    "beachfront":     lambda listing: bool(listing.get("is_beachfront")) or bool(listing.get("is_walk_to_beach")),
    "water_features": lambda listing: bool(listing.get("has_water_body")) or bool(listing.get("is_beachfront")),
    "ocean_view":     lambda listing: bool(listing.get("has_ocean_view")),
    "mountain_view":  lambda listing: bool(listing.get("has_mountain_view")),
    "flat_buildable": lambda listing: bool(listing.get("is_flat")) and bool(listing.get("has_paved_access")),
    "build_ready":    lambda listing: bool(listing.get("has_power")) and bool(listing.get("has_water")),
    "commercial":     lambda listing: bool(listing.get("is_commercial")),
    "under_50k":      lambda listing: (listing.get("price_usd") or 1e12) < 50_000,
    "under_100k":     lambda listing: (listing.get("price_usd") or 1e12) < 100_000,
    "price_drops":    lambda listing: bool(listing.get("is_repriced")),
    "motivated_sellers": lambda listing: bool(listing.get("is_motivated")),
}


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_new_in_window(listing: dict, window_start: datetime) -> bool:
    """A listing is 'new this issue' if it was first seen on or after the window start."""
    fs = _parse_iso(listing.get("first_seen_at"))
    if fs is None:
        return False
    if fs.tzinfo is None:
        fs = fs.replace(tzinfo=timezone.utc)
    return fs >= window_start


def apply_preference(listings: Iterable[dict], pref: Preference) -> list[dict]:
    """Filter listings to those that match the preference.

    An empty Preference field is a passthrough — "no opinion" means we keep
    everything along that axis. Matching is conjunctive across axes (zone AND
    price AND type AND categories), disjunctive within a list axis.
    """
    out: list[dict] = []
    zones_set = set(pref.zones)
    depts_set = {d.lower() for d in pref.departments}
    types_set = set(pref.property_types)
    cats = [CATEGORY_PREDICATES[k] for k in pref.categories if k in CATEGORY_PREDICATES]

    for listing in listings:
        if zones_set and (listing.get("zone") not in zones_set):
            continue
        if depts_set:
            dep = (listing.get("department") or "").lower()
            if dep not in depts_set:
                continue
        if types_set and (listing.get("property_type") not in types_set):
            continue
        price = listing.get("price_usd")
        if pref.max_price_usd is not None and price is not None and price > pref.max_price_usd:
            continue
        if pref.min_price_usd is not None and price is not None and price < pref.min_price_usd:
            continue
        if cats and not all(pred(listing) for pred in cats):
            continue
        out.append(listing)
    return out


def select_picks(
    listings: list[dict],
    *,
    pref: Preference,
    excluded_source_ids: set[str],
    window_start: datetime,
    top_n: int = 10,
) -> tuple[list[dict], list[dict]]:
    """Pick the top-N for the issue, plus a "skip" candidate.

    Returns (kept, skip_candidates). `kept` is the in-rank-order top-N after
    exclusion. `skip_candidates` is a small set of stale/borderline listings
    the commentary stage can choose from to write the "skip this one" block.

    Exclusion rule: a previously-sent source_id is excluded UNLESS the listing
    is currently flagged `is_repriced=True`. That allows a repeat to come back
    as a "price moved" story (different angle, not a duplicate).
    """
    filtered = apply_preference(listings, pref)

    kept: list[dict] = []
    for listing in filtered:
        sid = f"{listing.get('source')}:{listing.get('source_id')}"
        if sid in excluded_source_ids and not listing.get("is_repriced"):
            continue
        kept.append(listing)
        if len(kept) >= top_n:
            break

    # Skip candidates: stale (>=90 DOM), borderline data quality, or in-pool
    # listings ranked just outside the cut. Up to 5; commentary picks one.
    skip_candidates: list[dict] = []
    for listing in filtered:
        if listing in kept:
            continue
        if (listing.get("days_listed") or 0) >= 90:
            skip_candidates.append(listing)
        elif (listing.get("data_quality_score") or 1.0) < 0.55:
            skip_candidates.append(listing)
        if len(skip_candidates) >= 5:
            break

    # Mark "new this fortnight" inline — render_html reads this flag.
    for listing in kept:
        listing["_is_new_window"] = is_new_in_window(listing, window_start)

    return kept, skip_candidates
