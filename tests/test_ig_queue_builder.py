"""Tests for automation/ig_queue_builder.py.

Strategy: build a synthetic candidates pool covering all the shelf
selectors, then assert the right listing lands in each day.  The render
+ caption are injected via mocks so no Chromium / no DeepSeek.
"""
from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_queue_builder import (   # noqa: E402
    BATCH_1_PLAN,
    CENTRAL_DEPARTMENTS,
    ORIENTE_DEPARTMENTS,
    SURF_CITY_ZONES,
    _band_label,
    _pick_by_bargain_pct,
    _pick_by_ppm_in_surf_city,
    _pick_by_rank_score,
    _pick_diversify_region,
    _pick_top5_band,
    _pick_top5_zone,
    _region_of,
    _resolve_intro_listings,
    _resolve_wrap_listings,
    _schedule_dates,
    _select,
    _short_price,
    build_queue,
    main as queue_main,
)
from automation.ig_poster import (   # noqa: E402
    BIG_NUMBER, MAP_MARK, POST_IT, RECEIPT, STICKER, TYPO_MAX,
)


# ── fixtures: a candidate pool covering all shelves ───────────────────

def _c(
    lid: str, *, rank=10, rank_score=80.0, zone="el-tunco",
    department="La Libertad", price=300000, area=5000, ppm=None,
    pvp=0.0, comp_count=15, zone_median=None,
) -> dict:
    return {
        "listing_id":          lid,
        "source":              lid.split("__")[0],
        "source_id":           lid.split("__", 1)[1],
        "rank":                rank,
        "rank_score":          rank_score,
        "zone":                zone,
        "department":          department,
        "property_type":       "land",
        "subcategory":         "land",
        "photos_count":        6,
        "price_usd":           price,
        "area_m2":             area,
        "price_per_m2":        ppm if ppm is not None else price / area,
        "price_vs_zone_pct":   pvp,
        "price_vs_zone_median": zone_median or (price / area * 1.5),
        "zone_comp_count":     comp_count,
        "dist_beach_km":       1.4,
    }


def _candidates_pool() -> list[dict]:
    return [
        # SURF CITY zone — six entries spanning bands
        _c("a__01", rank=2,  rank_score=95.0, zone="el-zonte",   price=667000, area=19000),  # TOP RANK 1
        _c("a__02", rank=4,  rank_score=92.0, zone="el-tunco",   price=455000, area=4555),   # TOP RANK 2
        _c("a__03", rank=20, rank_score=80.0, zone="el-sunzal",  price=140000, area=698),
        _c("a__04", rank=30, rank_score=75.0, zone="la-libertad", price=280000, area=5374, ppm=52),  # best ppm
        _c("a__05", rank=40, rank_score=72.0, zone="tamanique",  price=340000, area=7000),
        _c("a__06", rank=50, rank_score=70.0, zone="el-zonte",   price=500000, area=28000),
        # ORIENTE — bargain alerts + diversifier
        _c("b__01", rank=6,  rank_score=88.0, zone="el-cuco",    department="San Miguel",  price=2_500_000, area=210000, pvp=-93.0),  # bargain 1
        _c("b__02", rank=11, rank_score=85.0, zone="san-miguel-zone", department="San Miguel", price=225000, area=16000, pvp=-45.0),  # bargain 2
        _c("b__03", rank=14, rank_score=83.0, zone="conchagua",  department="La Unión",   price=1_100_000, area=77000),  # diversify_oriente
        _c("b__04", rank=80, rank_score=60.0, zone="usulutan",   department="Usulután",   price=95000,  area=4200),
        # CENTRAL — diversify_central candidate
        _c("c__01", rank=15, rank_score=82.0, zone="san-martin", department="San Salvador", price=500000, area=28000),
        # extra padding to reach 5 in bands
        _c("a__07", rank=60, rank_score=68.0, zone="el-tunco",   price=300000, area=3493),
        _c("a__08", rank=70, rank_score=66.0, zone="el-sunzal",  price=900000, area=1449),
        _c("a__09", rank=90, rank_score=64.0, zone="tamanique",  price=550000, area=4000),
    ]


def _candidates_payload() -> dict:
    return {"version": 1, "candidates": _candidates_pool()}


# ── region detection ──────────────────────────────────────────────────

def test_region_of_oriente():
    assert _region_of({"department": "San Miguel"}) == "oriente"
    assert _region_of({"department": "La Unión"}) == "oriente"
    assert _region_of({"department": "Usulután"}) == "oriente"


def test_region_of_central():
    assert _region_of({"department": "La Libertad"}) == "central"
    assert _region_of({"department": "San Salvador"}) == "central"


def test_region_of_unknown():
    assert _region_of({"department": "Atlántida"}) is None
    assert _region_of({}) is None


def test_region_sets_are_disjoint():
    """A department can't be in two regions — would silently bias the
    diversifier picks."""
    assert ORIENTE_DEPARTMENTS.isdisjoint(CENTRAL_DEPARTMENTS)


def test_surf_city_zones_canonical():
    """If the v4 mockup ever shifts what counts as Surf City, update
    this set so the top5_zone:surf_city shelf matches the design."""
    for canon in ("el-tunco", "el-sunzal", "el-zonte"):
        assert canon in SURF_CITY_ZONES


# ── selectors ──────────────────────────────────────────────────────────

def test_pick_by_rank_score_returns_top_unused():
    """Each call picks the next best unused.  Sequence semantics:
    top_rank_1 + top_rank_2 are sequenced by their order in the plan
    (PASS 1 iteration), not by an explicit :N argument."""
    pool = _candidates_pool()
    used: set[str] = set()
    pick1 = _pick_by_rank_score(pool, used)
    assert pick1["listing_id"] == "a__01"   # rank_score=95
    used.add(pick1["listing_id"])
    pick2 = _pick_by_rank_score(pool, used)
    assert pick2["listing_id"] == "a__02"   # rank_score=92


def test_pick_by_rank_score_exhausted():
    assert _pick_by_rank_score([], set()) is None
    assert _pick_by_rank_score(_candidates_pool(),
                               used={c["listing_id"] for c in _candidates_pool()}) is None


def test_pick_by_bargain_pct_only_returns_below_threshold():
    """Only listings ≤ −20% qualify; others ignored.  Two bargains in
    the fixture, third call returns None."""
    pool = _candidates_pool()
    used: set[str] = set()
    b1 = _pick_by_bargain_pct(pool, used)
    assert b1["listing_id"] == "b__01"  # −93%
    used.add(b1["listing_id"])
    b2 = _pick_by_bargain_pct(pool, used)
    assert b2["listing_id"] == "b__02"  # −45%
    used.add(b2["listing_id"])
    b3 = _pick_by_bargain_pct(pool, used)
    assert b3 is None  # no third bargain in fixture


def test_pick_by_ppm_in_surf_city():
    pool = _candidates_pool()
    best = _pick_by_ppm_in_surf_city(pool, set())
    # Cheapest $/m² across SURF_CITY_ZONES.  Computed inline to avoid
    # baking in a brittle ID — the test is about the algorithm, not the
    # specific fixture.
    surf_city = [c for c in pool if c["zone"] in SURF_CITY_ZONES]
    expected = min(surf_city, key=lambda c: c["price_per_m2"])
    assert best["listing_id"] == expected["listing_id"]


def test_pick_by_ppm_excludes_used():
    pool = _candidates_pool()
    best = _pick_by_ppm_in_surf_city(pool, used={"a__04"})
    # Next cheapest in surf city should be... a__06 (500k/28k ≈ 17.8) or
    # a__01 (667k/19k ≈ 35).  Compute on the fly.
    others = [
        c for c in pool
        if c["zone"] in SURF_CITY_ZONES and c["listing_id"] != "a__04"
    ]
    expected = min(others, key=lambda c: c["price_per_m2"])
    assert best["listing_id"] == expected["listing_id"]


def test_pick_top5_zone_surf_city_returns_at_most_5():
    pool = _candidates_pool()
    rows = _pick_top5_zone(pool, "surf_city")
    assert len(rows) == 5
    # Sorted by rank_score desc — first one is a__01 (rank_score=95)
    assert rows[0]["listing_id"] == "a__01"


def test_pick_top5_zone_oriente_filters_by_region():
    pool = _candidates_pool()
    rows = _pick_top5_zone(pool, "oriente")
    # 4 oriente listings: b__01..04
    assert len(rows) == 4
    assert {r["listing_id"] for r in rows} == {"b__01", "b__02", "b__03", "b__04"}


def test_pick_top5_band():
    pool = _candidates_pool()
    rows = _pick_top5_band(pool, 0, 300000)   # under $300K
    # Eligible: a__03 ($140k), a__07 ($300k border excluded?), b__02 ($225k), b__04 ($95k)
    # Border: 300000 is hi-exclusive → a__07 ($300k) excluded.
    ids = {r["listing_id"] for r in rows}
    assert "a__03" in ids and "b__02" in ids and "b__04" in ids
    assert "a__07" not in ids  # boundary: hi-exclusive


def test_pick_diversify_region_picks_best_unused():
    pool = _candidates_pool()
    # Mark b__01 + b__02 + b__03 as used — diversify_oriente should fall
    # back to b__04.
    pick = _pick_diversify_region(pool, "oriente", used={"b__01", "b__02", "b__03"})
    assert pick["listing_id"] == "b__04"


def test_pick_diversify_region_falls_back_when_all_used():
    pool = _candidates_pool()
    # All oriente used: still picks best of the region (graceful).
    used = {f"b__0{i}" for i in range(1, 5)}
    pick = _pick_diversify_region(pool, "oriente", used=used)
    assert pick is not None
    assert _region_of(pick) == "oriente"


# ── _select dispatcher ────────────────────────────────────────────────

def test_select_unknown_spec_raises():
    with pytest.raises(ValueError):
        _select("bogus:thing", _candidates_pool(), set())


def test_select_multi_returns_none_placeholder():
    """multi shelves resolve in PASS 2 — selector returns (None, [])."""
    primary, listings = _select("multi:intro", _candidates_pool(), set())
    assert primary is None
    assert listings == []


# ── carousel resolvers ────────────────────────────────────────────────

def test_resolve_intro_listings_uses_zone_variety():
    items = [
        {"_primary_candidate": _c(f"x__{i:02d}", zone=z)}
        for i, z in enumerate(["el-zonte", "el-tunco", "el-cuco", "conchagua", "san-martin", "usulutan"])
    ]
    chosen = _resolve_intro_listings(items, _candidates_pool())
    zones = [c["zone"] for c in chosen]
    assert len(zones) == 6
    assert len(set(zones)) == 6  # all distinct


def test_resolve_intro_pads_with_top_rank_when_short():
    items = [{"_primary_candidate": _c("x__01", zone="el-zonte")}]
    chosen = _resolve_intro_listings(items, _candidates_pool())
    assert len(chosen) == 6


def test_resolve_wrap_listings_top6_by_rank_score():
    items = [
        {"_primary_candidate": _c(f"x__{i:02d}", rank_score=score)}
        for i, score in enumerate([95, 90, 85, 80, 75, 70, 65, 60])
    ]
    chosen = _resolve_wrap_listings(items)
    assert [c["rank_score"] for c in chosen] == [95, 90, 85, 80, 75, 70]


# ── scheduling ────────────────────────────────────────────────────────

def test_schedule_dates_count_and_increment():
    dates = _schedule_dates(date(2026, 6, 1), 14)
    assert len(dates) == 14
    # Each is 24h apart, in UTC (19:00 CST = 01:00 UTC next day)
    delta = (dates[1] - dates[0])
    assert delta.days == 1


def test_schedule_dates_at_19_cst_means_01_utc():
    """19:00 CST is UTC-6 → 01:00 UTC next day.  Pin this — IG and the
    cron schedule (PR-4) both read scheduled_for in UTC."""
    dates = _schedule_dates(date(2026, 6, 1), 1)
    # 2026-06-01 19:00 CST = 2026-06-02 01:00 UTC
    assert dates[0].hour == 1
    assert dates[0].day == 2
    assert dates[0].tzinfo.utcoffset(dates[0]).total_seconds() == 0


# ── helpers ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("usd,expected", [
    (140000,    "$140K"),
    (225000,    "$225K"),
    (1_000_000, "$1M"),
    (2_500_000, "$2.5M"),
    (None,      "—"),
    (0,         "—"),
])
def test_short_price(usd, expected):
    assert _short_price(usd) == expected


def test_band_label():
    rows = [_c("x__a", price=140000), _c("x__b", price=500000), _c("x__c", price=300000)]
    assert _band_label(rows) == "$140K — $500K"


def test_band_label_empty():
    assert _band_label([]) == "—"


# ── BATCH_1_PLAN shape ────────────────────────────────────────────────

def test_batch_1_plan_has_14_days():
    assert len(BATCH_1_PLAN) == 14


def test_batch_1_plan_covers_days_1_through_14():
    """Plan tuples are PROCESSING-ordered, not day-ordered (heroes get
    processed before listicles before multis to manage `used` correctly).
    But every day 1..14 must still be present."""
    days = sorted(row[0] for row in BATCH_1_PLAN)
    assert days == list(range(1, 15))


def test_batch_1_plan_shelf_ids_unique():
    shelves = [row[1] for row in BATCH_1_PLAN]
    assert len(set(shelves)) == 14


def test_batch_1_plan_poster_types_valid():
    valid = {TYPO_MAX, STICKER, POST_IT, BIG_NUMBER, RECEIPT, MAP_MARK}
    for _, _, _, ptype, _ in BATCH_1_PLAN:
        assert ptype in valid


# ── build_queue end-to-end with mocks ─────────────────────────────────

def _stub_render(*args, **kwargs):
    """Mock _render_via_playwright — write a tiny byte to the path."""
    output_path = args[4] if len(args) >= 5 else kwargs.get("output_path")
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mock-png")
    return output_path


def _stub_caption(candidate, listing=None, *, poster_type=TYPO_MAX, client=None,
                  overrides=None):
    """Mock caption — never touches the LLM."""
    return f"**Caption for {candidate.get('listing_id')}.**\n\npulpo.club"


def test_build_queue_produces_14_items(tmp_path):
    payload = build_queue(
        _candidates_payload(), [],
        start_date=date(2026, 6, 1),
        output_root=tmp_path,
        skip_render=True,                                # don't even touch Playwright
        caption_generator=_stub_caption,
    )
    assert payload["stats"]["items_built"] == 14
    assert len(payload["items"]) == 14
    # All items have the queue-state defaults set.
    for it in payload["items"]:
        assert it["approved"] is False
        assert it["posted"] is False
        assert it["posted_at"] is None
        assert it["status"] in ("pending", "needs_human")


def test_build_queue_assigns_correct_poster_type_per_day():
    payload = build_queue(
        _candidates_payload(), [],
        start_date=date(2026, 6, 1), skip_render=True,
        caption_generator=_stub_caption,
    )
    by_day = {it["day"]: it for it in payload["items"]}
    assert by_day[1]["poster_type"] == TYPO_MAX
    assert by_day[2]["poster_type"] == STICKER
    assert by_day[3]["poster_type"] == POST_IT
    assert by_day[7]["poster_type"] == BIG_NUMBER
    assert by_day[12]["poster_type"] == MAP_MARK
    assert by_day[14]["poster_type"] == RECEIPT


def test_build_queue_picks_top_rank_for_day_2():
    payload = build_queue(
        _candidates_payload(), [],
        start_date=date(2026, 6, 1), skip_render=True,
        caption_generator=_stub_caption,
    )
    day_2 = next(it for it in payload["items"] if it["day"] == 2)
    # a__01 (rank_score=95) is the top — should be day 2's hero.
    assert day_2["primary_listing_id"] == "a__01"


def test_build_queue_picks_bargains_for_days_3_and_11():
    payload = build_queue(
        _candidates_payload(), [],
        start_date=date(2026, 6, 1), skip_render=True,
        caption_generator=_stub_caption,
    )
    d3 = next(it for it in payload["items"] if it["day"] == 3)
    d11 = next(it for it in payload["items"] if it["day"] == 11)
    assert d3["primary_listing_id"] == "b__01"   # −93%
    assert d11["primary_listing_id"] == "b__02"  # −45%


def test_build_queue_heroes_dont_repeat_across_single_listing_shelves():
    """top_rank_1 + top_rank_2 + bargain_1 + bargain_2 + best_ppm +
    diversify_* must all use distinct listings."""
    payload = build_queue(
        _candidates_payload(), [],
        start_date=date(2026, 6, 1), skip_render=True,
        caption_generator=_stub_caption,
    )
    hero_shelves = {
        "top_rank_1", "top_rank_2", "bargain_1", "bargain_2",
        "best_ppm", "diversify_oriente", "diversify_central",
    }
    hero_ids = [
        it["primary_listing_id"] for it in payload["items"]
        if it["shelf"] in hero_shelves and it["primary_listing_id"]
    ]
    assert len(hero_ids) == len(set(hero_ids)), (
        f"hero shelves reused a listing: {hero_ids}"
    )


def test_build_queue_renders_posters_via_injected_renderer(tmp_path):
    renderer = MagicMock(side_effect=_stub_render)
    build_queue(
        _candidates_payload(), [],
        start_date=date(2026, 6, 1),
        output_root=tmp_path,
        skip_render=False,
        caption_generator=_stub_caption,
        poster_renderer=renderer,
    )
    # All 14 should have invoked the renderer (none should fall through
    # to the real Playwright path).
    assert renderer.call_count == 14


def test_build_queue_caption_lint_flags_needs_human(tmp_path):
    """A caption that contains a banned word should flip status →
    needs_human, even if rendering succeeds.  Specifically test the
    items that had a successfully-resolved primary candidate (multi
    shelves can also be needs_human from a missing primary; we filter
    those out for this assertion)."""
    bad_caption = "**Una premium oportunidad única en El Zonte.**"

    def _dirty_caption(*a, **kw):
        return bad_caption

    payload = build_queue(
        _candidates_payload(), [],
        start_date=date(2026, 6, 1),
        output_root=tmp_path, skip_render=True,
        caption_generator=_dirty_caption,
    )
    # Filter to items that DID get a caption-render path (primary
    # resolved) and got flagged.  Those must have lint_violations
    # populated — that's the contract the admin widget depends on.
    flagged_with_caption = [
        it for it in payload["items"]
        if it["status"] == "needs_human" and it["primary_listing_id"]
    ]
    assert flagged_with_caption, "no flagged items with captions — pool broken?"
    assert all(it["lint_violations"] for it in flagged_with_caption)


def test_build_queue_writes_assets_dir_per_item():
    payload = build_queue(
        _candidates_payload(), [],
        start_date=date(2026, 6, 1), skip_render=True,
        caption_generator=_stub_caption,
    )
    paths = [it["assets_dir"] for it in payload["items"]]
    # Per-item directory: drop_01/d01__intro, drop_01/d02__top_rank_1, ...
    assert all("drop_01" in p for p in paths)
    assert "d01__intro" in paths[0]
    assert "d14__wrap" in paths[-1]


def test_build_queue_includes_carousel_paths_for_receipt_items():
    payload = build_queue(
        _candidates_payload(), [],
        start_date=date(2026, 6, 1), skip_render=True,
        caption_generator=_stub_caption,
    )
    receipt_items = [it for it in payload["items"] if it["poster_type"] == RECEIPT]
    assert receipt_items, "test pool must produce some receipts"
    for it in receipt_items:
        # Receipt listicles should reference multiple listings.
        assert len(it["listing_ids"]) > 1


def test_build_queue_empty_candidates_raises():
    with pytest.raises(ValueError):
        build_queue({"version": 1, "candidates": []}, [])


# ── CLI ────────────────────────────────────────────────────────────────

def test_main_writes_queue_with_skip_render_skip_llm(tmp_path):
    """Smoke test the CLI end-to-end with both heavy paths skipped."""
    cand_path = tmp_path / "candidates.json"
    cand_path.write_text(json.dumps(_candidates_payload()))
    ranked_path = tmp_path / "ranked.json"
    ranked_path.write_text("[]")
    queue_path = tmp_path / "queue.json"

    rc = queue_main([
        "--candidates", str(cand_path),
        "--ranked",     str(ranked_path),
        "--output",     str(queue_path),
        "--assets-dir", str(tmp_path / "assets"),
        "--start-date", "2026-06-01",
        "--skip-render",
        "--skip-llm",
    ])
    assert rc == 0
    written = json.loads(queue_path.read_text())
    assert written["stats"]["items_built"] == 14


def test_main_handles_missing_inputs(tmp_path):
    rc = queue_main([
        "--candidates", str(tmp_path / "nope.json"),
        "--ranked",     str(tmp_path / "nope.json"),
        "--output",     str(tmp_path / "out.json"),
    ])
    assert rc == 2
