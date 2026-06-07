"""
Tests for the Nexo Inmobiliario scraper (pulpo/scrapers/nexo.py).

After the 2026-05-29 rewrite the scraper consumes
``/api/v1/public/listings`` JSON via curl_cffi instead of parsing
2017-era static HTML. These tests:

  1. Verify the fixture-mode crawl path still produces well-formed
     records (offline contract unchanged).
  2. Exercise the pure helpers ``parse_listing``, ``_slugify``,
     ``_photo_urls``, ``_parse_price_usd``, ``_parse_location`` against
     handcrafted API payloads so the parser's behaviour is testable
     without a live network.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.nexo import (  # noqa: E402
    NexoScraper,
    _is_placeholder_rel,
    _parse_location,
    _parse_price_usd,
    _photo_urls,
    _slugify,
    parse_listing,
)


# ── Offline fixture crawl ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def offline_records():
    scraper = NexoScraper(offline=True)
    return scraper.crawl(limit=10, offline=True)


def test_offline_returns_records(offline_records):
    assert len(offline_records) >= 1


def test_required_fields_present(offline_records):
    for r in offline_records:
        assert r.get("source_id"), f"Missing source_id: {r}"
        assert r.get("url", "").startswith("https://nexo.com.sv"), f"Bad url: {r}"
        assert r.get("title"), f"Missing title: {r}"
        assert r.get("property_type") == "land"
        assert isinstance(r.get("photo_urls"), list), "photo_urls must be a list"
        assert r.get("location_text"), "location_text must not be empty"


def test_photo_urls_are_absolute(offline_records):
    """All photo URLs must be absolute (https://...) and non-empty when present."""
    for r in offline_records:
        for u in r.get("photo_urls", []):
            assert u.startswith("https://"), f"Non-absolute photo URL: {u}"


def test_no_thumbnail_in_photo_urls(offline_records):
    """Hero photo URL must not be the thumbnail variant."""
    for r in offline_records:
        for u in r.get("photo_urls", []):
            assert "_thumbnail" not in u, f"Thumbnail in photo_urls: {u}"


def test_el_salvador_in_location(offline_records):
    """El Salvador must appear in location_text for every listing."""
    for r in offline_records:
        assert "El Salvador" in r.get("location_text", ""), (
            f"El Salvador missing from location: {r['location_text']!r}"
        )


def test_price_text_contains_dollar(offline_records):
    for r in offline_records:
        if r.get("raw_price_text"):
            assert "$" in r["raw_price_text"], f"Price text missing $: {r['raw_price_text']!r}"


# ── Unit tests for the API JSON parser ────────────────────────────────

# Canonical payload shape — minimal version of one production record.
# Kept inline (not a JSON fixture file) so the schema-vs-test relationship
# stays visible: a future API change is a code change in this test, not
# a "did anyone notice the fixture drifted" silent failure.
_VALID_API_LISTING = {
    "id": 1061,
    "listing_code": "C-VE-TER-15-000-57812510",
    "listing_type": {
        "id": 15,
        "name": "Lotes Residenciales",
        "category": "terrenos",
        "sale_rent": "venta",
    },
    "title": "San José Villanueva - terreno en venta 583 vrs2",
    "description": "Lote residencial en venta...",
    "price": "115000.00",
    "area": "583.00",
    "address": "Altos de la casona",
    "city": {"name": "San José Villanueva"},
    "zone": None,
    "listing_medias": [
        {
            "media_type": "image",
            "relative_path": "media/listings/1061/secondary.jpeg",
            "is_primary": False,
        },
        {
            "media_type": "image",
            "relative_path": "media/listings/1061/hero.jpeg",
            "is_primary": True,
        },
    ],
    "is_published": True,
    "is_active": True,
}


def test_parse_listing_canonical():
    rec = parse_listing(_VALID_API_LISTING)
    assert rec is not None
    assert rec["source_id"] == "C-VE-TER-15-000-57812510"
    assert rec["property_type"] == "land"
    assert rec["price_usd"] == 115000.0
    assert "$" in rec["raw_price_text"]
    assert rec["raw_size_text"] == "583.00 v²"
    assert rec["location_text"] == "San José Villanueva, El Salvador"
    assert rec["url"].endswith("/15/1061/san-jose-villanueva-terreno-en-venta-583-vrs2")
    # is_primary=True media is hoisted to position 0
    assert rec["photo_urls"][0].endswith("hero.jpeg")
    assert rec["photo_urls"][1].endswith("secondary.jpeg")


def test_parse_listing_varas_round_trips_through_normalize_to_metric_m2():
    """End-to-end pin: Nexo's "<N> v²" raw_size_text MUST land as a
    numeric `area_m2` after the normalize step, with the canonical
    Salvadoran 1 v² = 0.698896 m² factor.

    The 2026-06 scraper audit hypothesized that Nexo's varas-unit area
    broke cross-source dedup because other sources emit m². Confirmed
    NOT a bug at the unit-conversion layer: `pulpo/units.py` already
    recognizes `v²` and converts. After dedup PR #753 dropped URL from
    the property fingerprint, Nexo's 583 v² listing now collides
    correctly with the same physical lot listed at ~407 m² on
    Encuentra24 / Santizo.

    This test exists as the regression pin so a future refactor of
    `pulpo/units.py` that drops `v²` recognition would fail loudly
    here rather than silently re-introducing the cross-source dedup
    gap. Do NOT skip or relax this test without filing a follow-up to
    re-audit cross-source overlap."""
    from pulpo.normalize import normalize

    rec = parse_listing(_VALID_API_LISTING)
    assert rec is not None
    li = normalize(rec, source="nexo")
    assert li is not None, "nexo listing should survive normalize"
    # 583.00 v² × 0.698896 m²/v² ≈ 407.46 m² (rounded by normalize.py).
    assert li.area_m2 is not None, "varas raw_size_text must yield numeric area_m2"
    assert 405.0 < li.area_m2 < 410.0, (
        f"expected ~407 m² from 583 v², got {li.area_m2} — has units.py "
        "dropped the v² regex or the SV M2_PER_VARA2 constant?"
    )
    # raw_size_text is preserved verbatim so the public UI can show the
    # original Salvadoran-customary string alongside the metric value.
    assert li.raw_size_text == "583.00 v²"


def test_parse_listing_skips_non_terreno_categories():
    """Apartamentos, casas, oficinas, etc. must not slip through."""
    payload = {**_VALID_API_LISTING}
    payload["listing_type"] = {
        "id": 1, "name": "Casas en Venta",
        "category": "residenciales", "sale_rent": "venta",
    }
    assert parse_listing(payload) is None


def test_parse_listing_skips_rentals():
    """sale_rent == 'alquiler' is out of scope for the for-sale Pulpo feed."""
    payload = {**_VALID_API_LISTING}
    payload["listing_type"] = {
        "id": 16, "name": "Terrenos en Alquiler",
        "category": "terrenos", "sale_rent": "alquiler",
    }
    assert parse_listing(payload) is None


def test_parse_listing_skips_unpublished():
    payload = {**_VALID_API_LISTING, "is_published": False}
    assert parse_listing(payload) is None


def test_parse_listing_skips_inactive():
    payload = {**_VALID_API_LISTING, "is_active": False}
    assert parse_listing(payload) is None


def test_parse_listing_skips_missing_essentials():
    payload = {**_VALID_API_LISTING, "title": ""}
    assert parse_listing(payload) is None
    payload = {**_VALID_API_LISTING, "id": None}
    assert parse_listing(payload) is None


def test_parse_listing_falls_back_to_id_when_code_missing():
    payload = {**_VALID_API_LISTING, "listing_code": None}
    rec = parse_listing(payload)
    assert rec is not None
    assert rec["source_id"] == "id:1061"


def test_parse_listing_address_fallback_when_city_null():
    payload = {**_VALID_API_LISTING, "city": None}
    rec = parse_listing(payload)
    assert rec is not None
    assert rec["location_text"] == "Altos de la casona, El Salvador"


def test_parse_listing_country_only_when_no_city_no_address():
    payload = {**_VALID_API_LISTING, "city": None, "address": ""}
    rec = parse_listing(payload)
    assert rec is not None
    assert rec["location_text"] == "El Salvador"


# ── Helper unit tests ─────────────────────────────────────────────────

def test_slugify_strips_spanish_accents():
    # Mirrors the SPA's normalize("NFD") + accent-strip — exact slug the
    # site itself would route to for this title.
    assert _slugify("San José Villanueva - 583 vrs²") == "san-jose-villanueva-583-vrs"


def test_slugify_falls_back_to_inmueble_on_empty():
    assert _slugify("") == "inmueble"
    assert _slugify("!!!") == "inmueble"


def test_photo_urls_primary_first_then_order():
    medias = [
        {"media_type": "image", "relative_path": "a.jpg", "is_primary": False},
        {"media_type": "image", "relative_path": "hero.jpg", "is_primary": True},
        {"media_type": "image", "relative_path": "b.jpg", "is_primary": False},
    ]
    urls = _photo_urls(medias)
    assert urls[0].endswith("hero.jpg")
    assert urls[1].endswith("a.jpg")
    assert urls[2].endswith("b.jpg")
    assert all(u.startswith("https://nexo.com.sv/") for u in urls)


def test_photo_urls_skips_non_image_media_types():
    """Future-proof: if the API ever returns videos/PDFs, drop them.

    The schema today only carries images, but defensiveness costs nothing
    and the pre-rewrite scraper had the same guard."""
    medias = [
        {"media_type": "video", "relative_path": "promo.mp4"},
        {"media_type": "image", "relative_path": "ok.jpg"},
    ]
    urls = _photo_urls(medias)
    assert urls == ["https://nexo.com.sv/ok.jpg"]


# Regression: NR-C — nexo "propiedad-no-disponible.jpg" placeholder
# leaked into ranked.json from 2026-05-26 onward and cascaded to a
# hero-canary failure that blocked the nightly's commit + deploy for
# 6 days. /qa 2026-06-01.
# Report: ~/.claude/plans/the-last-nightly-run-tranquil-starfish.md
def test_is_placeholder_rel_catches_known_pattern():
    assert _is_placeholder_rel("images/propiedad-no-disponible.jpg") is True
    # Tolerate leading slash + uppercase drift — broker CDNs sometimes serve
    # capitalised paths or normalise leading slashes.
    assert _is_placeholder_rel("/images/propiedad-no-disponible.jpg") is True
    assert _is_placeholder_rel("IMAGES/PROPIEDAD-NO-DISPONIBLE.JPG") is True


def test_is_placeholder_rel_does_not_match_real_paths():
    assert _is_placeholder_rel("media/listings/1061/hero.jpeg") is False
    assert _is_placeholder_rel("") is False


def test_photo_urls_filters_placeholders():
    """A media list mixing real + placeholder paths drops the placeholder."""
    medias = [
        {"media_type": "image", "relative_path": "images/propiedad-no-disponible.jpg",
         "is_primary": True},
        {"media_type": "image", "relative_path": "media/listings/1061/real.jpg",
         "is_primary": False},
    ]
    urls = _photo_urls(medias)
    assert urls == ["https://nexo.com.sv/media/listings/1061/real.jpg"]


def test_photo_urls_returns_empty_when_all_placeholders():
    medias = [
        {"media_type": "image", "relative_path": "images/propiedad-no-disponible.jpg",
         "is_primary": True},
    ]
    assert _photo_urls(medias) == []


def test_parse_listing_drops_when_only_placeholder_photos():
    """A listing whose only media is the placeholder is unrenderable — drop it.

    Pre-NR-C the row would have survived with photo_urls=[<placeholder>] and
    poisoned the hero / detail / newsletter surfaces. NR-C drops the row
    so the hero canary never sees the missing .hero.jpg cascade."""
    payload = {
        **_VALID_API_LISTING,
        "listing_medias": [
            {
                "media_type": "image",
                "relative_path": "images/propiedad-no-disponible.jpg",
                "is_primary": True,
            },
        ],
    }
    assert parse_listing(payload) is None


def test_parse_listing_keeps_when_mixed_real_and_placeholder_photos():
    """A listing with a placeholder + at least one real photo survives;
    the placeholder is filtered, the real photo becomes the hero."""
    payload = {
        **_VALID_API_LISTING,
        "listing_medias": [
            {
                "media_type": "image",
                "relative_path": "images/propiedad-no-disponible.jpg",
                "is_primary": True,
            },
            {
                "media_type": "image",
                "relative_path": "media/listings/1061/real.jpg",
                "is_primary": False,
            },
        ],
    }
    rec = parse_listing(payload)
    assert rec is not None
    assert rec["photo_urls"] == ["https://nexo.com.sv/media/listings/1061/real.jpg"]


def test_parse_price_usd_handles_string_decimals():
    val, text = _parse_price_usd("115000.00")
    assert val == 115000.0
    assert "$" in text


def test_parse_price_usd_handles_comma_separators():
    val, text = _parse_price_usd("1,500,000.00")
    assert val == 1500000.0


def test_parse_price_usd_returns_none_for_invalid():
    assert _parse_price_usd(None) == (None, "")
    assert _parse_price_usd("") == (None, "")
    assert _parse_price_usd("not a number") == (None, "")
    # Zero / negative prices treated as missing — the broker uses them
    # as a "price on request" marker.
    assert _parse_price_usd(0) == (None, "")
    assert _parse_price_usd("-5") == (None, "")


def test_parse_location_prefers_city_over_address():
    listing = {
        "city": {"name": "Comasagua"},
        "address": "Calle el almendro",
    }
    assert _parse_location(listing) == "Comasagua, El Salvador"
