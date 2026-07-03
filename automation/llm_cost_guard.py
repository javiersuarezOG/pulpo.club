"""LLM cost guardrails — PR-D4.

Pulpo's LLM enrichment (DeepSeek) ALREADY computes per-call cost_usd
in automation/llm_enrichment.py and logs it via the metrics dict. What
it does NOT have: a hard cap that BLOCKS new calls once monthly /
daily spend exceeds a threshold. A runaway loop or a bad batch of
prompts can blow the month's budget in hours.

This module adds:
  * LLM_MONTHLY_USD_CAP (env-overridable; default $20)
  * LLM_DAILY_USD_CAP   (env-overridable; default $2)
  * Per-call cost log to web/data/llm_cost_history.jsonl (append-only,
    git-tracked — survives runner shutdown, no DB required)
  * record_cost() / check_budget() helpers
  * Warn thresholds at 80% / 95% of cap (Slack-pageable via the
    existing watchdog Slack step)

Per CLAUDE.md producer-consumer rule (post-2026-06-02):
KNOWN_BUDGET_VERDICTS is the closed set ('ok' | 'warn' | 'critical' |
'blocked'). Consumer = the LLM caller (blocks on 'blocked'), the
watchdog Slack alerter (pages on 'critical'), and the operator
dashboard (PR-S7 tile).

Why JSONL not a counter file
----------------------------
Append-only history lets us reconstruct ANY rolling window without
touching the writer. Today we use month-to-date + today; tomorrow a
7-day rolling cap is a 3-line addition with no schema migration.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import typing as t
from pathlib import Path


KNOWN_BUDGET_VERDICTS: frozenset[str] = frozenset({
    "ok",        # under 80% of both caps
    "warn",      # ≥80% of either cap
    "critical",  # ≥95% of either cap (Slack-page)
    "blocked",   # ≥100% of either cap (block new calls)
})
"""Closed set per CLAUDE.md producer-consumer rule (post-2026-06-02).
Contract test in tests/test_llm_cost_guard.py."""

DEFAULT_MONTHLY_USD_CAP = 20.0
DEFAULT_DAILY_USD_CAP = 2.0

WARN_FRACTION = 0.80
CRITICAL_FRACTION = 0.95

DEFAULT_HISTORY_PATH = Path("web/data/llm_cost_history.jsonl")


def monthly_cap_usd() -> float:
    """Env-overridable monthly USD cap. Falls back to $20."""
    val = os.environ.get("LLM_MONTHLY_USD_CAP")
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return DEFAULT_MONTHLY_USD_CAP


def daily_cap_usd() -> float:
    """Env-overridable daily USD cap. Falls back to $2."""
    val = os.environ.get("LLM_DAILY_USD_CAP")
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return DEFAULT_DAILY_USD_CAP


@dataclasses.dataclass(frozen=True)
class BudgetSnapshot:
    """A read of current spend vs caps. Computed by check_budget()."""

    month_to_date_usd: float
    today_usd: float
    monthly_cap_usd: float
    daily_cap_usd: float
    monthly_fraction: float  # mtd / cap, may exceed 1.0
    daily_fraction: float
    verdict: str             # one of KNOWN_BUDGET_VERDICTS
    blocking_reason: str | None  # populated only when verdict == 'blocked'

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _read_history(path: Path) -> list[dict]:
    """Tolerant JSONL reader — skips malformed lines."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _filter_by_window(
    rows: list[dict],
    *,
    after: dt.datetime,
) -> list[dict]:
    """Return rows whose ts is >= after. Rows with unparseable ts are dropped."""
    out = []
    for r in rows:
        ts_raw = r.get("ts")
        if not ts_raw:
            continue
        try:
            ts = dt.datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ts >= after:
            out.append(r)
    return out


def _sum_cost(rows: t.Iterable[dict]) -> float:
    """Sum cost_usd field across rows; defensively treats missing/bad as 0."""
    total = 0.0
    for r in rows:
        c = r.get("cost_usd")
        if isinstance(c, (int, float)):
            total += float(c)
    return total


def _classify(monthly_frac: float, daily_frac: float) -> tuple[str, str | None]:
    """Pure: return (verdict, blocking_reason)."""
    if monthly_frac >= 1.0:
        return "blocked", f"monthly cap exceeded ({monthly_frac:.1%})"
    if daily_frac >= 1.0:
        return "blocked", f"daily cap exceeded ({daily_frac:.1%})"
    if monthly_frac >= CRITICAL_FRACTION or daily_frac >= CRITICAL_FRACTION:
        return "critical", None
    if monthly_frac >= WARN_FRACTION or daily_frac >= WARN_FRACTION:
        return "warn", None
    return "ok", None


def check_budget(
    *,
    history_path: Path = DEFAULT_HISTORY_PATH,
    monthly_cap: float | None = None,
    daily_cap: float | None = None,
    now: dt.datetime | None = None,
) -> BudgetSnapshot:
    """Read the cost history and return a budget snapshot.

    Pure-ish (only reads the history file; no writes). Callers that
    intend to make a new LLM call should check ``verdict != 'blocked'``
    BEFORE the call, and record the realized cost AFTER via
    ``record_cost()``.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)

    rows = _read_history(history_path)

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    mtd_rows = _filter_by_window(rows, after=month_start)
    today_rows = _filter_by_window(rows, after=day_start)

    mtd_usd = _sum_cost(mtd_rows)
    today_usd = _sum_cost(today_rows)

    m_cap = monthly_cap if monthly_cap is not None else monthly_cap_usd()
    d_cap = daily_cap if daily_cap is not None else daily_cap_usd()
    m_frac = mtd_usd / m_cap if m_cap > 0 else 0.0
    d_frac = today_usd / d_cap if d_cap > 0 else 0.0

    verdict, blocking = _classify(m_frac, d_frac)

    return BudgetSnapshot(
        month_to_date_usd=round(mtd_usd, 6),
        today_usd=round(today_usd, 6),
        monthly_cap_usd=m_cap,
        daily_cap_usd=d_cap,
        monthly_fraction=round(m_frac, 4),
        daily_fraction=round(d_frac, 4),
        verdict=verdict,
        blocking_reason=blocking,
    )


def record_cost(
    *,
    cost_usd: float,
    purpose: str,
    model: str = "deepseek-chat",
    history_path: Path = DEFAULT_HISTORY_PATH,
    now: dt.datetime | None = None,
) -> None:
    """Append a single cost event to the history.

    Args:
        cost_usd: realized USD cost of this call.
        purpose: free-form tag (e.g. "enrichment", "dedup_tiebreak").
        model: model name. Default deepseek-chat per current usage.
        history_path: JSONL path. Default web/data/llm_cost_history.jsonl.
        now: optional UTC time (for test determinism).
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": now.isoformat(),
        "cost_usd": round(float(cost_usd), 6),
        "purpose": purpose,
        "model": model,
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def ensure_under_budget(
    *,
    history_path: Path = DEFAULT_HISTORY_PATH,
    monthly_cap: float | None = None,
    daily_cap: float | None = None,
    now: dt.datetime | None = None,
) -> BudgetSnapshot:
    """Convenience wrapper for the call-site guard.

    Raises ``BudgetExceededError`` if verdict is ``blocked``; otherwise
    returns the snapshot. Callers should use this just before issuing
    a new LLM API call so we don't blow the budget on a runaway loop.

    ``now`` is threaded to ``check_budget`` for test determinism — the
    month-to-date window is computed from it, so a test that seeds a
    fixed-date history MUST pin ``now`` to the same month or the spend
    reads as $0 outside it.
    """
    snap = check_budget(
        history_path=history_path,
        monthly_cap=monthly_cap,
        daily_cap=daily_cap,
        now=now,
    )
    if snap.verdict == "blocked":
        raise BudgetExceededError(snap.blocking_reason or "budget exceeded")
    return snap


class BudgetExceededError(RuntimeError):
    """Raised by ensure_under_budget() when verdict is 'blocked'."""
