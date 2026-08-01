"""The zone-image library fails CLOSED: only a vetted, licensed image counts;
anything unlicensed or malformed is treated as absent so the opener falls back
to the brand-safe designed poster. Adding a zone is one valid entry."""
from __future__ import annotations

from automation import ig_zone_images as zi


def test_seeded_zones_are_served_uncovered_fall_back():
    # The 5 verified zones resolve; an uncovered zone / None falls back to poster.
    for z in ("el-tunco", "el-zonte", "lago-coatepeque", "el-cuco", "lago-ilopango"):
        assert zi.has(z), f"{z} should be served"
    assert zi.get("nowhere-zone") is None
    assert zi.get(None) is None


def test_license_families_normalize():
    assert zi._license_family("CC BY-SA 4.0") == "cc-by-sa"
    assert zi._license_family("CC BY 4.0") == "cc-by"
    assert zi._license_family("CC0") == "cc0"
    assert zi._license_family("Public domain") == "public_domain"
    assert zi._license_family("pulpo_owned") == "pulpo_owned"
    assert zi._license_family("All rights reserved") is None   # rejected


def test_share_alike_is_flagged():
    # El Tunco/El Zonte are CC BY-SA; Coatepeque (CC BY) is not.
    assert zi.is_share_alike("el-tunco") is True
    assert zi.is_share_alike("lago-coatepeque") is False


def test_seeded_entries_require_attribution_only_for_cc_by():
    assert zi._requires_attribution("CC BY 4.0") is True
    assert zi._requires_attribution("CC BY-SA 3.0") is True
    assert zi._requires_attribution("CC0") is False


def test_a_valid_owned_entry_is_served(monkeypatch):
    monkeypatch.setitem(zi.ZONE_IMAGES, "el-tunco", {
        "image": f"{zi.ZONE_DIR}/el-tunco.jpg",
        "credit": "Pulpo", "license": "pulpo_owned",
    })
    got = zi.get("el-tunco")
    assert got and got["image"].endswith("el-tunco.jpg")
    assert "el-tunco" in zi.all_zones()
    assert ("el-tunco", "the iconic rock formations at golden hour") not in zi.missing_shots()


def test_unlicensed_or_malformed_entries_are_rejected(monkeypatch):
    bad = {
        "broker_photo":  {"image": "x.jpg", "credit": "Broker", "license": "broker"},
        "no_credit":     {"image": "x.jpg", "license": "pulpo_owned"},
        "no_image":      {"credit": "Pulpo", "license": "pulpo_owned"},
        "cc0_no_source": {"image": "x.jpg", "credit": "X", "license": "cc0"},  # cc0 needs license_url
    }
    for zone, entry in bad.items():
        monkeypatch.setitem(zi.ZONE_IMAGES, zone, entry)
        assert zi.get(zone) is None, f"{zone} should be rejected"


def test_cc0_with_source_is_accepted(monkeypatch):
    monkeypatch.setitem(zi.ZONE_IMAGES, "el-zonte", {
        "image": f"{zi.ZONE_DIR}/el-zonte.jpg", "credit": "A. Photographer",
        "license": "cc0", "license_url": "https://example.org/img",
    })
    assert zi.has("el-zonte")
