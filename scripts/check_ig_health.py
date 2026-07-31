#!/usr/bin/env python3
"""check_ig_health.py — the Social Brain's health canary.

A green publisher run proves it posted once; it does NOT prove the loop is
healthy. This canary watches the whole IG loop and Slack-pages on trouble —
never blocking (canaries page, don't block; the never-silent-freeze rule):

  * freshness      — did we post recently? (SUPPRESSED when IG_PAUSED — a
                     paused feed is stale ON PURPOSE, not a fault).
  * insights_flow  — is ig_insights polling recent posts? (Sense half alive).
  * token_expiry   — is the Graph token about to expire?
  * queue_supply   — is there approved, unposted content queued? (else the
                     feed starves; SUPPRESSED when paused).

Every check reads defensively: a missing/garbage file is `unknown`, never a
crash. Exit is ALWAYS 0 — a canary must not red a scheduled workflow. On any
`alert` it Slack-pages (SLACK_WEBHOOK_URL) and fires a PostHog heartbeat
(monitor.ig_health_completed) so the run is observable even when all is well.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

QUEUE = Path("web/data/ig_queue.json")
POST_LOG = Path("web/data/ig_post_log.jsonl")
INSIGHTS = Path("web/data/ig_insights.jsonl")
TOKEN_META = Path("web/data/ig_token_meta.json")

OK, WARN, ALERT, UNKNOWN = "ok", "warn", "alert", "unknown"

# thresholds
FRESHNESS_ALERT_DAYS = 3       # no post in 3 days (while live) → alert
INSIGHTS_STALE_DAYS = 4        # posts maturing but no insights rows → warn
TOKEN_ALERT_DAYS = 7           # token expiring within a week → alert


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _read_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _paused() -> bool:
    return str(os.environ.get("IG_PAUSED", "")).strip() in ("1", "true", "True", "yes")


# ── checks ─────────────────────────────────────────────────────────────

def check_freshness(now, log_path=None, paused=None) -> dict:
    paused = _paused() if paused is None else paused
    rows = [r for r in _read_jsonl(log_path or POST_LOG) if r.get("status") == "posted"]
    last = max((_parse_ts(r.get("ts", "")) for r in rows if _parse_ts(r.get("ts", ""))), default=None)
    if last is None:
        return {"name": "freshness", "status": UNKNOWN, "msg": "no posts in the log yet"}
    age_days = (_now(now) - last).total_seconds() / 86400
    if paused:
        return {"name": "freshness", "status": OK,
                "msg": f"paused; last post {age_days:.1f}d ago (stale on purpose)"}
    status = ALERT if age_days > FRESHNESS_ALERT_DAYS else OK
    return {"name": "freshness", "status": status, "msg": f"last post {age_days:.1f}d ago"}


def check_insights_flow(now, log_path=None, insights_path=None) -> dict:
    posts = [r for r in _read_jsonl(log_path or POST_LOG) if r.get("status") == "posted"]
    if not posts:
        return {"name": "insights_flow", "status": UNKNOWN, "msg": "no posts to measure"}
    rows = _read_jsonl(insights_path or INSIGHTS)
    if not rows:
        return {"name": "insights_flow", "status": WARN, "msg": "no insights rows yet (poller not run?)"}
    last = max((_parse_ts(r.get("polled_at", "")) for r in rows if _parse_ts(r.get("polled_at", ""))), default=None)
    if last is None:
        return {"name": "insights_flow", "status": WARN, "msg": "insights rows have no polled_at"}
    age = (_now(now) - last).total_seconds() / 86400
    status = WARN if age > INSIGHTS_STALE_DAYS else OK
    return {"name": "insights_flow", "status": status, "msg": f"last poll {age:.1f}d ago, {len(rows)} rows"}


def check_token(now, token_path=None) -> dict:
    meta = _read_json(token_path or TOKEN_META)
    if not meta:
        return {"name": "token_expiry", "status": UNKNOWN, "msg": "no token meta on disk"}
    exp = _parse_ts(meta.get("expires_at") or meta.get("expires_at_iso") or "")
    if exp is None:
        return {"name": "token_expiry", "status": UNKNOWN, "msg": "token meta has no expiry"}
    days = (exp - _now(now)).total_seconds() / 86400
    if days <= 0:
        return {"name": "token_expiry", "status": ALERT, "msg": f"token EXPIRED {-days:.1f}d ago"}
    status = ALERT if days < TOKEN_ALERT_DAYS else OK
    return {"name": "token_expiry", "status": status, "msg": f"token expires in {days:.1f}d"}


def check_queue_supply(queue_path=None, paused=None) -> dict:
    paused = _paused() if paused is None else paused
    data = _read_json(queue_path or QUEUE)
    items = (data or {}).get("items", []) if isinstance(data, dict) else []
    approved_unposted = [i for i in items if i.get("approved") and not i.get("posted")]
    n = len(approved_unposted)
    if paused:
        return {"name": "queue_supply", "status": OK, "msg": f"paused; {n} approved queued"}
    status = WARN if n == 0 else OK
    return {"name": "queue_supply", "status": status,
            "msg": f"{n} approved+unposted post(s) queued" + (" — feed will starve" if n == 0 else "")}


def run_checks(now=None, **paths) -> list[dict]:
    now = _now(now)
    return [
        check_freshness(now, paths.get("log_path")),
        check_insights_flow(now, paths.get("log_path"), paths.get("insights_path")),
        check_token(now, paths.get("token_path")),
        check_queue_supply(paths.get("queue_path")),
    ]


def worst(checks: list[dict]) -> str:
    order = {OK: 0, UNKNOWN: 1, WARN: 2, ALERT: 3}
    return max((c["status"] for c in checks), key=lambda s: order.get(s, 0), default=OK)


# ── side effects (page + heartbeat), both soft ─────────────────────────

def slack(text: str, *, dry_run: bool) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if dry_run or not url:
        print(text)
        return
    try:
        req = urllib.request.Request(
            url, data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # never raise from a canary
        print(f"[ig_health] slack post failed (non-fatal): {e}")


def heartbeat(checks: list[dict]) -> None:
    try:
        from automation import posthog_client as ph
        ph.capture("monitor.ig_health_completed",
                   {"worst": worst(checks), **{c["name"]: c["status"] for c in checks}})
    except Exception:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="IG loop health canary (pages, never blocks).")
    ap.add_argument("--dry-run", action="store_true", help="print instead of paging Slack")
    args = ap.parse_args(argv)

    checks = run_checks()
    w = worst(checks)
    lines = [f"{'🔴' if c['status']==ALERT else '🟡' if c['status']==WARN else '⚪' if c['status']==UNKNOWN else '🟢'} "
             f"{c['name']}: {c['msg']}" for c in checks]
    summary = "\n".join(lines)
    print(f"[ig_health] worst={w}\n{summary}")

    if w == ALERT:
        slack(":octopus: *Pulpo IG health* — needs attention:\n" + summary, dry_run=args.dry_run)
    heartbeat(checks)
    return 0  # ALWAYS 0 — a canary never reds the workflow


if __name__ == "__main__":
    sys.exit(main())
