#!/usr/bin/env python3
"""End-to-end newsletter send CLI.

Defaults to dry-run (PULPO_NEWSLETTER_DRY_RUN missing = dry-run ON in send.py).
Use `--only-email javier@suarez.ventures` for the first real send — Issue 01
to yourself, eyeball, then drop the flag for the broader audience.

Pipeline per recipient:
    subscribers.build_recipient_queue
      → build_issue(recipient, ranked_listings, ...)
        → render_html(issue)
          → send_issue(to_email, ...)

PostHog telemetry fires from build_issue (issue_built / commentary_generated)
and from this script (newsletter.send_succeeded / newsletter.send_failed).

Exit codes:
    0  — all recipients sent (or dry-ran) successfully
    1  — at least one failure; check logs / PostHog for the failed bucket
    2  — pre-flight failure (missing ranked.json, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.newsletter import build_issue, render_html                 # noqa: E402
from automation.newsletter.send import is_dry_run, send_issue              # noqa: E402
from automation.newsletter.subscribers import build_recipient_queue        # noqa: E402


def _capture(event: str, props: dict) -> None:
    try:
        from automation import posthog_client                              # noqa: PLC0415
        posthog_client.capture(event, props)
    except Exception:                                                      # noqa: BLE001
        pass


def _subject_for(issue, locale: str) -> str:
    # Editorial subject — variable substitution stays here so a future
    # A/B-test fixture can override per-recipient. The 14-day window is
    # the cadence reader expects ("this fortnight").
    if locale == "es":
        return f"Pulpo · Edición {issue.issue_number:02d} · 10 selecciones esta quincena"
    return f"Pulpo · Issue {issue.issue_number:02d} · 10 picks this fortnight"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ranked", default="web/data/ranked.json")
    p.add_argument("--issue-number", type=int, default=1)
    p.add_argument(
        "--only-email",
        action="append",
        default=None,
        help=(
            "Restrict the send to these addresses (case-insensitive). "
            "Pass multiple times. Used for smoke-testing before broadcast."
        ),
    )
    p.add_argument(
        "--include-unsubscribed",
        action="store_true",
        help="Ignore audience-level unsubscribed flag (FOR DEBUGGING ONLY).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of recipients (after filtering).",
    )
    p.add_argument(
        "--write-html-to",
        default=None,
        help="Optional dir — when set, every rendered issue is also written there.",
    )
    args = p.parse_args()

    ranked_path = Path(args.ranked)
    if not ranked_path.exists():
        print(f"[send] missing ranked.json at {ranked_path}", file=sys.stderr)
        return 2
    with ranked_path.open() as fh:
        ranked = json.load(fh)
    ranked = sorted(ranked, key=lambda x: x.get("rank") or 9_999)

    only = set(args.only_email) if args.only_email else None
    queue = build_recipient_queue(
        only_emails=only,
        include_unsubscribed=args.include_unsubscribed,
    )
    if args.limit:
        queue = queue[: args.limit]

    issue_date = datetime.now(timezone.utc)
    dry = is_dry_run()
    print(
        f"[send] mode={'dry-run' if dry else 'LIVE'} recipients={len(queue)} "
        f"issue={args.issue_number} ranked={len(ranked)}"
    )

    out_dir = Path(args.write_html_to) if args.write_html_to else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    sent = 0
    failed = 0
    t0 = time.monotonic()
    for recipient, email in queue:
        issue = build_issue(
            recipient=recipient,
            ranked_listings=ranked,
            issue_number=args.issue_number,
            issue_date=issue_date,
            history_rows=None,
        )
        html = render_html(issue)
        subject = _subject_for(issue, recipient.locale)

        if out_dir:
            stem = f"{issue.issue_id}-issue{args.issue_number:02d}-{recipient.email_hash[:8]}.html"
            (out_dir / stem).write_text(html)

        result = send_issue(
            to_email=email,
            recipient_hash=recipient.email_hash,
            issue_number=args.issue_number,
            subject=subject,
            html=html,
            tags={
                "issue_number": str(args.issue_number),
                "recipient_hash": recipient.email_hash,
                "cohort": issue.cohort,
                "locale": recipient.locale,
            },
            headers_extra={
                "X-Pulpo-Issue": str(args.issue_number),
                "X-Pulpo-Recipient": recipient.email_hash,
            },
        )

        if result.ok:
            sent += 1
            _capture("newsletter.send_succeeded", {
                "issue_id": issue.issue_id,
                "issue_number": args.issue_number,
                "recipient_hash": recipient.email_hash,
                "cohort": issue.cohort,
                "tier": recipient.tier,
                "locale": recipient.locale,
                "message_id": result.message_id,
                "dry_run": result.dry_run,
                "latency_ms": result.latency_ms,
                "attempt": result.attempt,
            })
            print(
                f"  ok  cohort={issue.cohort:<16s} tier={recipient.tier:<6s} "
                f"id={result.message_id} attempt={result.attempt} {result.latency_ms}ms"
            )
        else:
            failed += 1
            _capture("newsletter.send_failed", {
                "issue_id": issue.issue_id,
                "issue_number": args.issue_number,
                "recipient_hash": recipient.email_hash,
                "cohort": issue.cohort,
                "error": result.error,
                "error_detail": result.error_detail,
                "attempt": result.attempt,
                "latency_ms": result.latency_ms,
            })
            print(
                f"  FAIL cohort={issue.cohort:<16s} error={result.error} "
                f"detail={result.error_detail!r}",
                file=sys.stderr,
            )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    print(f"[send] done sent={sent} failed={failed} elapsed={elapsed_ms}ms")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
