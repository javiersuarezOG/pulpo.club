"""The zone-image library fails CLOSED: only a vetted, licensed image counts;
anything unlicensed or malformed is treated as absent so the opener falls back
to the brand-safe designed poster. Adding a zone is one valid entry."""
from __future__ import annotations

from automation import ig_zone_images as zi


def test_registry_starts_empty_so_openers_fall_back_safely():
    # No image ships until a human vets it — get() returns None → poster fallback.
    assert zi.get("el-tunco") is None
    assert zi.has("el-tunco") is False
    assert zi.get(None) is None


def test_shot_list_is_non_empty_and_everything_is_missing_today():
    assert len(zi.TARGET_ZONES) >= 10
    missing = dict(zi.missing_shots())
    for zone, _note in zi.TARGET_ZONES:
        assert zone in missing        # nothing sourced yet


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
