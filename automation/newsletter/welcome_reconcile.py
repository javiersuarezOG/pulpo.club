"""Pulpo Pro Welcome — reconciliation cron.

Catches Pro users who paid but never received the welcome email. Runs
hourly via `.github/workflows/pulpo-welcome-reconcile.yml`.

Why this exists:
  • The Stripe webhook + Clerk user.created webhook are best-effort.
    Network blips, GH Actions outages, Vercel cold-start timeouts,
    Resend 5xx — all can cause a welcome to silently fail. Without
    a backstop, the user gets nothing and we don't find out.
  • PostHog event-based retry was the obvious design, but recipient_hash
    is one-way (sha256 truncated) so a `newsletter.welcome_failed`
    event can't tell us which email to retry. Clerk is the only
    bidirectional store: query for "Pro users without the welcome
    stamp" → reconstruct the email → dispatch.

Eligibility filter (all must be true):
  • publicMetadata.plan == "pro"
  • publicMetadata.welcome_newsletter_sent_at is null/empty
  • created_at is within [now - max_age_days, now - min_age_hours]

The min_age_hours grace window prevents racing the regular dispatch
paths — a user who just paid 5 minutes ago is probably still in
flight through Path A/B/C. We wait 1h before considering them an
orphan.

The max_age_days cutoff (7 days) avoids welcoming people whose
"first 10" framing has gone stale — they've already seen weekly
digests, the welcome would feel anachronistic.

Per-run cap of 20 keeps Resend rate-limit headroom comfortable and
gives the cron a clear time budget (~60s for 20 sends at <3s each).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .subscribers import CLERK_API_BASE, _parse_clerk_user
from .welcome_dispatch import dispatch_welcome


# Public defaults — match the rationale in the module docstring.
DEFAULT_MIN_AGE_HOURS = 1
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_MAX_USERS = 20
CLERK_PAGE_SIZE = 200


@dataclass
class ReconcileResult:
    """Per-run summary surfaced to logs + PostHog."""
    found: int = 0       # Pro-no-welcome users discovered by the query
    sent: int = 0        # successful dispatches (Resend 2xx + Clerk stamp)
    skipped: int = 0     # filtered out by dispatcher (already_sent, ranked_missing, etc.)
    failed: int = 0      # dispatcher returned status="failed"
    dry_run: bool = False
    elapsed_ms: int = 0


def _capture(event: str, props: dict) -> None:
    """PostHog capture — silent no-op if creds missing. Mirror of the
    shape used elsewhere in automation/newsletter."""
    try:
        from automation import posthog_client                            # noqa: PLC0415
        posthog_client.capture(event, props)
    except Exception:                                                    # noqa: BLE001
        pass


def fetch_eligible_pros(
    *,
    secret_key: Optional[str] = None,
    now: Optional[datetime] = None,
    min_age_hours: int = DEFAULT_MIN_AGE_HOURS,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    limit: int = DEFAULT_MAX_USERS,
    get_override: Any = None,
) -> list:
    """Return Pro Clerk users eligible for welcome reconciliation.

    Uses Clerk's /v1/users endpoint with `created_at_after_epoch_ms` +
    `created_at_before_epoch_ms` to keep the scan tight. Without those
    filters we'd page through every Pro user on every cron tick.

    `get_override` is the test seam: pass a stub that takes (url,
    headers=, params=) and returns the parsed JSON. Used by the
    test suite to feed deterministic Clerk payloads without an httpx
    dependency.
    """
    secret_key = secret_key or os.environ.get("CLERK_SECRET_KEY", "")
    if not secret_key:
        return []
    if now is None:
        now = datetime.now(timezone.utc)

    # Clerk wants epoch ms. The created_at window:
    #   after  = now - max_age_days   (oldest eligible user)
    #   before = now - min_age_hours  (newest eligible — grace window
    #                                  so we don't race the live paths)
    after_ms = int((now - timedelta(days=max_age_days)).timestamp() * 1000)
    before_ms = int((now - timedelta(hours=min_age_hours)).timestamp() * 1000)

    headers = {"Authorization": f"Bearer {secret_key}"}

    def _default_getter(url, headers=None, params=None):
        import httpx                                                     # noqa: PLC0415
        r = httpx.get(url, headers=headers, params=params, timeout=20.0)
        r.raise_for_status()
        return r.json()

    getter = get_override or _default_getter
    eligible: list = []
    offset = 0
    while True:
        params = {
            "limit": CLERK_PAGE_SIZE,
            "offset": offset,
            # Clerk's filter is INCLUSIVE on both sides. The grace
            # window enforces the "wait 1h" rule from the docstring.
            "created_at_after_epoch_ms": after_ms,
            "created_at_before_epoch_ms": before_ms,
            # Order ascending so we send to the OLDEST orphans first.
            # If we hit `limit` early, the next cron tick picks up
            # where we left off.
            "order_by": "+created_at",
        }
        payload = getter(f"{CLERK_API_BASE}/users", headers=headers, params=params)
        rows = payload if isinstance(payload, list) else (
            payload.get("data") if isinstance(payload, dict) else None
        )
        if not isinstance(rows, list) or not rows:
            break
        for u in rows:
            user = _parse_clerk_user(u)
            if user is None:
                continue
            if user.plan != "pro":
                continue
            if user.welcome_sent_at:
                continue
            eligible.append(user)
            if len(eligible) >= limit:
                return eligible
        if len(rows) < CLERK_PAGE_SIZE:
            break
        offset += CLERK_PAGE_SIZE
    return eligible


def run_reconcile(
    *,
    dry_run: bool = True,
    max_users: int = DEFAULT_MAX_USERS,
    ranked_path: str = "web/data/ranked.json",
    secret_key: Optional[str] = None,
    now: Optional[datetime] = None,
    get_override: Any = None,
) -> ReconcileResult:
    """Run one reconciliation tick.

    Returns a ReconcileResult summary. Per-user dispatch failures
    DON'T raise — we want the cron to keep going even if one user's
    Clerk lookup or Resend send hits a transient error. The
    dispatcher's own telemetry surfaces the per-user failures.
    """
    import time
    t0 = time.monotonic()

    users = fetch_eligible_pros(
        secret_key=secret_key,
        now=now,
        limit=max_users,
        get_override=get_override,
    )
    result = ReconcileResult(found=len(users), dry_run=dry_run)
    print(f"[reconcile] found={len(users)} dry_run={dry_run} max={max_users}", flush=True)

    for user in users:
        if dry_run:
            print(f"[reconcile] DRY-RUN would dispatch user={user.id} email_hash={user.email[:3]}***", flush=True)
            result.skipped += 1
            continue
        try:
            dispatch_result = dispatch_welcome(
                email=user.email,
                source="reconcile_cron",
                ranked_path=ranked_path,
                # Never force from the reconcile path — if the stamp
                # is already set we genuinely want to skip.
                force=False,
            )
        except Exception as exc:                                          # noqa: BLE001
            print(f"[reconcile] user={user.id} dispatch_threw: {exc}", file=sys.stderr, flush=True)
            result.failed += 1
            _capture("newsletter.welcome_reconcile_threw", {
                "clerk_user_id": user.id,
                "error": str(exc)[:200],
            })
            continue
        if dispatch_result.status == "sent":
            result.sent += 1
        elif dispatch_result.status == "skipped":
            result.skipped += 1
        else:  # "failed"
            result.failed += 1
        print(
            f"[reconcile] user={user.id} status={dispatch_result.status} "
            f"reason={dispatch_result.reason or '-'} dry_run={dispatch_result.dry_run}",
            flush=True,
        )

    result.elapsed_ms = int((time.monotonic() - t0) * 1000)
    _capture("newsletter.welcome_reconcile_completed", {
        "found": result.found,
        "sent": result.sent,
        "skipped": result.skipped,
        "failed": result.failed,
        "dry_run": result.dry_run,
        "elapsed_ms": result.elapsed_ms,
        "max_users": max_users,
    })
    print(
        f"[reconcile] done found={result.found} sent={result.sent} "
        f"skipped={result.skipped} failed={result.failed} "
        f"elapsed={result.elapsed_ms}ms",
        flush=True,
    )
    return result


def main() -> int:
    """CLI entrypoint for the GH Actions cron + manual runs.

    Exit codes:
      0 — clean run (sent + skipped only, or dry-run)
      1 — at least one dispatch returned status="failed"
      2 — pre-flight failure (no Clerk secret, etc.)
    """
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument(
        "--send-mode",
        choices=("no", "yes"),
        default="no",
        help="`no` (default) = dry-run, log eligible users without dispatching. "
             "`yes` = live; calls dispatch_welcome for each eligible user.",
    )
    p.add_argument(
        "--max-users",
        type=int,
        default=DEFAULT_MAX_USERS,
        help=f"Cap per run. Default {DEFAULT_MAX_USERS}. Higher values risk "
             f"Resend rate limits + GH Actions timeout.",
    )
    p.add_argument(
        "--ranked",
        default="web/data/ranked.json",
        help="Path to ranked.json. The dispatcher reads this for the picks.",
    )
    args = p.parse_args()

    if not os.environ.get("CLERK_SECRET_KEY"):
        print("[reconcile] CLERK_SECRET_KEY not set — cannot enumerate users", file=sys.stderr)
        return 2

    result = run_reconcile(
        dry_run=(args.send_mode != "yes"),
        max_users=args.max_users,
        ranked_path=args.ranked,
    )
    return 1 if result.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
