"""PR-NL-6 — voice guide load, deterministic stories, LLM mock contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation.newsletter import commentary, llm_story
from automation.newsletter.types import Chip, IssuePick


# ── Voice guide loads from disk ──────────────────────────────────────

def test_voice_guide_file_exists_and_is_non_empty():
    """Operators expect to edit voice_guide.md directly. CI fails the
    moment that file is deleted or empty so we don't silently fall back
    to the hard-coded directive in production."""
    path = Path("automation/newsletter/voice_guide.md")
    assert path.exists(), "voice_guide.md is the editorial source of truth — restore it."
    text = path.read_text(encoding="utf-8")
    assert len(text) > 500, "voice_guide.md must contain meaningful rules, not a stub."
    # Spot-check a few load-bearing sections are present
    assert "Who Pulpo is" in text
    assert "Each pick paragraph MUST" in text
    assert "Tone targets per archetype" in text


def test_load_voice_guide_returns_real_file():
    """llm_story._load_voice_guide actually reads voice_guide.md, not
    the embedded fallback string."""
    loaded = llm_story._load_voice_guide()
    assert "knowing friend" in loaded.lower(), (
        "Voice guide didn't load the real file — got the fallback directive."
    )


# ── Deterministic story for every archetype ─────────────────────────

def _make_listing(**overrides) -> dict:
    """Minimal listing dict — overrides drive archetype selection."""
    base = {
        "source": "remax",
        "source_id": "0001",
        "title": "Test Listing",
        "property_type": "land",
        "price_usd": 100000,
        "department": "La Libertad",
        "municipality": "Tamanique",
        "area_m2": 1000,
        "days_listed": 30,
        "dist_beach_km": 8,
    }
    base.update(overrides)
    return base


def test_deterministic_story_coastal_walk_to_beach():
    listing = _make_listing(
        is_walk_to_beach=True,
        nearest_beach="El Tunco",
        price_vs_zone_pct=-60,
        readiness_score=2,
        has_power=True, has_water=True,
    )
    story = commentary.deterministic_story_for_pick(listing, locale="en")
    assert "walk to El Tunco" in story
    # Emotional center is wrapped in <em>
    assert "<em>" in story and "</em>" in story
    # Price gap surfaced honestly
    assert "well under" in story
    # Trade-off named
    assert "road" in story


def test_deterministic_story_mountain_archetype():
    listing = _make_listing(
        municipality="Comasagua",
        dist_beach_km=40,
        price_vs_zone_pct=-30,
        readiness_score=1,
        has_power=True,
    )
    story = commentary.deterministic_story_for_pick(listing, locale="en")
    assert "highlands" in story
    assert "<em>" in story


def test_deterministic_story_dropped_price():
    listing = _make_listing(
        is_repriced=True,
        previous_price=120000,
        price_usd=110000,
        readiness_score=3,
        has_power=True, has_water=True, has_paved_access=True,
    )
    story = commentary.deterministic_story_for_pick(listing, locale="en")
    # "$10,000" or "8%" — both are valid framings
    assert "$10,000" in story or "8%" in story
    assert "first move" in story
    assert "<em>" in story


def test_deterministic_story_stale_archetype():
    listing = _make_listing(
        days_listed=285,
        is_repriced=False,
        readiness_score=2,
        has_power=True, has_water=True,
    )
    story = commentary.deterministic_story_for_pick(listing, locale="en")
    assert "285 days" in story
    assert "<em>" in story
    # Voice guide rule: never fabricate urgency on stale
    assert "Don't miss" not in story
    assert "now or never" not in story


def test_deterministic_story_built_property():
    listing = _make_listing(
        property_type="house",
        bedrooms=4,
        bathrooms=3,
        built_area_m2=250,
    )
    story = commentary.deterministic_story_for_pick(listing, locale="en")
    assert "4 bedrooms" in story
    # Voice guide rule: room for a family, NOT investment opportunity
    assert "investment opportunity" not in story
    assert "<em>" in story


def test_deterministic_story_readiness_zero_names_the_gap():
    """Voice guide rule: 'Bring a build budget — never hide this'."""
    listing = _make_listing(readiness_score=0)
    story = commentary.deterministic_story_for_pick(listing, locale="en")
    assert "Bring a build budget" in story


def test_deterministic_story_spanish_locale():
    listing = _make_listing(
        is_walk_to_beach=True,
        nearest_beach="El Tunco",
        price_vs_zone_pct=-60,
    )
    story = commentary.deterministic_story_for_pick(listing, locale="es")
    # No English canary words from the EN templates leak in
    forbidden = ["A short walk", "well under", "bring a build budget"]
    for word in forbidden:
        assert word.lower() not in story.lower(), (
            f"English canary '{word}' leaked into ES story: {story}"
        )
    # ES anchor phrases present
    assert "playa" in story.lower() or "mar" in story.lower()


# ── LLM mock contract ─────────────────────────────────────────────────

class _StubChatChoice:
    """Mimic an OpenAI SDK choice object enough for llm_story to read."""
    def __init__(self, content: str, finish_reason: str = "stop"):
        self.message = type("M", (), {"content": content})()
        self.finish_reason = finish_reason


class _StubChatResponse:
    def __init__(self, content: str, finish_reason: str = "stop",
                 tokens_in: int = 150, tokens_out: int = 80):
        self.choices = [_StubChatChoice(content, finish_reason)]
        self.usage = type("U", (), {
            "prompt_tokens": tokens_in,
            "completion_tokens": tokens_out,
        })()


class _StubClient:
    """A drop-in replacement for the OpenAI client. Accepts ANY
    chat.completions.create kwargs and returns whatever the test
    constructed."""
    def __init__(self, response: _StubChatResponse):
        completions = type("C", (), {"create": lambda _s, **kw: response})()
        chat = type("Ch", (), {"completions": completions})()
        self.chat = chat


def test_llm_story_happy_path():
    response = _StubChatResponse(
        "A short walk to the beach. <em>Quiet mornings.</em> Power runs to the lot."
    )
    listing = _make_listing(is_walk_to_beach=True)
    result = llm_story.llm_story_for_pick(
        listing=listing, locale="en", client_override=_StubClient(response),
    )
    assert result.paragraph is not None
    assert "<em>" in result.paragraph
    assert result.error is None
    assert result.tokens_in == 150
    assert result.tokens_out == 80


def test_llm_story_strips_json_wrapper():
    """DeepSeek occasionally wraps the answer in JSON despite the
    instruction. _sanitize_paragraph unwraps it."""
    response = _StubChatResponse(
        '{"paragraph": "A short walk to the beach. <em>Quiet mornings.</em>"}'
    )
    result = llm_story.llm_story_for_pick(
        listing=_make_listing(), locale="en", client_override=_StubClient(response),
    )
    assert result.paragraph == "A short walk to the beach. <em>Quiet mornings.</em>"


def test_llm_story_empty_response_falls_through():
    response = _StubChatResponse("")
    result = llm_story.llm_story_for_pick(
        listing=_make_listing(), locale="en", client_override=_StubClient(response),
    )
    assert result.paragraph is None
    assert result.error == "empty_response"


def test_llm_story_finish_length_returns_error():
    """A length-truncated paragraph is unsafe to ship — better to fall
    back to deterministic than send a half-sentence."""
    response = _StubChatResponse(
        "A short walk to the beach. <em>Quiet morn",
        finish_reason="length",
    )
    result = llm_story.llm_story_for_pick(
        listing=_make_listing(), locale="en", client_override=_StubClient(response),
    )
    assert result.paragraph is None
    assert result.error == "finish_reason_length"


def test_llm_story_no_token_skipped_cleanly(monkeypatch):
    """Without DEEPSEEK_API_TOKEN, llm_story returns a clean skip — the
    caller in build_issue.py recognises this as a fall-through signal."""
    monkeypatch.delenv("DEEPSEEK_API_TOKEN", raising=False)
    result = llm_story.llm_story_for_pick(
        listing=_make_listing(), locale="en", client_override=None,
    )
    assert result.paragraph is None
    assert result.error == "no_token"
    assert result.finish_reason == "skipped"


def test_llm_story_exception_returns_error():
    """A network blow-up doesn't crash the issue render."""
    class _Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    raise ConnectionError("network down")
    result = llm_story.llm_story_for_pick(
        listing=_make_listing(), locale="en", client_override=_Boom(),
    )
    assert result.paragraph is None
    assert result.error == "ConnectionError"


# ── build_issue → story_html plumbing ────────────────────────────────

def test_build_issue_hero_picks_get_story_html(pro_with_prefs, ranked_pool, monkeypatch):
    """The top 3 picks (ISSUE_TOP_PICKS_RICH = 3) all carry a populated
    story_html + story_source. Short picks deliberately do not.

    Forces LLM off so the test exercises the deterministic path
    deterministically. Production default is LLM=ON (PR-NL-6 follow-
    up); the LLM-on path is covered by test_llm_story_* mocks above."""
    from datetime import datetime, timezone
    from automation.newsletter.build_issue import build_issue, reset_story_cache
    monkeypatch.setenv("PULPO_NEWSLETTER_USE_LLM", "0")
    reset_story_cache()
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=5,
        issue_date=datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
    )
    assert len(issue.picks_top) == 3
    for pick in issue.picks_top:
        assert pick.story_html, f"story_html empty on hero pick {pick.title}"
        assert pick.story_source == "deterministic"
        # <em> wraps the emotional center
        assert "<em>" in pick.story_html
    for pick in issue.picks_shortlist:
        # Short picks deliberately stay on legacy `blurb` for this PR
        assert pick.story_html == ""


def test_default_is_llm_on_when_env_unset(monkeypatch):
    """PR-NL-6 follow-up: when the env var is missing or empty, LLM is
    treated as ON. Operators opt OUT explicitly with =0."""
    from automation.newsletter.build_issue import _resolve_llm_toggle
    monkeypatch.delenv("PULPO_NEWSLETTER_USE_LLM", raising=False)
    assert _resolve_llm_toggle() is True
    monkeypatch.setenv("PULPO_NEWSLETTER_USE_LLM", "")
    assert _resolve_llm_toggle() is True


def test_explicit_zero_disables_llm(monkeypatch):
    """Operators can disable LLM with =0 / false / no / off."""
    from automation.newsletter.build_issue import _resolve_llm_toggle
    for disable_value in ("0", "false", "no", "off", "FALSE", "No"):
        monkeypatch.setenv("PULPO_NEWSLETTER_USE_LLM", disable_value)
        assert _resolve_llm_toggle() is False, f"{disable_value} should disable LLM"


def test_story_cache_dedupes_across_recipients(make_listing, monkeypatch):
    """The audience send loops `build_issue` per recipient; same listing
    × same locale should produce ONE LLM call regardless of how many
    recipients see it. The cache makes this true."""
    # `automation.newsletter.__init__` re-exports `build_issue` as a
    # function, so plain `import automation.newsletter.build_issue` would
    # resolve to that function. `importlib.import_module` reliably
    # returns the submodule object.
    import importlib
    bi_module = importlib.import_module("automation.newsletter.build_issue")
    bi_module.reset_story_cache()
    monkeypatch.setenv("PULPO_NEWSLETTER_USE_LLM", "0")  # keep test deterministic
    listing = make_listing(rank=1, source_id="CACHE_TEST")
    out_1 = bi_module._llm_or_deterministic_story(
        listing, locale="en", issue_id="2026-05-28",
    )
    out_2 = bi_module._llm_or_deterministic_story(
        listing, locale="en", issue_id="2026-05-28",
    )
    assert out_1 == out_2, "Same listing should produce the same story"
    # Cache should hold exactly one entry for this listing+locale
    assert ("remax:CACHE_TEST", "en") in bi_module._story_cache


def test_renderer_emits_em_styling():
    """The .body em / .body-2 em selectors must be in the rendered CSS
    so the emotional center renders italic + clay-deep."""
    from automation.newsletter.render_html import _CSS
    assert ".body em" in _CSS, "Story styling missing from CSS"
    assert "clay-deep" in _CSS
