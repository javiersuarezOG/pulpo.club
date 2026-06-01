"""Tests for scripts/notify_unsubscribes.py — the per-event
Slack-ping cron that surfaces newsletter unsubscribes in real time.

Covers the pure surface:
  • `query_unsubscribes` — PostHog HogQL query + response parsing.
    Verified that malformed responses + transport errors degrade
    to [] rather than crashing the cron.
  • `format_slack_blocks` — payload shape including hash truncation
    (privacy-safe — no full hashes in Slack), batch header, and
    event-ID tail for the at-most-twice duplicate signal.
  • `post_slack` — happy path + transport error.

We don't unit-test main() — the entry-point wiring (env check,
exit codes, stdout logging) is operationally simple and an
integration test on the GH Actions cron itself is the right
verification surface.
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import notify_unsubscribes as notify  # noqa: E402


# ── query_unsubscribes ────────────────────────────────────────────────


def _posthog_response(rows: list[list]) -> bytes:
    """Serialize a PostHog HogQL response shape. rows is a list of
    [event_id, ts, recipient_hash, issue_number, source] tuples."""
    return json.dumps({"results": rows}).encode("utf-8")


def _mock_urlopen(body: bytes):
    """Return a context manager that mimics urllib.request.urlopen."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(read=lambda: body))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_query_unsubscribes_parses_rows():
    rows = [
        ["evt_abc", "2026-06-01T15:00:00Z", "hash_001", "24", "one_click"],
        ["evt_def", "2026-06-01T15:05:00Z", "hash_002", "24", "manual"],
    ]
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_posthog_response(rows))):
        result = notify.query_unsubscribes(
            host="https://eu.posthog.com", project="proj", key="key", window_min=35,
        )
    assert len(result) == 2
    assert result[0]["event_id"] == "evt_abc"
    assert result[0]["recipient_hash"] == "hash_001"
    assert result[0]["issue_number"] == "24"
    assert result[0]["source"] == "one_click"


def test_query_unsubscribes_returns_empty_list_on_url_error():
    """Network failures must degrade to [] — better silent than a
    misleading Slack ping built from partial data."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("network down")):
        result = notify.query_unsubscribes(
            host="https://eu.posthog.com", project="proj", key="key", window_min=35,
        )
    assert result == []


def test_query_unsubscribes_returns_empty_on_malformed_json():
    """If PostHog returns garbage (rare but possible during outage),
    we should not crash."""
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(b"not-json")):
        result = notify.query_unsubscribes(
            host="https://eu.posthog.com", project="proj", key="key", window_min=35,
        )
    assert result == []


def test_query_unsubscribes_skips_short_rows():
    """Schema-drift safety: a PostHog query returning fewer columns
    than expected should drop those rows, not crash with IndexError."""
    rows = [
        ["evt_abc"],                                          # too short
        ["evt_def", "ts", "hash", "issue", "source"],         # valid
    ]
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_posthog_response(rows))):
        result = notify.query_unsubscribes(
            host="https://eu.posthog.com", project="proj", key="key", window_min=35,
        )
    assert len(result) == 1
    assert result[0]["event_id"] == "evt_def"


def test_query_unsubscribes_window_min_threads_through():
    """The window_min argument must end up in the HogQL query — without
    it the cron's 30-min cadence becomes a meaningless 'all time' query."""
    captured = {}

    def _capture_request(req, timeout=None):
        # Grab the body before urlopen tries to fire.
        captured["body"] = req.data.decode("utf-8")
        return _mock_urlopen(_posthog_response([]))

    with patch("urllib.request.urlopen", side_effect=_capture_request):
        notify.query_unsubscribes(
            host="https://eu.posthog.com", project="proj", key="key", window_min=42,
        )
    assert "toIntervalMinute(42)" in captured["body"]


# ── format_slack_blocks ───────────────────────────────────────────────


def test_format_slack_blocks_returns_none_for_empty_rows():
    """Empty input → None → caller skips the Slack POST entirely.
    Critical: a Slack ping with '0 unsubscribes' is noise."""
    assert notify.format_slack_blocks([]) is None


def test_format_slack_blocks_uses_singular_grammar_for_one_unsub():
    rows = [{
        "event_id": "evt_xyz123", "ts": "2026-06-01T15:00:00Z",
        "recipient_hash": "abc12345def", "issue_number": "24",
        "source": "one_click",
    }]
    payload = notify.format_slack_blocks(rows)
    assert "1 newsletter unsubscribe in the last 30 min" in payload["text"]
    # Critical: no extra "s" on a single unsub. Cosmetic but lossy if
    # the operator scans by reading "5 unsubscribes" vs "1 unsubscribe".
    assert "1 newsletter unsubscribes" not in payload["text"]


def test_format_slack_blocks_plural_for_multiple():
    rows = [{
        "event_id": f"evt_{i}", "ts": "2026-06-01T15:00:00Z",
        "recipient_hash": f"hash_{i:03d}", "issue_number": "24",
        "source": "one_click",
    } for i in range(3)]
    payload = notify.format_slack_blocks(rows)
    assert "3 newsletter unsubscribes in the last 30 min" in payload["text"]


def test_format_slack_blocks_truncates_recipient_hash_for_privacy():
    """The full sha256-truncated hash is 16 chars; the Slack message
    surfaces only the first 8 to avoid putting full hashes in chat
    history. Operator can resolve a hash → user via Clerk dashboard
    server-side if they need to."""
    rows = [{
        "event_id": "evt_xyz", "ts": "2026-06-01T15:00:00Z",
        "recipient_hash": "abcdef1234567890",
        "issue_number": "24", "source": "one_click",
    }]
    payload = notify.format_slack_blocks(rows)
    assert "hash=abcdef12" in payload["text"]
    # The fuller hash must NOT appear (privacy regression guard).
    assert "abcdef1234567890" not in payload["text"]


def test_format_slack_blocks_includes_event_id_tail_for_dup_detection():
    """The 30-min cron + 35-min query window allows the same unsub to
    appear in TWO consecutive Slack pings. Including the event ID tail
    in the message lets the operator spot the duplicate visually."""
    rows = [{
        "event_id": "evt_0987654321abcdef",
        "ts": "2026-06-01T15:00:00Z",
        "recipient_hash": "hash_001",
        "issue_number": "24", "source": "one_click",
    }]
    payload = notify.format_slack_blocks(rows)
    # Last 8 chars of event_id should be in the message.
    assert "evt=21abcdef" in payload["text"]


def test_format_slack_blocks_handles_missing_fields_gracefully():
    """A malformed PostHog event (missing recipient_hash, issue_number,
    or source) should still render — degrade to '?' for the missing
    field. We don't want to silently drop unsubs because of one bad
    property."""
    rows = [{
        "event_id": "evt_abc", "ts": "2026-06-01T15:00:00Z",
        "recipient_hash": "",
        "issue_number": "",
        "source": "",
    }]
    payload = notify.format_slack_blocks(rows)
    assert "hash=?" in payload["text"]
    assert "issue ?" in payload["text"]
    assert "source=?" in payload["text"]


# ── post_slack ────────────────────────────────────────────────────────


def test_post_slack_returns_true_on_2xx():
    response = MagicMock(status=200)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=response)
    cm.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=cm):
        assert notify.post_slack("https://hooks.slack.com/services/X", {"text": "hi"}) is True


def test_post_slack_returns_false_on_url_error():
    """Slack outage during a Pulpo unsub batch must NOT page the cron
    or crash the script. Return False so the caller logs + continues."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("slack down")):
        assert notify.post_slack("https://hooks.slack.com/services/X", {"text": "hi"}) is False


def test_post_slack_returns_false_on_non_2xx():
    response = MagicMock(status=503)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=response)
    cm.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=cm):
        assert notify.post_slack("https://hooks.slack.com/services/X", {"text": "hi"}) is False
