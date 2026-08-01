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
        "zone": "el-tunco", "department": "La Libertad", "dist_beach_km": 0.2,
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


def test_arc_opens_on_hero_and_closes_on_cta():
    sb = ig_story.build_storyboard(_listing(), "aspiration")
    assert sb[0]["role"] == "opener"
    assert sb[0]["image"].endswith("pic0.jpg")   # hero = first ordered photo
    assert sb[-1]["role"] == "cta"


def test_middle_slides_are_the_listings_own_reasons():
    li = _listing()
    sb = ig_story.build_storyboard(li, "investment")
    proof = [s["text_es"] for s in sb if s["role"] == "proof"]
    assert "22 m de frente a la carretera" in proof
    assert "3 minutos a la playa" in proof


def test_every_slide_has_an_image_and_both_languages():
    sb = ig_story.build_storyboard(_listing(), "social_proof")
    for s in sb:
        assert s["image"] and s["text_es"] and s["text_en"]
        assert s["text_es"] != s["text_en"] or s["role"] == "cta"  # cta line is shared


def test_never_more_slides_than_photos_no_blanks():
    li = _listing(photo_urls=["https://cdn/a.jpg", "https://cdn/b.jpg",
                              "https://cdn/c.jpg", "https://cdn/d.jpg"], photos_count=4)
    sb = ig_story.build_storyboard(li, "scarcity")
    assert len(sb) <= 4
    assert len({s["index"] for s in sb}) == len(sb)  # indices unique
    imgs = [s["image"] for s in sb]
    assert all(imgs)


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
