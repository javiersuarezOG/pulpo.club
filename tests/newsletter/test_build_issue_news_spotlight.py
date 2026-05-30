"""build_issue's Weekly News Spotlight wiring.

Covers the build_issue path that decides whether to populate
`Issue.news_spotlight`:

  • LLM toggle off            → None (no fetch, no LLM call, no telemetry-noisy event)
  • LLM toggle on + no token  → None (skip RSS fetch entirely — avoids burning network timeouts when DEEPSEEK_API_TOKEN isn't wired)
  • LLM toggle on + token + mocked fetch_pick_and_summarize → NewsSpotlight populated, telemetry event fired with outlet + article URL
  • Per-process cache shares the spotlight across recipients in the same (issue_id, locale)

The LLM + RSS modules themselves are exercised in test_llm_news.py and
test_news_search.py — here we only verify the build_issue wiring.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import pytest

from automation.newsletter.build_issue import build_issue
from automation.newsletter.types import NewsSpotlight, Preference, Recipient

_BUILD_ISSUE_MODULE = sys.modules["automation.newsletter.build_issue"]

ISSUE_DATE = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clear_news_spotlight_cache():
    """The per-process cache survives between tests by default — clear it
    so each test sees a fresh (no cache hit) build."""
    _BUILD_ISSUE_MODULE._NEWS_SPOTLIGHT_CACHE.clear()
    yield
    _BUILD_ISSUE_MODULE._NEWS_SPOTLIGHT_CACHE.clear()


@pytest.fixture
def captured_events(monkeypatch):
    events: list[tuple[str, dict]] = []
    def _capture(event, props):
        events.append((event, dict(props)))
    monkeypatch.setattr(_BUILD_ISSUE_MODULE, "_telemetry_capture", _capture)
    return events


def _make_recipient(**overrides) -> Recipient:
    base = dict(
        email_hash="abc123",
        display_name="Javier",
        locale="en",
        tier="pro",
        has_account=True,
        preference=Preference(
            departments=["La Libertad"],
            property_types=["land"],
            max_price_usd=500_000,
        ),
    )
    base.update(overrides)
    return Recipient(**base)


def test_news_spotlight_none_when_llm_toggle_off(captured_events, ranked_pool, monkeypatch):
    """USE_LLM unset → no spotlight, no telemetry event fired."""
    monkeypatch.delenv("PULPO_NEWSLETTER_USE_LLM", raising=False)
    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.news_spotlight is None
    # The spotlight event should NOT fire when the LLM toggle is off —
    # the build short-circuits before any fetch / LLM call.
    spot_events = [name for name, _ in captured_events if name == "newsletter.news_spotlight_built"]
    assert spot_events == []


def test_news_spotlight_none_when_no_deepseek_token(captured_events, ranked_pool, monkeypatch):
    """USE_LLM=1 but no DEEPSEEK_API_TOKEN → skip everything (no RSS, no LLM).

    Defends against burning 5×10s of network timeouts in dev/CI when
    the toggle is flipped on without a real key wired.
    """
    monkeypatch.setenv("PULPO_NEWSLETTER_USE_LLM", "1")
    monkeypatch.delenv("DEEPSEEK_API_TOKEN", raising=False)
    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.news_spotlight is None


def test_news_spotlight_populated_when_llm_returns_pick(captured_events, ranked_pool, monkeypatch):
    """Happy path: USE_LLM=1 + token + LLM picks → NewsSpotlight + telemetry."""
    monkeypatch.setenv("PULPO_NEWSLETTER_USE_LLM", "1")
    monkeypatch.setenv("DEEPSEEK_API_TOKEN", "sk-fake-test-key")

    fake_spotlight = NewsSpotlight(
        title="Why the eastern coast just changed",
        paragraph="The Lempa bridge cuts your drive by 45 minutes.",
        source_name="El Diario de Hoy",
        source_url="https://www.elsalvador.com/article/lempa-bridge/",
        source_date="28 May 2026",
        candidates_seen=12,
        llm_cost_usd=0.0042,
    )

    # Monkeypatch the llm_news.fetch_pick_and_summarize that build_issue
    # imports lazily. Patch the module dict directly since build_issue
    # does `from . import llm_news as llm_news_mod` inside the helper.
    import automation.newsletter.llm_news as llm_news_mod
    monkeypatch.setattr(llm_news_mod, "fetch_pick_and_summarize", lambda **kw: fake_spotlight)

    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=99,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.news_spotlight is fake_spotlight

    spot_props = next(p for name, p in captured_events if name == "newsletter.news_spotlight_built")
    assert spot_props["source"] == "llm"
    assert spot_props["outlet"] == "El Diario de Hoy"
    assert spot_props["article_url"] == "https://www.elsalvador.com/article/lempa-bridge/"
    assert spot_props["candidates_seen"] == 12
    assert spot_props["llm_cost_usd"] == 0.0042
    assert spot_props["locale"] == "en"
    assert spot_props["issue_number"] == 99


def test_news_spotlight_fallback_telemetry_when_llm_returns_none(captured_events, ranked_pool, monkeypatch):
    """LLM available but returned None (slow week / parse error) → telemetry
    records the fallback so we can monitor LLM hit rate over time."""
    monkeypatch.setenv("PULPO_NEWSLETTER_USE_LLM", "1")
    monkeypatch.setenv("DEEPSEEK_API_TOKEN", "sk-fake-test-key")

    import automation.newsletter.llm_news as llm_news_mod
    monkeypatch.setattr(llm_news_mod, "fetch_pick_and_summarize", lambda **kw: None)

    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.news_spotlight is None

    spot_props = next(p for name, p in captured_events if name == "newsletter.news_spotlight_built")
    assert spot_props["source"] == "fallback"
    assert spot_props["outlet"] is None
    assert spot_props["article_url"] is None


def test_news_spotlight_cache_shares_call_across_recipients(captured_events, ranked_pool, monkeypatch):
    """A cron with N recipients in the same locale fires the LLM exactly
    once via the (issue_id, locale) cache."""
    monkeypatch.setenv("PULPO_NEWSLETTER_USE_LLM", "1")
    monkeypatch.setenv("DEEPSEEK_API_TOKEN", "sk-fake-test-key")

    call_count = {"n": 0}
    fake_spotlight = NewsSpotlight(
        title="Cached pick",
        paragraph="Body.",
        source_name="El Mundo",
        source_url="https://elmundo.sv/cached/",
        source_date="28 May 2026",
        candidates_seen=5,
    )

    def _fake_fetch(**kw):
        call_count["n"] += 1
        return fake_spotlight

    import automation.newsletter.llm_news as llm_news_mod
    monkeypatch.setattr(llm_news_mod, "fetch_pick_and_summarize", _fake_fetch)

    # Build the same issue (same issue_id derived from issue_date) for 3
    # different recipients. The cache should kick in after the first call.
    for hash_ in ("a", "b", "c"):
        build_issue(
            recipient=_make_recipient(email_hash=hash_),
            ranked_listings=ranked_pool,
            issue_number=42,
            issue_date=ISSUE_DATE,
            history_rows=[],
        )

    # LLM-pipeline was called ONCE, not three times.
    assert call_count["n"] == 1


def test_news_spotlight_swallows_llm_exception(captured_events, ranked_pool, monkeypatch):
    """If the LLM module raises, build_issue must NOT propagate — the
    newsletter ships either way via the deterministic renderer fallback."""
    monkeypatch.setenv("PULPO_NEWSLETTER_USE_LLM", "1")
    monkeypatch.setenv("DEEPSEEK_API_TOKEN", "sk-fake-test-key")

    def _boom(**kw):
        raise RuntimeError("upstream down")

    import automation.newsletter.llm_news as llm_news_mod
    monkeypatch.setattr(llm_news_mod, "fetch_pick_and_summarize", _boom)

    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.news_spotlight is None
