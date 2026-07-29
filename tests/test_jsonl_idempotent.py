"""Tests for automation/_jsonl.append_jsonl_idempotent (image/nightly
audit 2026-07-29, PR-H).

Pins: rerun REPLACES same-key rows (no duplication); genuinely-new rows
append; key_fn->None rows are always kept; retention drops old rows but
keeps timestamp-less rows; malformed existing lines self-heal; the normal
one-run-per-day path stays a clean append.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation._jsonl import append_jsonl_idempotent  # noqa: E402

NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)


def _read(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _key(row: dict):
    return (row.get("ts", "")[:10], row.get("source"))


def test_first_write_creates_file(tmp_path):
    p = tmp_path / "h.jsonl"
    rows = [{"ts": "2026-07-29T00:00:00+00:00", "source": "remax", "count": 5}]
    stats = append_jsonl_idempotent(p, rows, key_fn=_key, now=NOW)
    assert stats["added"] == 1 and stats["replaced"] == 0
    assert _read(p) == rows


def test_rerun_replaces_same_key_no_duplication(tmp_path):
    p = tmp_path / "h.jsonl"
    day = "2026-07-29T00:00:00+00:00"
    append_jsonl_idempotent(p, [{"ts": day, "source": "remax", "count": 5}],
                            key_fn=_key, now=NOW)
    # Same-day rerun with an updated count.
    stats = append_jsonl_idempotent(p, [{"ts": day, "source": "remax", "count": 9}],
                                    key_fn=_key, now=NOW)
    rows = _read(p)
    assert len(rows) == 1  # replaced, not duplicated
    assert rows[0]["count"] == 9
    assert stats["replaced"] == 1 and stats["added"] == 0


def test_new_day_appends_clean(tmp_path):
    p = tmp_path / "h.jsonl"
    append_jsonl_idempotent(p, [{"ts": "2026-07-28T00:00:00+00:00", "source": "remax"}],
                            key_fn=_key, now=NOW)
    append_jsonl_idempotent(p, [{"ts": "2026-07-29T00:00:00+00:00", "source": "remax"}],
                            key_fn=_key, now=NOW)
    rows = _read(p)
    assert [r["ts"][:10] for r in rows] == ["2026-07-28", "2026-07-29"]  # order preserved


def test_none_key_rows_always_kept(tmp_path):
    p = tmp_path / "h.jsonl"

    def key_none(_row):
        return None

    append_jsonl_idempotent(p, [{"ts": "2026-07-29T00:00:00+00:00", "x": 1}],
                            key_fn=key_none, now=NOW)
    append_jsonl_idempotent(p, [{"ts": "2026-07-29T00:00:00+00:00", "x": 1}],
                            key_fn=key_none, now=NOW)
    assert len(_read(p)) == 2  # never deduped


def test_retention_drops_old_keeps_recent(tmp_path):
    p = tmp_path / "h.jsonl"
    old = (NOW - timedelta(days=40)).isoformat()
    recent = (NOW - timedelta(days=5)).isoformat()
    append_jsonl_idempotent(
        p,
        [{"ts": old, "source": "a"}, {"ts": recent, "source": "b"}],
        key_fn=_key, retention_days=30, now=NOW,
    )
    rows = _read(p)
    assert [r["source"] for r in rows] == ["b"]


def test_retention_keeps_timestampless_rows(tmp_path):
    p = tmp_path / "h.jsonl"
    stats = append_jsonl_idempotent(
        p,
        [{"source": "no_ts"}],  # no ts field
        key_fn=lambda r: r.get("source"), retention_days=30, now=NOW,
    )
    assert stats["pruned"] == 0
    assert _read(p) == [{"source": "no_ts"}]


def test_malformed_existing_lines_self_heal(tmp_path):
    p = tmp_path / "h.jsonl"
    p.write_text('{"ts": "2026-07-20T00:00:00+00:00", "source": "ok"}\n'
                 "{ this is not json\n"
                 '\n')
    stats = append_jsonl_idempotent(
        p, [{"ts": "2026-07-29T00:00:00+00:00", "source": "new"}],
        key_fn=_key, now=NOW,
    )
    rows = _read(p)
    # The good existing row survived; the malformed line was dropped; the
    # new row appended.
    assert [r["source"] for r in rows] == ["ok", "new"]
    assert stats["added"] == 1


def test_trailing_newline_and_valid_json_output(tmp_path):
    p = tmp_path / "h.jsonl"
    append_jsonl_idempotent(p, [{"ts": "2026-07-29T00:00:00+00:00", "source": "x"}],
                            key_fn=_key, now=NOW)
    text = p.read_text()
    assert text.endswith("\n")
    for ln in text.splitlines():
        json.loads(ln)  # every line parses
