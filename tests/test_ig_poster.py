"""Tests for automation/ig_poster.py.

Focus: HTML correctness without touching a real browser.  Rendering via
Playwright is exercised separately by the nightly + manual smoke runs;
unit tests would slow CI by ~20s if they launched Chromium per test.

What we DO test here:
  - build_html() produces an HTML doc with the right structure for each
    of the 6 poster systems
  - Listing fields render through ig_units formatters (no raw 18917.05)
  - photo_src resolves correctly (explicit URL > local hero > photo_urls)
  - Overrides take effect
  - HTML-escaping covers the four reserved chars
  - The render entry point invokes the (mocked) Playwright path with
    the expected viewport + output path

What we DO NOT test here:
  - Actual rendered pixels.  That belongs to the visual-fidelity sanity
    review of the 14 generated posters at PR-3 merge time.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation import ig_poster   # noqa: E402
from automation.ig_poster import (   # noqa: E402
    BIG_NUMBER, MAP_MARK, PALETTES, POSTER_H, POSTER_TYPES, POSTER_W,
    POST_IT, RECEIPT, STICKER, TYPO_MAX,
    _encode_photo_as_data_url, _html_escape, _listing_n, _resolve_photo_url,
    build_html, render_poster,
)


# ── fixtures ───────────────────────────────────────────────────────────

def _candidate(**override) -> dict:
    base = {
        "listing_id":          "bienesraices__test_001",
        "source":              "bienesraices",
        "source_id":           "test_001",
        "rank":                11,
        "zone":                "el-zonte",
        "department":          "La Libertad",
        "property_type":       "land",
        "area_m2":             18917.05,
        "price_usd":           667295.0,
        "price_per_m2":        35.27,
        "price_vs_zone_pct":   -93.0,
        "dist_beach_km":       1.4,
    }
    base.update(override)
    return base


def _listing(**override) -> dict:
    base = {
        "source":         "bienesraices",
        "source_id":      "test_001",
        "title":          "Raw Land 1.9 ha El Zonte",
        "photo_urls":     ["https://cdn.example.com/test_001.jpg"],
    }
    base.update(override)
    return base


# ── constants + invariants ─────────────────────────────────────────────

def test_poster_dimensions():
    """Pin the IG carousel slot — changing this breaks the publisher
    which uploads at exactly this aspect."""
    assert (POSTER_W, POSTER_H) == (1080, 1350)


def test_poster_types_stable():
    """Renames break the queue builder (PR-3) + admin widget."""
    assert set(POSTER_TYPES) == {
        TYPO_MAX, STICKER, POST_IT, BIG_NUMBER, RECEIPT, MAP_MARK,
    }


def test_palettes_stable():
    assert set(PALETTES) == {"ink", "paper", "cream"}


def test_dispatch_covers_all_types():
    """Every POSTER_TYPES entry has a body builder.  Guards against
    typos when someone adds a new system."""
    # The assertion at the bottom of ig_poster.py covers this at module
    # load; a second assert here makes the failure mode obvious if the
    # module ever ships in a partially-implemented state.
    assert set(ig_poster._DISPATCH) == set(POSTER_TYPES)


# ── _listing_n + _html_escape + _zone_label ────────────────────────────

def test_listing_n_pads_to_three_digits():
    assert _listing_n({"rank": 11}) == "LISTING N° 011"
    assert _listing_n({"rank": 200}) == "LISTING N° 200"
    assert _listing_n({"rank": 1}) == "LISTING N° 001"


def test_listing_n_missing_rank():
    assert _listing_n({}) == "LISTING N° ???"


def test_html_escape_covers_reserved():
    assert _html_escape("<>&\"'") == "&lt;&gt;&amp;&quot;'"
    assert _html_escape(None) == ""


# ── _resolve_photo_url ─────────────────────────────────────────────────

def test_resolve_photo_url_prefers_explicit(tmp_path):
    src = _resolve_photo_url(
        _candidate(), _listing(),
        photo_url="https://cdn.test/explicit.jpg",
        photo_dir=tmp_path,
    )
    assert src == "https://cdn.test/explicit.jpg"


def test_resolve_photo_url_falls_back_to_local_hero(tmp_path):
    """If no explicit URL, prefer the local .hero.jpg over the remote
    photo_urls (base64-encoded so the HTML stays self-contained)."""
    hero = tmp_path / "bienesraices_test_001.hero.jpg"
    hero.write_bytes(b"\xff\xd8\xff\xe0fake-jpg-bytes")
    src = _resolve_photo_url(
        _candidate(), _listing(),
        photo_url=None, photo_dir=tmp_path,
    )
    assert src.startswith("data:image/jpeg;base64,")


def test_resolve_photo_url_falls_back_to_remote_url(tmp_path):
    """No local file → use first photo_urls entry."""
    src = _resolve_photo_url(
        _candidate(), _listing(),
        photo_url=None, photo_dir=tmp_path,
    )
    assert src == "https://cdn.example.com/test_001.jpg"


def test_resolve_photo_url_returns_empty_when_none_available(tmp_path):
    src = _resolve_photo_url(
        _candidate(), _listing(photo_urls=[]),
        photo_url=None, photo_dir=tmp_path,
    )
    assert src == ""


def test_encode_photo_as_data_url_jpg(tmp_path):
    p = tmp_path / "x.jpg"
    p.write_bytes(b"hello-jpg")
    src = _encode_photo_as_data_url(p)
    assert src.startswith("data:image/jpeg;base64,")


def test_encode_photo_as_data_url_png(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"hello-png")
    src = _encode_photo_as_data_url(p)
    assert src.startswith("data:image/png;base64,")


# ── build_html per system ──────────────────────────────────────────────

def test_build_html_typo_max_contains_units_via_ig_units():
    """The hero element must render through format_area_m2 (19,000 m²)
    — never the raw 18917.05."""
    html = build_html(_candidate(), _listing(), TYPO_MAX, "ink")
    assert "19,000 m²" in html
    assert "18917" not in html
    assert "$667,295" in html
    assert "EL-ZONTE" in html  # zone label uppercased
    assert "poster typo_max ink" in html


def test_build_html_typo_max_paper_palette():
    html = build_html(_candidate(), _listing(), TYPO_MAX, "paper")
    assert "poster typo_max paper" in html


def test_build_html_typo_max_uses_eyebrow_listing_n():
    html = build_html(_candidate(rank=11), _listing(), TYPO_MAX, "ink")
    assert "LISTING N° 011" in html


def test_build_html_sticker_includes_photo_and_stamps():
    html = build_html(
        _candidate(), _listing(), STICKER, "ink",
        photo_url="https://cdn.test/p.jpg",
    )
    assert 'src="https://cdn.test/p.jpg"' in html
    assert "TOP RANK" in html
    assert "TENTÁCULO" in html
    assert "EL-ZONTE" in html
    assert "LISTING N° 011" in html


def test_build_html_sticker_stamp_palette_maps():
    """ink → green stamp; paper → red; cream → gold (smoke-test the map)."""
    for palette, css_cls in [("ink", "green"), ("paper", "red"), ("cream", "gold")]:
        html = build_html(_candidate(), _listing(), STICKER, palette,
                          photo_url="x")
        assert f"corner-stamp {css_cls}" in html


def test_build_html_post_it_renders_alert_with_pct():
    html = build_html(
        _candidate(price_vs_zone_pct=-93), _listing(), POST_IT, "ink",
        photo_url="x",
    )
    assert "ALERTA · −93%" in html  # typographic minus per format_zone_delta_pct
    assert "— el pulpo" in html


def test_build_html_post_it_can_take_custom_note():
    html = build_html(
        _candidate(), _listing(), POST_IT, "ink",
        photo_url="x",
        overrides={"note": "Custom note here.", "sig": "— firmado"},
    )
    assert "Custom note here." in html
    assert "— firmado" in html


def test_build_html_big_number_renders_ppm_by_default():
    html = build_html(_candidate(), _listing(), BIG_NUMBER, "gold")
    assert "$35.27/m²" in html
    assert "poster big_number gold" in html


def test_build_html_big_number_accepts_custom_number():
    html = build_html(
        _candidate(), _listing(), BIG_NUMBER, "gold",
        overrides={"number": "$11.82", "context": "el más bajo del catálogo."},
    )
    assert "$11.82" in html
    assert "el más bajo del catálogo." in html


def test_build_html_receipt_renders_items():
    items = [
        {"n": "01", "desc": "Surf City", "sub": "698 m²", "price": "$140K"},
        {"n": "02", "desc": "El Cuco",   "sub": "16,000 m²", "price": "$225K"},
    ]
    totals = [
        {"label": "DESDE", "value": "$140K"},
        {"label": "5 ITEMS", "value": "CURADO"},
    ]
    html = build_html(
        _candidate(), _listing(), RECEIPT, "cream",
        overrides={
            "title": "Top 5", "subtitle": "5 TERRENOS",
            "items": items, "totals": totals,
            "footer": "pulpo.club · top 5",
        },
    )
    assert "Top 5" in html
    assert "Surf City" in html
    assert "El Cuco" in html
    assert "$140K" in html
    assert "$225K" in html
    assert "DESDE" in html
    assert "CURADO" in html


def test_build_html_receipt_ink_mode():
    html = build_html(
        _candidate(), _listing(), RECEIPT, "ink",
        overrides={"items": [], "totals": []},
    )
    assert "poster receipt ink" in html


def test_build_html_map_mark_renders_region_oriente():
    html = build_html(_candidate(), _listing(), MAP_MARK, "cream")
    # Contains the SVG path for the Oriente highlight + pin.
    assert "El-Zonte" in html  # zone label title-cased
    assert "TENTÁCULO" in html
    # Region paths use heart-red fill.
    assert "oklch(0.62 0.20 25)" in html


def test_build_html_map_mark_central_region():
    html = build_html(
        _candidate(), _listing(), MAP_MARK, "cream",
        overrides={"region": "central"},
    )
    assert "oklch(0.62 0.20 25)" in html  # Central region path still red


def test_build_html_unknown_poster_type_raises():
    with pytest.raises(ValueError):
        build_html(_candidate(), _listing(), "bogus", "ink")


def test_build_html_unknown_palette_for_typo_max_raises():
    with pytest.raises(ValueError):
        build_html(_candidate(), _listing(), TYPO_MAX, "magenta")


def test_build_html_always_includes_font_link():
    """Without Google Fonts the Playwright render falls back to Georgia
    and the brand starts looking like 90s WordPress."""
    html = build_html(_candidate(), _listing(), TYPO_MAX, "ink")
    assert "Instrument+Serif" in html
    assert "Inter:" in html
    assert "JetBrains+Mono" in html


def test_build_html_doctype():
    """Browser must render in standards mode."""
    html = build_html(_candidate(), _listing(), TYPO_MAX, "ink")
    assert html.startswith("<!DOCTYPE html>")


# ── render_poster (mocked Playwright) ──────────────────────────────────

def test_render_poster_invokes_playwright_with_expected_args(tmp_path):
    """render_poster() builds HTML + delegates to _render_via_playwright
    with positional (html, output_path).  Defaults for width/height live
    on the renderer signature — the orchestrator doesn't override them."""
    out = tmp_path / "out.png"

    def _fake(html, output_path, **kwargs):
        # Verify the orchestrator passed through the right things:
        assert "poster typo_max ink" in html
        assert output_path == out
        # Renderer defaults match the IG carousel slot.
        assert kwargs.get("width", POSTER_W) == POSTER_W
        assert kwargs.get("height", POSTER_H) == POSTER_H
        output_path.write_bytes(b"fake-png")
        return output_path

    with patch.object(ig_poster, "_render_via_playwright", side_effect=_fake):
        rv = render_poster(_candidate(), _listing(), TYPO_MAX, "ink", out)

    assert rv == out
    assert out.read_bytes() == b"fake-png"


def test_render_poster_default_path(tmp_path, monkeypatch):
    """No output_path → defaults to web/data/ig_assets/{listing_id}/
    poster_{type}_{palette}.png."""
    captured = {}

    def _fake(html, output_path, **kwargs):
        captured["path"] = output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"x")
        return output_path

    monkeypatch.chdir(tmp_path)
    with patch.object(ig_poster, "_render_via_playwright", side_effect=_fake):
        render_poster(_candidate(), _listing(), STICKER, "ink",
                      photo_url="https://test/x.jpg")

    # The default path is relative (web/data/ig_assets/...); after the
    # monkeypatch chdir, the resolved file lives under tmp_path.
    expected_rel = Path("web/data/ig_assets/bienesraices__test_001/poster_sticker_ink.png")
    assert captured["path"] == expected_rel
    assert (tmp_path / expected_rel).exists()
