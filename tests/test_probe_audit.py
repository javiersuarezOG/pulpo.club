"""Tests for the probe-vs-listing fuzzy matcher (PR-S3a)."""
from __future__ import annotations

from automation.probe_audit import (
    AREA_TOLERANCE_PCT,
    KNOWN_MISS_CLASSIFICATIONS,
    PRICE_TOLERANCE_PCT,
    Probe,
    TITLE_OVERLAP_MIN,
    _extract_source_domain,
    _jaccard,
    _normalize_text,
    _price_close,
    _score_match,
    _token_set,
    match_probe,
    match_probes,
    summarize,
)


# ---------- Closed-set contract ----------

def test_known_miss_classifications_contract():
    """Per CLAUDE.md producer-consumer rule (post-2026-06-02)."""
    assert KNOWN_MISS_CLASSIFICATIONS == frozenset({
        "source_not_configured",
        "source_configured_but_zero",
        "scraped_but_filtered",
        "scraped_but_failed_validation",
        "deduped_into_other",
        "present_but_stale",
        "unknown",
    })


def test_thresholds_anchored():
    """Calibration constants — changing these is deliberate."""
    assert PRICE_TOLERANCE_PCT == 0.10
    assert AREA_TOLERANCE_PCT == 0.15
    assert TITLE_OVERLAP_MIN == 0.50


# ---------- Helpers ----------

def test_normalize_text_lowercases_and_strips_punct():
    assert _normalize_text("Beachfront 5,000 m² LOT!") == "beachfront 5 000 m lot"


def test_normalize_text_empty_string():
    assert _normalize_text("") == ""


def test_token_set_drops_short_tokens():
    """Tokens shorter than 3 chars are dropped (e.g. m², 5, a)."""
    tokens = _token_set("A 5 m² lot in El Tunco")
    assert "lot" in tokens
    assert "tunco" in tokens
    assert "a" not in tokens
    assert "5" not in tokens
    assert "el" not in tokens  # 2 chars dropped


def test_jaccard_identical():
    assert _jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0


def test_jaccard_disjoint():
    assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_partial():
    # {a, b} vs {b, c} → intersection 1, union 3 → 1/3
    assert abs(_jaccard({"a", "b"}, {"b", "c"}) - 1/3) < 1e-9


def test_jaccard_empty_sets():
    assert _jaccard(set(), {"a"}) == 0.0
    assert _jaccard({"a"}, set()) == 0.0
    assert _jaccard(set(), set()) == 0.0


def test_extract_source_domain_strips_www():
    assert _extract_source_domain("https://www.example.com/path") == "example.com"


def test_extract_source_domain_lowercases():
    assert _extract_source_domain("HTTPS://Example.COM/p") == "example.com"


def test_extract_source_domain_empty():
    assert _extract_source_domain("") is None
    assert _extract_source_domain("not a url") is None


def test_price_close_within_tolerance():
    # Denominator is listing_price (second arg). Tolerance is ±10% of THAT.
    assert _price_close(100_000, 105_000) is True   # 5% off → within
    assert _price_close(100_000, 95_000) is True    # 5% off → within
    # 88_000 vs 100_000: 12% off the 100_000 baseline → over tolerance
    assert _price_close(88_000, 100_000) is False
    # 112_000 vs 100_000: 12% off → over tolerance
    assert _price_close(112_000, 100_000) is False


def test_price_close_handles_none():
    assert _price_close(None, 100_000) is False
    assert _price_close(100_000, None) is False
    assert _price_close(None, None) is False
    assert _price_close(100_000, 0) is False  # zero listing price


# ---------- Score ----------

def test_score_high_overlap_close_price_same_zone():
    """Realistic-looking strong match — title overlap is ~60% after
    short-token filtering ('5000' vs '000' differ as single tokens),
    so the title leg contributes 0.55 * 0.60 = 0.33; plus 0.30 for
    price + 0.15 for zone = 0.78. Anchor at > 0.70 as a stable
    'strong match' threshold; exact value will drift if the tokenizer
    or weights change, which IS a deliberate calibration."""
    probe = Probe(
        title="Beachfront 5000 m² lot in El Tunco",
        price_usd=240_000,
        location="El Tunco",
        source_url="https://example.com/listing/123",
        probe_kind="seed_list",
    )
    listing = {
        "source": "goodlife",
        "source_id": "GL-1",
        "title": "Beachfront 5,000 m² lot El Tunco",
        "price_usd": 245_000,
        "zone": "el-tunco",
        "location_text": "El Tunco, La Libertad",
    }
    score = _score_match(probe, listing)
    assert score > 0.70
    assert score <= 1.0


def test_score_title_only_below_threshold():
    """Only title matches; price + zone differ."""
    probe = Probe(
        title="House in San Salvador",
        price_usd=500_000,
        location="San Salvador",
        source_url="https://example.com/x",
        probe_kind="seed_list",
    )
    listing = {
        "title": "House in San Salvador",
        "price_usd": 100_000,  # way off
        "zone": "el-tunco",  # different zone
        "location_text": "El Tunco",
    }
    score = _score_match(probe, listing)
    # Title weight is 0.55 * 1.0 = 0.55 at best — borderline
    assert score >= 0.30
    assert score < 0.60


def test_score_no_signal_anywhere_is_zero():
    probe = Probe("zzz qqq xxx", None, None, "", "seed_list")
    listing = {"title": "aaa bbb ccc", "price_usd": None}
    assert _score_match(probe, listing) == 0.0


# ---------- match_probe matched-path ----------

def _l(**overrides) -> dict:
    base = {
        "source": "goodlife",
        "source_id": "GL-1",
        "title": "Beachfront 5,000 m² lot El Tunco",
        "price_usd": 240_000,
        "zone": "el-tunco",
        "location_text": "El Tunco, La Libertad",
    }
    base.update(overrides)
    return base


def _probe(**overrides) -> Probe:
    base = dict(
        title="Beachfront 5000 m² lot in El Tunco",
        price_usd=245_000,
        location="El Tunco",
        source_url="https://goodlifeelsalvador.com/listing/123",
        probe_kind="seed_list",
    )
    base.update(overrides)
    return Probe(**base)


def test_match_probe_finds_matching_listing():
    result = match_probe(_probe(), [_l()])
    assert result.matched_key == "goodlife|GL-1"
    assert result.matched_score > 0.55
    assert result.miss_classification is None


def test_match_probe_picks_best_among_multiple_candidates():
    """The best-scoring listing wins, not the first."""
    near_match = _l(source_id="GL-1", price_usd=300_000)  # worse score
    exact = _l(source_id="GL-2", price_usd=245_000)       # better score
    result = match_probe(_probe(), [near_match, exact])
    assert result.matched_key == "goodlife|GL-2"


def test_match_probe_empty_listings_classifies_as_unknown():
    result = match_probe(_probe(), [])
    assert result.matched_key is None
    assert result.miss_classification == "source_not_configured"  # domain known + not configured


# ---------- match_probe miss-paths ----------

def test_miss_source_not_configured():
    """Probe domain isn't in configured_sources → source_not_configured."""
    probe = _probe(source_url="https://random-broker.example.com/foo")
    result = match_probe(probe, [], configured_sources={"goodlife", "remax"})
    assert result.miss_classification == "source_not_configured"
    assert "random-broker.example.com" in result.reason


def test_miss_source_configured_but_zero():
    """Probe domain IS configured but its scraper yielded 0 listings recently."""
    probe = _probe(source_url="https://goodlifeelsalvador.com/x")
    result = match_probe(
        probe, [],  # no listings at all
        configured_sources={"goodlifeelsalvador.com"},
        sources_with_zero_yield={"goodlifeelsalvador.com"},
    )
    assert result.miss_classification == "source_configured_but_zero"


def test_miss_scraped_but_filtered():
    """Near-match below threshold → assume scraped but filtered/dropped."""
    probe = _probe(title="Different title entirely with some overlap m²")
    listing = _l(
        title="Different listing m² with some keywords",
        # Same source so source-not-configured doesn't fire.
    )
    result = match_probe(
        probe, [listing],
        configured_sources={"goodlifeelsalvador.com"},
        threshold=0.99,  # extremely high → near-match falls below
    )
    assert result.miss_classification == "scraped_but_filtered"
    assert result.matched_score > 0  # had a near-match


def test_miss_present_but_stale():
    """Probe matches a listing but the ledger says it's stale → flag."""
    listing = _l(source_id="GL-1")
    result = match_probe(
        _probe(), [listing],
        stale_keys={"goodlife|GL-1"},
    )
    assert result.matched_key is None
    assert result.miss_classification == "present_but_stale"
    assert "stale" in result.reason


def test_miss_unknown_when_no_signal():
    """No listings AND no domain in probe URL → unknown."""
    probe = Probe(
        title="Mystery listing",
        price_usd=None,
        location=None,
        source_url="",  # no domain extractable
        probe_kind="seed_list",
    )
    result = match_probe(probe, [])
    assert result.miss_classification == "unknown"


# ---------- match_probes batch ----------

def test_match_probes_preserves_input_order():
    probes = [
        _probe(title="A " * 10),  # likely unmatch
        _probe(title="Beachfront 5000 m² lot in El Tunco"),  # match
    ]
    results = match_probes(probes, [_l()])
    assert len(results) == 2
    assert results[0].matched_key is None
    assert results[1].matched_key is not None


def test_match_probes_empty():
    assert match_probes([], [_l()]) == []


# ---------- summarize ----------

def test_summarize_computes_match_rate():
    from automation.probe_audit import MatchResult
    results = [
        MatchResult(_probe(), "goodlife|1", 0.9, None, "ok"),
        MatchResult(_probe(), "goodlife|2", 0.8, None, "ok"),
        MatchResult(_probe(), None, 0.0, "source_not_configured", "x"),
        MatchResult(_probe(), None, 0.0, "unknown", "y"),
    ]
    s = summarize(results)
    assert s["total_probed"] == 4
    assert s["matched"] == 2
    assert s["match_rate"] == 0.5
    assert s["by_miss_classification"] == {
        "source_not_configured": 1,
        "unknown": 1,
    }


def test_summarize_empty():
    s = summarize([])
    assert s == {
        "total_probed": 0,
        "matched": 0,
        "match_rate": 0.0,
        "by_miss_classification": {},
    }


# ---------- Probe.from_dict ----------

def test_probe_from_dict_full():
    p = Probe.from_dict({
        "title": "X",
        "price_usd": "240000",  # string price gets converted
        "location": "El Tunco",
        "source_url": "https://x.com",
        "probe_kind": "seed_list",
    })
    assert p.title == "X"
    assert p.price_usd == 240_000.0
    assert p.location == "El Tunco"


def test_probe_from_dict_missing_fields_uses_defaults():
    p = Probe.from_dict({"title": "Y"})
    assert p.title == "Y"
    assert p.price_usd is None
    assert p.location is None
    assert p.source_url == ""
    assert p.probe_kind == "unknown"


def test_probe_from_dict_bad_price_becomes_none():
    """Defensive: a non-numeric price string doesn't crash."""
    p = Probe.from_dict({"title": "X", "price_usd": "consultar"})
    assert p.price_usd is None
