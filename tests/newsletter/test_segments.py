"""Filter + select tests — the slice that produces a recipient's top-10."""

from __future__ import annotations

from datetime import datetime, timezone

from automation.newsletter.segments import (
    apply_preference,
    is_new_in_window,
    select_picks,
)
from automation.newsletter.types import Preference


def test_empty_preference_is_passthrough(ranked_pool):
    out = apply_preference(ranked_pool, Preference())
    assert len(out) == len(ranked_pool)


def test_zone_filter_disjunctive(ranked_pool):
    out = apply_preference(ranked_pool, Preference(zones=["el-zonte", "el-tunco"]))
    zones = {listing["zone"] for listing in out}
    assert zones <= {"el-zonte", "el-tunco"}
    assert len(out) == 20  # 10 el-zonte + 10 el-tunco from the fixture


def test_department_filter_case_insensitive(ranked_pool):
    out = apply_preference(ranked_pool, Preference(departments=["la libertad"]))
    departments = {listing["department"] for listing in out}
    assert departments == {"La Libertad"}


def test_property_type_filter_excludes_houses(ranked_pool):
    out = apply_preference(ranked_pool, Preference(property_types=["land"]))
    assert all(listing["property_type"] == "land" for listing in out)


def test_max_price_excludes_above_band(ranked_pool):
    out = apply_preference(ranked_pool, Preference(max_price_usd=200_000))
    assert all(listing["price_usd"] <= 200_000 for listing in out)


def test_categories_conjunctive_within_axis(ranked_pool):
    out = apply_preference(ranked_pool, Preference(categories=["build_ready", "under_100k"]))
    for listing in out:
        assert listing["price_usd"] < 100_000
        assert listing["has_power"] and listing["has_water"]


def test_select_picks_excludes_seen_unless_repriced(ranked_pool):
    # Mark rank=3 as repriced; rank=2 as not.
    for listing in ranked_pool:
        if listing["rank"] == 2:
            listing["is_repriced"] = False
        if listing["rank"] == 3:
            listing["is_repriced"] = True
    seen = {f"{listing['source']}:{listing['source_id']}" for listing in ranked_pool if listing["rank"] in (2, 3)}
    kept, _ = select_picks(
        ranked_pool,
        pref=Preference(),
        excluded_source_ids=seen,
        window_start=datetime(2026, 5, 1, tzinfo=timezone.utc),
        top_n=10,
    )
    kept_ranks = [listing["rank"] for listing in kept]
    assert 2 not in kept_ranks                  # excluded, not repriced
    assert 3 in kept_ranks                      # excluded but repriced → back in


def test_select_picks_skip_candidates_picks_stale(ranked_pool):
    # Filter by department so the stale listing (zone=la-libertad, dep=La Libertad)
    # is part of the matching pool but ranks lower than the freshly-listed picks.
    _, skip = select_picks(
        ranked_pool,
        pref=Preference(departments=["La Libertad"], property_types=["land"]),
        excluded_source_ids=set(),
        window_start=datetime(2026, 5, 1, tzinfo=timezone.utc),
        top_n=10,
    )
    # The stale listing in the fixture has days_listed=145 and dq=0.5
    assert any(listing.get("rank") == 99 for listing in skip)


def test_is_new_in_window():
    listing = {"first_seen_at": "2026-05-15T00:00:00+00:00"}
    assert is_new_in_window(listing, datetime(2026, 5, 1, tzinfo=timezone.utc)) is True
    assert is_new_in_window(listing, datetime(2026, 5, 16, tzinfo=timezone.utc)) is False
    assert is_new_in_window({"first_seen_at": None}, datetime(2026, 5, 1, tzinfo=timezone.utc)) is False
