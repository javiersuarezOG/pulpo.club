"""Operational decisioning for per-source row-count deltas.

Combines the row-count sentinel verdict with source-health rows and the
source-success model so Slack can say what happened, not just that a
source is red.
"""
from __future__ import annotations

import dataclasses
from typing import Mapping, Sequence

from automation.row_count_sentinel import DropVerdict, TOTAL_KEY


KNOWN_DELTA_DECISIONS: frozenset[str] = frozenset({
    "source_failed",
    "source_partial",
    "validation_collapse",
    "expected_change",
    "unknown",
})
"""Closed set. Consumers: Slack formatter + carry-forward runbook."""


@dataclasses.dataclass(frozen=True)
class DeltaDecision:
    source: str
    country: str
    bucket: str
    level: str
    prev_count: int
    curr_count: int
    delta: int
    reason: str
    failure_id: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _latest_health_by_source(rows: Sequence[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        src = row.get("source")
        if not isinstance(src, str) or not src:
            continue
        ts = row.get("ts") or ""
        if src not in out or ts > (out[src].get("ts") or ""):
            out[src] = row
    return out


def _lifecycle(source: str, metadata: Mapping[str, dict] | None) -> str:
    if source == TOTAL_KEY:
        return "active"
    if not metadata:
        return "active"
    value = (metadata.get(source) or {}).get("lifecycle")
    return value if isinstance(value, str) else "active"


def classify_decision(
    verdict: DropVerdict,
    *,
    latest_health: Mapping[str, dict] | None = None,
    succeeded_sources: set[str] | None = None,
    metadata: Mapping[str, dict] | None = None,
) -> DeltaDecision:
    """Classify one row-count verdict into the runbook bucket."""
    latest_health = latest_health or {}
    succeeded_sources = succeeded_sources or set()
    health = latest_health.get(verdict.source) or {}

    if verdict.level == "ok":
        bucket = "expected_change"
        reason = verdict.reason
    elif _lifecycle(verdict.source, metadata) == "experimental":
        bucket = "expected_change"
        reason = f"experimental_lifecycle_log_only | {verdict.reason}"
    elif verdict.source not in succeeded_sources or health.get("status") == "red":
        bucket = "source_failed"
        reason = verdict.reason
    elif int(health.get("scraped") or 0) > 0 and int(health.get("kept") or 0) == 0:
        bucket = "validation_collapse"
        reason = "scraped_nonzero_kept_zero"
    elif verdict.curr_count > 0 and verdict.curr_count < verdict.prev_count:
        bucket = "source_partial"
        reason = verdict.reason
    else:
        bucket = "unknown"
        reason = verdict.reason

    return DeltaDecision(
        source=verdict.source,
        country=verdict.country,
        bucket=bucket,
        level=verdict.level,
        prev_count=verdict.prev_count,
        curr_count=verdict.curr_count,
        delta=verdict.delta,
        reason=reason,
        failure_id=health.get("failure_id"),
    )


def decide_deltas(
    verdicts: Sequence[DropVerdict],
    *,
    source_health_rows: Sequence[dict] = (),
    succeeded_sources: set[str] | None = None,
    metadata: Mapping[str, dict] | None = None,
) -> list[DeltaDecision]:
    latest = _latest_health_by_source(source_health_rows)
    decisions = [
        classify_decision(
            v,
            latest_health=latest,
            succeeded_sources=succeeded_sources,
            metadata=metadata,
        )
        for v in verdicts
        if v.source != TOTAL_KEY
    ]
    order = {name: i for i, name in enumerate(sorted(KNOWN_DELTA_DECISIONS))}
    return sorted(decisions, key=lambda d: (order.get(d.bucket, 99), d.source))


def format_slack_decision(decisions: Sequence[DeltaDecision], run_url: str | None = None) -> str:
    actionable = [d for d in decisions if d.level in {"critical", "warn"}]
    if not actionable:
        return "*Pulpo delta decision*: no source deltas require action."
    lines = ["*Pulpo delta decision*"]
    for d in actionable[:12]:
        suffix = f" failure_id={d.failure_id}" if d.failure_id else ""
        lines.append(
            f"- `{d.country}/{d.source}` {d.bucket}: "
            f"{d.prev_count} -> {d.curr_count} (Δ {d.delta}) — {d.reason}{suffix}"
        )
    if run_url:
        lines.append(f"<{run_url}|Open Actions run>")
    return "\n".join(lines)
