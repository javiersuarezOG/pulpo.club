"""build_issue's LLM toggle + PostHog telemetry wiring.

Covers the build_issue path that picks LLM vs deterministic and fires
the two newsletter PostHog events. The LLM module itself is exercised
in test_llm_commentary.py — here we only verify the wiring.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest

from automation.newsletter.build_issue import build_issue
from automation.newsletter.types import Preference, Recipient

# The package's __init__.py re-exports the `build_issue` function, which
# shadows the submodule on `automation.newsletter.build_issue` attribute
# access. Grab the actual module via sys.modules so monkeypatch.setattr
# targets the right object.
_BUILD_ISSUE_MODULE = sys.modules["automation.newsletter.build_issue"]


ISSUE_DATE = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def captured_events(monkeypatch):
    """Capture every PostHog event the build path fires.

    `_telemetry_capture` is a thin wrapper around posthog_client.capture
    that swallows ImportError/Exception. We patch it via the sys.modules
    path so the resolution matches the runtime call site exactly.
    """
    events: list[tuple[str, dict]] = []

    def _capture(event, props):
        events.append((event, dict(props)))

    monkeypatch.setattr(_BUILD_ISSUE_MODULE, "_telemetry_capture", _capture)
    yield events


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


def test_deterministic_path_fires_both_events(captured_events, ranked_pool, monkeypatch):
    monkeypatch.delenv("PULPO_NEWSLETTER_USE_LLM", raising=False)
    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=3,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.commentary.eyebrow_hero  # rendered something
    event_names = [e[0] for e in captured_events]
    assert "newsletter.commentary_generated" in event_names
    assert "newsletter.issue_built" in event_names

    commentary_props = next(p for name, p in captured_events if name == "newsletter.commentary_generated")
    assert commentary_props["source"] == "deterministic"
    assert commentary_props["recipient_hash"] == "abc123"
    assert commentary_props["cohort"] == "pro_prefs"

    issue_props = next(p for name, p in captured_events if name == "newsletter.issue_built")
    assert issue_props["picks_total"] >= 1
    assert issue_props["issue_number"] == 3
    assert issue_props["tier"] == "pro"
    assert issue_props["paywall_banner"] is False


def test_llm_success_path_uses_llm_commentary(captured_events, ranked_pool):
    """When a stub client is injected, the LLM path runs even without env."""
    from tests.newsletter.test_llm_commentary import GOOD_PAYLOAD, StubClient
    stub = StubClient(lambda _kw: _ResponseShim(GOOD_PAYLOAD))
    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
        llm_client_override=stub,
    )
    assert issue.commentary.headline_hero == "Ten this fortnight."  # from stub payload
    commentary_props = next(p for name, p in captured_events if name == "newsletter.commentary_generated")
    assert commentary_props["source"] == "llm"
    assert commentary_props["llm_error"] is None
    assert commentary_props["tokens_in"] > 0
    assert commentary_props["cost_usd"] > 0


def test_llm_error_falls_back_to_deterministic(captured_events, ranked_pool):
    """LLM failure must never break a render — fall back silently."""
    from tests.newsletter.test_llm_commentary import StubClient

    def _boom(_kw):
        raise RuntimeError("upstream down")

    stub = StubClient(_boom)
    issue = build_issue(
        recipient=_make_recipient(),
        ranked_listings=ranked_pool,
        issue_number=1,
        issue_date=ISSUE_DATE,
        history_rows=[],
        llm_client_override=stub,
    )
    # Deterministic copy contains the named greeting; LLM stub would have
    # said "For Javier" but the error path falls back, which uses
    # i18n.t("hero.eyebrow.named", "en", name="Javier") = "Hand-picked for Javier".
    assert "Javier" in issue.commentary.eyebrow_hero
    commentary_props = next(p for name, p in captured_events if name == "newsletter.commentary_generated")
    assert commentary_props["source"] == "deterministic_fallback"
    assert commentary_props["llm_error"] == "RuntimeError"


def test_anonymous_cohort_telemetry(captured_events, ranked_pool):
    rec = _make_recipient(
        email_hash="anon-h",
        display_name=None,
        has_account=False,
        tier="free",
        preference=Preference(),
    )
    build_issue(
        recipient=rec,
        ranked_listings=ranked_pool,
        issue_number=4,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    issue_props = next(p for name, p in captured_events if name == "newsletter.issue_built")
    assert issue_props["cohort"] == "anonymous"
    assert issue_props["has_account"] is False
    assert issue_props["tier"] == "free"


# ── Minimal response shim that satisfies llm_commentary._parse_response ──
class _ResponseShim:
    """Mimics the OpenAI SDK chat-completion response just enough to run."""
    class _Choice:
        def __init__(self, content):
            class _Msg:
                pass
            self.message = _Msg()
            self.message.content = json.dumps(content)
            self.finish_reason = "stop"

    class _Usage:
        prompt_tokens = 1500
        completion_tokens = 800

    def __init__(self, payload):
        self.choices = [self._Choice(payload)]
        self.usage = self._Usage()
