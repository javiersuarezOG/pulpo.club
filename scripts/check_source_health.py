#!/usr/bin/env python3
"""Pre-canary source-health Slack alert.

Reads the working-tree ``web/data/source_health_history.jsonl`` (NOT
the committed ``main`` copy), dedupes by ``(source, ts)`` via the
watchdog's existing logic, and posts a single Slack message naming
any source whose latest row is ``status="red"``.

Why "pre-canary"
----------------
This script runs INSIDE the nightly workflow immediately after the
pipeline step, BEFORE the hero / count / per-type / data-quality
canaries. The canaries gate the data commit; when they fail, the
freshest source-health rows never reach ``main``. The previously-
scheduled watchdog reading ``main`` is therefore blind to red rows
from THIS run during exactly the failure mode that matters most
(silent placeholder-storms, fresh 403s on a previously-healthy
source). Reading the working tree closes the blind spot.

Best-effort
-----------
- Always exits 0. Slack failures must not block the deploy path.
- Skips silently when ``SLACK_WEBHOOK_URL`` is unset (local dev,
  test harnesses).
- Stale rows (> 36 hours old) are ignored so a since-recovered
  source doesn't trip the alert on the next nightly.

Usage
-----
::

    SLACK_WEBHOOK_URL=...  python3 scripts/check_source_health.py \\
        --data-dir web/data \\
        --run-url https://github.com/.../actions/runs/12345
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Reuse the watchdog's dedup logic so the pre-canary alert + the
# scheduled watchdog speak the same "what is the latest state of
# source X" schema. Any future change to the (source, ts) collapse
# rule lives in one place.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation.watchdog import _read_source_history  # noqa: E402
from pulpo.source_health import (  # noqa: E402
    SourceBrownoutResult,
    compute_brownout_states,
)


# Stale-row cutoff. A red row older than this is silently ignored — it
# may belong to a historical incident the scheduled watchdog already
# alerted on, and re-paging on it here would be noise. 36 h covers the
# nightly cadence plus runtime jitter.
STALE_CUTOFF_HOURS = 36.0


def latest_row_per_source(rows: list[dict]) -> dict[str, dict]:
    """Return the latest (by ts) row per source. Pure; tests pin behaviour."""
    by_src: dict[str, dict] = {}
    for r in rows:
        src = r.get("source") or "?"
        cur_ts = r.get("ts") or ""
        if src not in by_src or cur_ts > (by_src[src].get("ts") or ""):
            by_src[src] = r
    return by_src


def fresh_red_rows(
    latest_by_source: dict[str, dict],
    *,
    now: Optional[datetime] = None,
    stale_cutoff_hours: float = STALE_CUTOFF_HOURS,
) -> list[dict]:
    """Filter a `latest_row_per_source` map down to fresh red rows.

    A row is ``fresh`` if its ``ts`` parses and is within
    ``stale_cutoff_hours`` of ``now``. ``red`` is the run.py-emitted
    status string. Rows with unparsable timestamps are skipped silently
    so a malformed file never fires the alert.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=stale_cutoff_hours)
    out: list[dict] = []
    for _src, r in latest_by_source.items():
        ts_str = r.get("ts") or ""
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts < cutoff:
            continue
        if r.get("status") == "red":
            out.append(r)
    return out


def build_message(red_rows: list[dict], *, run_url: Optional[str]) -> str:
    """Pure: build the Slack message body from the red-row set."""
    n = len(red_rows)
    lines: list[str] = []
    lines.append(f"*Pulpo nightly: {n} source(s) red (pre-canary)*")
    for r in sorted(red_rows, key=lambda x: x.get("source", "")):
        src = r.get("source", "?")
        # `scraped` carries the post-NR-C count; fall back to legacy `count`.
        scraped = r.get("scraped", r.get("count", 0))
        kept = r.get("kept")
        kept_str = str(kept) if kept is not None else "n/a"
        err = r.get("error_class") or "ZeroRecords"
        fid = r.get("failure_id") or "—"
        lines.append(
            f"• `{src}` scraped={scraped} kept={kept_str} err={err} failure_id={fid}"
        )
    if run_url:
        lines.append(f"<{run_url}|Open Actions run>")
    return "\n".join(lines)


def _post_slack(webhook_url: str, text: str) -> None:
    """Best-effort Slack POST. Errors print to stderr and do not raise."""
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except (urllib.error.URLError, TimeoutError) as e:
        # We never block the nightly on alerting. The next scheduled
        # watchdog will still see the row once it commits.
        print(f"[source-health] Slack POST failed: {e}", file=sys.stderr)


def brownout_alert_lines(results: list[SourceBrownoutResult]) -> list[str]:
    """One Slack line per non-green source. PRD P1-9 — count, median,
    ratio, latest failure id all live in the message body so oncall
    can act without opening the dashboard."""
    out: list[str] = []
    for r in sorted(results, key=lambda x: x.source):
        if r.status in {"green", "skipped", "unknown"}:
            continue
        median_str = (
            f"{r.rolling_median_7:.0f}" if r.rolling_median_7 is not None else "?"
        )
        ratio_str = f"{(r.ratio or 0) * 100:.0f}%" if r.ratio is not None else "?"
        suffix_parts: list[str] = []
        if r.failure_id:
            suffix_parts.append(f"failure_id={r.failure_id}")
        if r.error_class:
            suffix_parts.append(f"err={r.error_class}")
        suffix = (" " + " ".join(suffix_parts)) if suffix_parts else ""
        out.append(
            f"• `{r.source}` {r.status} "
            f"count={r.count} median={median_str} ratio={ratio_str}"
            f"{suffix}"
        )
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-canary source-health Slack alert.")
    parser.add_argument(
        "--data-dir",
        default="web/data",
        help="Directory containing source_health_history.jsonl.",
    )
    parser.add_argument(
        "--run-url",
        default=None,
        help="GitHub Actions run URL embedded in the alert body.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the alert body but do not POST.",
    )
    args = parser.parse_args(argv)

    rows = _read_source_history(Path(args.data_dir))
    latest = latest_row_per_source(rows)
    red = fresh_red_rows(latest)

    # PRD P1-9 — extend the alert to brownout states. Existing red-row
    # behaviour is preserved; degraded/red/recovering sources land as
    # additional lines in the same Slack message.
    brownouts = compute_brownout_states(rows)
    brownout_lines = brownout_alert_lines(brownouts)

    if not red and not brownout_lines:
        print("[source-health] OK — no red sources in current run.")
        return 0

    text_parts: list[str] = []
    if red:
        text_parts.append(build_message(red, run_url=args.run_url))
    if brownout_lines:
        text_parts.append(
            "*Pulpo nightly: source brownouts*\n" + "\n".join(brownout_lines)
        )
        if args.run_url:
            text_parts.append(f"<{args.run_url}|Open Actions run>")
    text = "\n".join(text_parts)
    print(text)

    if args.dry_run:
        print("[source-health] --dry-run: not posting.")
        return 0

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        print("[source-health] SLACK_WEBHOOK_URL unset — skipping POST.")
        return 0

    _post_slack(webhook_url, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
