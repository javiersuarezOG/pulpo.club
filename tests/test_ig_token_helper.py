"""Tests for automation/ig_token_helper.py.

Network calls are mocked at the urlopen boundary so no real Graph API
hits happen.  Coverage is intentionally tight — this helper runs
~ every 60 days; the priority is "no nasty surprises when Sebas rotates
the token", not exhaustive edge-case coverage.

Resilience note: every test that patches `_http_get` resolves the helper
module via a fixture that re-imports it.  tests/test_first_seen.py
nukes `sys.modules['automation.*']` to force fresh imports, which
leaves any module-top binding of automation.* stale.  The fixture below
re-imports inside the test scope so patches always target the LIVE
module, regardless of what ran before us in the suite.
"""
from __future__ import annotations
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Module-top import is only used by the pure-function tests below
# (pick_pulpo_page).  Anything that patches `_http_get` MUST use the
# `helper` fixture instead — see module docstring.
from automation.ig_token_helper import pick_pulpo_page   # noqa: E402


@pytest.fixture
def helper():
    """Always returns a freshly-reloaded `automation.ig_token_helper`.

    Other tests (notably tests/test_first_seen.py) nuke
    sys.modules['automation.*'] to force a re-import of automation/run
    with a fresh PULPO_OFFLINE env. That invalidates any module-top
    binding of our helper, so we re-import here to guarantee any
    `patch.object(helper, "_http_get", …)` targets the LIVE module."""
    import automation.ig_token_helper as mod
    return importlib.reload(mod)


# ── pick_pulpo_page (pure, no HTTP) ──────────────────────────────────

def test_pick_pulpo_page_single():
    pages = [{"id": "1", "name": "Pulpo Club"}]
    assert pick_pulpo_page(pages, hint=None)["id"] == "1"


def test_pick_pulpo_page_picks_by_hint():
    pages = [
        {"id": "1", "name": "My Coffee Shop"},
        {"id": "2", "name": "Pulpo Club"},
    ]
    assert pick_pulpo_page(pages, hint="pulpo")["id"] == "2"


def test_pick_pulpo_page_hint_case_insensitive():
    pages = [{"id": "1", "name": "My Page"}, {"id": "2", "name": "PULPO Club"}]
    assert pick_pulpo_page(pages, hint="pulpo")["id"] == "2"


def test_pick_pulpo_page_raises_on_empty():
    with pytest.raises(RuntimeError, match="no Facebook pages"):
        pick_pulpo_page([], hint=None)


def test_pick_pulpo_page_raises_when_ambiguous_without_hint():
    pages = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
    with pytest.raises(RuntimeError, match="pass --page-hint"):
        pick_pulpo_page(pages, hint=None)


def test_pick_pulpo_page_raises_when_hint_matches_multiple():
    pages = [
        {"id": "1", "name": "Pulpo Main"},
        {"id": "2", "name": "Pulpo Spanish"},
    ]
    with pytest.raises(RuntimeError, match="multiple pages match"):
        pick_pulpo_page(pages, hint="pulpo")


def test_pick_pulpo_page_raises_when_hint_matches_none():
    pages = [{"id": "1", "name": "Other"}]
    with pytest.raises(RuntimeError, match="no page name contains"):
        pick_pulpo_page(pages, hint="pulpo")


# ── ig_user_id_from_page ─────────────────────────────────────────────

def test_ig_user_id_from_page_inline(helper):
    """When /me/accounts already returned the IG account expansion."""
    page = {"id": "p1", "name": "Pulpo Club",
            "instagram_business_account": {"id": "ig_17841999"}}
    # No HTTP call needed.
    assert helper.ig_user_id_from_page(page, "tok") == "ig_17841999"


def test_ig_user_id_from_page_falls_back_to_per_page_fetch(helper):
    """If the inline field is missing (sometimes Graph elides it), fall
    back to a direct GET on the page."""
    page = {"id": "p1", "name": "Pulpo Club"}

    def fake_http_get(url):
        assert url.startswith(f"{helper.GRAPH_BASE}/p1?")
        return {"instagram_business_account": {"id": "ig_17841999"}}

    with patch.object(helper, "_http_get", fake_http_get):
        assert helper.ig_user_id_from_page(page, "tok") == "ig_17841999"


def test_ig_user_id_from_page_raises_when_not_linked(helper):
    page = {"id": "p1", "name": "No IG Page"}

    with patch.object(helper, "_http_get", lambda _: {}):
        with pytest.raises(RuntimeError, match="not linked to an Instagram"):
            helper.ig_user_id_from_page(page, "tok")


# ── exchange_for_long_lived_token + list_pages ───────────────────────

def test_exchange_for_long_lived_token_url_shape(helper):
    """Pin the URL params we send to Graph — IG silently 200s with
    weird responses if a param is misspelled, so verify the shape."""
    captured = {}

    def fake_http_get(url):
        captured["url"] = url
        return {"access_token": "long_lived_token", "expires_in": 5183944}

    with patch.object(helper, "_http_get", fake_http_get):
        out = helper.exchange_for_long_lived_token("short", "app_id", "secret")

    assert out["access_token"] == "long_lived_token"
    assert "grant_type=fb_exchange_token" in captured["url"]
    assert "client_id=app_id" in captured["url"]
    assert "client_secret=secret" in captured["url"]
    assert "fb_exchange_token=short" in captured["url"]


def test_list_pages_extracts_data(helper):
    def fake_http_get(url):
        return {"data": [{"id": "1", "name": "P"}, {"id": "2", "name": "Q"}]}

    with patch.object(helper, "_http_get", fake_http_get):
        pages = helper.list_pages("tok")

    assert len(pages) == 2
    assert pages[0]["id"] == "1"


def test_list_pages_returns_empty_for_missing_data(helper):
    with patch.object(helper, "_http_get", lambda _: {}):
        assert helper.list_pages("tok") == []


# ── mint end-to-end (all HTTP mocked) ─────────────────────────────────

def test_mint_end_to_end(helper):
    responses = {
        "oauth/access_token": {"access_token": "lt", "expires_in": 5183944},
        "/me/accounts":       {"data": [{
            "id":   "page_42",
            "name": "Pulpo Club",
            "instagram_business_account": {"id": "ig_17841"},
        }]},
    }

    def fake_http_get(url):
        for needle, resp in responses.items():
            if needle in url:
                return resp
        raise AssertionError(f"unexpected URL: {url}")

    with patch.object(helper, "_http_get", fake_http_get):
        result = helper.mint("short", "appid", "secret", page_hint="pulpo")

    assert result["IG_ACCESS_TOKEN"]   == "lt"
    assert result["IG_USER_ID"]        == "ig_17841"
    assert result["page_id"]           == "page_42"
    assert result["page_name"]         == "Pulpo Club"
    assert result["expires_in_s"]      == 5183944
    assert result["expires_in_days"]   == 60.0   # 5183944 / 86400 ≈ 60.0


def test_mint_raises_when_exchange_fails(helper):
    """An invalid short-lived token returns {"error": {...}} with no
    access_token field — surface as a clear RuntimeError."""
    def fake_http_get(url):
        if "oauth/access_token" in url:
            return {"error": {"message": "Invalid OAuth access token", "code": 190}}
        raise AssertionError(f"unexpected URL: {url}")

    with patch.object(helper, "_http_get", fake_http_get):
        with pytest.raises(RuntimeError, match="long-lived exchange failed"):
            helper.mint("bad_short", "appid", "secret")


# ── CLI ──────────────────────────────────────────────────────────────

def test_main_json_output(helper, capsys, monkeypatch):
    monkeypatch.setenv("META_APP_ID", "x")
    monkeypatch.setenv("META_APP_SECRET", "y")
    monkeypatch.setenv("IG_SHORT_TOKEN", "z")

    responses = {
        "oauth/access_token": {"access_token": "lt", "expires_in": 5183944},
        "/me/accounts":       {"data": [{
            "id": "p1", "name": "Pulpo Club",
            "instagram_business_account": {"id": "ig_999"},
        }]},
    }
    with patch.object(
        helper, "_http_get",
        lambda url: next(v for k, v in responses.items() if k in url),
    ):
        rc = helper.main(["--json"])

    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["IG_USER_ID"] == "ig_999"
    assert parsed["IG_ACCESS_TOKEN"] == "lt"


def test_main_missing_inputs_returns_2(helper, monkeypatch):
    monkeypatch.delenv("META_APP_ID", raising=False)
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    monkeypatch.delenv("IG_SHORT_TOKEN", raising=False)
    rc = helper.main([])
    assert rc == 2


def test_main_mint_failure_returns_1(helper, monkeypatch, capsys):
    monkeypatch.setenv("META_APP_ID", "x")
    monkeypatch.setenv("META_APP_SECRET", "y")
    monkeypatch.setenv("IG_SHORT_TOKEN", "z")
    with patch.object(
        helper, "_http_get",
        lambda url: {"error": {"message": "bad"}},
    ):
        rc = helper.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "mint failed" in err
