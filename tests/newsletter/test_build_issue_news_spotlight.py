"""build_issue's Weekly News Spotlight wiring.

The spotlight is READ from the committed artifact
(web/data/news_spotlight.json) via `news_store.load_spotlight` — no live
LLM call on the send path. These tests cover the build_issue wiring:

  • Artifact has the locale  → Issue.news_spotlight populated + telemetry (source=artifact)
  • Artifact missing/empty    → None + telemetry (source=missing)
  • Per-process cache shares the read across recipients in the same (issue_id, locale)
  • A broken artifact (load raises) is swallowed — the issue still builds

The store IO itself is exercised in test_news_store.py; the nightly
refresh + carry-forward in test_refresh_news_spotlight.py.

NOTE: the newsletter conftest's autouse `_news_spotlight_artifact` fixture
points PULPO_NEWS_SPOTLIGHT_PATH at a populated temp file by default. Tests
here that need a different artifact override that env / write that file.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest

from automation.newsletter.build_issue import build_issue
from automation.newsletter.types import Preference, Recipient

_BUILD_ISSUE_MODULE = sys.modules["automation.newsletter.build_issue"]

ISSUE_DATE = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)


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


def _point_at_empty_artifact(monkeypatch, tmp_path):
    """Override the conftest's populated artifact with a path that has no
    spotlight for any locale (cold start)."""
    empty = tmp_path / "empty_spotlight.json"
    empty.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("PULPO_NEWS_SPOTLIGHT_PATH", str(empty))
    _BUILD_ISSUE_MODULE._NEWS_SPOTLIGHT_CACHE.clear()


def test_news_spotlight_populated_from_artifact(captured_events, ranked_pool):
    """Default (conftest) artifact has the EN locale → Issue carries it +
    telemetry records source=artifact with the outlet + article URL."""
    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=99,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.news_spotlight is not None
    assert issue.news_spotlight.source_name == "La Prensa Gráfica"
    assert issue.news_spotlight.source_url.startswith("https://")

    spot_props = next(p for name, p in captured_events if name == "newsletter.news_spotlight_built")
    assert spot_props["source"] == "artifact"
    assert spot_props["outlet"] == "La Prensa Gráfica"
    assert spot_props["article_url"].startswith("https://")
    assert spot_props["locale"] == "en"
    assert spot_props["issue_number"] == 99


def test_news_spotlight_none_when_artifact_empty(captured_events, ranked_pool, monkeypatch, tmp_path):
    """Cold start (artifact has no entry for the locale) → None +
    telemetry source=missing. The renderer omits the section."""
    _point_at_empty_artifact(monkeypatch, tmp_path)
    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.news_spotlight is None

    spot_props = next(p for name, p in captured_events if name == "newsletter.news_spotlight_built")
    assert spot_props["source"] == "missing"
    assert spot_props["outlet"] is None
    assert spot_props["article_url"] is None


def test_news_spotlight_locale_specific(captured_events, ranked_pool):
    """ES recipient reads the ES entry from the artifact, not EN."""
    issue = build_issue(
        recipient=_make_recipient(locale="es"),
        ranked_listings=ranked_pool,
        issue_number=7,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.news_spotlight is not None
    assert issue.news_spotlight.title.startswith("Nueva carretera")


def test_news_spotlight_cache_shares_read_across_recipients(captured_events, ranked_pool, monkeypatch):
    """A cron with N recipients in the same locale reads the artifact
    exactly once via the (issue_id, locale) cache."""
    import automation.newsletter.news_store as news_store_mod

    call_count = {"n": 0}
    real_load = news_store_mod.load_spotlight

    def _counting_load(locale, **kw):
        call_count["n"] += 1
        return real_load(locale, **kw)

    monkeypatch.setattr(news_store_mod, "load_spotlight", _counting_load)
    _BUILD_ISSUE_MODULE._NEWS_SPOTLIGHT_CACHE.clear()

    for hash_ in ("a", "b", "c"):
        build_issue(
            recipient=_make_recipient(email_hash=hash_),
            ranked_listings=ranked_pool,
            issue_number=42,
            issue_date=ISSUE_DATE,
            history_rows=[],
        )

    assert call_count["n"] == 1


def test_news_spotlight_swallows_load_exception(captured_events, ranked_pool, monkeypatch):
    """If the store read raises, build_issue must NOT propagate — the
    issue still builds and the renderer omits the section."""
    import automation.newsletter.news_store as news_store_mod

    def _boom(locale, **kw):
        raise RuntimeError("corrupt artifact")

    monkeypatch.setattr(news_store_mod, "load_spotlight", _boom)
    _BUILD_ISSUE_MODULE._NEWS_SPOTLIGHT_CACHE.clear()

    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.news_spotlight is None
