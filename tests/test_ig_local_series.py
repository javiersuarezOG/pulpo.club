"""Tests for automation/ig_local_series.py — the local-voice content engine.

Pure functions; no I/O. We assert the format rotation, the slide plans, and
that every caption + comment passes the caption linter (the local voice must
never trip the listing-speak / urgency guards).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pytest   # noqa: E402

from automation import ig_local_series as S   # noqa: E402
from automation.ig_caption_lint import check as lint_check   # noqa: E402


def _cand(**over):
    base = {
        "listing_id": "src__1", "zone": "el-tunco", "area_m2": 1580.9,
        "price_usd": 225000.0, "price_per_m2": 142.32, "dist_beach_km": 0.0,
        "price_vs_zone_pct": -33.5, "property_type": "land",
    }
    base.update(over)
    return base


THREE = ["a.jpg", "b.jpg", "c.jpg"]
TWO = ["a.jpg", "b.jpg"]


# ── rotation ───────────────────────────────────────────────────────────

def test_rotation_is_deterministic_and_weights_guess():
    seq = [S.format_for_index(i) for i in range(len(S.FORMAT_ROTATION))]
    assert seq == list(S.FORMAT_ROTATION)
    # guess is the flywheel → appears more than the others in one cycle
    assert seq.count("guess") >= 2
    assert set(seq) == {"guess", "numero_uno", "regreso"}


def test_format_for_index_wraps():
    n = len(S.FORMAT_ROTATION)
    assert S.format_for_index(n) == S.format_for_index(0)


# ── every format builds + lints clean ─────────────────────────────────

@pytest.mark.parametrize("fmt", ["guess", "numero_uno", "regreso"])
def test_format_builds_and_lints_clean(fmt):
    post = S.build_post(fmt, _cand(), {}, THREE)
    assert post["format"] == fmt
    assert post["color_key"] in ("terrenos_playa", "casas_playa", "apartamentos")
    assert post["slides"], "must produce slides"
    assert lint_check(post["caption"]) == [], f"{fmt} caption trips the linter"
    assert lint_check(post["comment"]) == [], f"{fmt} comment trips the linter"
    assert "pulpo.club" in post["caption"]
    assert "#" in post["comment"]


# ── guess format: price hidden on cover, revealed at the end ───────────

def test_guess_hides_price_on_cover_reveals_at_end():
    post = S.build_post("guess", _cand(), {}, THREE)
    types = [s["t"] for s in post["slides"]]
    assert types[0] == "guess" and types[-1] == "reveal"
    cover = post["slides"][0]
    # the cover carries the hook + size teaser but NOT the price
    assert "$" not in (cover.get("hook", "") + cover.get("sub", ""))
    # the reveal carries the formatted price
    assert "$225,000" in post["slides"][-1]["price"]
    # and the caption reveals it only after the divider
    body = post["caption"]
    assert "$225,000" in body
    assert body.index("· · ·") < body.index("$225,000")


def test_guess_two_photos_collapses_to_cover_plus_reveal():
    post = S.build_post("guess", _cand(), {}, TWO)
    types = [s["t"] for s in post["slides"]]
    assert types == ["guess", "reveal"]


# ── numero_uno: data authority, playa-o-lago question ─────────────────

def test_numero_uno_leads_with_ranking_and_asks_a_question():
    post = S.build_post("numero_uno", _cand(), {}, THREE)
    assert post["slides"][0]["t"] == "statement"
    assert "#1" in post["caption"]
    assert "playa o lago" in post["caption"].lower()


# ── regreso: diaspora, bilingual ──────────────────────────────────────

def test_regreso_is_bilingual_and_warm():
    post = S.build_post("regreso", _cand(), {}, THREE)
    assert post["slides"][0]["t"] == "statement"
    assert post["slides"][-1]["t"] == "cta"
    # carries an English block for the diaspora reader
    assert "Salvadoran" in post["caption"]


# ── category mapping ──────────────────────────────────────────────────

def test_category_maps_type_and_beach_proximity():
    assert S.category(_cand(property_type="condo"))[0] == "apartamentos"
    assert S.category(_cand(property_type="house", dist_beach_km=0.5))[1] == "CASA DE PLAYA"
    assert S.category(_cand(property_type="house", dist_beach_km=40))[1] == "CASA"
    assert S.category(_cand(property_type="land", dist_beach_km=0.0))[1] == "TERRENO DE PLAYA"


# ── photo-count guard ─────────────────────────────────────────────────

def test_build_post_returns_none_when_too_few_photos():
    assert S.build_post("guess", _cand(), {}, ["only.jpg"]) is None
    assert S.build_post("numero_uno", _cand(), {}, ["only.jpg"]) is None
    # regreso only needs one photo
    assert S.build_post("regreso", _cand(), {}, ["only.jpg"]) is not None


def test_value_line_prefers_below_zone_signal():
    line = S._value_line(_cand(price_vs_zone_pct=-33.5))
    assert "bajo el precio de la zona" in line
    # no below-zone signal → falls back to a coastal/price line, never crashes
    line2 = S._value_line(_cand(price_vs_zone_pct=2.0, dist_beach_km=0.0))
    assert "Frente al mar" in line2
