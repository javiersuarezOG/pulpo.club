"""The generator ties Scout + Creative Director + Copywriter + code-stamp into
review items. These pin the guarantees a reviewer relies on: brand-safe only,
diversified, every lever gets airtime, and every item carries a router-valid
attribution code — with NO queue write or publish anywhere in the path."""
from __future__ import annotations

import re

import pytest

from automation import ig_content_categories as cats
from automation import ig_generate_post as gen
from automation import ig_photo_gate


@pytest.fixture(autouse=True)
def _stub_gate(monkeypatch):
    """Test the GENERATOR, not the photo gate: treat any listing with a real
    hero photo as brand-safe. The gate itself has its own suite."""
    monkeypatch.setattr(ig_photo_gate, "passes_gate",
                        lambda li, cfg=None: bool(li.get("hero_photo_path")))


def _listing(sid, zone, price, *, safe=True):
    """A minimal brand-safe (or not) land listing the photo gate accepts."""
    li = {
        "source": "test", "source_id": sid, "zone": zone,
        "property_type": "terreno", "price_usd": price, "rank_score": price / 1000.0,
        "hero_photo_path": f"web/photos/{sid}.jpg",
        "title_canonical": {"en": f"Land {sid}", "es": f"Terreno {sid}"},
        "size_m2": 4000, "dist_beach_km": 0.3,
        "photo_urls": [f"https://cdn/{sid}_{i}.jpg" for i in range(6)], "photos_count": 6,
        "reasons_to_buy": [
            {"es": "frente amplio", "en": "wide frontage"},
            {"es": "cerca del mar", "en": "near the sea"},
        ],
    }
    if not safe:
        li["hero_photo_path"] = None
        li["photo_urls"] = []
        li["photos_count"] = 0
    return li


def _pool():
    zones = ["mizata", "el-zonte", "la-libertad", "el-tunco", "el-cuco",
             "la-union", "conchagua", "el-sunzal", "punta-mango"]
    return [_listing(f"s{i}", z, 50_000 + i * 40_000) for i, z in enumerate(zones)]


def test_rotate_levers_covers_every_lever_no_starvation():
    levers = gen.rotate_levers(len(cats.SLUGS))
    assert set(levers) == set(cats.SLUGS)


def test_rotate_levers_offset_varies_the_lead():
    assert gen.rotate_levers(3, start=0)[0] != gen.rotate_levers(3, start=1)[0]


def test_pick_listings_is_zone_diversified():
    picks = gen.pick_listings(_pool(), 7)
    zones = [p["zone"] for p in picks]
    assert len(zones) == 7
    assert len(set(zones)) == 7  # every pick a distinct zone


def test_generate_batch_shape_and_coverage():
    batch = gen.generate_batch(_pool(), 7, start_day=301)
    assert len(batch) == 7
    # every lever represented exactly once across a 7-post week
    assert sorted(p["lever"] for p in batch) == sorted(cats.SLUGS)
    for p in batch:
        assert p["caption_es"] and p["caption_en"]
        assert p["comment_es"] and p["comment_en"]
        assert p["hero_photo_path"]           # brand-safe: real photo
        assert p["zone"]
        assert p["slide_count"] >= 4          # every post is a ≥4-slide story
        assert p["slides"][0]["role"] == "opener" and p["slides"][-1]["role"] == "cta"


def test_every_code_is_router_valid_and_day_sequenced():
    batch = gen.generate_batch(_pool(), 7, start_day=301)
    code_re = re.compile(r"^ig-d(\d{1,4})-([a-z_]+)(?:-(?:free|pro))?$")
    for i, p in enumerate(batch):
        assert p["day"] == 301 + i
        m = code_re.match(p["attribution_code"])
        assert m, p["attribution_code"]
        assert m.group(2) in cats.CATEGORIES
        assert p["go_url"] == f"/go/{p['attribution_code']}"


def test_batch_excludes_brand_unsafe_listings():
    pool = _pool() + [_listing("unsafe", "el-tunco", 999_000, safe=False)]
    batch = gen.generate_batch(pool, len(pool))
    assert all(p["hero_photo_path"] for p in batch)
    assert "test_unsafe" not in {p["listing_id"] for p in batch}


def test_generate_batch_is_pure_no_side_effects():
    pool = _pool()
    snapshot = [dict(li) for li in pool]
    gen.generate_batch(pool, 5)
    assert pool == snapshot  # inputs untouched; nothing written anywhere


def test_tier_follows_the_lever_registry_default():
    batch = gen.generate_batch(_pool(), 7, start_day=1)
    by_lever = {p["lever"]: p for p in batch}
    for slug in cats.SLUGS:
        assert by_lever[slug]["tier"] == cats.get(slug)["default_tier"]
