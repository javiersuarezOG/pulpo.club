#!/usr/bin/env python3
"""
Geo-enrichment coverage canary — alert (never block).

This is the positive heartbeat for the GEO pass. A green unit test only
proves the fetch code works when invoked; it does not prove the pass still
runs, that its cache still persists, or that a provider hasn't quietly
started refusing us. Those are exactly the failure modes that stay
invisible because the site keeps looking fine (the 2026-05-27 Resend
outage was silent for 7 days for the same reason).

Six things it watches, each mapping to a way this can rot:

  sidecar missing   the pass never ran, or its git-add line was dropped
  stale             assembled_at is old -> the pass stopped running
  coverage below    a provider is not resolving for enough listings
  coverage drop     a provider regressed sharply vs the previous run
  provider disabled the run's short-circuit fired (auth/quota/ban)
  cache shrank      geo_cells.json is not persisting, so every night
                    re-pays every external call -- the single most
                    expensive silent failure available here

Per the never-silent-freeze rule in CLAUDE.md this ALWAYS exits 0 so it
can never block a data commit; --strict is only for proving the guardrail
fires on a known-bad input.

Usage:
    python3 scripts/check_geo_coverage.py --data-dir web/data
    SLACK_WEBHOOK_URL=... python3 scripts/check_geo_coverage.py --run-url "$URL"
    python3 scripts/check_geo_coverage.py --strict   # guardrail self-test
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_SIDECAR = "geo_enrichment.json"
_CELLS = "geo_cells.json"
_HISTORY = "geo_enrichment_history.jsonl"

# A provider counts as "resolved" for a listing at either ok or na: "no
# modeled river within this cell" is a real answer, not a coverage gap.
_RESOLVED = ("ok", "na")

_DEFAULT_COVERAGE_THRESHOLD = 90.0
_DEFAULT_MAX_DROP_PCT = 20.0
_DEFAULT_MAX_AGE_HOURS = 48.0
# Below this fraction of the previous run's cell count, the cache is not
# surviving between runs and we are re-paying for everything.
_CACHE_SHRINK_RATIO = 0.5


def _read_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _read_history(path: Path, keep: int = 2) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-keep:]:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except Exception:  # noqa: BLE001
            continue
    return out


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def audit(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    """Measure the current state of the geo sidecar, cache and history."""
    now = now or datetime.now(timezone.utc)
    sidecar = _read_json(data_dir / _SIDECAR)
    cells = _read_json(data_dir / _CELLS)
    history = _read_history(data_dir / _HISTORY)

    report: dict[str, Any] = {
        "sidecar_present": isinstance(sidecar, dict),
        "records": 0,
        "coverage": {},
        "newest_assembled_at": None,
        "age_hours": None,
        "cells_cached": len(cells) if isinstance(cells, dict) else None,
        "prev_cells_cached": None,
        "last_run": history[-1] if history else None,
        "prev_run": history[-2] if len(history) > 1 else None,
    }
    if not isinstance(sidecar, dict):
        return report

    report["records"] = len(sidecar)
    resolved: dict[str, int] = {}
    seen: dict[str, int] = {}
    newest: Optional[datetime] = None

    for rec in sidecar.values():
        if not isinstance(rec, dict):
            continue
        ts = _parse_iso(rec.get("assembled_at"))
        if ts and (newest is None or ts > newest):
            newest = ts
        for name, info in (rec.get("providers") or {}).items():
            seen[name] = seen.get(name, 0) + 1
            if isinstance(info, dict) and info.get("status") in _RESOLVED:
                resolved[name] = resolved.get(name, 0) + 1

    report["coverage"] = {
        name: round(100.0 * resolved.get(name, 0) / count, 1)
        for name, count in sorted(seen.items())
    }
    if newest:
        report["newest_assembled_at"] = newest.isoformat()
        report["age_hours"] = round((now - newest).total_seconds() / 3600.0, 1)

    prev = report["prev_run"]
    if isinstance(prev, dict):
        report["prev_cells_cached"] = prev.get("cells_cached")
    return report


def failing(report: dict,
            *,
            coverage_threshold: float = _DEFAULT_COVERAGE_THRESHOLD,
            max_drop_pct: float = _DEFAULT_MAX_DROP_PCT,
            max_age_hours: float = _DEFAULT_MAX_AGE_HOURS) -> list[str]:
    """Human-readable failure lines (empty list = healthy)."""
    out: list[str] = []

    if not report["sidecar_present"]:
        return [f"`{_SIDECAR}` is missing — the geo pass has never produced "
                f"committed output. Check the git-add lines in pulpo-nightly.yml."]
    if report["records"] == 0:
        return [f"`{_SIDECAR}` has 0 records — the pass ran but enriched nothing."]

    age = report.get("age_hours")
    if age is not None and age > max_age_hours:
        out.append(f"stale: newest record is {age:.0f}h old (limit {max_age_hours:.0f}h) "
                   f"— the geo pass has stopped running or stopped committing.")

    for name, pct in (report.get("coverage") or {}).items():
        if pct < coverage_threshold:
            out.append(f"`{name}` coverage {pct}% of {report['records']} records "
                       f"(threshold {coverage_threshold}%)")

    last, prev = report.get("last_run"), report.get("prev_run")
    if isinstance(last, dict) and isinstance(prev, dict):
        last_cov = last.get("coverage") or {}
        prev_cov = prev.get("coverage") or {}
        for name, prev_pct in prev_cov.items():
            now_pct = last_cov.get(name)
            if not isinstance(now_pct, (int, float)) or not isinstance(prev_pct, (int, float)):
                continue
            drop = (prev_pct - now_pct) * 100.0
            if drop > max_drop_pct:
                out.append(f"`{name}` coverage dropped {drop:.0f} points "
                           f"({prev_pct * 100:.0f}% → {now_pct * 100:.0f}%) since the previous run")

    if isinstance(last, dict):
        disabled = last.get("providers_disabled") or []
        if disabled:
            out.append(f"provider(s) disabled mid-run: {', '.join(disabled)} — "
                       f"auth, quota or a ban tripped the short-circuit.")
        failed = last.get("calls_failed") or 0
        if failed:
            out.append(f"{failed} cell fetch(es) failed in the last run.")

    cells, prev_cells = report.get("cells_cached"), report.get("prev_cells_cached")
    if isinstance(cells, int) and isinstance(prev_cells, int) and prev_cells > 0:
        if cells < prev_cells * _CACHE_SHRINK_RATIO:
            out.append(f"`{_CELLS}` shrank {prev_cells} → {cells} cells. The cache is "
                       f"not persisting between runs, so every night re-pays every "
                       f"external API call. Check its git-add line.")
    return out


def _post_slack(webhook_url: str, text: str) -> None:
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"[geo-coverage] Slack POST failed: {e}", file=sys.stderr)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Geo-enrichment coverage canary (alert, never block).")
    ap.add_argument("--data-dir", default="web/data")
    ap.add_argument("--run-url", default=None)
    ap.add_argument("--coverage-threshold", type=float, default=_DEFAULT_COVERAGE_THRESHOLD)
    ap.add_argument("--max-drop-pct", type=float, default=_DEFAULT_MAX_DROP_PCT)
    ap.add_argument("--max-age-hours", type=float, default=_DEFAULT_MAX_AGE_HOURS)
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on failure (guardrail self-test; the nightly never uses this)")
    args = ap.parse_args(argv)

    report = audit(Path(args.data_dir))
    if report["sidecar_present"]:
        cov = " | ".join(f"{k} {v}%" for k, v in (report["coverage"] or {}).items())
        print(f"[geo-coverage] {report['records']} records | {cov or 'no providers'} "
              f"| {report['cells_cached']} cells | age {report['age_hours']}h")

    problems = failing(
        report,
        coverage_threshold=args.coverage_threshold,
        max_drop_pct=args.max_drop_pct,
        max_age_hours=args.max_age_hours,
    )
    if not problems:
        print("[geo-coverage] OK — geo enrichment fresh, complete and caching ✓")
        return 0

    lines = ["*Pulpo: geo-enrichment coverage problem*"]
    lines.extend("• " + p for p in problems)
    lines.append("Listings keep serving normally — this is a data-completeness "
                 "alert. Re-run `scripts/backfill_geo_enrichment.py` once the "
                 "cause is fixed.")
    if args.run_url:
        lines.append(f"<{args.run_url}|Open Actions run>")
    body = "\n".join(lines)
    print(body)

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if webhook_url:
        _post_slack(webhook_url, body)
    else:
        print("[geo-coverage] SLACK_WEBHOOK_URL unset — skipping POST.")

    # Never block the nightly (CLAUDE.md: alert + backfill, don't freeze).
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
