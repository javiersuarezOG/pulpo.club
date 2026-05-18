"""Per-recipient send history — JSONL on disk.

Append-only log, one row per `{recipient_hash, issue_id, sent_at, picks}`.
Used to:
  • exclude recently-seen listings from a recipient's next issue (90d window)
  • derive each recipient's eligibility window (last_send_at) on the fly
  • feed observability + Slack roll-ups in PR-NL-3

PII rule: NEVER write raw email or display name. Recipients are keyed by
sha256(email + salt). The same salt lives in env (PULPO_NEWSLETTER_SALT);
dry-run uses a deterministic dev salt so cohort fixtures are reproducible.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HISTORY_PATH = Path("web/data/newsletter_history.jsonl")
DEV_SALT = "pulpo-newsletter-dev-salt"
EXCLUSION_WINDOW_DAYS = 90


def email_hash(email: str, salt: Optional[str] = None) -> str:
    s = salt or os.environ.get("PULPO_NEWSLETTER_SALT") or DEV_SALT
    return hashlib.sha256(f"{s}:{email.strip().lower()}".encode()).hexdigest()[:24]


@dataclass
class HistoryRow:
    recipient_hash: str
    issue_id: str
    sent_at: str                              # ISO8601 UTC
    cohort: str
    source_ids: list[str]                     # ["remax:001461165132", ...]


def load_history(path: Path = HISTORY_PATH) -> list[HistoryRow]:
    if not path.exists():
        return []
    rows: list[HistoryRow] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(
                HistoryRow(
                    recipient_hash=d["recipient_hash"],
                    issue_id=d["issue_id"],
                    sent_at=d["sent_at"],
                    cohort=d.get("cohort", "unknown"),
                    source_ids=d.get("source_ids", []),
                )
            )
    return rows


def append_history(row: HistoryRow, path: Path = HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(row.__dict__) + "\n")


def excluded_source_ids_for(
    recipient_hash: str,
    *,
    now: Optional[datetime] = None,
    window_days: int = EXCLUSION_WINDOW_DAYS,
    history: Optional[list[HistoryRow]] = None,
) -> set[str]:
    """All source_ids sent to this recipient inside the exclusion window."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    rows = history if history is not None else load_history()
    out: set[str] = set()
    for r in rows:
        if r.recipient_hash != recipient_hash:
            continue
        sent = _parse_iso(r.sent_at)
        if sent is None or sent < cutoff:
            continue
        out.update(r.source_ids)
    return out


def last_send_at_for(
    recipient_hash: str,
    history: Optional[list[HistoryRow]] = None,
) -> Optional[datetime]:
    rows = history if history is not None else load_history()
    times = [
        _parse_iso(r.sent_at)
        for r in rows
        if r.recipient_hash == recipient_hash
    ]
    times = [t for t in times if t is not None]
    return max(times) if times else None


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
