"""Shared fixtures for the newsletter test module.

Builds synthetic ranked.json rows in the shape automation/run.py writes,
so tests don't depend on the live web/data/ranked.json snapshot.
"""

from __future__ import annotations

import pytest

from automation.newsletter.store import email_hash
from automation.newsletter.types import Preference, Recipient


def _listing(
    *,
    rank: int,
    source: str = "remax",
    source_id: str | None = None,
    title: str = "Listing",
    title_en: str = "Listing",
    title_es: str = "Propiedad",
    zone: str = "el-zonte",
    municipality: str = "Chiltiupán",
    department: str = "La Libertad",
    price_usd: float = 200_000,
    price_per_m2: float = 65,
    price_vs_zone_pct: float = -10,
    property_type: str = "land",
    is_beachfront: bool = False,
    is_walk_to_beach: bool = False,
    is_repriced: bool = False,
    is_motivated: bool = False,
    first_seen_at: str = "2026-05-15T00:00:00+00:00",
    days_listed: int = 3,
    data_quality_score: float = 0.85,
    area_m2: float = 2000,
    has_power: bool = True,
    has_water: bool = True,
    has_paved_access: bool = False,
    dist_beach_km: float | None = 2.0,
    dist_airport_km: float | None = 40.0,
    description: str = "A beautiful property with ocean views.",
    photo_url: str = "https://example.com/photo.jpg",
    url: str | None = None,
    reasons: list[dict] | None = None,
) -> dict:
    resolved_id = source_id if source_id is not None else f"{rank:04d}"
    return {
        "rank": rank,
        "rank_score": 100 - rank,
        "value_score": 90,
        "location_score": 85,
        "momentum_score": 50,
        "rank_reasons": ["value 90 (mock)", "location 85 (mock)"],
        "source": source,
        "source_id": resolved_id,
        "url": url or f"https://{source}.example.com/{rank:04d}",
        "title": title,
        "title_canonical": {"en": title_en, "es": title_es},
        "short_description_canonical": {
            "en": description,
            "es": "Una propiedad hermosa con vistas al océano.",
        },
        "reasons_to_buy": reasons or [
            {"en": "Ocean view", "es": "Vista al mar"},
            {"en": "Power on site", "es": "Luz disponible"},
        ],
        "zone": zone,
        "municipality": municipality,
        "department": department,
        "property_type": property_type,
        "price_usd": price_usd,
        "price_per_m2": price_per_m2,
        "price_vs_zone_pct": price_vs_zone_pct,
        "is_beachfront": is_beachfront,
        "is_walk_to_beach": is_walk_to_beach,
        "is_repriced": is_repriced,
        "is_motivated": is_motivated,
        "first_seen_at": first_seen_at,
        "days_listed": days_listed,
        "data_quality_score": data_quality_score,
        "area_m2": area_m2,
        "has_power": has_power,
        "has_water": has_water,
        "has_paved_access": has_paved_access,
        "dist_beach_km": dist_beach_km,
        "dist_airport_km": dist_airport_km,
        "has_ocean_view": True,
        "has_water_body": False,
        "is_flat": True,
        "photo_urls": [photo_url],
        "hero_photo_path": f"/photos/{source}_{resolved_id}.jpg",
    }


@pytest.fixture
def make_listing():
    return _listing


@pytest.fixture
def ranked_pool(make_listing):
    """A 31-listing pool with mixed zones, types, prices — enough to exercise filters."""
    out: list[dict] = []
    # 10 in La Libertad / el-zonte, all under $500k so the Pro filter keeps them
    for i in range(10):
        out.append(make_listing(
            rank=i + 1,
            zone="el-zonte",
            department="La Libertad",
            price_usd=100_000 + i * 40_000,        # 100k → 460k
            is_walk_to_beach=(i < 3),
        ))
    # 10 in La Libertad / el-tunco — over budget for the Free fixture, houses
    for i in range(10):
        out.append(make_listing(
            rank=i + 11,
            zone="el-tunco",
            department="La Libertad",
            price_usd=300_000 + i * 100_000,
            property_type="house",
        ))
    # 10 elsewhere
    for i in range(10):
        out.append(make_listing(
            rank=i + 21,
            zone="costa-del-sol",
            department="La Paz",
            price_usd=150_000 + i * 30_000,
        ))
    # One stale candidate for the "skip" pick. Department-level zone so it
    # doesn't perturb el-zonte/el-tunco zone-filter counts but still matches
    # a La Libertad + land preference.
    out.append(make_listing(
        rank=99,
        source="goodlife",
        title="Stale listing",
        title_en="Stale listing",
        title_es="Propiedad estancada",
        zone="la-libertad",
        department="La Libertad",
        price_usd=180_000,
        days_listed=145,
        price_vs_zone_pct=40,
        data_quality_score=0.5,
    ))
    return out


@pytest.fixture
def pro_with_prefs() -> Recipient:
    return Recipient(
        email_hash=email_hash("pro-with-prefs@test.local"),
        display_name="Javier",
        locale="en",
        tier="pro",
        has_account=True,
        preference=Preference(
            departments=["La Libertad"],
            property_types=["land"],
            max_price_usd=500_000,
        ),
    )


@pytest.fixture
def free_with_prefs() -> Recipient:
    return Recipient(
        email_hash=email_hash("free-with-prefs@test.local"),
        display_name="Sofía",
        locale="en",
        tier="free",
        has_account=True,
        preference=Preference(
            zones=["el-zonte"],
            property_types=["land"],
            max_price_usd=250_000,
        ),
    )


@pytest.fixture
def logged_no_prefs() -> Recipient:
    return Recipient(
        email_hash=email_hash("no-prefs@test.local"),
        display_name="Lucas",
        locale="en",
        tier="pro",
        has_account=True,
        preference=Preference(),
    )


@pytest.fixture
def anonymous() -> Recipient:
    return Recipient(
        email_hash=email_hash("anon@test.local"),
        display_name=None,
        locale="en",
        tier="free",
        has_account=False,
        preference=Preference(),
    )
