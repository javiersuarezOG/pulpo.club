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

from automation.newsletter import (                                        # noqa: E402
    TEMPLATE_VERSION,
    build_issue,
    render_html,
)
from automation.newsletter.send import is_dry_run, send_issue              # noqa: E402
from automation.newsletter.subscribers import (                            # noqa: E402
    build_recipient_queue,
    synthesize_preview_recipients,
)


def _capture(event: str, props: dict) -> None:
    try:
        from automation import posthog_client                              # noqa: PLC0415
        posthog_client.capture(event, props)
    except Exception:                                                      # noqa: BLE001
        pass


def _subject_for(issue, locale: str, *, preview: bool = False) -> str:
    # Editorial subject — variable substitution stays here so a future
    # A/B-test fixture can override per-recipient. The 14-day window is
    # the cadence reader expects ("this fortnight").
    # In preview mode the cohort is stamped into the prefix so the
    # operator can tell the three variants apart in their own inbox.
    if preview:
        return f"[PULPO PREVIEW · {issue.cohort}] Issue {issue.issue_number:02d}"
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
        "--preview-cohorts",
        default=None,
        metavar="EMAIL",
        help=(
            "Admin preview mode. Skip the audience queue; instead send a "
            "single Pro-with-prefs preview of the current issue to this "
            "email. Subject is prefixed '[PULPO PREVIEW · pro_prefs]' so "
            "the operator can tell it apart from real audience sends. "
            "PR-NL-9 (audience scope): the personalised newsletter is a "
            "Pro feature; only the pro_prefs variant is meaningful here. "
            "Forces LIVE send (DRY_RUN must be off in the env)."
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

    preview_mode = bool(args.preview_cohorts)
    if preview_mode:
        if args.only_email:
            print(
                "[send] --preview-cohorts and --only-email are mutually exclusive",
                file=sys.stderr,
            )
            return 2
        try:
            queue = synthesize_preview_recipients(args.preview_cohorts)
        except ValueError as e:
            print(f"[send] {e}", file=sys.stderr)
            return 2
    else:
        only = set(args.only_email) if args.only_email else None
        queue = build_recipient_queue(
            only_emails=only,
            include_unsubscribed=args.include_unsubscribed,
        )
    if args.limit:
        queue = queue[: args.limit]

    issue_date = datetime.now(timezone.utc)
    dry = is_dry_run()
    if preview_mode and dry:
        # Preview mode is explicit and goes to a single operator-chosen
        # address — let it fail loud rather than silently no-op'ing the
        # send the operator clicked to trigger.
        print(
            "[send] preview mode requires LIVE send "
            "(set PULPO_NEWSLETTER_DRY_RUN=0 in the workflow / env)",
            file=sys.stderr,
        )
        return 2
    mode_label = "PREVIEW" if preview_mode else ("dry-run" if dry else "LIVE")
    print(
        f"[send] mode={mode_label} recipients={len(queue)} "
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
        subject = _subject_for(issue, recipient.locale, preview=preview_mode)

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
                # LEARNING: discriminator read by api/resend-webhook.js so
                # newsletter.* lifecycle events in PostHog carry a clean
                # email_type=newsletter axis (vs activation). See
                # docs/email-audit.md.
                "email_type": "newsletter",
            },
            headers_extra={
                "X-Pulpo-Issue": str(args.issue_number),
                "X-Pulpo-Recipient": recipient.email_hash,
                "X-Pulpo-Email-Type": "newsletter",
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
            # New per-recipient event in the email.* namespace. Lets PostHog
            # slice "sends from template v2.1 to recipient_hash X" without
            # joining tables. recipient_count carries the batch context so
            # one event row is self-describing. dry_… ids are intentional
            # telemetry, not noise — filter on dry_run=true to ignore.
            _capture("email.newsletter.sent", {
                "recipient_count": len(queue),
                "template_version": TEMPLATE_VERSION,
                "resend_message_id": result.message_id,
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
            # GUARDRAIL: cross-flow telemetry sibling to the activation-side
            # `email.send.failed` in api/_activation_email.js. Same shape:
            # { flow, error_code, error_message, recipient }. We keep the
            # newsletter.send_failed event above for dashboard back-compat;
            # this new event is what cross-flow ops dashboards subscribe to.
            # See docs/email-audit.md.
            _capture("email.send.failed", {
                "flow": "newsletter",
                "error_code": result.error or "",
                "error_message": result.error_detail or "",
                "recipient": recipient.email_hash,
                "status_code": 0,  # SendResult does not surface HTTP status
            })
            print(
                f"  FAIL cohort={issue.cohort:<16s} error={result.error} "
                f"detail={result.error_detail!r}",
                file=sys.stderr,
            )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    # Batch-summary event in the email.* namespace. One row per run with
    # the whole-batch outcome — letting ops dashboards answer "what's the
    # latest newsletter send doing?" without aggregating per-recipient
    # rows. issue_id matches what newsletter.issue_built / send_succeeded
    # already use so funnels can chain.
    _capture("email.newsletter.batch_sent", {
        "issue_number": args.issue_number,
        "issue_id": issue_date.strftime("%Y-%m-%d"),
        "recipient_count": len(queue),
        "sent_count": sent,
        "failed_count": failed,
        "template_version": TEMPLATE_VERSION,
        "dry_run": dry,
        "preview_mode": preview_mode,
        "elapsed_ms": elapsed_ms,
    })
    print(f"[send] done sent={sent} failed={failed} elapsed={elapsed_ms}ms")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
