"""Row-count sentinel — PR-D2.

Snapshots per-source ranked listing counts on a regular cadence,
classifies deltas vs the rolling 7-tick history, and Slack-pages on
CRIT drops.

Why this exists
---------------
The 2026-05-26 → 2026-06-01 6-day silent freeze ran 5 nightlies before
anyone noticed pulpo.club was stale. The nightly's existing canaries
fire only at the END of the ~60-min run, and the watchdog cares about
staleness (24h+), not mid-day source brownouts. This sentinel sits
between those two: on each cron tick it diffs current per-source counts
vs the 7 prior committed history rows and fires Slack on CRIT.

Pattern lifted from events-discovery's `row_count_sentinel.py`. Adapted
to pulpo's JSON-files-in-git data layer (events-discovery uses a
Postgres `events_row_count_history` table; pulpo uses
`web/data/row_count_history.jsonl`).

Thresholds (same as events-discovery, validated on real freeze data)
--------------------------------------------------------------------
- ``critical``: drop >= 20% of prior OR drop >= 200 rows absolute
- ``warn``:     drop >= 5%  of prior OR drop >= 50 rows absolute
- ``ok``:       otherwise (including any non-negative delta — count
                growth is never bad)

The "OR" matters for small sources: nexo dropping 5 → 0 is 100% but
only 5 rows; the absolute threshold wouldn't fire (50), the percent
threshold WILL fire (20%) — so the OR catches it.

Synthetic ``__total__`` key
---------------------------
Every tick also computes the sum across all sources. The total is
classified independently. Catches the case where one source drops to
zero AND another's parser bug doubles its count — the per-source
sentinel would see "one OK, one CRIT", the platform-total would see
"net zero", but the total catches it if the actual ranked-listing
count crashed.

Consumers (per CLAUDE.md producer-consumer rule, post-2026-06-02)
-----------------------------------------------------------------
- ``.github/workflows/pulpo-row-count-sentinel.yml`` runs this every
  6h and Slack-pages on any CRIT.
- The operator dashboard (PR-S7) reads
  ``web/data/row_count_history.jsonl`` for the per-source drop pill.
- ``.github/workflows/pulpo-nightly.yml`` invokes this in-line as a
  pre-commit canary with ``record=False`` so candidate data can be
  classified without polluting the committed-truth baseline.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import typing as t
from dataclasses import replace
from pathlib import Path


# ---------- Constants ----------

KNOWN_DROP_LEVELS: frozenset[str] = frozenset({"ok", "warn", "critical"})
"""Closed set; producers must only emit these. Contract test:
``tests/test_row_count_classifier.py::test_known_drop_levels_contract``."""

WARN_PCT = 0.05
WARN_ABS = 50
CRIT_PCT = 0.20
CRIT_ABS = 200

TOTAL_KEY = "__total__"
"""Synthetic source key for the sum across all real sources. Reserved —
no real scraper may use this slug."""

DEFAULT_HISTORY_PATH = Path("web/data/row_count_history.jsonl")
RANKED_JSON_PATH = Path("web/data/ranked.json")


# ---------- Data model ----------

@dataclasses.dataclass(frozen=True)
class Tick:
    """One per-source count observation. Persisted as one JSONL row per
    (tick_at, source) pair — so a single tick produces N+1 rows
    (N sources + 1 synthetic total)."""

    tick_at: str  # ISO-8601 UTC
    source: str
    count: int
    country: str  # 'sv' or 'pa' — scoped per-country totals are useful

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Tick":
        return cls(
            tick_at=d["tick_at"],
            source=d["source"],
            count=int(d["count"]),
            country=d.get("country", "sv"),
        )


@dataclasses.dataclass(frozen=True)
class DropVerdict:
    """Pure-function output of ``classify_drop``. The Slack-alert
    formatter reads ``level``; the dashboard reads everything."""

    source: str
    country: str
    prev_count: int
    curr_count: int
    delta: int          # negative = drop, positive = growth
    pct: float          # negative for drop; 0.0 when prev_count == 0
    level: str          # one of KNOWN_DROP_LEVELS
    reason: str
    prior_median: int   # 7-tick median of prior counts; for context

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------- Classifier (pure function) ----------

def classify_drop(
    source: str,
    country: str,
    curr_count: int,
    prior_counts: t.Sequence[int],
) -> DropVerdict:
    """Pure function over (current, prior history) → drop verdict.

    ``prior_counts`` is the chronologically-ordered list of recent
    historical counts for this source (most recent LAST). The function
    compares against the most-recent prior tick for the delta. The
    median of all prior_counts is computed for context (used by the
    Slack formatter to spot "this drop is also vs. the typical week").

    Edge cases:
    - Empty prior_counts → ok, "first_observation". Caller will record
      the tick but no alert fires.
    - prev_count == 0 → ratio undefined; use absolute thresholds only.
    - Count growth (delta > 0) → always ok. Growth is good news.
    """
    if not prior_counts:
        return DropVerdict(
            source=source,
            country=country,
            prev_count=0,
            curr_count=curr_count,
            delta=curr_count,
            pct=0.0,
            level="ok",
            reason="first_observation",
            prior_median=0,
        )

    prev_count = prior_counts[-1]
    delta = curr_count - prev_count
    median = _median(prior_counts)

    # Growth is always ok.
    if delta >= 0:
        return DropVerdict(
            source=source,
            country=country,
            prev_count=prev_count,
            curr_count=curr_count,
            delta=delta,
            pct=delta / prev_count if prev_count else 0.0,
            level="ok",
            reason="non_negative_delta",
            prior_median=median,
        )

    abs_drop = -delta  # positive number for clarity
    pct_drop = (abs_drop / prev_count) if prev_count else 0.0
    pct_signed = -pct_drop  # negative pct in the output

    # Critical: 20% drop OR 200 rows absolute.
    if pct_drop >= CRIT_PCT or abs_drop >= CRIT_ABS:
        triggers = []
        if pct_drop >= CRIT_PCT:
            triggers.append(f"pct={pct_drop:.1%}>={CRIT_PCT:.0%}")
        if abs_drop >= CRIT_ABS:
            triggers.append(f"abs={abs_drop}>={CRIT_ABS}")
        return DropVerdict(
            source=source,
            country=country,
            prev_count=prev_count,
            curr_count=curr_count,
            delta=delta,
            pct=pct_signed,
            level="critical",
            reason=" | ".join(triggers),
            prior_median=median,
        )

    # Warn: 5% drop OR 50 rows absolute.
    if pct_drop >= WARN_PCT or abs_drop >= WARN_ABS:
        triggers = []
        if pct_drop >= WARN_PCT:
            triggers.append(f"pct={pct_drop:.1%}>={WARN_PCT:.0%}")
        if abs_drop >= WARN_ABS:
            triggers.append(f"abs={abs_drop}>={WARN_ABS}")
        return DropVerdict(
            source=source,
            country=country,
            prev_count=prev_count,
            curr_count=curr_count,
            delta=delta,
            pct=pct_signed,
            level="warn",
            reason=" | ".join(triggers),
            prior_median=median,
        )

    return DropVerdict(
        source=source,
        country=country,
        prev_count=prev_count,
        curr_count=curr_count,
        delta=delta,
        pct=pct_signed,
        level="ok",
        reason=f"within_threshold (drop={abs_drop}, pct={pct_drop:.1%})",
        prior_median=median,
    )


def _median(values: t.Sequence[int]) -> int:
    """Integer median (rounded down)."""
    if not values:
        return 0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) // 2


# ---------- Ranked.json reader ----------

def count_listings_by_source(ranked_path: Path) -> dict[str, int]:
    """Read ranked.json, return {source: count}. Adds the synthetic
    ``__total__`` key with the platform-wide sum. Per-country
    discrimination is done by the caller using the country-specific
    file (e.g. ranked.PA.json).
    """
    if not ranked_path.exists():
        return {}
    data = json.loads(ranked_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return {}
    counts: dict[str, int] = {}
    for listing in data:
        if not isinstance(listing, dict):
            continue
        source = listing.get("source")
        if not source:
            continue
        counts[source] = counts.get(source, 0) + 1
    counts[TOTAL_KEY] = sum(c for k, c in counts.items() if k != TOTAL_KEY)
    return counts


# ---------- History persistence ----------

def load_history(history_path: Path) -> list[Tick]:
    """Read the append-only JSONL. Each line is one Tick. Tolerant of
    malformed lines — skips them rather than crashing the sentinel."""
    if not history_path.exists():
        return []
    out: list[Tick] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            out.append(Tick.from_dict(d))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return out


def append_tick(tick: Tick, history_path: Path) -> None:
    """Append one row. The file is git-tracked so concurrent appends
    would conflict — but the workflow is single-flight (concurrency
    group + cancel-in-progress), so only one writer at a time."""
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(tick.to_dict()) + "\n")


def prior_counts_for(
    source: str,
    country: str,
    history: t.Sequence[Tick],
    *,
    window: int = 7,
) -> list[int]:
    """Filter history to (source, country) and return the most recent
    ``window`` counts in chronological order (oldest first, newest
    last) so callers can use ``prior_counts[-1]`` as "prev"."""
    filtered = [
        t for t in history
        if t.source == source and t.country == country
    ]
    # History rows are appended in time order so a simple tail slice
    # is correct. We still sort defensively in case of out-of-order
    # writes (concurrent test runs, etc.).
    filtered.sort(key=lambda r: r.tick_at)
    return [r.count for r in filtered[-window:]]


# ---------- Orchestration ----------

def run_tick(
    *,
    ranked_paths: t.Mapping[str, Path],
    history_path: Path = DEFAULT_HISTORY_PATH,
    now_iso: str | None = None,
    record: bool = True,
) -> list[DropVerdict]:
    """Read every (country, ranked_path), compute per-source counts +
    total, classify vs history, optionally append new history rows,
    return the full verdict list (sorted level desc so the caller can
    stop at first critical).

    ``ranked_paths`` is {country_code: Path}. Today: ``{'sv':
    Path('web/data/ranked.json'), 'pa': Path('web/data/ranked.PA.json')}``.

    ``record=False`` is load-bearing for the nightly pre-commit gate:
    the gate classifies a candidate ``ranked.json`` that may never ship,
    so appending it would poison the 7-tick baseline used by the 6h
    committed-data cron.
    """
    tick_at = now_iso or dt.datetime.now(dt.timezone.utc).isoformat()
    history = load_history(history_path)
    verdicts: list[DropVerdict] = []

    for country, ranked_path in sorted(ranked_paths.items()):
        counts = count_listings_by_source(ranked_path)
        if not counts:
            continue
        # Classify the UNION of (sources present today) and (sources seen in
        # this country's trailing history). A source that zero-yielded is
        # absent from today's ranked.json, so iterating `counts` alone would
        # never classify it — exactly the 2026-06-08 incident (citymax_sc
        # 162→0) that this gate exists to catch. A history-known source
        # missing today is classified with count=0, which trips a 100% drop.
        history_sources = {tk.source for tk in history if tk.country == country}
        for source in sorted(set(counts) | history_sources):
            count = counts.get(source, 0)
            prior = prior_counts_for(source, country, history)
            if not prior and source not in counts:
                # Never seen before AND absent today — nothing to classify.
                continue
            verdict = classify_drop(source, country, count, prior)
            verdicts.append(verdict)
            if record:
                append_tick(
                    Tick(
                        tick_at=tick_at,
                        source=source,
                        count=count,
                        country=country,
                    ),
                    history_path,
                )

    # Critical first; then warn; then ok.
    order = {"critical": 0, "warn": 1, "ok": 2}
    verdicts.sort(key=lambda v: (order[v.level], v.source))
    return verdicts


def any_critical(verdicts: t.Sequence[DropVerdict]) -> bool:
    return any(v.level == "critical" for v in verdicts)


def gate_decision(
    verdicts: t.Sequence[DropVerdict],
    floor: int | None = None,
) -> tuple[bool, str]:
    """Decide whether a ``--fail-on-crit`` row-count gate should BLOCK or DEGRADE.

    A single source cratering must never freeze a healthy catalogue. Block ONLY
    on a catastrophic TOTAL collapse — the ``sv __total__`` verdict itself going
    critical, or the total dropping below ``floor``. Per-source craters while the
    catalogue is healthy DEGRADE to a non-blocking warning (the dead source is
    still surfaced by delta-decision, the source_health red row, and the
    scraper-repair agent).

    Motivation — nightly 27399389866: ``xitios`` 28→0 (critical) hard-failed the
    run while the ``sv __total__`` GREW 1590→2104 (+32%). One dead source froze
    2104 perfectly good listings.

    ``floor=None`` preserves the original strict behaviour (any critical blocks),
    so callers that don't pass a floor are unchanged.

    Returns ``(should_block, message)``. ``message`` is empty when nothing is
    critical.
    """
    crit = [v for v in verdicts if v.level == "critical"]
    if not crit:
        return False, ""

    sv_total = next(
        (v for v in verdicts if v.source == TOTAL_KEY and v.country == "sv"),
        None,
    )
    total_curr = (
        sv_total.curr_count
        if sv_total is not None
        else sum(v.curr_count for v in verdicts
                 if v.source != TOTAL_KEY and v.country == "sv")
    )
    total_critical = bool(sv_total is not None and sv_total.level == "critical")
    crit_sources = [v.source for v in crit if v.source != TOTAL_KEY]
    catalogue_healthy = (
        floor is not None and total_curr >= floor and not total_critical
    )

    if catalogue_healthy and crit_sources:
        return False, (
            f"DEGRADE: per-source CRITICAL {crit_sources} but the catalogue is "
            f"healthy (sv total {total_curr} >= floor {floor}, sv __total__ not "
            f"critical) — shipping. A single source cratering must not freeze "
            f"{total_curr} good listings; the dead source(s) are alerted via "
            f"delta-decision + source_health + auto-repair."
        )
    return True, (
        f"CATASTROPHIC: blocking commit (total_critical={total_critical}, "
        f"total={total_curr}, floor={floor}, crit_sources={crit_sources})."
    )


def _lifecycle_for(source: str, metadata: t.Mapping[str, dict] | None) -> str:
    if source == TOTAL_KEY:
        return "active"
    if not metadata:
        return "active"
    meta = metadata.get(source) or {}
    lifecycle = meta.get("lifecycle")
    return lifecycle if isinstance(lifecycle, str) else "active"


def downgrade_experimental(verdicts: t.Sequence[DropVerdict],
                           metadata: t.Mapping[str, dict] | None) -> list[DropVerdict]:
    """Return verdicts with experimental-source CRITs downgraded to WARN.

    Consumer: the row-count CLI and pre-commit gate. Experimental sources
    are still visible in logs/Slack, but they must not block production
    inventory commits.
    """
    out: list[DropVerdict] = []
    for verdict in verdicts:
        if verdict.level == "critical" and _lifecycle_for(verdict.source, metadata) == "experimental":
            out.append(replace(
                verdict,
                level="warn",
                reason=f"experimental_lifecycle_log_only | {verdict.reason}",
            ))
        else:
            out.append(verdict)
    order = {"critical": 0, "warn": 1, "ok": 2}
    out.sort(key=lambda v: (order[v.level], v.source))
    return out


def format_slack_message(verdicts: t.Sequence[DropVerdict], run_url: str) -> str:
    """Compact Slack-friendly summary. Includes the worst offenders + a
    pointer to the run for the full picture."""
    crit = [v for v in verdicts if v.level == "critical"]
    warn = [v for v in verdicts if v.level == "warn"]
    if not crit and not warn:
        return f"*Pulpo row-count sentinel*: all sources OK. <{run_url}|view run>"
    lines = ["*Pulpo row-count sentinel CRIT*"]
    for v in crit[:10]:
        lines.append(
            f"- `{v.country}/{v.source}`: {v.prev_count} → {v.curr_count} "
            f"(Δ {v.delta}, {v.pct:.1%}) — {v.reason}"
        )
    if warn and len(crit) < 10:
        lines.append("_warn:_")
        for v in warn[: 10 - len(crit)]:
            lines.append(
                f"- `{v.country}/{v.source}`: {v.prev_count} → {v.curr_count} "
                f"(Δ {v.delta}, {v.pct:.1%})"
            )
    lines.append(f"<{run_url}|view run>")
    return "\n".join(lines)
