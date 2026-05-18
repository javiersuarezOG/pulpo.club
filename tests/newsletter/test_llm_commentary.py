"""LLM commentary path — tested with a stub client.

The real DeepSeek call is gated behind PULPO_NEWSLETTER_USE_LLM env and
DEEPSEEK_API_TOKEN, and CI doesn't have the token. These tests inject a
stub client through the `client_override` seam so we exercise every code
path (success, length-truncation, bad-json, schema-miss, exception)
without making an HTTP call.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from automation.newsletter import llm_commentary as llm
from automation.newsletter.types import Preference


# ── Stub OpenAI client ────────────────────────────────────────────────────
class _Msg:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, content: str, finish_reason: str = "stop"):
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _Usage:
    def __init__(self, tin: int, tout: int):
        self.prompt_tokens = tin
        self.completion_tokens = tout


class _Resp:
    def __init__(self, content: str, finish_reason: str = "stop",
                 tin: int = 1500, tout: int = 800):
        self.choices = [_Choice(content, finish_reason)]
        self.usage = _Usage(tin, tout)


class _Completions:
    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._behaviour(kwargs)


class _Chat:
    def __init__(self, completions: _Completions):
        self.completions = completions


class StubClient:
    """A minimal OpenAI-shaped stub.

    Construct with a callable taking the call kwargs and returning either
    a `_Resp` or raising. The `.calls` list captures every request shape
    so tests can assert on the prompt structure if needed.
    """

    def __init__(self, behaviour):
        self.chat = _Chat(_Completions(behaviour))

    @property
    def calls(self):
        return self.chat.completions.calls


GOOD_PAYLOAD = {
    "eyebrow_hero": "For Javier",
    "headline_hero": "Ten this fortnight.",
    "lede_hero": "We scanned 910 listings; ten cleared the bar.",
    "filter_chips": ["La Libertad", "Land OK", "Under $500k"],
    "glance_subhead": "Nine to read. One to skip.",
    "skip_headline": "Stale listing on the cliff",
    "skip_blurb": "117 days on market with no movement — pass.",
    "market_context": [
        "Rains started 12 May, earlier than last year.",
        "Sunset Park opened on the La Libertad malecón.",
    ],
    "one_number_title": "$45 per vara² — the new floor.",
    "one_number_body": "Two corridor lots priced exactly there.",
}


@pytest.fixture
def kept_picks():
    return [{
        "rank": 1,
        "title": "Coffee farm",
        "title_canonical": {"en": "Coffee farm", "es": "Finca de café"},
        "zone": "el-zonte",
        "municipality": "Chiltiupán",
        "department": "La Libertad",
        "property_type": "land",
        "price_usd": 185_000,
        "price_per_m2": 30,
        "price_vs_zone_pct": -50,
        "area_m2": 6000,
        "days_listed": 3,
        "is_repriced": False,
        "is_beachfront": False,
        "is_walk_to_beach": False,
        "dist_beach_km": 25,
        "_is_new_window": True,
    }]


@pytest.fixture
def pref():
    return Preference(departments=["La Libertad"], property_types=["land"], max_price_usd=500_000)


def test_success_path_returns_commentary(kept_picks, pref):
    stub = StubClient(lambda _kw: _Resp(json.dumps(GOOD_PAYLOAD)))
    out = llm.llm_commentary(
        cohort="pro_prefs",
        locale="en",
        pref=pref,
        display_name="Javier",
        n_scanned=910,
        picks=kept_picks,
        skip_pick=None,
        client_override=stub,
    )
    assert out.error is None
    assert out.commentary is not None
    assert out.commentary.headline_hero == "Ten this fortnight."
    assert out.commentary.filter_chips == ["La Libertad", "Land OK", "Under $500k"]
    assert out.tokens_in == 1500 and out.tokens_out == 800
    assert out.cost_usd > 0
    assert len(stub.calls) == 1
    # System prompt must remain byte-stable for prefix-cache hits
    assert stub.calls[0]["messages"][0]["role"] == "system"
    assert stub.calls[0]["messages"][0]["content"].startswith("You are the editorial voice")


def test_no_token_returns_skip(kept_picks, pref, monkeypatch):
    """No client + no env → 'no_token' error, no commentary."""
    monkeypatch.delenv("DEEPSEEK_API_TOKEN", raising=False)
    out = llm.llm_commentary(
        cohort="pro_prefs",
        locale="en",
        pref=pref,
        display_name="Javier",
        n_scanned=910,
        picks=kept_picks,
        skip_pick=None,
    )
    assert out.error == "no_token"
    assert out.commentary is None


def test_finish_reason_length_treated_as_error(kept_picks, pref):
    stub = StubClient(lambda _kw: _Resp(json.dumps(GOOD_PAYLOAD), finish_reason="length"))
    out = llm.llm_commentary(
        cohort="pro_prefs", locale="en", pref=pref, display_name=None,
        n_scanned=10, picks=kept_picks, skip_pick=None,
        client_override=stub,
    )
    assert out.error == "finish_reason_length"
    assert out.commentary is None


def test_bad_json_returns_error(kept_picks, pref):
    stub = StubClient(lambda _kw: _Resp("not-json {{{"))
    out = llm.llm_commentary(
        cohort="pro_prefs", locale="en", pref=pref, display_name=None,
        n_scanned=10, picks=kept_picks, skip_pick=None,
        client_override=stub,
    )
    assert out.error == "bad_json"
    assert out.commentary is None


def test_schema_miss_returns_error(kept_picks, pref):
    # Missing required field `lede_hero`
    payload = {**GOOD_PAYLOAD}
    del payload["lede_hero"]
    stub = StubClient(lambda _kw: _Resp(json.dumps(payload)))
    out = llm.llm_commentary(
        cohort="pro_prefs", locale="en", pref=pref, display_name=None,
        n_scanned=10, picks=kept_picks, skip_pick=None,
        client_override=stub,
    )
    assert out.error == "schema_miss"
    assert out.commentary is None


def test_exception_returns_error(kept_picks, pref):
    def _boom(_kw):
        raise TimeoutError("upstream slow")
    stub = StubClient(_boom)
    out = llm.llm_commentary(
        cohort="pro_prefs", locale="en", pref=pref, display_name=None,
        n_scanned=10, picks=kept_picks, skip_pick=None,
        client_override=stub,
    )
    assert out.error == "TimeoutError"
    assert out.commentary is None
    assert out.tokens_in == 0 and out.tokens_out == 0


def test_cost_math():
    # 2_000_000 tokens in = $0.54; 1_000_000 out = $1.10 → $1.64 total
    assert llm.cost_usd(2_000_000, 1_000_000) == pytest.approx(1.64, abs=0.001)
    assert llm.cost_usd(0, 0) == 0.0
