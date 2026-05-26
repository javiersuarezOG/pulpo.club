"""
Tests for automation/zone_medians.py — pins the FR-7.5 + cascade contract:

- Bucketing per (zone, property_type)
- Cascade zone → macro → country, each gated at ≥ MIN_LISTINGS_PER_ZONE
- Active-filter exclusions (no price, sold, > 365 days_listed)
- Signed-percent computation for price_vs_zone_pct
- zone_comparison_scope reflects the tier the cascade picked
- Idempotency (recompute each run = same values)
- Mixed-property-type segmentation (house $/m² doesn't pollute land $/m²)
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.zone_medians import (   # noqa: E402
    compute_zone_medians,
    apply_zone_metrics,
    compute_and_apply,
    _is_active,
    _bucket_key,
    MIN_LISTINGS_PER_ZONE,
    MAX_DAYS_LISTED_FOR_COMPS,
)


def _li(zone: str = "el-tunco", property_type: str = "land",
        price_per_m2: float | None = 200.0,
        days_listed: int | None = 30,
        is_sold: bool = False,
        country: str = "SV") -> dict:
    return {
        "zone":            zone,
        "property_type":   property_type,
        "country":         country,
        "price_per_m2":    price_per_m2,
        "days_listed":     days_listed,
        "is_sold":         is_sold,
        "price_vs_zone_median": None,
        "price_vs_zone_pct":    None,
    }


def _bucket(median: float, *, mn: float | None = None,
            mx: float | None = None, n: int = MIN_LISTINGS_PER_ZONE) -> dict:
    """Build a bucket-stats dict for apply_zone_metrics tests. Defaults keep
    min/max equal to the median when callers only care about pct semantics."""
    return {
        "median": median,
        "min":    median if mn is None else mn,
        "max":    median if mx is None else mx,
        "n":      n,
    }


# ── _is_active filter ──────────────────────────────────────────────────

def test_active_basic():
    assert _is_active(_li())


def test_inactive_when_sold():
    assert not _is_active(_li(is_sold=True))


def test_inactive_when_no_price():
    assert not _is_active(_li(price_per_m2=None))


def test_inactive_when_zero_price():
    assert not _is_active(_li(price_per_m2=0))


def test_inactive_when_negative_price():
    assert not _is_active(_li(price_per_m2=-1))


def test_inactive_when_too_old():
    """PRD §FR-7.5 — exclude listings older than MAX_DAYS_LISTED_FOR_COMPS."""
    assert not _is_active(_li(days_listed=MAX_DAYS_LISTED_FOR_COMPS + 1))


def test_active_at_threshold():
    """At-the-threshold listings count (boundary: ≤365)."""
    assert _is_active(_li(days_listed=MAX_DAYS_LISTED_FOR_COMPS))


def test_active_when_days_listed_none():
    """Missing days_listed shouldn't disqualify (some scrapers don't expose it)."""
    assert _is_active(_li(days_listed=None))


# ── _bucket_key ────────────────────────────────────────────────────────

def test_bucket_key_basic():
    assert _bucket_key(_li(zone="el-cuco", property_type="land")) == ("el-cuco", "land")


def test_bucket_key_none_when_zone_missing():
    assert _bucket_key(_li(zone="")) is None
    assert _bucket_key({"zone": None, "property_type": "land"}) is None


def test_bucket_key_none_when_zone_unresolved():
    assert _bucket_key(_li(zone="unresolved")) is None


def test_bucket_key_defaults_property_type_to_land():
    assert _bucket_key({"zone": "el-tunco", "property_type": None}) == ("el-tunco", "land")


# ── compute_zone_medians — tier shape ──────────────────────────────────

def test_compute_returns_tier_keyed_dict():
    """Stats dict is keyed by (tier, scope_slug, property_type)."""
    listings = [_li(price_per_m2=100 + i * 10) for i in range(MIN_LISTINGS_PER_ZONE)]
    stats = compute_zone_medians(listings)
    # Zone tier qualifies
    assert ("zone", "el-tunco", "land") in stats
    # Macro tier also qualifies — el-tunco is in central-pacific
    assert ("macro", "central-pacific", "land") in stats
    # Country tier always qualifies when ≥10 listings exist anywhere in SV
    assert ("country", "SV", "land") in stats


def test_compute_at_min_returns_stats():
    listings = [_li(price_per_m2=p) for p in range(100, 100 + MIN_LISTINGS_PER_ZONE * 10, 10)]
    assert len(listings) == MIN_LISTINGS_PER_ZONE
    stats = compute_zone_medians(listings)
    bucket = stats[("zone", "el-tunco", "land")]
    # Even spread 100, 110, 120, ..., 190 → median is between 140 and 150
    assert 140 <= bucket["median"] <= 150
    assert bucket["min"] == 100.0
    assert bucket["max"] == 190.0
    assert bucket["n"]   == MIN_LISTINGS_PER_ZONE


def test_compute_segments_by_property_type():
    """House $/m² shouldn't pollute land $/m² in the same zone."""
    land_listings  = [_li(price_per_m2=200) for _ in range(MIN_LISTINGS_PER_ZONE)]
    house_listings = [_li(price_per_m2=1000, property_type="house")
                      for _ in range(MIN_LISTINGS_PER_ZONE)]
    stats = compute_zone_medians(land_listings + house_listings)
    assert stats[("zone", "el-tunco", "land")]["median"]  == 200.0
    assert stats[("zone", "el-tunco", "house")]["median"] == 1000.0


def test_compute_excludes_sold_listings():
    listings  = [_li(price_per_m2=100) for _ in range(MIN_LISTINGS_PER_ZONE)]
    listings += [_li(price_per_m2=999, is_sold=True) for _ in range(20)]
    stats = compute_zone_medians(listings)
    bucket = stats[("zone", "el-tunco", "land")]
    assert bucket["median"] == 100.0
    assert bucket["max"]    == 100.0


def test_compute_excludes_stale_listings():
    listings  = [_li(price_per_m2=100) for _ in range(MIN_LISTINGS_PER_ZONE)]
    listings += [_li(price_per_m2=999, days_listed=400) for _ in range(20)]
    stats = compute_zone_medians(listings)
    assert stats[("zone", "el-tunco", "land")]["median"] == 100.0


def test_compute_min_max_and_n_populated():
    """min/max/n surfaced alongside median for the detail-page context block."""
    ppm_values = [50, 80, 100, 120, 150, 180, 200, 220, 250, 300, 350, 500]
    listings = [_li(price_per_m2=p) for p in ppm_values]
    stats = compute_zone_medians(listings)
    bucket = stats[("zone", "el-tunco", "land")]
    assert bucket["min"] == 50.0
    assert bucket["max"] == 500.0
    assert bucket["n"]   == 12


# ── cascade behaviour ─────────────────────────────────────────────────

def test_cascade_zone_picked_when_zone_qualifies():
    listings = [_li(zone="el-tunco", price_per_m2=100 + i * 10)
                for i in range(MIN_LISTINGS_PER_ZONE)]
    metrics = compute_and_apply(listings, history_path=Path("/tmp/test-h-zone.jsonl"))
    assert metrics["listings_scored"] == MIN_LISTINGS_PER_ZONE
    assert metrics["listings_scored_zone"] == MIN_LISTINGS_PER_ZONE
    for li in listings:
        assert li["zone_comparison_scope"] == "zone"


def test_cascade_falls_back_to_macro():
    """Two sparse zones in the same macro region pool together qualify."""
    # 5 el-tunco + 5 el-zonte = 10 in central-pacific (≥ gate)
    listings  = [_li(zone="el-tunco", price_per_m2=100 + i * 10) for i in range(5)]
    listings += [_li(zone="el-zonte", price_per_m2=200 + i * 10) for i in range(5)]
    stats = compute_zone_medians(listings)
    # Neither zone qualifies on its own
    assert ("zone", "el-tunco", "land") not in stats
    assert ("zone", "el-zonte", "land") not in stats
    # Macro qualifies
    assert ("macro", "central-pacific", "land") in stats
    metrics = compute_and_apply(listings, history_path=Path("/tmp/test-h-macro.jsonl"))
    assert metrics["listings_scored"] == 10
    assert metrics["listings_scored_macro"] == 10
    for li in listings:
        assert li["zone_comparison_scope"] == "macro"


def test_cascade_falls_back_to_country():
    """Listings in zones that don't share a macro region still pool to country."""
    # 5 el-tunco (central-pacific) + 5 el-cuco (eastern-pacific) = no macro qualifies
    listings  = [_li(zone="el-tunco", price_per_m2=100 + i * 10) for i in range(5)]
    listings += [_li(zone="el-cuco",  price_per_m2=200 + i * 10) for i in range(5)]
    stats = compute_zone_medians(listings)
    # No macro qualifies (each macro has 5)
    assert not any(k[0] == "macro" for k in stats)
    # Country qualifies (10 SV-land listings)
    assert ("country", "SV", "land") in stats
    metrics = compute_and_apply(listings, history_path=Path("/tmp/test-h-country.jsonl"))
    assert metrics["listings_scored"] == 10
    assert metrics["listings_scored_country"] == 10
    for li in listings:
        assert li["zone_comparison_scope"] == "country"


def test_cascade_no_tier_leaves_all_fields_none():
    """A rare property_type with too few peers everywhere → no comparison."""
    listings = [_li(zone="el-tunco", property_type="exotic", price_per_m2=100 + i * 10)
                for i in range(5)]
    metrics = compute_and_apply(listings, history_path=Path("/tmp/test-h-none.jsonl"))
    assert metrics["listings_scored"] == 0
    assert metrics["listings_skipped_no_pool"] == 5
    for li in listings:
        assert li.get("zone_comparison_scope") is None
        assert li.get("price_vs_zone_median")  is None
        assert li.get("zone_comp_count")       is None


def test_cascade_prefers_most_specific_tier():
    """When zone qualifies, listings get zone-tier stats (not macro)."""
    # Build a fully-populated central-pacific macro pool (30 listings)
    # AND a zone-eligible el-tunco bucket (10 listings).
    big_macro = [_li(zone="el-zonte", price_per_m2=500 + i) for i in range(30)]
    tunco     = [_li(zone="el-tunco", price_per_m2=100 + i * 10) for i in range(10)]
    listings = big_macro + tunco
    apply_zone_metrics(listings, compute_zone_medians(listings))
    # el-tunco listings should get zone tier
    for li in tunco:
        assert li["zone_comparison_scope"] == "zone"
    # el-zonte (also in central-pacific) should also get zone (since 30 ≥ 10)
    for li in big_macro:
        assert li["zone_comparison_scope"] == "zone"


def test_cascade_zoneless_listing_falls_through_to_country():
    """A listing without a zone still gets country-tier context if SV has ≥10."""
    background = [_li(zone="el-tunco", price_per_m2=100 + i * 10) for i in range(15)]
    orphan     = _li(zone=None, price_per_m2=200)
    listings = background + [orphan]
    apply_zone_metrics(listings, compute_zone_medians(listings))
    assert orphan["zone_comparison_scope"] == "country"
    # background gets the more specific zone tier
    for li in background:
        assert li["zone_comparison_scope"] == "zone"


# ── apply_zone_metrics ─────────────────────────────────────────────────

def test_apply_signs_pct_correctly():
    """Positive pct = above median; negative = below."""
    stats = {("zone", "el-tunco", "land"): _bucket(200.0)}
    listings = [
        _li(price_per_m2=200),   # at median → 0%
        _li(price_per_m2=240),   # +20% above
        _li(price_per_m2=160),   # -20% below
    ]
    apply_zone_metrics(listings, stats)
    assert listings[0]["price_vs_zone_pct"] == 0.0
    assert listings[1]["price_vs_zone_pct"] == 20.0
    assert listings[2]["price_vs_zone_pct"] == -20.0


def test_apply_sets_median_field_too():
    stats = {("zone", "el-tunco", "land"): _bucket(175.5)}
    li = _li(price_per_m2=200)
    apply_zone_metrics([li], stats)
    assert li["price_vs_zone_median"] == 175.5


def test_apply_sets_zone_distribution_fields():
    """min/max/comp_count + scope copied onto every eligible listing."""
    stats = {("zone", "el-tunco", "land"): _bucket(150.0, mn=50.0, mx=500.0, n=14)}
    listings = [_li(price_per_m2=200), _li(price_per_m2=120)]
    apply_zone_metrics(listings, stats)
    for li in listings:
        assert li["zone_price_per_m2_min"] == 50.0
        assert li["zone_price_per_m2_max"] == 500.0
        assert li["zone_comp_count"]       == 14
        assert li["zone_comparison_scope"] == "zone"


def test_apply_skips_listings_with_no_pool():
    """No bucket at any tier → all fields stay None (explicitly written)."""
    listings = [_li(zone="rare-zone", price_per_m2=100)]
    metrics = apply_zone_metrics(listings, {})
    li = listings[0]
    assert li["price_vs_zone_median"]    is None
    assert li["price_vs_zone_pct"]       is None
    # Use indexing (not .get) — these keys MUST exist so the dict path
    # matches the dataclass path's None defaults. Required by the JSON
    # schema that validates ranked.json on every nightly.
    assert li["zone_price_per_m2_min"]   is None
    assert li["zone_price_per_m2_max"]   is None
    assert li["zone_comp_count"]         is None
    assert li["zone_comparison_scope"]   is None
    assert metrics["listings_skipped_no_pool"] == 1


def test_apply_skips_inactive_listings():
    listings = [_li(price_per_m2=None), _li(is_sold=True),
                _li(price_per_m2=100)]
    metrics = apply_zone_metrics(listings,
        {("zone", "el-tunco", "land"): _bucket(100.0)})
    assert metrics["listings_skipped_inactive"] == 2
    assert metrics["listings_scored"] == 1


def test_apply_writes_null_keys_on_inactive_listings():
    """Inactive (sold / no $/m²) listings get explicit None on every owned
    field — the dict code path must match the dataclass defaults so
    ranked.json schema validation passes for nightly + backfill outputs."""
    sold = _li(is_sold=True)
    noprice = _li(price_per_m2=None)
    apply_zone_metrics([sold, noprice],
        {("zone", "el-tunco", "land"): _bucket(100.0)})
    for li in (sold, noprice):
        for k in ("price_vs_zone_median", "price_vs_zone_pct",
                  "zone_price_per_m2_min", "zone_price_per_m2_max",
                  "zone_comp_count", "zone_comparison_scope"):
            assert k in li, f"{k} missing on inactive listing"
            assert li[k] is None, f"{k} not None on inactive listing"


# ── compute_and_apply (end-to-end) ─────────────────────────────────────

def test_compute_and_apply_full_path(tmp_path):
    """End-to-end with the cascade — sparse el-cuco still gets country tier."""
    # 12 land listings in el-tunco — eligible for zone tier
    listings = [_li(price_per_m2=p) for p in [100, 110, 120, 130, 140, 150,
                                                 160, 170, 180, 190, 200, 210]]
    # 5 listings in el-cuco — below zone gate, but the SV-land country
    # pool now has 17 listings → el-cuco listings get country tier
    listings += [_li(zone="el-cuco", price_per_m2=p) for p in [50, 60, 70, 80, 90]]
    # Sold listing excluded
    listings.append(_li(price_per_m2=9999, is_sold=True))

    metrics = compute_and_apply(listings, history_path=tmp_path / "h.jsonl")
    assert metrics["listings_scored"] == 17           # 12 + 5 (sold excluded)
    assert metrics["listings_scored_zone"] == 12      # el-tunco only
    assert metrics["listings_scored_country"] == 5    # el-cuco fallback

    # el-tunco median: midpoint of 12 sorted values is between 150 and 160
    assert listings[0]["price_vs_zone_median"] == 155.0
    assert listings[0]["zone_comparison_scope"] == "zone"

    # el-cuco listings get country-tier stats
    el_cuco = [li for li in listings if li["zone"] == "el-cuco"]
    for li in el_cuco:
        assert li["zone_comparison_scope"] == "country"
        assert li["price_vs_zone_median"] is not None


def test_idempotent_repeat_application(tmp_path):
    """Running twice with the same inputs produces identical outputs."""
    history = tmp_path / "h.jsonl"
    listings = [_li(price_per_m2=100 + i * 10) for i in range(MIN_LISTINGS_PER_ZONE)]
    compute_and_apply(listings, history_path=history)
    snapshot = [(li["price_vs_zone_median"], li["price_vs_zone_pct"], li["zone_comparison_scope"])
                for li in listings]
    compute_and_apply(listings, history_path=history)
    again = [(li["price_vs_zone_median"], li["price_vs_zone_pct"], li["zone_comparison_scope"])
             for li in listings]
    assert snapshot == again


def test_metrics_shape(tmp_path):
    metrics = compute_and_apply([], history_path=tmp_path / "h.jsonl")
    for k in ("buckets_computed", "listings_scored",
              "listings_scored_zone", "listings_scored_macro", "listings_scored_country",
              "listings_skipped_inactive", "listings_skipped_no_pool"):
        assert k in metrics


# ── telemetry sidecar ──────────────────────────────────────────────────

def test_telemetry_writes_one_row_per_eligible_zone_bucket(tmp_path):
    """Only zone-tier rows go into the telemetry sidecar — macro/country
    are derivable from the zone rolls and would just double-count."""
    import json
    history = tmp_path / "zone_medians_history.jsonl"
    listings = []
    for i in range(MIN_LISTINGS_PER_ZONE):
        listings.append(_li(zone="el-tunco", price_per_m2=100 + i * 10))
    for i in range(MIN_LISTINGS_PER_ZONE):
        listings.append(_li(zone="el-cuco", price_per_m2=200 + i * 5))
    compute_and_apply(listings, history_path=history)
    rows = [json.loads(line) for line in history.read_text().splitlines() if line.strip()]
    # Two zone-tier rows + the macro/country rows aren't written
    assert len(rows) == 2
    zones = {r["zone"] for r in rows}
    assert zones == {"el-tunco", "el-cuco"}


def test_telemetry_includes_n_listings_and_median(tmp_path):
    import json
    history = tmp_path / "h.jsonl"
    listings = [_li(zone="el-tunco", price_per_m2=p)
                for p in range(100, 100 + MIN_LISTINGS_PER_ZONE * 10, 10)]
    compute_and_apply(listings, history_path=history)
    # Two rows expected: one per (zone, ptype) bucket. el-tunco/land qualifies.
    rows = [json.loads(line) for line in history.read_text().splitlines() if line.strip()]
    tunco_row = next(r for r in rows if r["zone"] == "el-tunco")
    assert tunco_row["property_type"] == "land"
    assert tunco_row["n_listings"] == MIN_LISTINGS_PER_ZONE
    assert tunco_row["median_ppm_usd"] is not None
    assert "ts" in tunco_row


def test_telemetry_skips_below_threshold_buckets(tmp_path):
    """Zone buckets below MIN_LISTINGS_PER_ZONE don't appear in zone-tier history."""
    import json
    history = tmp_path / "h.jsonl"
    listings = [_li(zone="rare-zone", price_per_m2=100) for _ in range(3)]
    compute_and_apply(listings, history_path=history)
    if history.exists():
        rows = [json.loads(line) for line in history.read_text().splitlines() if line.strip()]
        assert len(rows) == 0


def test_telemetry_appends_across_runs(tmp_path):
    """History is append-only across nightly runs."""
    import json
    history = tmp_path / "h.jsonl"
    listings = [_li(zone="el-tunco", price_per_m2=p)
                for p in range(100, 100 + MIN_LISTINGS_PER_ZONE * 10, 10)]
    compute_and_apply(listings, history_path=history)
    compute_and_apply(listings, history_path=history)
    rows = [json.loads(line) for line in history.read_text().splitlines() if line.strip()]
    assert len(rows) == 2   # one zone-tier row per run × 2 runs


def test_telemetry_write_failure_is_non_fatal(tmp_path):
    """Pipeline continues if history can't be written."""
    bad_path = tmp_path / "is_a_file"
    bad_path.write_text("blocking")
    history = bad_path / "h.jsonl"
    listings = [_li(zone="el-tunco", price_per_m2=p)
                for p in range(100, 100 + MIN_LISTINGS_PER_ZONE * 10, 10)]
    metrics = compute_and_apply(listings, history_path=history)
    assert metrics["listings_scored"] == MIN_LISTINGS_PER_ZONE
