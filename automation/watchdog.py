"""
Pipeline watchdog — validates that the nightly run produced sane output.

Checks (all must pass):
  1. Freshness     — last_updated.json timestamp within 36 hours
  2. Volume        — ranked.json count within ±20% of 7-day rolling median
  3. Parser errors — parser_errors.log has no non-comment content if recently written
  4. Public deploy — https://pulpo.club/data/ranked.json returns 200 + valid JSON

Exit 0 on success, 1 on any failure. Prints diagnostic lines to stdout.
"""
from __future__ import annotations
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Thresholds
FRESHNESS_HOURS   = 36
VOLUME_TOLERANCE  = 0.20   # ±20% from 7-day rolling median
VOLUME_FLOOR      = 50     # absolute minimum if history is unavailable
MIN_HISTORY_RUNS  = 3      # need at least 3 full runs to compute a median
FULL_RUN_FLOOR    = 200    # runs with total < this are test runs, excluded from median


def check_freshness(data_dir: Path) -> tuple[bool, str]:
    """Verify last_updated.json is within FRESHNESS_HOURS."""
    path = data_dir / "last_updated.json"
    if not path.exists():
        return False, "FAIL freshness: last_updated.json missing"
    try:
        meta = json.loads(path.read_text())
        ts = datetime.fromisoformat(meta["last_updated"].replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - ts
        if age > timedelta(hours=FRESHNESS_HOURS):
            return False, (
                f"FAIL freshness: last_updated is {age.total_seconds()/3600:.1f}h old "
                f"(limit {FRESHNESS_HOURS}h). Last run: {meta['last_updated']}"
            )
        return True, f"OK   freshness: {age.total_seconds()/3600:.1f}h ago"
    except Exception as e:
        return False, f"FAIL freshness: could not parse last_updated.json — {e}"


def check_volume(data_dir: Path) -> tuple[bool, str]:
    """Verify ranked.json count is within ±VOLUME_TOLERANCE of 7-day rolling median."""
    ranked_path = data_dir / "ranked.json"
    history_path = data_dir / "run_history.json"

    if not ranked_path.exists():
        return False, "FAIL volume: ranked.json missing"

    try:
        current = len(json.loads(ranked_path.read_text()))
    except Exception as e:
        return False, f"FAIL volume: could not read ranked.json — {e}"

    # Compute 7-day rolling median from run_history.json
    median = None
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            recent_totals = [
                r["total"] for r in history
                if r.get("total", 0) >= FULL_RUN_FLOOR
                and datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) >= cutoff
            ]
            if len(recent_totals) >= MIN_HISTORY_RUNS:
                median = statistics.median(recent_totals)
        except Exception:
            pass

    if median is not None:
        lo = median * (1 - VOLUME_TOLERANCE)
        hi = median * (1 + VOLUME_TOLERANCE)
        if current < lo or current > hi:
            return False, (
                f"FAIL volume: {current} listings outside ±{VOLUME_TOLERANCE*100:.0f}% "
                f"of 7-day median {median:.0f} (band [{lo:.0f}, {hi:.0f}])"
            )
        return True, f"OK   volume: {current} listings (median {median:.0f}, band [{lo:.0f}, {hi:.0f}])"

    # Fallback to absolute floor
    if current < VOLUME_FLOOR:
        return False, f"FAIL volume: {current} listings < floor {VOLUME_FLOOR} (no history to compute median)"
    return True, f"OK   volume: {current} listings (floor check only — insufficient history)"


def check_parser_errors(data_dir: Path) -> tuple[bool, str]:
    """Fail if parser_errors.log has non-comment content and was recently written."""
    path = data_dir / "parser_errors.log"
    if not path.exists():
        return True, "OK   parser_errors: file absent (clean)"

    content = path.read_text(encoding="utf-8", errors="replace")
    # Skip comment lines (start with #) and blank lines
    real_lines = [
        line for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not real_lines:
        return True, "OK   parser_errors: file is header-only (clean)"

    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
    if age_h <= 36:
        snippet = "\n".join(real_lines[-20:])
        return False, (
            f"FAIL parser_errors: {len(real_lines)} error line(s) in recent log:\n{snippet}"
        )
    return True, f"OK   parser_errors: errors exist but log is {age_h:.1f}h old (not from this run)"


def check_public_deploy(url: str = "https://pulpo.club/data/ranked.json") -> tuple[bool, str]:
    """Verify the public endpoint returns 200 and valid JSON."""
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=15) as resp:
            status = resp.status
            body = resp.read()
        if status != 200:
            return False, f"FAIL deploy: {url} returned HTTP {status}"
        data = json.loads(body)
        if not isinstance(data, list) or len(data) == 0:
            return False, "FAIL deploy: response is not a non-empty JSON array"
        return True, f"OK   deploy: {url} returned {len(data)} listings"
    except Exception as e:
        return False, f"FAIL deploy: {url} unreachable — {e}"


# ── v2 checks: source-level health from source_health_history.jsonl ─────

# How many consecutive red runs trigger a per-source alert.
SOURCE_CONSECUTIVE_RED_THRESHOLD = 2

# Latency regression ratio: today's duration_s vs 7-day median.
# 3.0 = "today's run took 3× longer than the recent median" — almost always
# a DOM change, anti-bot kicking in, or proxy slowness. Anything below 2× is
# noise; we don't want to alert on every blip.
LATENCY_REGRESSION_RATIO = 3.0
LATENCY_MIN_SAMPLES      = 3      # need at least 3 historical samples to compare
LATENCY_MIN_DURATION_S   = 5.0    # don't alert on <5s baselines (too jittery)


def _read_source_history(data_dir: Path) -> list[dict]:
    """Read all rows from source_health_history.jsonl. Empty list if missing."""
    path = data_dir / "source_health_history.jsonl"
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def check_source_consecutive_red(data_dir: Path) -> tuple[bool, str]:
    """Alert if any source has been red for SOURCE_CONSECUTIVE_RED_THRESHOLD+ runs.

    'Red' is the status string the run.py telemetry writes — set when a
    source either errored or returned zero listings. A single red run is
    noise; two in a row is a signal worth chasing.
    """
    rows = _read_source_history(data_dir)
    if not rows:
        return True, "OK   source_health: no history yet (skipping consecutive-red check)"

    # Group rows by source, sorted by ts descending.
    by_source: dict[str, list[dict]] = {}
    for r in rows:
        by_source.setdefault(r.get("source", "?"), []).append(r)
    for src in by_source:
        by_source[src].sort(key=lambda r: r.get("ts") or "", reverse=True)

    streaks: list[str] = []
    for src, entries in sorted(by_source.items()):
        recent = entries[:SOURCE_CONSECUTIVE_RED_THRESHOLD]
        if len(recent) < SOURCE_CONSECUTIVE_RED_THRESHOLD:
            continue
        if all(r.get("status") == "red" for r in recent):
            err_classes = sorted({(r.get("error_class") or "ZeroRecords") for r in recent})
            streaks.append(f"{src} ({SOURCE_CONSECUTIVE_RED_THRESHOLD}× red, "
                           f"errors={','.join(err_classes)})")

    if streaks:
        return False, ("FAIL source_health: consecutive-red streaks detected — "
                       + "; ".join(streaks))
    return True, f"OK   source_health: no source red ≥{SOURCE_CONSECUTIVE_RED_THRESHOLD}× in a row"


def check_source_latency_regression(data_dir: Path) -> tuple[bool, str]:
    """Alert if any source's latest duration_s is >LATENCY_REGRESSION_RATIO×
    its rolling median. Catches DOM changes / anti-bot before they go red."""
    rows = _read_source_history(data_dir)
    if not rows:
        return True, "OK   latency: no history yet (skipping regression check)"

    by_source: dict[str, list[dict]] = {}
    for r in rows:
        by_source.setdefault(r.get("source", "?"), []).append(r)

    regressions: list[str] = []
    for src, entries in sorted(by_source.items()):
        entries.sort(key=lambda r: r.get("ts") or "")
        if len(entries) < LATENCY_MIN_SAMPLES + 1:
            continue
        latest = entries[-1]
        history = entries[-(LATENCY_MIN_SAMPLES * 5):-1]  # last ~15 entries excl. today
        durations = [float(r.get("duration_s") or 0) for r in history if r.get("duration_s")]
        if len(durations) < LATENCY_MIN_SAMPLES:
            continue
        median = statistics.median(durations)
        latest_d = float(latest.get("duration_s") or 0)
        if median < LATENCY_MIN_DURATION_S:
            continue   # baseline too small — ratios are noisy
        if latest_d / median > LATENCY_REGRESSION_RATIO:
            regressions.append(f"{src}: {latest_d:.1f}s vs median {median:.1f}s "
                               f"({latest_d/median:.1f}×)")

    if regressions:
        return False, "FAIL latency: regressions detected — " + "; ".join(regressions)
    return True, "OK   latency: no source >3× rolling median"


def run(data_dir: Path | None = None, skip_deploy: bool = False) -> list[str]:
    """Run all checks. Returns list of result strings; any starting with 'FAIL' is a failure."""
    if data_dir is None:
        data_dir = REPO / "web" / "data"

    results = []
    results.append(check_freshness(data_dir)[1])
    results.append(check_volume(data_dir)[1])
    results.append(check_parser_errors(data_dir)[1])
    results.append(check_source_consecutive_red(data_dir)[1])
    results.append(check_source_latency_regression(data_dir)[1])
    if not skip_deploy:
        results.append(check_public_deploy()[1])
    return results


def main() -> int:
    skip_deploy = "--skip-deploy" in sys.argv
    results = run(skip_deploy=skip_deploy)
    failures = [r for r in results if r.startswith("FAIL")]

    for r in results:
        print(r)

    if failures:
        print(f"\nWATCHDOG FAILED: {len(failures)} check(s) failed")
        return 1

    print("\nWATCHDOG OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
