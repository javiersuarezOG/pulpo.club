"""
Data quality tests — property-type filter, price-outlier check,
development tagging, and price-None ranker stability.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pulpo.normalize import is_non_land_title, normalize
from pulpo.developments import detect_development
from pulpo.ranker import rank
from pulpo.models import Listing


# ── Phase 1: property-type title filter ──────────────────────────────────────

@pytest.mark.parametrize("title,source,expect_drop", [
    # Always-drop patterns
    ("3-Bedroom House in El Zonte, $850,000",        "goodlife",      True),
    ("Newly Built Condo with Partial Ocean view",     "goodlife",      True),
    ("Apartment en El Zonte, $300k",                 "bienesraices",  True),
    # House/casa WITH land keyword — must NOT drop
    ("Land With House Near the Beach",               "remax",         False),
    ("Terreno con casa en La Libertad",              "bienesraices",  False),
    ("Finca con casa colonial 10mz",                 "remax",         False),
    # Pure land titles — must NOT drop
    ("Lot in El Zonte, $350,000",                    "goodlife",      False),
    ("TERRENO 40mz PLAYA EL TUNCO",                  "bienesraices",  False),
    ("Farm for sale – Guayaltepe, Ahuachapán",       "remax",         False),
    # Filter not applied to oceanside / century21
    ("3-Bedroom House in Surf City",                 "oceanside",     False),
    ("Casa con piscina $1M",                         "century21",     False),
])
def test_property_type_filter(title, source, expect_drop):
    assert is_non_land_title(title, source) == expect_drop, (
        f"is_non_land_title({title!r}, {source!r}) expected {expect_drop}"
    )


# ── Phase 2: price-outlier check via normalize ────────────────────────────────

def _raw(price_usd, area_m2, title="Lot test", source="bienesraices"):
    return {
        "source_id": "test-001",
        "url": "https://example.com/lot",
        "title": title,
        "price_usd": price_usd,
        "area_m2": area_m2,
        "description": "",
        "raw_price_text": "",
        "raw_size_text": "",
        "location_text": "El Salvador",
        "property_type": "land",
    }


@pytest.mark.parametrize("price,area,should_survive_normalize", [
    # Parser-error range — normalize passes these through (outlier check is in run.py)
    # but the run.py canary will drop them. These test that normalize itself doesn't
    # silently corrupt them.
    (7.0,        153_757.0, True),   # classic parser error — survives normalize
    (4.3,        320_000.0, True),   # survives normalize
    # Legitimate listings — must survive
    (1_000.0,    5_000.0,  True),
    (50_000.0,   1_400.0,  True),
    (215_000.0,  2_000.0,  True),
    (299_000.0, 11_760.0,  True),
])
def test_normalize_price_outlier_not_dropped_at_normalize_stage(price, area, should_survive_normalize):
    """normalize() itself does not drop price outliers — that's run.py's job.
    These listings survive normalize() regardless of price/area ratio.
    """
    raw = _raw(price, area)
    li = normalize(raw, source="bienesraices")
    if should_survive_normalize:
        assert li is not None, f"normalize dropped ${price}/{area}m² — should survive"
    else:
        assert li is None


# ── Phase 3: development tagging ─────────────────────────────────────────────

@pytest.mark.parametrize("title,description,expect_flag,expect_name", [
    # Known named developments
    ("TERRENO PLAYA ISLA SAN BLAS 558vr2 (PRIVADO) LADO PLAYA", "",
     True, "San Blas"),
    ("TERRENO PLAYA 58mz ( SURF CITY 1 ) ZONA MIZATA", "",
     True, "Surf City 1"),
    ("Lote en Surf City 2, vista al oceano", "",
     True, "Surf City 2"),
    ("Two Oceanview Lots in Solymar", "",
     True, "Solymar"),
    ("Subdivision Mirador Del Mar",   "",
     True, "Mirador del Mar"),
    ("Terreno en Complejo Privado Atami | La Libertad", "",
     True, "Atami"),
    ("Lotes en Venta en Canarias Surf City 1", "",
     True, "Canarias"),
    # Generic indicators — flag set but no named development
    ("Lote en Condominio Vista Mar", "",
     True, None),
    ("Terreno en lotificacion Parque Real", "",
     True, None),
    # Standalone / loose parcels — no flag
    ("Finca en venta en San Matias Canton Santa Teresa La Libertad", "",
     False, None),
    ("Land for sale with high housing potential in Tonacatepeque", "",
     False, None),
    ("30 Manzanas Beachfront El Cuco frente al mar", "",
     False, None),
])
def test_development_tagging(title, description, expect_flag, expect_name):
    flag, name = detect_development(title, description)
    assert flag == expect_flag, (
        f"detect_development({title!r}) flag={flag}, expected {expect_flag}"
    )
    assert name == expect_name, (
        f"detect_development({title!r}) name={name!r}, expected {expect_name!r}"
    )


def test_development_fields_on_listing():
    """Listings with development names get both fields set through normalize()."""
    raw = _raw(150_000, 500, title="Lote en Canarias Surf City 1 vista al mar")
    li = normalize(raw, source="bienesraices")
    assert li is not None
    assert li.is_in_development is True
    assert li.development_name == "Canarias"

    raw2 = _raw(250_000, 5_000, title="Terreno frente al mar El Cuco")
    li2 = normalize(raw2, source="bienesraices")
    assert li2 is not None
    assert li2.is_in_development is False
    assert li2.development_name is None


# ── Phase 4(b): price_usd=None listings survive and don't crash ranker ────────

def _listing(**kwargs) -> Listing:
    defaults = dict(
        source="test", source_id="t1", url="https://x.com/1",
        scraped_at="2026-01-01T00:00:00Z", title="Lot",
        zone="el-tunco", area_m2=1000.0,
        price_usd=None, price_per_m2=None,
    )
    defaults.update(kwargs)
    return Listing(**defaults)


def test_none_price_survives_normalize():
    """Listings with no price but valid area survive normalize() (Phase 4-b)."""
    raw = {
        "source_id": "btc-lot",
        "url": "https://example.com/btc",
        "title": "Two Oceanview Lots in El Zonte Hills, 2.75 BTC",
        "price_usd": None,
        "area_m2": 2_000.0,
        "raw_price_text": "2.75 BTC",
        "raw_size_text": "2000 m2",
        "description": "",
        "location_text": "El Zonte",
        "property_type": "land",
    }
    li = normalize(raw, source="goodlife")
    assert li is not None, "BTC-priced listing with area should survive normalize()"
    assert li.price_usd is None
    assert li.area_m2 == 2000.0


def test_ranker_stable_with_none_price():
    """Ranker completes without error when some listings have price_usd=None."""
    # Provide 4 priced listings so comp pool meets MIN_COMPS=3, plus one no-price.
    listings = [
        _listing(source_id="no-price", price_usd=None,       price_per_m2=None,  area_m2=1_000.0),
        _listing(source_id="cheap",    price_usd=50_000.0,   price_per_m2=50.0,  area_m2=1_000.0),
        _listing(source_id="mid",      price_usd=200_000.0,  price_per_m2=200.0, area_m2=1_000.0),
        _listing(source_id="pricey",   price_usd=800_000.0,  price_per_m2=800.0, area_m2=1_000.0),
        _listing(source_id="v-pricey", price_usd=1_500_000.0,price_per_m2=1500.0,area_m2=1_000.0),
    ]
    ranked = rank(listings)
    assert len(ranked) == 5
    assert all(li.rank is not None for li in ranked)
    assert all(li.rank_score is not None for li in ranked)
    # "cheap" should rank above "no-price" (cheap gets high value score;
    # no-price gets the neutral 35 default from NO_PRICE_VALUE_DEFAULT).
    cheap_rank   = next(li for li in ranked if li.source_id == "cheap").rank
    no_price_rank = next(li for li in ranked if li.source_id == "no-price").rank
    assert cheap_rank < no_price_rank, (
        f"Cheap listing (rank {cheap_rank}) should beat no-price (rank {no_price_rank})"
    )
