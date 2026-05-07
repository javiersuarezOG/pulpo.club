"""
Tests for pulpo/derived_rules.py — pins readiness_score, investment_signal,
source_label, data_quality_score, and the apply_all orchestrator.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pulpo.derived_rules import (   # noqa: E402
    compute_readiness_score,
    compute_investment_signal,
    compute_source_label,
    compute_data_quality_score,
    apply_all,
    derive_source_type,
    derive_previous_price,
    OFF_MARKET_SOURCES,
    SCOREABLE_FIELDS,
    SCOREABLE_TOTAL,
    _is_populated,
)


def _li(**kwargs) -> dict:
    base = {
        "source": "goodlife",
        "source_id": "GL-001",
        "url": "https://example.com/x",
        "title": "Test",
        "description": "x" * 50,
        "scraped_at": "2026-05-04T12:00:00+00:00",
        "country": "SV",
        "department": "La Libertad",
        "zone": "el-tunco",
        "area_m2": 5000.0,
        "price_usd": 150_000.0,
        "price_per_m2": 30.0,
        "property_type": "land",
        "first_seen_at": "2026-04-01T12:00:00+00:00",
        "broker_name": "Test Broker",
        "broker_phone": "555-1234",
        "broker_email": "broker@example.com",
        "is_in_development": False,
        "is_beachfront": False,
        "has_water": False,
        "has_power": False,
        "has_paved_access": False,
        "is_flat": False,
        "is_repriced": False,
        "photo_urls": [],
        "photos_count": 0,
        "lat": None,
        "days_listed": None,
        "source_type": None,
    }
    base.update(kwargs)
    return base


# ── _is_populated semantics ────────────────────────────────────────────

def test_is_populated_treats_false_bool_as_not_populated():
    """For booleans, only True counts as informative — False is the default."""
    assert _is_populated(True)
    assert not _is_populated(False)


def test_is_populated_treats_empty_strings_and_lists_as_not_populated():
    assert not _is_populated("")
    assert not _is_populated("   ")
    assert not _is_populated([])
    assert not _is_populated({})


def test_is_populated_zero_numeric_is_not_populated():
    """Zero often signals 'no data' (0 photos, 0 area). Match PRD intent."""
    assert not _is_populated(0)
    assert not _is_populated(0.0)


# ── compute_readiness_score (PRD §FR-7.1) ─────────────────────────────

def test_readiness_zero_when_nothing():
    assert compute_readiness_score(_li()) == 0


def test_readiness_one_when_water_only():
    assert compute_readiness_score(_li(has_water=True)) == 1


def test_readiness_three_when_all_three_utilities():
    li = _li(has_water=True, has_power=True, has_paved_access=True)
    assert compute_readiness_score(li) == 3


def test_readiness_none_when_all_inputs_absent():
    """If has_water/has_power/has_paved_access are all None, return None
    (no signal, not 0)."""
    li = {"has_water": None, "has_power": None, "has_paved_access": None}
    assert compute_readiness_score(li) is None


# ── compute_investment_signal (PRD §FR-7.2 — full rule) ───────────────

def test_signal_deal_when_repriced_and_below_median():
    """Strict PRD path: is_repriced AND price_vs_zone_pct ≤ -10."""
    li = _li(is_repriced=True, price_vs_zone_pct=-15.0)
    assert compute_investment_signal(li) == "deal"


def test_signal_deal_at_threshold():
    """Boundary: pct = -10 exactly counts as 'deal' (≤, not <)."""
    li = _li(is_repriced=True, price_vs_zone_pct=-10.0)
    assert compute_investment_signal(li) == "deal"


def test_signal_deal_fallback_when_pct_unknown():
    """~32% of catalog is in low-volume buckets where price_vs_zone_pct is
    None. Without a fallback, those listings would lose 'deal' even when
    heavily repriced. Keep the conservative fallback."""
    li = _li(is_repriced=True, price_vs_zone_pct=None)
    assert compute_investment_signal(li) == "deal"


def test_signal_not_deal_when_repriced_but_above_threshold():
    """Repriced but only -5% off median — full rule says NOT a deal.
    Falls through to days_listed-based rules (or None)."""
    li = _li(is_repriced=True, price_vs_zone_pct=-5.0, days_listed=30)
    assert compute_investment_signal(li) is None


def test_signal_repriced_above_threshold_falls_through_to_stale():
    """Repriced + shallow discount + old = stale (not deal)."""
    li = _li(is_repriced=True, price_vs_zone_pct=-5.0, days_listed=120)
    assert compute_investment_signal(li) == "stale"


def test_signal_repriced_above_threshold_falls_through_to_new():
    """Repriced + shallow discount + recent = new (not deal)."""
    li = _li(is_repriced=True, price_vs_zone_pct=-5.0, days_listed=3)
    assert compute_investment_signal(li) == "new"


def test_signal_repriced_above_median_does_not_fire_deal():
    """Repriced but +20% above median — definitely not a deal."""
    li = _li(is_repriced=True, price_vs_zone_pct=20.0, days_listed=30)
    assert compute_investment_signal(li) is None


def test_signal_stale_when_old():
    assert compute_investment_signal(_li(days_listed=120)) == "stale"


def test_signal_new_when_recent():
    assert compute_investment_signal(_li(days_listed=3)) == "new"


def test_signal_none_when_no_rules_apply():
    assert compute_investment_signal(_li(days_listed=30)) is None


def test_signal_priority_deal_over_stale():
    """deal beats stale even when both technically apply (low-volume
    fallback path: pct=None, repriced=True, days_listed=120 → still deal)."""
    li = _li(is_repriced=True, days_listed=120)
    assert compute_investment_signal(li) == "deal"


# ── compute_source_label (PRD §FR-7.3) ────────────────────────────────

def test_source_label_beachfront():
    labels = compute_source_label(_li(is_beachfront=True))
    assert "Beachfront" in labels


def test_source_label_off_market():
    labels = compute_source_label(_li(source_type="off_market"))
    assert "Off-Market" in labels


def test_source_label_price_drop():
    labels = compute_source_label(_li(is_repriced=True))
    assert "Price Drop" in labels


def test_source_label_new_when_days_listed_low():
    labels = compute_source_label(_li(days_listed=5))
    assert "New" in labels


def test_source_label_build_ready_when_readiness_three():
    li = _li(has_water=True, has_power=True, has_paved_access=True)
    labels = compute_source_label(li)
    assert "Build-Ready" in labels


def test_source_label_empty_when_nothing():
    labels = compute_source_label(_li())
    assert labels == []


def test_source_label_combines_multiple():
    li = _li(is_beachfront=True, is_repriced=True, days_listed=3,
             has_water=True, has_power=True, has_paved_access=True)
    labels = compute_source_label(li)
    for required in ("Beachfront", "Price Drop", "New", "Build-Ready"):
        assert required in labels


# ── compute_data_quality_score (PRD §FR-7.4) ──────────────────────────

def test_quality_score_in_zero_one_range():
    score = compute_data_quality_score(_li())
    assert 0.0 <= score <= 1.0


def test_quality_score_higher_when_more_populated():
    sparse = compute_data_quality_score({"source": "x"})
    rich   = compute_data_quality_score(_li(
        is_in_development=True, is_beachfront=True,
        has_water=True, has_power=True,
        photo_urls=["https://example.com/1.jpg"],
        lat=13.5,
    ))
    assert rich > sparse


def test_quality_score_uses_known_field_count():
    """Sanity: SCOREABLE_TOTAL is what we documented."""
    assert SCOREABLE_TOTAL == len(SCOREABLE_FIELDS)
    assert 15 <= SCOREABLE_TOTAL <= 30


# ── apply_all — orchestrator ──────────────────────────────────────────

def test_apply_all_sets_all_four_fields():
    li = _li(is_beachfront=True, is_repriced=True, days_listed=5,
             has_water=True, has_power=True, has_paved_access=True)
    written = apply_all(li)
    assert "readiness_score"   in written
    assert "investment_signal" in written
    assert "source_label"      in written
    assert "data_quality_score" in written
    assert li["readiness_score"] == 3
    assert li["investment_signal"] == "deal"
    assert "Build-Ready" in li["source_label"]
    assert 0 < li["data_quality_score"] <= 1


def test_apply_all_handles_dict_and_dataclass_like():
    """apply_all should work on both dicts and dataclass-like objects."""
    class Fake:
        is_beachfront = False
        is_repriced = True
        days_listed = 10
        has_water = True
        has_power = False
        has_paved_access = False
        source_type = None
        is_in_development = False
        is_flat = False
        zone_confidence = "specific"
        zone = "el-tunco"
        # Plus all the Listing fields …
        source = "x"
        source_id = "y"
        title = "x"
        description = "x"
        url = "x"
        scraped_at = "x"
        country = "SV"
        department = "x"
        municipality = None
        area_m2 = 1000
        price_usd = 100
        price_per_m2 = 0.1
        property_type = "land"
        first_seen_at = "2026-04-01"
        broker_name = None
        broker_phone = None
        broker_email = None
        photos_count = 0
        photo_urls: list = []
        lat = None
    fake = Fake()
    apply_all(fake)
    assert getattr(fake, "investment_signal") == "deal"
    assert isinstance(getattr(fake, "source_label"), list)


# ── PR-7: derive_source_type ───────────────────────────────────────────

def test_source_type_off_market_for_whatsapp():
    assert derive_source_type(_li(source="whatsapp")) == "off_market"


def test_source_type_off_market_for_facebook():
    assert derive_source_type(_li(source="facebook")) == "off_market"


def test_source_type_off_market_for_private():
    assert derive_source_type(_li(source="private")) == "off_market"


def test_source_type_off_market_case_insensitive():
    """Defensive — scraper configs sometimes capitalize."""
    assert derive_source_type(_li(source="WhatsApp")) == "off_market"


def test_source_type_on_market_for_indexed_scraper():
    """Default + whitelist semantics: anything not in OFF_MARKET_SOURCES is on_market."""
    assert derive_source_type(_li(source="goodlife")) == "on_market"
    assert derive_source_type(_li(source="remax")) == "on_market"


def test_source_type_on_market_for_unknown_source():
    """A new scraper that hasn't been added to OFF_MARKET_SOURCES yet
    must NOT accidentally land on the paywall side."""
    assert derive_source_type(_li(source="brand-new-scraper")) == "on_market"


def test_source_type_off_market_set_is_frozen():
    """Caller can't mutate the constant by accident."""
    import pytest
    with pytest.raises(AttributeError):
        OFF_MARKET_SOURCES.add("zillow")  # type: ignore[attr-defined]


# ── PR-7: derive_previous_price ────────────────────────────────────────

def test_previous_price_none_when_not_repriced():
    """No need to spelunk history if the listing isn't flagged as repriced."""
    li = _li(is_repriced=False, price_usd=100_000)
    history = {"goodlife|GL-001": [
        {"ts": "2026-04-01", "price_usd": 120_000.0},
        {"ts": "2026-05-01", "price_usd": 100_000.0},
    ]}
    assert derive_previous_price(li, history) is None


def test_previous_price_returns_last_different_entry():
    """Walks backwards from the snapshot before current; returns the
    first one with a different price."""
    li = _li(is_repriced=True, price_usd=100_000)
    history = {"goodlife|GL-001": [
        {"ts": "2026-04-01", "price_usd": 130_000.0},
        {"ts": "2026-04-15", "price_usd": 120_000.0},
        {"ts": "2026-05-01", "price_usd": 100_000.0},
    ]}
    assert derive_previous_price(li, history) == 120_000.0


def test_previous_price_skips_same_price_echoes():
    """Some snapshots write redundant equal-price rows. Walk past them
    until we find a real prior price."""
    li = _li(is_repriced=True, price_usd=100_000)
    history = {"goodlife|GL-001": [
        {"ts": "2026-03-01", "price_usd": 130_000.0},
        {"ts": "2026-04-01", "price_usd": 100_000.0},
        {"ts": "2026-05-01", "price_usd": 100_000.0},
    ]}
    assert derive_previous_price(li, history) == 130_000.0


def test_previous_price_none_when_history_missing():
    """Some scrapers reslug source_id over time; the history key
    detaches and we can't look up. Return None — the FE shows no
    strikethrough rather than crashing."""
    li = _li(is_repriced=True, price_usd=100_000)
    assert derive_previous_price(li, {}) is None
    assert derive_previous_price(li, None) is None


def test_previous_price_none_when_only_one_entry():
    """First-time scrape: history has just the current price. Nothing
    prior to compare against."""
    li = _li(is_repriced=True, price_usd=100_000)
    history = {"goodlife|GL-001": [
        {"ts": "2026-05-01", "price_usd": 100_000.0},
    ]}
    assert derive_previous_price(li, history) is None


def test_previous_price_none_when_current_price_missing():
    """Bad upstream data — without a current price, "previous" is meaningless."""
    li = _li(is_repriced=True, price_usd=None)
    history = {"goodlife|GL-001": [
        {"ts": "2026-04-01", "price_usd": 100_000.0},
        {"ts": "2026-05-01", "price_usd": 90_000.0},
    ]}
    assert derive_previous_price(li, history) is None


# ── PR-7: regression guard ─────────────────────────────────────────────

def test_regression_guard_skips_when_no_baseline():
    """First run after this guard lands — prev_meta has no
    derived_field_population block. Skip cleanly."""
    from automation.pipeline_steps import check_population_regression
    new = {"source_type_off_market": 0.05, "previous_price": 0.02}
    assert check_population_regression(None, new) == []
    assert check_population_regression({}, new) == []
    assert check_population_regression({"derived_field_population": {}}, new) == []


def test_regression_guard_clean_when_within_threshold():
    from automation.pipeline_steps import check_population_regression
    prev = {"derived_field_population": {"is_beachfront": 0.30}}
    new = {"is_beachfront": 0.27}    # 10% relative drop, under threshold
    assert check_population_regression(prev, new) == []


def test_regression_guard_flags_drops_above_threshold():
    """A field falling from 30% → 5% is the canonical NLP regression."""
    from automation.pipeline_steps import check_population_regression
    prev = {"derived_field_population": {"is_beachfront": 0.30}}
    new = {"is_beachfront": 0.05}    # 83% relative drop
    msgs = check_population_regression(prev, new, threshold=0.20)
    assert len(msgs) == 1
    assert "is_beachfront" in msgs[0]


def test_regression_guard_skips_new_fields():
    """A field added in the current run has no baseline — don't flag.
    It becomes baseline for next run."""
    from automation.pipeline_steps import check_population_regression
    prev = {"derived_field_population": {"is_beachfront": 0.30}}
    new = {"is_beachfront": 0.30, "land_type_agricultural": 0.0}  # newly added, 0%
    assert check_population_regression(prev, new) == []
