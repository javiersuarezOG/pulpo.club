"""History store: hash + append/load roundtrip + exclusion window."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from automation.newsletter.store import (
    HistoryRow,
    append_history,
    email_hash,
    excluded_source_ids_for,
    last_send_at_for,
    load_history,
)


def test_email_hash_deterministic_per_salt():
    h1 = email_hash("a@b.com", salt="s1")
    h2 = email_hash("a@b.com", salt="s1")
    h3 = email_hash("a@b.com", salt="s2")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 24


def test_email_hash_case_and_whitespace_normalised():
    assert email_hash("  Foo@bar.com  ", salt="s") == email_hash("foo@bar.com", salt="s")


def test_history_roundtrip(tmp_path: Path):
    log = tmp_path / "h.jsonl"
    row = HistoryRow(
        recipient_hash="abc123",
        issue_id="2026-05-04",
        sent_at="2026-05-04T14:00:00+00:00",
        cohort="pro_prefs",
        source_ids=["remax:1", "remax:2"],
    )
    append_history(row, path=log)
    loaded = load_history(log)
    assert len(loaded) == 1
    assert loaded[0].source_ids == ["remax:1", "remax:2"]


def test_excluded_source_ids_window(tmp_path: Path):
    log = tmp_path / "h.jsonl"
    # Old send — outside the 90d window
    append_history(HistoryRow(
        recipient_hash="abc123",
        issue_id="2025-01-01",
        sent_at="2025-01-01T14:00:00+00:00",
        cohort="pro_prefs",
        source_ids=["remax:OLD"],
    ), path=log)
    # Recent send — inside the window
    append_history(HistoryRow(
        recipient_hash="abc123",
        issue_id="2026-05-04",
        sent_at="2026-05-04T14:00:00+00:00",
        cohort="pro_prefs",
        source_ids=["remax:NEW"],
    ), path=log)
    rows = load_history(log)
    out = excluded_source_ids_for(
        "abc123",
        now=datetime(2026, 5, 18, tzinfo=timezone.utc),
        history=rows,
    )
    assert "remax:NEW" in out
    assert "remax:OLD" not in out


def test_last_send_at(tmp_path: Path):
    log = tmp_path / "h.jsonl"
    append_history(HistoryRow(
        recipient_hash="abc",
        issue_id="2026-05-04",
        sent_at="2026-05-04T14:00:00+00:00",
        cohort="pro_prefs",
        source_ids=[],
    ), path=log)
    append_history(HistoryRow(
        recipient_hash="abc",
        issue_id="2026-05-18",
        sent_at="2026-05-18T14:00:00+00:00",
        cohort="pro_prefs",
        source_ids=[],
    ), path=log)
    rows = load_history(log)
    out = last_send_at_for("abc", history=rows)
    assert out is not None
    assert out.isoformat().startswith("2026-05-18")
