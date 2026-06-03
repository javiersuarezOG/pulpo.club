#!/usr/bin/env python3
"""End-of-nightly "tell the story" summary.

Reads the runner's own telemetry — produced by the pipeline + the
existing source_health writers + the commit/deploy step outputs passed
through env vars — and emits a single, self-contained summary that
answers:

  1. Did the pipeline produce a ranked.json? How many listings?
  2. How did each source do (scraped / kept / status / error)?
  3. Did the data PR commit + did Vercel deploy?
  4. What date will pulpo.club show after this run?
  5. Where to find the artifacts if something went wrong?

Runs as the FINAL ``if: always()`` step in pulpo-nightly.yml so the
operator reading the bottom of the job log gets the whole story
without having to grep 70 minutes of pipeline stdout + 3 JSONL files.

The same content is written to ``web/data/nightly_summary.md`` so it
survives the runner via the diagnostics artifact (PR #602).

Inputs (filesystem)
-------------------
  web/data/run_history.json          — per_source_raw + source_status
  web/data/source_health_history.jsonl — crawl + post_validation rows
                                         (deduped via watchdog logic)
  web/data/last_updated.json         — pipeline-produced timestamp
  web/data/ranked.json               — total listing count (counted lazily)

Inputs (env, passed by the workflow step)
-----------------------------------------
  NIGHTLY_RUN_URL    — GitHub Actions run URL (linkable in the summary)
  NIGHTLY_COMMITTED  — "true" | "false" from steps.commit.outputs.committed
  NIGHTLY_DEPLOY_OUTCOME — "success" | "failure" | "skipped" from
                            steps.deploy.outcome

Always exits 0 — observability never blocks the pipeline.

Usage
-----
::

    NIGHTLY_RUN_URL=https://github.com/.../runs/12345 \\
    NIGHTLY_COMMITTED=true \\
    NIGHTLY_DEPLOY_OUTCOME=success \\
    python3 scripts/nightly_summary.py --data-dir web/data
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Reuse the watchdog's (source, ts) dedup so the post_validation row's
# stricter status overrides the crawl-phase row when both are present.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation.watchdog import _read_source_history  # noqa: E402


# Status order, worst → best, for the per-source mark column.
_STATUS_MARK = {"green": "✓", "red": "✗", "skipped": "·"}
PROD_HEALTH_URL = "https://pulpo.club/api/nightly/health"


def _read_json(path: Path) -> Optional[object]:
    """Read a JSON file, tolerating missing / malformed inputs."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def latest_row_per_source(rows: list[dict]) -> dict[str, dict]:
    """Return the most recent row per source by ``ts``. Pure for tests."""
    by_src: dict[str, dict] = {}
    for r in rows:
        src = r.get("source") or "?"
        if src not in by_src or (r.get("ts") or "") > (by_src[src].get("ts") or ""):
            by_src[src] = r
    return by_src


def count_listings(ranked_path: Path) -> Optional[int]:
    """Return the count of listings in ranked.json without holding the full
    payload in memory longer than needed. None if the file is unreadable —
    a canary-blocked nightly may still leave ranked.json on the runner."""
    obj = _read_json(ranked_path)
    if isinstance(obj, list):
        return len(obj)
    return None


def fetch_remote_health(url: str = PROD_HEALTH_URL, timeout: float = 8.0) -> tuple[Optional[dict], Optional[str]]:
    """Fetch production nightly health for local checkout summaries."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:  # nosec B310 - fixed production health URL
            obj = json.loads(res.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return None, str(exc)
    return (obj if isinstance(obj, dict) else None), None


def _sort_sources(rows_by_src: dict[str, dict]) -> list[tuple[str, dict]]:
    """Order red sources first (most actionable), then green by descending
    kept count (biggest contributors first). Skipped goes last."""
    def keyfn(item: tuple[str, dict]) -> tuple[int, float, str]:
        src, row = item
        status = row.get("status", "?")
        # Red first, then green by -kept, then skipped, then unknown.
        order = {"red": 0, "green": 1, "skipped": 2}.get(status, 3)
        kept = row.get("kept", row.get("count", 0)) or 0
        return (order, -float(kept), src)
    return sorted(rows_by_src.items(), key=keyfn)


def format_source_line(src: str, row: dict) -> str:
    """One line per source for the PER-SOURCE HEALTH block."""
    status = row.get("status", "?")
    mark = _STATUS_MARK.get(status, "?")
    scraped = row.get("scraped", row.get("count", 0))
    kept = row.get("kept")
    kept_str = f"kept={kept}" if kept is not None else "kept=n/a"
    extras: list[str] = []
    if row.get("error_class"):
        extras.append(f"error={row['error_class']}")
    if row.get("failure_id"):
        extras.append(f"failure_id={row['failure_id']}")
    extras_str = "  " + "  ".join(extras) if extras else ""
    return f"  {mark} {src:<18} scraped={scraped:<5} {kept_str:<11} {status}{extras_str}"


def format_summary(
    *,
    listing_count: Optional[int],
    pipeline_ts: Optional[str],
    rows_by_src: dict[str, dict],
    committed: Optional[str],
    deploy_outcome: Optional[str],
    run_url: Optional[str],
    today_iso: str,
    mode: str = "workflow",
    remote_health: Optional[dict] = None,
    remote_health_error: Optional[str] = None,
) -> str:
    """Pure: assemble the final summary block from the resolved inputs."""
    lines: list[str] = []
    bar = "=" * 70
    lines.append(bar)
    lines.append(f"NIGHTLY SUMMARY — {today_iso}")
    lines.append(f"Mode: {mode}")
    if run_url:
        lines.append(f"Run: {run_url}")
    lines.append(bar)
    lines.append("")

    # Pipeline output
    lines.append("PIPELINE OUTPUT")
    if listing_count is not None:
        lines.append(f"  Generated ranked.json with {listing_count} listings.")
    else:
        lines.append("  ranked.json not found on the runner.")
    if pipeline_ts:
        lines.append(f"  Pipeline timestamp: {pipeline_ts}")
    lines.append("")

    # Per-source health
    lines.append("PER-SOURCE HEALTH (collapsed crawl + post_validation)")
    if rows_by_src:
        for src, row in _sort_sources(rows_by_src):
            lines.append(format_source_line(src, row))
    else:
        lines.append("  (no source rows captured — telemetry write failed?)")
    lines.append("")

    # Commit + deploy
    if mode == "local":
        lines.append("PRODUCTION HEALTH")
        if remote_health:
            prod_ts = remote_health.get("last_updated") or remote_health.get("last_data_commit_at")
            prod_count = remote_health.get("listing_count") or remote_health.get("total_listings")
            lines.append(f"  Health endpoint: ✓ {PROD_HEALTH_URL}")
            if prod_ts:
                lines.append(f"  pulpo.club currently reports: {prod_ts}")
            if prod_count is not None:
                lines.append(f"  pulpo.club listing count: {prod_count}")
        else:
            lines.append(f"  Health endpoint: ? unavailable ({remote_health_error or 'unknown error'})")
        lines.append("")
    else:
        lines.append("POST-CANARY OUTCOME")
        if committed == "true":
            lines.append("  Commit:  ✓ COMMITTED")
        elif committed == "false":
            lines.append("  Commit:  ✗ NO COMMIT  (commit step ran but found nothing to push)")
        else:
            lines.append("  Commit:  ✗ NOT REACHED  (an earlier step failed)")

        if deploy_outcome == "success":
            lines.append("  Deploy:  ✓ DEPLOYED to Vercel")
        elif deploy_outcome == "failure":
            lines.append("  Deploy:  ✗ DEPLOY FAILED")
        elif deploy_outcome == "skipped":
            lines.append("  Deploy:  ✗ SKIPPED  (commit didn't run, deploy gated on it)")
        else:
            lines.append("  Deploy:  ? UNKNOWN  (step not reached)")
        lines.append("")

    # Site state
    lines.append("SITE STATE")
    if mode == "local":
        if remote_health:
            prod_ts = remote_health.get("last_updated") or remote_health.get("last_data_commit_at")
            if prod_ts:
                lines.append(f"  pulpo.club is serving data timestamp: {prod_ts}")
            else:
                lines.append("  pulpo.club health is reachable, but no data timestamp was present.")
        else:
            lines.append("  pulpo.club state unknown — production health endpoint was unavailable.")
    else:
        if committed == "true" and deploy_outcome == "success":
            if pipeline_ts:
                lines.append(f"  pulpo.club will show: {pipeline_ts}")
            else:
                lines.append("  pulpo.club will show: today's pipeline output (timestamp unavailable)")
        else:
            lines.append("  pulpo.club will NOT refresh this run — still showing the last")
            lines.append("  successfully-deployed nightly.")
    lines.append("")
    lines.append(bar)

    summary = "\n".join(lines) + "\n"
    if mode == "local":
        return "\n".join(f"[mode=local] {line}" if line else "[mode=local]" for line in summary.splitlines()) + "\n"
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="End-of-nightly story summary.")
    parser.add_argument(
        "--data-dir",
        default="web/data",
        help="Directory containing the run's telemetry files.",
    )
    parser.add_argument(
        "--write-md",
        action="store_true",
        help="Also write the summary to <data-dir>/nightly_summary.md so it "
             "lands in the diagnostics artifact.",
    )
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)

    # Pipeline output
    listing_count = count_listings(data_dir / "ranked.json")
    last_updated = _read_json(data_dir / "last_updated.json") or {}
    pipeline_ts = last_updated.get("last_updated") if isinstance(last_updated, dict) else None

    # Per-source rows from the deduped source_health JSONL
    rows = _read_source_history(data_dir)
    rows_by_src = latest_row_per_source(rows)

    # Workflow-passed env signals. If absent, this is a local checkout
    # invocation; read production health rather than inventing a failed
    # commit/deploy story from missing workflow-only env vars.
    committed = os.environ.get("NIGHTLY_COMMITTED")
    deploy_outcome = os.environ.get("NIGHTLY_DEPLOY_OUTCOME")
    run_url = os.environ.get("NIGHTLY_RUN_URL")
    mode = "workflow" if run_url else "local"
    remote_health = None
    remote_health_error = None
    if mode == "local":
        remote_health, remote_health_error = fetch_remote_health()

    # Use today's UTC date as a label so the summary header reads cleanly
    # even when the pipeline timestamp is missing.
    from datetime import datetime, timezone as _tz
    today_iso = datetime.now(_tz.utc).date().isoformat()

    summary = format_summary(
        listing_count=listing_count,
        pipeline_ts=pipeline_ts,
        rows_by_src=rows_by_src,
        committed=committed,
        deploy_outcome=deploy_outcome,
        run_url=run_url,
        today_iso=today_iso,
        mode=mode,
        remote_health=remote_health,
        remote_health_error=remote_health_error,
    )

    # Always print to stdout — this is the operator-facing surface.
    print(summary)

    # And persist to the diagnostics artifact path when asked.
    if args.write_md:
        out_path = data_dir / "nightly_summary.md"
        try:
            out_path.write_text(summary, encoding="utf-8")
            print(f"[nightly_summary] wrote {out_path}")
        except OSError as e:
            # Observability never blocks. Log + carry on.
            print(f"[nightly_summary] could not write {out_path}: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
