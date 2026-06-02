"""Per-source brownout health model (PRD P1-9).

The legacy `automation/watchdog.py` treats a source as `green` once it
returns any non-zero kept-listings count. Audit 2026-06-02 found the
latest run reported elagente=2, nexo=5, realtyelsalvador=100 — all
green — even though elagente and nexo were >90% below their rolling
medians. Data Science saw skewed source distributions without an alert.

This module computes a richer four-state model from the existing
`source_health_history.jsonl` rows (already deduped by
`watchdog._read_source_history`):

    green       — kept-count ≥ 90% of rolling 7-run median.
    degraded    — kept-count < 50% of median for the latest run.
    red         — kept-count < 50% of median for two+ consecutive runs.
    recovering  — previous run was degraded/red AND current ratio
                  is 50%-90% (climbing back).

The Slack-facing helper formats one short line per source. The
`/api/nightly/health` JSON shape mirrors what `summarizeSourceBrownout`
on the JS side expects.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable


__all__ = [
    "SourceBrownoutResult",
    "DEGRADED_RATIO_THRESHOLD",
    "RECOVERING_RATIO_CEILING",
    "ROLLING_WINDOW",
    "compute_brownout_states",
]


# PRD P1-9 thresholds. Lock the magnitudes so dashboards downstream can
# rely on them.
DEGRADED_RATIO_THRESHOLD = 0.5
RECOVERING_RATIO_CEILING = 0.9
ROLLING_WINDOW = 7              # last 7 *successful* runs per source
MIN_HISTORY_FOR_RATIO = 3       # need at least 3 historical kept values
                                # before a ratio is meaningful


@dataclass
class SourceBrownoutResult:
    """Per-source brownout snapshot."""

    source: str
    status: str                 # green | degraded | red | recovering | unknown
    count: int                  # latest run's kept count
    rolling_median_7: float | None
    ratio: float | None         # count / rolling_median_7
    consecutive_degraded_runs: int
    previous_status: str | None
    failure_id: str | None = None
    error_class: str | None = None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "status": self.status,
            "count": self.count,
            "rolling_median_7": (
                None if self.rolling_median_7 is None
                else round(self.rolling_median_7, 2)
            ),
            "ratio": None if self.ratio is None else round(self.ratio, 4),
            "consecutive_degraded_runs": self.consecutive_degraded_runs,
            "previous_status": self.previous_status,
            "failure_id": self.failure_id,
            "error_class": self.error_class,
        }


def _kept_count(row: dict) -> int:
    """Best-effort extraction of the kept-listings count for a row.

    Handles the dedup-collapsed schema: the post-validation row carries
    `kept`; the crawl-phase row carries `scraped`. Prefer `kept` when
    present so brownout-by-validation (placeholders, schema drift) is
    distinguishable from brownout-by-fetch (HTTP 403).
    """
    raw = row.get("kept")
    if raw is None:
        raw = row.get("scraped")
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _status_to_brownout(status: str | None) -> str:
    """Map the existing `green | red | skipped` schema to brownout terms."""
    if status == "green":
        return "green"
    if status == "red":
        return "red"
    if status == "skipped":
        return "skipped"
    return "unknown"


def _per_source_history(rows: Iterable[dict]) -> dict[str, list[dict]]:
    by_source: dict[str, list[dict]] = {}
    for r in rows:
        src = r.get("source") or "?"
        by_source.setdefault(src, []).append(r)
    for src in by_source:
        by_source[src].sort(key=lambda r: r.get("ts") or "")
    return by_source


def _classify(
    source: str,
    history: list[dict],
) -> SourceBrownoutResult:
    """Run the brownout state machine over one source's chronological history."""
    if not history:
        return SourceBrownoutResult(
            source=source, status="unknown", count=0,
            rolling_median_7=None, ratio=None,
            consecutive_degraded_runs=0, previous_status=None,
        )

    latest = history[-1]
    latest_count = _kept_count(latest)
    failure_id = latest.get("failure_id")
    error_class = latest.get("error_class")

    # Rolling window is the last 7 runs EXCLUDING the current one — we
    # don't want today's count to drag itself toward the median.
    window = history[-(ROLLING_WINDOW + 1):-1]
    historical_counts = [_kept_count(r) for r in window if _kept_count(r) > 0]
    if len(historical_counts) < MIN_HISTORY_FOR_RATIO:
        # Not enough baseline. Surface as `unknown` so the watchdog can
        # decide whether to alert on a newly-added source.
        return SourceBrownoutResult(
            source=source, status="unknown", count=latest_count,
            rolling_median_7=None, ratio=None,
            consecutive_degraded_runs=0,
            previous_status=_status_to_brownout(
                history[-2].get("status") if len(history) > 1 else None
            ),
            failure_id=failure_id, error_class=error_class,
        )

    median = statistics.median(historical_counts)
    ratio = latest_count / median if median > 0 else 0.0

    # Walk backwards from the most recent to count consecutive degraded
    # runs. Each prior run uses its own rolling window of seven before
    # itself — costly but the history is small (one row per nightly per
    # source), and this catches the "stuck at 5% for two weeks" pattern.
    consecutive = 0
    for i in range(len(history) - 1, -1, -1):
        row = history[i]
        count = _kept_count(row)
        prior_window = [
            _kept_count(r)
            for r in history[max(0, i - ROLLING_WINDOW):i]
            if _kept_count(r) > 0
        ]
        if len(prior_window) < MIN_HISTORY_FOR_RATIO:
            break
        prior_median = statistics.median(prior_window)
        prior_ratio = count / prior_median if prior_median > 0 else 0.0
        if prior_ratio < DEGRADED_RATIO_THRESHOLD:
            consecutive += 1
        else:
            break

    previous_status = (
        _status_to_brownout(history[-2].get("status"))
        if len(history) > 1 else None
    )

    if ratio < DEGRADED_RATIO_THRESHOLD:
        status = "red" if consecutive >= 2 else "degraded"
    elif ratio < RECOVERING_RATIO_CEILING and previous_status in {"red", "degraded"}:
        status = "recovering"
    else:
        status = "green"

    return SourceBrownoutResult(
        source=source, status=status, count=latest_count,
        rolling_median_7=median, ratio=ratio,
        consecutive_degraded_runs=consecutive,
        previous_status=previous_status,
        failure_id=failure_id, error_class=error_class,
    )


def compute_brownout_states(
    rows: Iterable[dict],
) -> list[SourceBrownoutResult]:
    """Run the brownout classifier across every source in the history.

    Caller passes the deduped rows from
    `automation.watchdog._read_source_history`. Returns one
    `SourceBrownoutResult` per source, sorted alphabetically.
    """
    by_source = _per_source_history(rows)
    return sorted(
        (_classify(src, history) for src, history in by_source.items()),
        key=lambda r: r.source,
    )
