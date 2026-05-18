"""Tests for pulpo.scrapers._photo_url_upgrade (Phase 4 O1).

Covers each of the 5 strategies plus fall-through behavior + HEAD
validation. Strategy logic is exercised directly against the helper's
public API; no live network.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pulpo.scrapers import _photo_url_upgrade as helper  # noqa: E402


def _patch_config(monkeypatch, cfg: dict) -> None:
    helper.load_photo_config.cache_clear()
    monkeypatch.setattr(helper, "load_photo_config", lambda: cfg)


def test_noop_strategy_returns_urls_unchanged(monkeypatch):
    cfg = {"sources": {"x": {"full_res": {"strategy": "noop"}}}, "defaults": {}}
    _patch_config(monkeypatch, cfg)
    urls = ["https://a.test/1.jpg", "https://a.test/2.jpg"]
    assert helper.upgrade_photo_urls("x", urls) == urls


def test_url_replace_literal_and_regex(monkeypatch):
    cfg = {
        "sources": {
            "x": {
                "full_res": {
                    "strategy": "url_replace",
                    "rules": [
                        {"match": "/thumb/", "replace": "/full/"},
                        {"match": r"_\d+x\d+\.jpg$", "replace": ".jpg", "regex": True},
                    ],
                }
            }
        },
        "defaults": {},
    }
    _patch_config(monkeypatch, cfg)
    out = helper.upgrade_photo_urls(
        "x",
        ["https://a.test/thumb/pic_600x400.jpg", "https://a.test/full/keep.jpg"],
    )
    assert out == [
        "https://a.test/full/pic.jpg",
        "https://a.test/full/keep.jpg",
    ]


def test_wordpress_size_strip_default_regex(monkeypatch):
    cfg = {
        "sources": {
            "x": {"full_res": {"strategy": "wordpress_size_strip"}}
        },
        "defaults": {},
    }
    _patch_config(monkeypatch, cfg)
    out = helper.upgrade_photo_urls(
        "x",
        [
            "https://a.test/uploads/hero-1024x768.jpg",
            "https://a.test/uploads/hero.JPEG",
            "https://a.test/uploads/no-suffix.png",
        ],
    )
    assert out == [
        "https://a.test/uploads/hero.jpg",
        "https://a.test/uploads/hero.JPEG",
        "https://a.test/uploads/no-suffix.png",
    ]


def test_field_swap_promotes_payload_url(monkeypatch):
    cfg = {
        "sources": {
            "x": {
                "full_res": {
                    "strategy": "field_swap",
                    "rules": [{"from_field": "featured_image", "to_field": "image_hd"}],
                }
            }
        },
        "defaults": {},
    }
    _patch_config(monkeypatch, cfg)
    payload = {
        "featured_image": "https://a.test/low.jpg",
        "image_hd": "https://a.test/hd.jpg",
    }
    out = helper.upgrade_photo_urls(
        "x",
        ["https://a.test/low.jpg", "https://a.test/other.jpg"],
        payload=payload,
    )
    assert out[0] == "https://a.test/hd.jpg"
    assert "https://a.test/other.jpg" in out


def test_cloudfront_image_handler_raises_resize(monkeypatch):
    cfg = {
        "sources": {
            "x": {
                "full_res": {
                    "strategy": "cloudfront_image_handler",
                    "rules": [{"raise_resize_to": 2400}],
                }
            }
        },
        "defaults": {},
    }
    _patch_config(monkeypatch, cfg)
    payload = {
        "bucket": "alterestate",
        "key": "static/properties/abc/photo.jpeg",
        "edits": {"resize": {"width": 1024, "height": 768}},
    }
    encoded = (
        base64.b64encode(json.dumps(payload).encode())
        .decode()
        .rstrip("=")
    )
    url = f"https://d2.cloudfront.net/{encoded}"
    out = helper.upgrade_photo_urls("x", [url])
    assert len(out) == 1
    new_payload_b64 = out[0].rsplit("/", 1)[-1]
    decoded = json.loads(
        base64.b64decode(new_payload_b64 + "=" * (-len(new_payload_b64) % 4))
    )
    assert decoded["edits"]["resize"]["width"] == 2400
    assert "height" not in decoded["edits"]["resize"]


def test_cloudfront_image_handler_non_payload_url_passthrough(monkeypatch):
    cfg = {
        "sources": {
            "x": {
                "full_res": {
                    "strategy": "cloudfront_image_handler",
                    "rules": [{"drop_resize": True}],
                }
            }
        },
        "defaults": {},
    }
    _patch_config(monkeypatch, cfg)
    # A regular URL (not base64-encoded JSON) survives untouched.
    url = "https://d2.cloudfront.net/static/properties/abc/photo.jpeg"
    assert helper.upgrade_photo_urls("x", [url]) == [url]


def test_unknown_source_falls_through_to_defaults(monkeypatch):
    cfg = {"sources": {}, "defaults": {"min_source_long_side_px": 1080}}
    _patch_config(monkeypatch, cfg)
    urls = ["https://a.test/1.jpg"]
    assert helper.upgrade_photo_urls("never-configured", urls) == urls


def test_validate_via_head_falls_back_on_404(monkeypatch):
    cfg = {
        "sources": {
            "x": {
                "full_res": {
                    "strategy": "url_replace",
                    "rules": [{"match": "thumb", "replace": "full"}],
                    "validate_via_head": True,
                }
            }
        },
        "defaults": {},
    }
    _patch_config(monkeypatch, cfg)

    class _R:
        status_code = 404

    fake_httpx = mock.MagicMock()
    fake_httpx.head.return_value = _R()
    with mock.patch.dict(sys.modules, {"httpx": fake_httpx}):
        out = helper.upgrade_photo_urls("x", ["https://a.test/thumb/pic.jpg"])
    assert out == ["https://a.test/thumb/pic.jpg"]


def test_source_weight_resolves_per_source_and_defaults(monkeypatch):
    cfg = {
        "sources": {"down": {"deprioritize_weight": 0.5}},
        "defaults": {"deprioritize_weight": 1.0},
    }
    _patch_config(monkeypatch, cfg)
    assert helper.source_weight("down") == 0.5
    assert helper.source_weight("unknown") == 1.0


def test_source_weight_defaults_to_one_when_config_missing(monkeypatch):
    _patch_config(monkeypatch, {"sources": {}, "defaults": {}})
    assert helper.source_weight("anything") == 1.0


def test_empty_url_list_returns_empty(monkeypatch):
    _patch_config(monkeypatch, {"sources": {}, "defaults": {}})
    assert helper.upgrade_photo_urls("x", []) == []
