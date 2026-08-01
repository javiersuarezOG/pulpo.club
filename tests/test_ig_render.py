"""ig_render turns a post into safe slide specs + an ig_publish queue item.
Safe-by-construction: the only photo is the curated zone image; everything else
is a designed slide. These pin that contract without invoking Playwright."""
from __future__ import annotations

from pathlib import Path

import pytest

from automation import ig_render
from automation import ig_zone_images


def _post(zone="mizata", lever="aspiration", **over):
    p = {
        "day": 254, "lever": lever, "zone": zone, "department": "La Libertad",
        "price_usd": 350000.0, "listing_id": "test_1",
        "attribution_code": "ig-d254-aspiration", "go_url": "/go/ig-d254-aspiration",
        "caption_es": "**Hook.**\n\nBody.\n\npulpo.club · link en bio",
        "comment_es": "Comentario.\n\n#Pulpo",
        "slides": [
            {"role": "opener", "text_es": "POV: nadie sabe todavía que esto es tuyo.", "kind": "poster"},
            {"role": "place", "text_es": "Mizata · minutos del mar"},
            {"role": "proof", "text_es": "22 m de frente"},
            {"role": "proof", "text_es": "3 minutos a la playa"},
            {"role": "meaning", "text_es": "Y tu domingo empieza acá."},
            {"role": "cta", "text_es": "pulpo.club · link en bio"},
        ],
    }
    p.update(over)
    return p


def _fake_renderer(spec, color, out_path):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(b"jpeg")   # stand-in; no Playwright in tests
    return out_path


def test_specs_are_opener_detail_usps_cta_and_designed_safe():
    specs = ig_render.build_specs(_post())
    kinds = [s["t"] for s in specs]
    assert kinds[0] in ("story", "statement")     # opener
    assert kinds[-1] == "cta"                       # closer
    assert "detail" in kinds and "usp" in kinds     # the listing + its USPs
    # NO raw-photo slide type anywhere (no broker photos) unless it's the
    # curated zone image on a story opener
    assert all(s["t"] != "photo" for s in specs)


def test_poster_fallback_when_zone_has_no_image():
    specs = ig_render.build_specs(_post(zone="nowhere-zone"))
    assert specs[0]["t"] == "statement"             # designed text opener
    assert specs[0]["l1"] and specs[0]["l2"]


def test_zone_photo_opener_when_curated(monkeypatch):
    monkeypatch.setitem(ig_zone_images.ZONE_IMAGES, "el-tunco", {
        "image": "web/data/ig_assets/zones/el-tunco.jpg", "credit": "X",
        "license": "CC0", "license_url": "http://c/x"})
    specs = ig_render.build_specs(_post(zone="el-tunco"))
    assert specs[0]["t"] == "story"
    assert specs[0]["img"].endswith("el-tunco.jpg")


def test_eyebrow_not_doubled_in_hook():
    # eyebrow "POV" + hook "POV: …" must not render "POV" twice
    specs = ig_render.build_specs(_post(zone="nowhere", lever="aspiration"))
    assert not specs[0]["l1"].upper().startswith("POV")


def test_attribution_only_for_cc_by(monkeypatch):
    monkeypatch.setitem(ig_zone_images.ZONE_IMAGES, "cc0z", {
        "image": "z.jpg", "credit": "A", "license": "CC0", "license_url": "http://x"})
    monkeypatch.setitem(ig_zone_images.ZONE_IMAGES, "byz", {
        "image": "z.jpg", "credit": "B", "license": "CC BY 4.0", "license_url": "http://x"})
    assert ig_render._attribution(_post(zone="cc0z")) == ""          # CC0 → no attribution
    attr = ig_render._attribution(_post(zone="byz"))
    assert "B" in attr and "CC BY 4.0" in attr                       # CC-BY → credited


def test_render_post_returns_publish_ready_item():
    item = ig_render.render_post(_post(), out_root=Path("/tmp/sb_test"), renderer=_fake_renderer)
    assert item["poster_path"] and item["carousel_photo_paths"]
    assert item["approved"] is False and item["posted"] is False    # staged, not live
    assert item["shelf"] == "social_brain"
    assert item["primary_listing_id"] == "test_1"
    # poster + carousel = the full carousel, capped at IG's 10
    assert 1 + len(item["carousel_photo_paths"]) <= 10
