"""Tests for pulpo.quality_score.

PR A6 — the PRD's "soft quality score" used as a ranking nudge.
RANK-ONLY: this score never gates visibility; the strictness slider
(A2) handles the hard gate and the FE shelf-aware photo waiver (A3)
handles the rendering layer.

Scoring table:

  +3  photos_count >= 3
  +2  area_m2 present (numeric > 0)
  +1  description >= 30 words
  +1  contact info (email OR phone OR agent_url)
  +1  source institutional (encuentra24 / remax / century21 / citymax / csbr / ...)
  +1  price_per_m2 calculable (price_usd > 0 AND area_m2 > 0)
  +1  card_eligible (photo phase verdict)
  +1  hero_eligible (only when card_eligible is also True)

Max 11.
"""
from __future__ import annotations

from pulpo.quality_score import (
    INSTITUTIONAL_SOURCES,
    MAX_SCORE,
    compute,
)


def _li(**fields):
    base = {
        "source": "encuentra24",
        "url": "https://example.test/x",
        "price_usd": 100_000,
        "area_m2": 500,
        "property_type": "land",
        "photos_count": 3,
        "description": "x" * 200,  # easily > 30 words once split by re
        "broker_email": "agent@example.test",
        "broker_phone": "555-1234",
        "card_eligible": True,
        "hero_eligible": True,
    }
    base.update(fields)
    return base


def test_complete_institutional_listing_hits_max_or_near():
    """A listing with photos>=3, area, description, contact, institutional
    source, and price+area scores 9 (the full ramp). Worth nine points."""
    # description must have >= 30 actual words, not just chars
    li = _li(description=" ".join(["palabra"] * 40))
    score = compute(li)
    assert score == MAX_SCORE


def test_empty_listing_scores_zero():
    li = {
        "source": "unknown_source",
        "url": "",
        "price_usd": None,
        "area_m2": None,
        "photos_count": 0,
        "description": "",
    }
    assert compute(li) == 0


def test_photos_threshold_at_three():
    assert compute(_li(photos_count=2)) == compute(_li(photos_count=0)) + 0  # both lose +3
    assert compute(_li(photos_count=3)) > compute(_li(photos_count=2))


def test_area_present_adds_two():
    base = compute(_li(area_m2=None))
    with_area = compute(_li(area_m2=500))
    # area=500 also unlocks price_per_m2 calculable, so +2 (area) + +1 (ppm) = +3
    assert with_area == base + 3


def test_description_word_count_threshold_at_thirty():
    base_li = _li(description="short")
    long_li = _li(description=" ".join(["word"] * 30))
    assert compute(long_li) == compute(base_li) + 1
    # Exactly 29 words: no bonus
    short_li = _li(description=" ".join(["word"] * 29))
    assert compute(short_li) == compute(base_li)


def test_contact_info_any_of_three():
    no_contact = _li(broker_email=None, broker_phone=None, agent_url=None)
    base_score = compute(no_contact)
    for field in ("broker_email", "broker_phone", "agent_url"):
        li = _li(broker_email=None, broker_phone=None, agent_url=None)
        li[field] = "value@example.com"
        assert compute(li) == base_score + 1, f"{field} should grant +1"


def test_institutional_sources_membership():
    """The institutional set must include the PRD-prioritized agency
    portals + the franchise scrapers."""
    expected = {"encuentra24", "remax", "century21", "citymax"}
    assert expected.issubset(INSTITUTIONAL_SOURCES)


def test_institutional_source_grants_one():
    base = compute(_li(source="unknown_source"))
    inst = compute(_li(source="encuentra24"))
    assert inst == base + 1


def test_price_per_m2_calculable_grants_one():
    """+1 fires only when BOTH price and area are present and > 0.
    Missing either drops the bonus."""
    full = compute(_li(price_usd=100_000, area_m2=500))
    no_price = compute(_li(price_usd=None, area_m2=500))
    no_area = compute(_li(price_usd=100_000, area_m2=None))
    # Missing area: lose +2 (area) + +1 (ppm) = -3
    assert no_area == full - 3
    # Missing price: lose +1 (ppm) only
    assert no_price == full - 1


def test_image_fitness_adds_two_when_both_eligible():
    """card_eligible + hero_eligible grants +2 over the same listing with
    both image verdicts None (unverified)."""
    none_li = _li(card_eligible=None, hero_eligible=None)
    both_li = _li(card_eligible=True, hero_eligible=True)
    assert compute(both_li) == compute(none_li) + 2


def test_hero_eligible_without_card_eligible_confers_nothing():
    """The nesting matters: hero_eligible only counts when card_eligible is
    also True. card_eligible None/False zeroes both image points even if
    hero_eligible is True."""
    base = compute(_li(card_eligible=None, hero_eligible=None))
    none_card = compute(_li(card_eligible=None, hero_eligible=True))
    false_card = compute(_li(card_eligible=False, hero_eligible=True))
    assert none_card == base
    assert false_card == base


def test_card_eligible_alone_adds_one():
    """card_eligible True with hero_eligible False/None grants exactly +1."""
    base = compute(_li(card_eligible=None, hero_eligible=None))
    card_only = compute(_li(card_eligible=True, hero_eligible=False))
    assert card_only == base + 1


def test_score_is_int_in_range():
    """Score is always an int in [0, MAX_SCORE]."""
    for li in (
        _li(),
        _li(photos_count=0),
        _li(area_m2=None, price_usd=None),
        {"source": "unknown"},
    ):
        s = compute(li)
        assert isinstance(s, int)
        assert 0 <= s <= MAX_SCORE


def test_compute_accepts_dataclass_like_object():
    """Works on a dataclass-like attribute object, not just dicts.
    Mirrors the actual Listing dataclass in production."""

    class FakeListing:
        source = "encuentra24"
        price_usd = 100_000
        area_m2 = 500
        photos_count = 3
        description = " ".join(["palabra"] * 40)
        broker_email = "x@example.com"
        broker_phone = None
        agent_url = None
        card_eligible = True
        hero_eligible = True

    score = compute(FakeListing())
    assert score == MAX_SCORE
