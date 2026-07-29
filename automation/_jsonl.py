"""Idempotent, retention-bounded JSONL history writes.

Image/nightly audit 2026-07-29 (PR-H). Several nightly history files are
appended with a bare ``open("a")`` loop — one row (or row-set) per run.
Two problems follow:

1. **Rerun duplication.** A manual same-day rerun (workflow_dispatch,
   failure recovery) appends a SECOND full row-set. Consumers that read
   these files then see phantom duplicates.

2. **Unbounded growth.** Nothing prunes them; they are re-committed to
   git every nightly. ``type_classifier_log.jsonl`` reached ~40 MB /
   ~100k rows.

``append_jsonl_idempotent`` fixes both: it merges the new rows into the
existing file keyed by a caller-supplied idempotency key (a rerun
REPLACES same-key rows in place instead of duplicating), then optionally
drops rows older than a retention window. The whole file is rewritten
atomically via ``_atomic.atomic_write_text``.

Design notes:
- Existing row ORDER is preserved; genuinely-new rows append at the end,
  so the normal one-run-per-day case still produces a clean append-only
  git diff.
- ``key_fn`` returning ``None`` means "this row has no stable identity" —
  it is always kept, never deduped (safer than collapsing rows that only
  looked equal because a field was missing).
- Malformed existing lines are skipped, never fatal — a half-written
  file from a crash self-heals on the next run.
- Best-effort by contract at the call site: history I/O must never kill a
  pipeline run (callers wrap in try/except per the never-block rule).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from automation._atomic import atomic_write_text


def _read_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip malformed; self-heal
        if isinstance(row, dict):
            out.append(row)
    return out


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def append_jsonl_idempotent(
    path: Path,
    rows: Iterable[dict],
    *,
    key_fn: Callable[[dict], Any],
    retention_days: Optional[int] = None,
    ts_field: str = "ts",
    now: Optional[datetime] = None,
) -> dict:
    """Merge ``rows`` into the JSONL file at ``path``, idempotently.

    Args:
        path: the ``.jsonl`` history file.
        rows: new rows to write this run.
        key_fn: maps a row to a hashable idempotency key. A new row whose
            key matches an existing row REPLACES it in place (rerun
            safety). ``key_fn(row) is None`` → the row is always kept,
            never deduped.
        retention_days: when set, drop rows whose ``ts_field`` is older
            than this many days before ``now``. Rows with an unparsable /
            missing timestamp are always kept (never silently dropped).
        ts_field: the timestamp field name used for retention.
        now: injectable clock for tests; defaults to UTC now.

    Returns a small stats dict: ``{added, replaced, pruned, total}``.
    """
    now = now or datetime.now(timezone.utc)
    existing = _read_existing(path)

    # Index existing rows by key (last-wins if the file already had dups).
    index_by_key: dict[Any, int] = {}
    for i, r in enumerate(existing):
        try:
            k = key_fn(r)
        except Exception:
            k = None
        if k is not None:
            index_by_key[k] = i

    merged = list(existing)
    added = replaced = 0
    for row in rows:
        try:
            k = key_fn(row)
        except Exception:
            k = None
        if k is not None and k in index_by_key:
            merged[index_by_key[k]] = row
            replaced += 1
        else:
            if k is not None:
                index_by_key[k] = len(merged)
            merged.append(row)
            added += 1

    pruned = 0
    if retention_days is not None:
        cutoff = now - timedelta(days=retention_days)
        kept: list[dict] = []
        for r in merged:
            ts = _parse_ts(r.get(ts_field))
            if ts is not None and ts < cutoff:
                pruned += 1
                continue
            kept.append(r)
        merged = kept

    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in merged)
    atomic_write_text(path, payload)
    return {"added": added, "replaced": replaced, "pruned": pruned, "total": len(merged)}
