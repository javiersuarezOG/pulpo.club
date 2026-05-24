"""
Tests for the essurf scraper (pulpo/scrapers/essurf.py).

Two surfaces:
  1. Offline-fixture smoke (the source-integration contract).
  2. Pure-function tests on _map, _classify_from_url, _title_from_slug,
     _parse_area_from_specs using synthetic API records shaped like
     real essurf payloads (audited 2026-05-25).
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.essurf import (  # noqa: E402
    ESSurfScraper, _URL_TOKEN_TO_TYPE, _classify_from_url, _map,
    _parse_area_from_specs, _title_from_slug,
)


# ── Offline-fixture smoke ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def offline_records():
    return ESSurfScraper(offline=True).crawl(limit=20, offline=True)


def test_offline_returns_records(offline_records):
    if not offline_records:
        pytest.skip("No essurf fixture records — add to fixtures/sample_listings.json")
    assert len(offline_records) >= 1


def test_required_fields_present(offline_records):
    if not offline_records:
        pytest.skip("No fixture records")
    for r in offline_records:
        assert r.get("source") == "essurf"
        assert r.get("source_id"), f"Missing source_id: {r}"
        assert r.get("url", "").startswith("https://elsalvadorsurfrealestate.com/")
        assert r.get("title"), "Missing title"
        assert r.get("property_type") in {"land", "house", "condo"}
        assert isinstance(r.get("photo_urls", []), list)


# ── URL → property_type classification ────────────────────────────────


def test_url_token_to_type_map_is_total():
    """Every URL slug type token we audited maps to a known Pulpo type."""
    assert set(_URL_TOKEN_TO_TYPE.values()) <= {"house", "condo", "land"}
    # The four most common tokens MUST be mapped (audited 2026-05-25):
    for tok in ("home", "lot", "land", "condo", "apartment"):
        assert tok in _URL_TOKEN_TO_TYPE


@pytest.mark.parametrize("url,expected", [
    ("https://elsalvadorsurfrealestate.com/bahia-dorada-home-for-sale-460000/", "house"),
    ("https://elsalvadorsurfrealestate.com/el-zonte-lot-for-sale-180000/", "land"),
    ("https://elsalvadorsurfrealestate.com/punta-mango-condo-for-sale-350000/", "condo"),
    ("https://elsalvadorsurfrealestate.com/sunzal-villa-for-sale-900000/", "house"),
    ("https://elsalvadorsurfrealestate.com/costa-del-sol-apartment-for-sale-250000/", "condo"),
    ("https://elsalvadorsurfrealestate.com/atami-terreno-for-sale-100000/", "land"),
    # Unknown — returns None so the listing is dropped
    ("https://elsalvadorsurfrealestate.com/special-investment-opportunity/", None),
])
def test_classify_from_url(url, expected):
    assert _classify_from_url(url) == expected


# ── Title synthesis from slug ─────────────────────────────────────────


def test_title_strips_price_suffix():
    assert _title_from_slug("bahia-dorada-home-for-sale-460000") == "Bahia Dorada Home"


def test_title_strips_for_sale_token():
    assert _title_from_slug("el-zonte-lot-for-sale-180000") == "El Zonte Lot"


def test_title_handles_no_price_suffix():
    """Some slugs omit the price — title still parses cleanly."""
    assert _title_from_slug("atami-home-special-listing") == "Atami Home Special Listing"


# ── _parse_area_from_specs ────────────────────────────────────────────


def test_parse_area_prefers_m2():
    val, raw = _parse_area_from_specs({"square mts.": "701.39", "beds": "4"})
    assert val == 701.39
    assert raw == "701.39 m2"


def test_parse_area_falls_back_to_varas():
    val, raw = _parse_area_from_specs({"vara cuadrada": "1,487.00", "beds": "4"})
    assert val is None
    assert raw == "1487.0 v2"


def test_parse_area_returns_none_when_absent():
    assert _parse_area_from_specs({}) == (None, "")
    assert _parse_area_from_specs({"beds": "4"}) == (None, "")


def test_parse_area_tolerates_bad_values():
    assert _parse_area_from_specs({"square mts.": "n/a"}) == (None, "")


# ── _map: full pipeline ──────────────────────────────────────────────


def _coastal_house_api_rec(**override) -> dict:
    base = {
        "id":     5268,
        "url":    "https://elsalvadorsurfrealestate.com/atami-home-for-sale-270000/",
        "status": "active",
        "price":  270000,
        "priceString": "$270,000.00",
        "address": {
            "city":  "Tamanique", "state": "La Libertad",
            "street": "Atami",   "zip":    "00177",
            "full":   "Atami, Tamanique, La Libertad 00177",
        },
        "specs":   {"square mts.": "701.39", "beds": "4", "baths": "3", "vara cuadrada": "1,000.00"},
        "beds":    "4",
        "baths":   "3",
        "lat":     "13.4999",
        "lng":     "-89.4191",
        "images":  ["https://assets.example.com/photo1.jpg"],
        "thumb":   "https://assets.example.com/thumb.jpg",
        "thumb2x": "https://assets.example.com/thumb2x.jpg",
        "badges":  [],
        "classes": "active",
    }
    base.update(override)
    return base


def test_map_active_house_passes():
    out = _map(_coastal_house_api_rec())
    assert out is not None
    assert out["source"] == "essurf"
    assert out["source_id"] == "5268"
    assert out["property_type"] == "house"
    assert out["price_usd"] == 270000.0
    assert out["bedrooms"] == 4
    assert out["bathrooms"] == 3.0
    assert out["lat"] == 13.4999
    assert out["lng"] == -89.4191
    # Built area present because specs has both m² and varas² (so the m²
    # value is the built area not the lot — the heuristic guarantees this).
    assert out["built_area_m2"] == 701.39
    # Photos deduped: thumb2x + thumb + images[0] = 3 unique
    assert len(out["photo_urls"]) == 3


def test_map_drops_sold_listings():
    sold = _coastal_house_api_rec(status="sold")
    assert _map(sold) is None


def test_map_drops_rentals():
    rental = _coastal_house_api_rec(
        url="https://elsalvadorsurfrealestate.com/atami-home-for-rent-2000/",
    )
    assert _map(rental) is None


def test_map_drops_unknown_url_type():
    weird = _coastal_house_api_rec(
        url="https://elsalvadorsurfrealestate.com/special-investment-opportunity/",
    )
    assert _map(weird) is None


def test_map_drops_inland_house_via_default_gate():
    """House gate: no coastal zone in location_text + no waterfront kw
    in title → dropped. The synthesized title is 'San Salvador Home',
    no waterfront tokens."""
    inland = _coastal_house_api_rec(
        url="https://elsalvadorsurfrealestate.com/san-salvador-home-for-sale-300000/",
        address={"full": "San Salvador, San Salvador 00001",
                 "city": "San Salvador", "state": "San Salvador"},
    )
    assert _map(inland) is None


def test_map_land_in_coastal_zone_passes_without_force_gate():
    """Land is gate-exempt by default (essurf is coastal-only, force=False).
    Even an inland slug here would pass — kept for parity with other
    scrapers' convention."""
    lot = _coastal_house_api_rec(
        id=4900,
        url="https://elsalvadorsurfrealestate.com/el-zonte-lot-for-sale-180000/",
        address={"full": "El Zonte, La Libertad", "city": "El Zonte", "state": "La Libertad"},
        specs={"square mts.": "1200.0"},
        beds=None, baths=None,
    )
    out = _map(lot)
    assert out is not None
    assert out["property_type"] == "land"


def test_map_appends_el_salvador_when_missing():
    """location_text should always end with 'El Salvador' so downstream
    zone-detection regexes see a stable suffix."""
    out = _map(_coastal_house_api_rec())
    assert "El Salvador" in out["location_text"]


def test_map_handles_missing_lat_lng():
    no_geo = _coastal_house_api_rec(lat=None, lng=None)
    out = _map(no_geo)
    assert out is not None
    assert "lat" not in out
    assert "lng" not in out
