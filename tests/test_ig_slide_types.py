"""Tests for the new guess/reveal slide types in ig_campaign_poster.

build_slide_html is pure (no browser) but base64-encodes the photo, so we
write a tiny temp JPEG to feed it.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pytest   # noqa: E402

from automation.ig_campaign_poster import build_slide_html, _DISPATCH   # noqa: E402


@pytest.fixture
def img(tmp_path):
    from PIL import Image
    p = tmp_path / "photo.jpg"
    Image.new("RGB", (1080, 1350), (40, 120, 180)).save(p, "JPEG")
    return str(p)


def test_guess_and_reveal_registered():
    assert "guess" in _DISPATCH and "reveal" in _DISPATCH


def test_guess_cover_shows_hook_and_hides_price(img):
    html = build_slide_html(
        {"t": "guess", "img": img, "ribbon": "TERRENO DE PLAYA",
         "hook": "¿Cuánto\ncuesta?", "sub": "1,581 m² en El Tunco.\nAdiviná 👇"},
        "#1073b8",
    )
    assert "ghook" in html
    assert "¿Cuánto" in html and "Adiviná" in html
    assert "TERRENO DE PLAYA" in html
    # a guess cover must NOT render a price-pill element (the class is
    # defined in the shared stylesheet, but nothing should USE it here)
    assert 'class="pricepill"' not in html


def test_reveal_shows_price_and_kicker(img):
    html = build_slide_html(
        {"t": "reveal", "img": img, "ribbon": "TERRENO DE PLAYA",
         "kicker": "¿Le atinaste?", "price": "$225,000"},
        "#1073b8",
    )
    assert "rvl" in html
    assert "$225,000" in html
    assert "¿Le atinaste?" in html


def test_reveal_long_price_uses_smaller_class(img):
    html = build_slide_html(
        {"t": "reveal", "img": img, "price": "$11,200,000"}, "#1073b8",
    )
    assert "amt sm" in html


def test_unknown_slide_type_raises(img):
    with pytest.raises(ValueError):
        build_slide_html({"t": "nope", "img": img}, "#1073b8")
