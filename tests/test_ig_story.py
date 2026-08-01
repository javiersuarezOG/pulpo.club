"""The Story Director builds a ≥4-slide carousel that reads opener → place →
the listing's OWN reasons-to-buy → meaning → CTA, one photo per slide. The
middle is drawn from source data so no two listings tell the same story."""
from __future__ import annotations

import pytest

from automation import ig_content_categories as cats
from automation import ig_photo_gate
from automation import ig_story


def _listing(**over):
    li = {
        # an UNCOVERED zone by default, so the opener exercises the poster
        # fallback; the curated-image test overrides to a registered zone.
        "zone": "test-cove", "department": "La Libertad", "dist_beach_km": 0.2,
        "photo_urls": [f"https://cdn/pic{i}.jpg" for i in range(9)],
        "photos_count": 9,
        "reasons_to_buy": [
            {"es": "22 m de frente a la carretera", "en": "22 m of road frontage"},
            {"es": "3 minutos a la playa", "en": "3 minutes to the beach"},
            {"es": "entrada plana", "en": "flat entrance"},
        ],
    }
    li.update(over)
    return li


@pytest.fixture(autouse=True)
def _stub_order(monkeypatch):
    # Isolate the story arc from the photo-gate's per-frame scoring: hero-first,
    # source order. The gate has its own suite.
    monkeypatch.setattr(ig_photo_gate, "order_photo_indices",
                        lambda li: list(range(li.get("photos_count") or 0)))


def test_storyboard_has_at_least_four_slides():
    sb = ig_story.build_storyboard(_listing(), "scarcity")
    assert len(sb) >= ig_story.MIN_SLIDES


def test_opener_and_cta_are_designed_middle_is_real_photos():
    sb = ig_story.build_storyboard(_listing(), "aspiration")
    assert sb[0]["role"] == "opener" and sb[0]["designed"] is True
    assert sb[-1]["role"] == "cta" and sb[-1]["designed"] is True
    # opener without a curated zone image = poster fallback (no raw photo)
    assert sb[0]["kind"] == "poster" and sb[0]["image"] is None
    # middle slides are real listing photos, flagged for human watermark review
    middle = sb[1:-1]
    assert middle and all(s["designed"] is False and s["needs_review"] for s in middle)
    assert all(s["kind"] == "listing_photo" and s["image"] for s in middle)


def test_curated_zone_image_becomes_the_opener(monkeypatch):
    monkeypatch.setitem(ig_story.ig_zone_images.ZONE_IMAGES, "test-cove", {
        "image": "web/data/ig_assets/zones/test-cove.jpg",
        "credit": "Pulpo", "license": "pulpo_owned",
    })
    sb = ig_story.build_storyboard(_listing(), "aspiration")
    assert sb[0]["kind"] == "zone_photo"
    assert sb[0]["image"].endswith("test-cove.jpg")
    assert sb[0]["needs_review"] is False   # curated + licensed = trusted


def test_designed_slides_never_need_review():
    sb = ig_story.build_storyboard(_listing(), "scarcity")
    for s in sb:
        if s["designed"]:
            assert s["needs_review"] is False


def test_middle_slides_are_the_listings_own_reasons():
    li = _listing()
    sb = ig_story.build_storyboard(li, "investment")
    proof = [s["text_es"] for s in sb if s["role"] == "proof"]
    assert "22 m de frente a la carretera" in proof
    assert "3 minutos a la playa" in proof


def test_every_slide_has_text_both_languages():
    sb = ig_story.build_storyboard(_listing(), "social_proof")
    for s in sb:
        assert s["text_es"] and s["text_en"]
        assert s["text_es"] != s["text_en"] or s["role"] == "cta"  # cta line is shared


def test_real_photo_slides_never_exceed_available_photos():
    li = _listing(photo_urls=["https://cdn/a.jpg", "https://cdn/b.jpg",
                              "https://cdn/c.jpg", "https://cdn/d.jpg"], photos_count=4)
    sb = ig_story.build_storyboard(li, "scarcity")
    assert len({s["index"] for s in sb}) == len(sb)          # indices unique
    real = [s for s in sb if s["kind"] == "listing_photo"]
    assert len(real) <= 4 and all(s["image"] for s in real)  # no blank real slides
    # each real slide gets a distinct photo (no repeats)
    assert len({s["image"] for s in real}) == len(real)


def test_capped_at_ten_and_cta_survives_trim():
    li = _listing(photo_urls=[f"https://cdn/p{i}.jpg" for i in range(20)], photos_count=20,
                  reasons_to_buy=[{"es": f"razón {i}", "en": f"reason {i}"} for i in range(15)])
    sb = ig_story.build_storyboard(li, "education")
    assert len(sb) <= ig_story.MAX_SLIDES
    assert sb[-1]["role"] == "cta"             # closer preserved even when trimming
    assert sb[0]["role"] == "opener"


def test_no_photos_yields_no_story():
    assert ig_story.build_storyboard(_listing(photo_urls=[], photos_count=0), "scarcity") == []


def test_every_lever_produces_a_valid_opener():
    for lever in cats.SLUGS:
        sb = ig_story.build_storyboard(_listing(), lever)
        assert sb and sb[0]["text_es"]
