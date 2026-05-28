"""Tests for automation/ig_queue_apply.py.

Covers the three things that can silently corrupt the queue:
  1. Bad decision payloads (the dispatch endpoint already validates,
     but this is the last line of defence inside the workflow).
  2. Mutating a posted item (must NEVER reverse a published post).
  3. Batch-mismatch (operator submitting against a stale drop).

Plus the happy paths: approve flips `approved: true`, skip flips
`approved: false` + sets `skipped`, idempotent re-run is a no-op.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_queue_apply import (  # noqa: E402
    apply_decisions,
    main,
    parse_decisions,
)


# ── helpers ──────────────────────────────────────────────────────────


def _queue(items: list[dict]) -> dict:
    return {
        "version": 1,
        "batch": "drop_01",
        "items": items,
    }


def _item(day: int, **overrides) -> dict:
    base = {
        "day": day,
        "shelf": "intro",
        "approved": False,
        "posted_at": None,
    }
    base.update(overrides)
    return base


# ── parse_decisions ──────────────────────────────────────────────────


def test_parse_decisions_happy_path():
    out = parse_decisions('{"1":"approve","2":"skip"}')
    assert out == {1: "approve", 2: "skip"}


def test_parse_decisions_rejects_bad_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_decisions("not-json")


def test_parse_decisions_rejects_non_object():
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_decisions('["approve"]')


def test_parse_decisions_rejects_non_integer_day():
    with pytest.raises(ValueError, match="not an integer day"):
        parse_decisions('{"foo":"approve"}')


def test_parse_decisions_rejects_unknown_decision():
    with pytest.raises(ValueError, match="is not one of"):
        parse_decisions('{"1":"maybe"}')


def test_parse_decisions_empty_object_is_ok():
    assert parse_decisions("{}") == {}


# ── apply_decisions ──────────────────────────────────────────────────


def test_apply_decisions_approve_flips_flag():
    payload = _queue([_item(1)])
    summary = apply_decisions(payload, {1: "approve"}, now_iso="2026-05-28T12:00:00+00:00")
    assert payload["items"][0]["approved"] is True
    assert payload["items"][0]["approved_at"] == "2026-05-28T12:00:00+00:00"
    assert summary["approved"] == [1]
    assert summary["unchanged"] is False


def test_apply_decisions_skip_sets_skipped_and_clears_approved():
    payload = _queue([_item(1, approved=True)])
    summary = apply_decisions(payload, {1: "skip"}, now_iso="2026-05-28T12:00:00+00:00")
    assert payload["items"][0]["approved"] is False
    assert payload["items"][0]["skipped"] is True
    assert payload["items"][0]["skipped_at"] == "2026-05-28T12:00:00+00:00"
    assert "approved_at" not in payload["items"][0]
    assert summary["skipped"] == [1]
    assert summary["unchanged"] is False


def test_apply_decisions_reapprove_clears_skipped():
    """Operator changes their mind: skipped → approved should
    remove the skipped flag and clear skipped_at."""
    payload = _queue([_item(1, approved=False, skipped=True, skipped_at="2026-05-27T10:00:00Z")])
    apply_decisions(payload, {1: "approve"}, now_iso="2026-05-28T12:00:00+00:00")
    assert payload["items"][0]["approved"] is True
    assert "skipped" not in payload["items"][0]
    assert "skipped_at" not in payload["items"][0]


def test_apply_decisions_idempotent_reapprove():
    """Re-approving an already-approved item is unchanged=True."""
    payload = _queue([_item(1, approved=True, approved_at="2026-05-27T10:00:00Z")])
    summary = apply_decisions(payload, {1: "approve"}, now_iso="2026-05-28T12:00:00+00:00")
    # No change: flag was already true, approved_at preserved.
    assert summary["unchanged"] is True
    assert payload["items"][0]["approved_at"] == "2026-05-27T10:00:00Z"


def test_apply_decisions_frozen_when_already_posted():
    """A posted item must NEVER be mutated, even by an approve
    decision (would imply 'unpost', which we cannot do)."""
    payload = _queue([_item(1, approved=True, posted_at="2026-05-27T10:00:00Z")])
    summary = apply_decisions(payload, {1: "skip"}, now_iso="2026-05-28T12:00:00+00:00")
    assert summary["frozen"] == [1]
    assert summary["skipped"] == []
    assert payload["items"][0]["posted_at"] == "2026-05-27T10:00:00Z"
    assert payload["items"][0]["approved"] is True
    assert summary["unchanged"] is True


def test_apply_decisions_ignored_unknown_day():
    """Day not in the queue (operator looking at stale UI) is
    recorded but doesn't fail the run."""
    payload = _queue([_item(1)])
    summary = apply_decisions(payload, {99: "approve"})
    assert summary["ignored"] == [{"day": 99, "reason": "unknown_day"}]
    assert summary["unchanged"] is True


def test_apply_decisions_handles_mixed_batch():
    """Realistic: 3 approves, 1 skip, 1 already-posted."""
    payload = _queue([
        _item(1),
        _item(2),
        _item(3, approved=True, posted_at="2026-05-26T12:00:00Z"),
        _item(4),
        _item(5),
    ])
    decisions = {1: "approve", 2: "skip", 3: "approve", 4: "approve", 5: "skip"}
    summary = apply_decisions(payload, decisions, now_iso="2026-05-28T12:00:00+00:00")
    assert sorted(summary["approved"]) == [1, 4]
    assert sorted(summary["skipped"]) == [2, 5]
    assert summary["frozen"] == [3]
    # Day 3 untouched.
    assert payload["items"][2]["posted_at"] == "2026-05-26T12:00:00Z"


# ── main (CLI) ───────────────────────────────────────────────────────


def _write_queue_file(tmp_path: Path, batch: str = "drop_01") -> Path:
    p = tmp_path / "ig_queue.json"
    payload = _queue([_item(1), _item(2), _item(3)])
    payload["batch"] = batch
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def test_main_happy_path_writes_disk(tmp_path, capsys):
    qpath = _write_queue_file(tmp_path)
    rc = main([
        "--batch", "drop_01",
        "--decisions", '{"1":"approve","2":"skip"}',
        "--queue", str(qpath),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "approved=1" in out
    assert "skipped=1" in out

    written = json.loads(qpath.read_text(encoding="utf-8"))
    by_day = {it["day"]: it for it in written["items"]}
    assert by_day[1]["approved"] is True
    assert by_day[2]["approved"] is False
    assert by_day[2]["skipped"] is True
    assert by_day[3]["approved"] is False  # untouched


def test_main_dry_run_does_not_write(tmp_path, capsys):
    qpath = _write_queue_file(tmp_path)
    original = qpath.read_text(encoding="utf-8")
    rc = main([
        "--batch", "drop_01",
        "--decisions", '{"1":"approve"}',
        "--queue", str(qpath),
        "--dry-run",
    ])
    assert rc == 0
    assert "dry-run" in capsys.readouterr().out
    assert qpath.read_text(encoding="utf-8") == original


def test_main_batch_mismatch_returns_4(tmp_path, capsys):
    qpath = _write_queue_file(tmp_path, batch="drop_01")
    rc = main([
        "--batch", "drop_02",  # operator submitted against stale drop
        "--decisions", '{"1":"approve"}',
        "--queue", str(qpath),
    ])
    assert rc == 4
    err = capsys.readouterr().err
    assert "batch mismatch" in err


def test_main_bad_decisions_returns_2(tmp_path, capsys):
    qpath = _write_queue_file(tmp_path)
    rc = main([
        "--batch", "drop_01",
        "--decisions", '{"1":"maybe"}',
        "--queue", str(qpath),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "bad --decisions" in err


def test_main_missing_queue_returns_3(tmp_path, capsys):
    rc = main([
        "--batch", "drop_01",
        "--decisions", '{"1":"approve"}',
        "--queue", str(tmp_path / "nope.json"),
    ])
    assert rc == 3
    err = capsys.readouterr().err
    assert "queue not found" in err


def test_main_empty_decisions_is_noop(tmp_path, capsys):
    qpath = _write_queue_file(tmp_path)
    original = qpath.read_text(encoding="utf-8")
    rc = main([
        "--batch", "drop_01",
        "--decisions", "{}",
        "--queue", str(qpath),
    ])
    assert rc == 0
    assert qpath.read_text(encoding="utf-8") == original
    assert "nothing to do" in capsys.readouterr().out
