"""Tests for the 'Tu pedazo de paraíso' campaign builder (ig_campaign +
ig_campaign_poster).  All pure/no-browser: render_slide is monkeypatched
so these run in CI without Playwright."""
from __future__ import annotations

import json

import pytest

from automation import ig_campaign
from automation.ig_campaign_poster import (
    CATEGORY_COLORS,
    INSPIRACION,
    build_slide_html,
)


# ── ig_campaign_poster: pure HTML builders ─────────────────────────────

def test_category_colors_match_board():
    # These hexes are shared with web/app + the review board; a change
    # here means a cross-surface drift, so pin them.
    assert CATEGORY_COLORS["inspiracion"] == "#e8462a"
    assert CATEGORY_COLORS["casas_playa"] == "#0a97ab"
    assert CATEGORY_COLORS["terrenos_lago"] == "#2f9e44"


def test_build_slide_html_statement_is_selfcontained():
    html = build_slide_html(
        {"t": "statement", "eyebrow": "El Salvador", "l1": "La costa",
         "l2": "no crece.", "punch": "Pero la fila sí."},
        INSPIRACION,
    )
    assert html.startswith("<!DOCTYPE html>")
    assert "1080px" in html and "1350px" in html
    assert "no crece." in html and "El Salvador" in html
    # self-contained: no external <img> fetches
    assert "<img" not in html


def test_build_slide_html_stat_and_usp():
    stat = build_slide_html({"t": "stat", "big": "139",
                             "label": "de 1,916", "src": "Datos Pulpo"}, INSPIRACION)
    assert ">139<" in stat and "Dato real" in stat
    usp = build_slide_html({"t": "usp", "eyebrow": "Cómo ayuda Pulpo",
                            "title": "Las tenemos todas.", "body": "Rankeadas."}, INSPIRACION)
    assert "Las tenemos todas." in usp


def test_build_slide_html_escapes_and_rejects_unknown():
    html = build_slide_html({"t": "usp", "eyebrow": "x",
                             "title": "<script>", "body": "b"}, INSPIRACION)
    assert "<script>" not in html and "&lt;script&gt;" in html
    with pytest.raises(ValueError):
        build_slide_html({"t": "nope"}, INSPIRACION)


# ── ig_campaign: item build + queue patch ──────────────────────────────

@pytest.fixture
def no_browser(monkeypatch, tmp_path):
    """Stub the Playwright render so render_post writes marker PNGs."""
    def fake_render(spec, color, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"PNG")
        return output_path
    monkeypatch.setattr(ig_campaign, "render_slide", fake_render)
    monkeypatch.setattr(ig_campaign, "ASSETS_ROOT", tmp_path / "campaign")


def test_render_post_day1_item_shape(no_browser):
    post = ig_campaign.PLAN_BY_DAY[201]
    item = ig_campaign.render_post(post)
    assert item["day"] == 201
    assert item["selector"] == "campaign_v1"
    assert item["approved"] is True and item["posted"] is False
    # 3 slides → poster_path + 2 carousel photos
    assert item["poster_path"].endswith("slide1.png")
    assert len(item["carousel_photo_paths"]) == 2
    # bilingual wire: ES then EN joined by the divider, hashtags on comment
    assert ig_campaign.DIV in item["caption"]
    assert "oceanfront" in item["caption"].lower()
    assert item["comment"].strip().endswith("#TuPedazoDeParaiso")
    # inspiration post carries no listing
    assert item["listing_ids"] == [] and item["primary_listing_id"] is None


def test_patch_queue_supersedes_and_is_idempotent(no_browser, tmp_path):
    queue = tmp_path / "ig_queue.json"
    queue.write_text(json.dumps({"items": [
        {"day": 100, "shelf": "old", "approved": True, "posted": True},          # history: untouched
        {"day": 105, "shelf": "autopilot_brand", "selector": "autopilot",
         "approved": True, "posted": False, "scheduled_for": "2026-07-11T01:00:00+00:00"},
    ]}), encoding="utf-8")

    item = ig_campaign.render_post(ig_campaign.PLAN_BY_DAY[201])
    ig_campaign.patch_queue(item, queue_path=queue)
    data = json.loads(queue.read_text(encoding="utf-8"))
    by_day = {it["day"]: it for it in data["items"]}

    assert by_day[100]["posted"] is True                      # history untouched
    assert by_day[105]["approved"] is False                   # old pending superseded
    assert by_day[105]["status"] == "superseded_campaign_v1"
    assert by_day[201]["approved"] is True                    # campaign item inserted

    # idempotent: re-applying doesn't duplicate day 201
    ig_campaign.patch_queue(item, queue_path=queue)
    data2 = json.loads(queue.read_text(encoding="utf-8"))
    assert sum(1 for it in data2["items"] if it["day"] == 201) == 1
