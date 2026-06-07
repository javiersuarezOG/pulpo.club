"""Tests for automation/field_audit.py — focused on the acceptance-test mode.

The legacy info-only flow (TRACKED list, compute_completeness,
print_source_table) is exercised implicitly by the nightly pipeline.
This file pins the PRD-driven acceptance gate:

  • HARD_GATE_FIELDS = (property_type, location_text, price_usd)
  • Threshold ≥ 85% on the first 50 listings per source.
  • Failure → exit 1 with the offending source(s) named.

Any future PR that adjusts the threshold or the sample size MUST update
these tests in the same change — that's the contract the field-audit
acceptance mode is meant to enforce.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.field_audit import (  # noqa: E402
    ACCEPTANCE_HARD_GATE_THRESHOLD,
    ACCEPTANCE_SAMPLE_SIZE,
    HARD_GATE_FIELDS,
    acceptance_check,
    hard_gate_pct,
    main as field_audit_main,
)


def _li(**overrides) -> dict:
    """Return a minimal hard-gate-complete listing dict."""
    base = {
        "source": "test_source",
        "property_type": "land",
        "location_text": "El Tunco, La Libertad",
        "price_usd": 100_000.0,
    }
    base.update(overrides)
    return base


def _li_zone_only(**overrides) -> dict:
    """Listing with derived location fields but blank location_text —
    matches Phase C scraper output post-normalize. The hard-gate
    "location" check must accept this as satisfying the gate."""
    base = {
        "source": "test_source",
        "property_type": "land",
        "location_text": "",
        "zone": "el-tunco",
        "municipality": "Tamanique",
        "department": "La Libertad",
        "price_usd": 100_000.0,
    }
    base.update(overrides)
    return base


# ── hard_gate_pct ─────────────────────────────────────────────────────


def test_hard_gate_pct_empty_yields_zeroes():
    pct = hard_gate_pct([])
    assert pct == {f: 0.0 for f in HARD_GATE_FIELDS}


def test_hard_gate_pct_full_complete_yields_ones():
    pct = hard_gate_pct([_li() for _ in range(20)])
    assert pct["property_type"] == 1.0
    assert pct["location"] == 1.0
    assert pct["price_usd"] == 1.0


def test_hard_gate_pct_partial_property_type_missing():
    listings = [_li() for _ in range(8)] + [_li(property_type="") for _ in range(2)]
    pct = hard_gate_pct(listings)
    # 8 of 10 have property_type populated
    assert pct["property_type"] == 0.8
    assert pct["location"] == 1.0


def test_hard_gate_pct_property_type_strips_whitespace():
    """Whitespace-only is NOT a populated property_type — would silently
    survive an unwrapped scraper output otherwise."""
    listings = [_li(property_type="   ") for _ in range(5)]
    pct = hard_gate_pct(listings)
    assert pct["property_type"] == 0.0


def test_hard_gate_pct_location_accepts_zone_when_location_text_blank():
    """The single most important PRD-vs-implementation alignment:
    Phase C scrapers (Santizo, Vivo Latam, CSBR, etc.) emit a blank
    `location_text` but populate `zone` / `municipality` / `department`
    after normalize. The hard-gate "location" check MUST credit those
    listings — otherwise the acceptance gate trips on real, shelf-ready
    inventory. Pre-2026-06-07 version of this check returned 0% for
    these sources and would have broken CI when wired."""
    listings = [_li_zone_only() for _ in range(10)]
    pct = hard_gate_pct(listings)
    assert pct["location"] == 1.0


def test_hard_gate_pct_location_zero_when_no_location_signal_anywhere():
    """A listing with NO location signal in any of the four backing
    fields fails the gate. This is what a broken scraper produces and
    is exactly what the gate should catch."""
    listings = [
        {"source": "broken", "property_type": "land", "price_usd": 100_000}
        for _ in range(10)
    ]
    pct = hard_gate_pct(listings)
    assert pct["location"] == 0.0


# ── acceptance_check ──────────────────────────────────────────────────


def test_acceptance_check_passes_when_all_sources_clear_threshold():
    listings = [_li(source="goodlife") for _ in range(50)] + \
               [_li(source="nexo") for _ in range(50)]
    code, reports = acceptance_check(listings)
    assert code == 0
    assert len(reports) == 2
    assert all(r["failures"] == [] for r in reports)


def test_acceptance_check_fails_when_any_source_below_threshold():
    """The PRD threshold is 85%. 5 of 50 missing price_usd = 90% — passes.
    10 of 50 missing = 80% — fails."""
    good = [_li(source="goodlife") for _ in range(50)]
    bad = (
        [_li(source="brokensrc", price_usd=None) for _ in range(11)]
        + [_li(source="brokensrc") for _ in range(39)]
    )
    code, reports = acceptance_check(good + bad)
    assert code == 1
    bad_report = next(r for r in reports if r["source"] == "brokensrc")
    assert "price_usd" in bad_report["failures"]
    good_report = next(r for r in reports if r["source"] == "goodlife")
    assert good_report["failures"] == []


def test_acceptance_check_caps_at_sample_size():
    """Sources with > sample_size listings only evaluate the first N."""
    # 60 listings; first 50 clean, last 10 missing price. Sample = 50 →
    # acceptance should PASS because we only look at the first 50.
    listings = (
        [_li(source="big") for _ in range(50)]
        + [_li(source="big", price_usd=None) for _ in range(10)]
    )
    code, reports = acceptance_check(listings)
    assert code == 0
    r = reports[0]
    assert r["n_sample"] == ACCEPTANCE_SAMPLE_SIZE
    assert r["failures"] == []


def test_acceptance_check_allows_overriding_sample_size():
    """Operator override: sample=full inventory → catches tail
    breakage that the default 50-sample misses."""
    listings = (
        [_li(source="big") for _ in range(50)]
        + [_li(source="big", price_usd=None) for _ in range(10)]
    )
    code, _ = acceptance_check(listings, sample_size=60)
    assert code == 1


def test_acceptance_check_allows_overriding_threshold():
    """Operator override: tighter threshold catches partial degradation
    earlier (e.g. while ramping up a new source)."""
    # 5 of 50 listings missing every location signal → 90% coverage.
    # Passes default 85% but fails 95% override.
    no_loc = {"source": "src", "property_type": "land", "price_usd": 100_000.0}
    listings = [no_loc for _ in range(5)] + [_li(source="src") for _ in range(45)]
    code_default, _ = acceptance_check(listings)
    code_strict, _ = acceptance_check(listings, threshold=0.95)
    assert code_default == 0
    assert code_strict == 1


def test_acceptance_check_handles_small_sources():
    """A new source with only 3 listings still runs the gate — exits
    0 only if all 3 are complete. Gates very-new sources at parity
    with established ones."""
    listings = [_li(source="tinysrc") for _ in range(3)]
    code, reports = acceptance_check(listings)
    assert code == 0
    assert reports[0]["n_sample"] == 3


def test_acceptance_check_returns_per_source_pct_for_log_visibility():
    """The exit code is the gate; the per-source pct dict is what the
    operator needs to fix the failing source. Pin the shape so the CI
    log stays interpretable when the gate trips."""
    no_loc = {"source": "x", "property_type": "land", "price_usd": 100_000.0}
    listings = [no_loc for _ in range(50)]
    code, reports = acceptance_check(listings)
    assert code == 1
    pct = reports[0]["hard_gate_pct"]
    assert pct["property_type"] == 1.0
    assert pct["location"] == 0.0
    assert pct["price_usd"] == 1.0


# ── shelf-eligible filter (oceanside-class luxury sources) ─────────────


def test_acceptance_check_excludes_is_incomplete_by_default():
    """The 2026-06-07 audit run flagged oceanside at 68% price coverage.
    Investigation showed all 7 missing-price listings were already
    marked is_incomplete=True (luxury "consultar" patterns the data
    layer already hides). The PRD asks "can this listing serve a
    buyer?" — is_incomplete=True is the data layer's "no", and the
    gate should respect that."""
    visible = [_li(source="oceanside") for _ in range(15)]
    hidden_no_price = [
        {"source": "oceanside", "property_type": "land",
         "location_text": "El Tunco", "is_incomplete": True}
        for _ in range(7)
    ]
    code, reports = acceptance_check(visible + hidden_no_price)
    assert code == 0
    # n_sample should only count the 15 shelf-eligible listings.
    assert reports[0]["n_sample"] == 15
    assert reports[0]["hard_gate_pct"]["price_usd"] == 1.0


def test_acceptance_check_excludes_is_agricultural_by_default():
    """Agricultural listings are tagged-but-not-shelved per the PRD
    update. They shouldn't count against price/location coverage."""
    visible = [_li(source="src") for _ in range(20)]
    hidden_agri = [
        {"source": "src", "property_type": "land",
         "location_text": "Apaneca", "is_agricultural": True}
        for _ in range(5)
    ]
    code, reports = acceptance_check(visible + hidden_agri)
    assert code == 0
    assert reports[0]["n_sample"] == 20


def test_acceptance_check_still_fails_when_visible_listings_are_below_threshold():
    """The filter only excludes already-hidden listings. A source whose
    VISIBLE inventory has a real coverage gap must still fail — otherwise
    the gate would be useless."""
    bad_visible = [
        {"source": "broken", "property_type": "land",
         "location_text": "El Tunco"}  # missing price
        for _ in range(15)
    ]
    code, reports = acceptance_check(bad_visible)
    assert code == 1
    assert reports[0]["hard_gate_pct"]["price_usd"] == 0.0


def test_acceptance_check_include_hidden_reverts_to_legacy_behavior():
    """Forensic mode: ``include_hidden=True`` counts every listing.
    Useful for diagnosing why the data layer excluded specific
    listings, but NOT what CI should use."""
    visible = [_li(source="oceanside") for _ in range(15)]
    hidden_no_price = [
        {"source": "oceanside", "property_type": "land",
         "location_text": "El Tunco", "is_incomplete": True}
        for _ in range(7)
    ]
    code_default, _ = acceptance_check(visible + hidden_no_price)
    code_forensic, reports_forensic = acceptance_check(
        visible + hidden_no_price, include_hidden=True
    )
    assert code_default == 0
    assert code_forensic == 1
    # Forensic mode includes ALL 22 in n_sample.
    assert reports_forensic[0]["n_sample"] == 22
    # And price coverage shows the real 15/22 ≈ 68%.
    assert reports_forensic[0]["hard_gate_pct"]["price_usd"] < 0.7


def test_acceptance_check_treats_is_incomplete_false_as_eligible():
    """Explicit False is NOT the same as True — only True excludes.
    A listing with is_incomplete=False or no is_incomplete key counts
    toward the gate."""
    explicit_false = [
        dict(_li(source="src"), is_incomplete=False) for _ in range(5)
    ]
    no_key = [_li(source="src") for _ in range(5)]
    code, reports = acceptance_check(explicit_false + no_key)
    assert code == 0
    assert reports[0]["n_sample"] == 10


# ── threshold + constants ──────────────────────────────────────────────


def test_constants_match_prd():
    """The PRD specifies 85% over a 50-listing sample. Pin both so a
    silent constant change requires updating this test alongside."""
    assert ACCEPTANCE_HARD_GATE_THRESHOLD == 0.85
    assert ACCEPTANCE_SAMPLE_SIZE == 50
    assert HARD_GATE_FIELDS == ("property_type", "location", "price_usd")


# ── main() integration ────────────────────────────────────────────────


def test_main_acceptance_test_exits_zero_on_clean_data(tmp_path, capsys):
    """End-to-end: clean ranked.json → acceptance PASS, exit 0."""
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps([_li(source="g") for _ in range(10)]))
    rc = field_audit_main([str(ranked), "--acceptance-test"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "acceptance: PASS" in out


def test_main_acceptance_test_exits_one_on_failing_data(tmp_path, capsys):
    """End-to-end: broken ranked.json → acceptance FAIL, exit 1, naming
    the offending source. Pin the output format so a CI log scrape
    surfaces the actionable source name."""
    ranked = tmp_path / "ranked.json"
    listings = [_li(source="g") for _ in range(10)] + \
               [_li(source="brokensrc", property_type="") for _ in range(20)]
    ranked.write_text(json.dumps(listings))
    rc = field_audit_main([str(ranked), "--acceptance-test"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out
    assert "brokensrc" in out


def test_main_legacy_mode_unchanged(tmp_path, capsys):
    """Legacy info-only path: no flag, exits 0 even on broken data."""
    ranked = tmp_path / "ranked.json"
    listings = [_li(source="brokensrc", property_type="") for _ in range(20)]
    ranked.write_text(json.dumps(listings))
    rc = field_audit_main([str(ranked)])
    out = capsys.readouterr().out
    assert rc == 0
    # Legacy table is rendered, not the acceptance report.
    assert "acceptance:" not in out
    assert "brokensrc" in out
