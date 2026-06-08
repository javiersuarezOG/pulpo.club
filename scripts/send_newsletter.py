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
from automation.newsletter.templates import TEMPLATES                      # noqa: E402
from automation.newsletter.issue_state import next_issue_number            # noqa: E402
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


def _run_welcome(args) -> int:
    """Welcome-route entry. Returns 0 for sent OR skipped (skips are
    expected outcomes, not failures). Returns 1 on actual send failure,
    2 on bad CLI args."""
    from automation.newsletter.welcome_dispatch import dispatch_welcome  # noqa: PLC0415

    if not args.welcome_single_email:
        print(
            "[send] --newsletter=pulpo-pro-welcome requires "
            "--welcome-single-email <email>",
            file=sys.stderr,
        )
        return 2
    if args.only_email or args.preview_cohorts or args.allow_all_subscribers:
        print(
            "[send] --welcome-single-email is mutually exclusive with "
            "--only-email / --preview-cohorts / --allow-all-subscribers",
            file=sys.stderr,
        )
        return 2

    email = args.welcome_single_email.strip().lower()
    variant = getattr(args, "welcome_variant", "welcome") or "welcome"
    # Optional locale override (admin preview). None → dispatcher uses the
    # recipient's Clerk locale (production behavior).
    locale = getattr(args, "welcome_locale", None) or None
    print(f"[welcome] dispatching email={email} source={args.welcome_source} "
          f"force={args.welcome_force} variant={variant} locale={locale or 'clerk'}")
    result = dispatch_welcome(
        email=email,
        locale=locale,
        source=args.welcome_source,
        ranked_path=args.ranked,
        force=args.welcome_force,
        variant=variant,
    )
    print(
        f"[welcome] status={result.status} reason={result.reason or '-'} "
        f"message_id={result.message_id or '-'} dry_run={result.dry_run} "
        f"latency_ms={result.latency_ms}"
    )
    if result.status == "failed":
        return 1
    return 0


def _run_free_welcome(args) -> int:
    """Free welcome / welcome-back route. DB-free + Clerk-free dispatch
    (free subscribers can be anonymous). Same exit-code contract as
    _run_welcome. The CLI/admin surface forces the send (is_new_contact +
    force) so an operator can always render a test; the production trigger
    decides idempotency from the Resend new-contact signal."""
    from automation.newsletter.free_welcome_dispatch import dispatch_free_welcome  # noqa: PLC0415

    if not args.welcome_single_email:
        print(
            f"[send] --newsletter={args.newsletter} requires "
            "--welcome-single-email <email>",
            file=sys.stderr,
        )
        return 2
    if args.only_email or args.preview_cohorts or args.allow_all_subscribers:
        print(
            "[send] --welcome-single-email is mutually exclusive with "
            "--only-email / --preview-cohorts / --allow-all-subscribers",
            file=sys.stderr,
        )
        return 2

    email = args.welcome_single_email.strip().lower()
    variant = ("free_welcome_back" if args.newsletter == "pulpo-free-welcome-back"
               else "free_welcome")
    locale = getattr(args, "welcome_locale", None) or "en"
    print(f"[free-welcome] dispatching email={email} source={args.welcome_source} "
          f"variant={variant} locale={locale}")
    result = dispatch_free_welcome(
        email=email,
        variant=variant,
        locale=locale,
        source=args.welcome_source,
        ranked_path=args.ranked,
        is_new_contact=True,
        force=args.welcome_force,
    )
    print(
        f"[free-welcome] status={result.status} reason={result.reason or '-'} "
        f"message_id={result.message_id or '-'} dry_run={result.dry_run} "
        f"latency_ms={result.latency_ms}"
    )
    if result.status == "failed":
        return 1
    return 0


def _subject_for(issue, locale: str, *, preview: bool = False) -> str:
    # Tag-style subject: "{Brand} {Tier} · Issue NN". The brand-only
    # prefix was redundant with the From column ("Pulpo · ...") so we
    # drop the wasted chars and surface the tier ("Pro") instead — both
    # for product clarity today and so free-weekly reads differently in
    # the inbox once that template ships. Issue-content tease moves to
    # the hidden preheader (`render_html._preheader_html`) — the inbox
    # preview line should carry curiosity, the subject should carry
    # identity. Preview-cohort sends keep their `[PULPO PREVIEW · …]`
    # prefix so operators can tell test sends from real broadcasts.
    if preview:
        return f"[PULPO PREVIEW · {issue.cohort}] Issue {issue.issue_number:02d}"
    if locale == "es":
        return f"Pulpo Pro · Edición {issue.issue_number:02d}"
    return f"Pulpo Pro · Issue {issue.issue_number:02d}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ranked", default="web/data/ranked.json")
    p.add_argument(
        "--newsletter",
        default="pulpo-pro-general",
        choices=("pulpo-pro-general", "pulpo-pro-welcome", "pulpo-free-general",
                 "pulpo-free-welcome", "pulpo-free-welcome-back"),
        help=(
            "Which template to route this run through. Default is the "
            "weekly digest (`pulpo-pro-general`). `pulpo-free-general` is "
            "the free-tier weekly. `pulpo-free-welcome` / "
            "`pulpo-free-welcome-back` are the free one-shot onboarding "
            "emails (DB-free + Clerk-free dispatch) — REQUIRE "
            "--welcome-single-email. `pulpo-pro-welcome` is the Pro "
            "one-shot welcome. All paths share send.py + the Resend send "
            "mechanics but the audience and idempotency model differ."
        ),
    )
    p.add_argument(
        "--welcome-single-email",
        default=None,
        metavar="EMAIL",
        help=(
            "Welcome-template path only. Single recipient email. The "
            "dispatcher in automation/newsletter/welcome_dispatch.py "
            "handles Clerk lookup, idempotency check, render + send. "
            "Pre-flight skips (already_sent, not_pro, etc.) exit 0 — "
            "they're expected outcomes, not failures."
        ),
    )
    p.add_argument(
        "--welcome-source",
        default="admin",
        help=(
            "Welcome-template telemetry tag — \"stripe\", \"admin\", "
            "\"test\", etc. Surfaces in newsletter.welcome_sent so "
            "dashboards can slice by trigger source."
        ),
    )
    p.add_argument(
        "--welcome-force",
        action="store_true",
        help=(
            "Welcome-template: bypass the already_sent idempotency "
            "check (admin Test-send-to-me uses this so an operator can "
            "re-render the welcome without manually clearing Clerk)."
        ),
    )
    p.add_argument(
        "--welcome-variant",
        default="welcome",
        choices=("welcome", "welcome_back"),
        help=(
            "Welcome sub-version: \"welcome\" (first-time onboarding, "
            "default) or \"welcome_back\" (resubscribe re-acquisition — "
            "same template, 'welcome back' hero). Admin Test-send-to-me "
            "passes welcome_back to preview the returning-user email "
            "without a Stripe resubscribe."
        ),
    )
    p.add_argument(
        "--welcome-locale",
        default=None,
        choices=("en", "es"),
        help=(
            "Welcome-template locale override (admin preview / the tool's "
            "Language toggle). When omitted the dispatcher uses the "
            "recipient's Clerk publicMetadata.profile.locale — the "
            "production behavior."
        ),
    )
    p.add_argument(
        "--issue-number",
        type=int,
        default=None,
        help=(
            "Issue number to stamp into this run. When omitted, the script "
            "queries PostHog for max(issue_number) from successful past "
            "sends and uses that + 1 (falls back to 1 on any error). Auto-"
            "increment only applies to audience-wide LIVE sends; preview "
            "and --only-email smoke sends require an explicit value so a "
            "tester send can't bump production state."
        ),
    )
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
        "--preview-locale",
        choices=("en", "es"),
        default="en",
        help=(
            "Locale for the preview render. EN or ES. Only meaningful "
            "alongside --preview-cohorts."
        ),
    )
    p.add_argument(
        "--include-unsubscribed",
        action="store_true",
        help="Ignore audience-level unsubscribed flag (FOR DEBUGGING ONLY).",
    )
    p.add_argument(
        "--allow-all-subscribers",
        action="store_true",
        help=(
            "Bypass the Pro/Agency audience gate. Anonymous Resend-only "
            "contacts AND free-tier Clerk users land in the queue alongside "
            "Pro/Agency. Intended for one-off launch/announcement sends; "
            "non-Pro recipients see the Pro-weekly template with fallback "
            "preferences and (for free Clerk users) the paywall banner. "
            "Do not leave on for recurring sends — overrides PR-NL-9."
        ),
    )
    p.add_argument(
        "--free-audience",
        action="store_true",
        help=(
            "Build the FREE-tier audience instead of the Pro one: free "
            "Clerk users + anonymous Resend contacts, with Pro/Agency "
            "EXCLUDED. Pair with `--newsletter pulpo-free-general` for the "
            "free weekly. Staged: the Sunday cron stays Pro-only; this is "
            "run via workflow_dispatch and is dry-run unless send_mode=yes."
        ),
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

    # ── Welcome route — early branch ──────────────────────────────────
    # The welcome template runs through a separate dispatcher with its
    # own idempotency model (Clerk publicMetadata stamp) and audience
    # (one email at a time, not the joined Resend+Clerk queue). Keeping
    # the branch high lets us reject incompatible flags loudly and avoid
    # touching ranked.json twice.
    if args.newsletter == "pulpo-pro-welcome":
        return _run_welcome(args)
    if args.newsletter in ("pulpo-free-welcome", "pulpo-free-welcome-back"):
        return _run_free_welcome(args)

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
            queue = synthesize_preview_recipients(
                args.preview_cohorts,
                locale=args.preview_locale,
            )
        except ValueError as e:
            print(f"[send] {e}", file=sys.stderr)
            return 2
    else:
        only = set(args.only_email) if args.only_email else None
        if args.allow_all_subscribers:
            # Loud single line so the audit log is unambiguous about why
            # non-Pro recipients are in this run. PR review + post-mortem
            # should grep for this exact string.
            print("[send] ⚠️  --allow-all-subscribers ON — Pro/Agency gate BYPASSED")
        if args.free_audience:
            print("[send] FREE AUDIENCE — free Clerk users + anonymous contacts; Pro/Agency excluded")
        queue = build_recipient_queue(
            only_emails=only,
            include_unsubscribed=args.include_unsubscribed,
            allow_non_pro=args.allow_all_subscribers,
            free_only=args.free_audience,
        )
    if args.limit:
        queue = queue[: args.limit]

    # Resolve issue_number: explicit CLI > PostHog auto-increment > 1.
    # Smoke (--only-email) and preview sends MUST pass an explicit
    # number so a tester send can't bump the audience's running counter
    # (and so a 1-recipient test doesn't end up looking like Issue NN+1
    # in everyone's history of received issues).
    if args.issue_number is None:
        if preview_mode or args.only_email:
            print(
                "[send] --issue-number is required for --preview-cohorts "
                "and --only-email runs (auto-increment is audience-only)",
                file=sys.stderr,
            )
            return 2
        resolved_issue_number = next_issue_number(default=1)
        print(f"[send] auto-incremented issue_number={resolved_issue_number} (from PostHog)")
    else:
        resolved_issue_number = args.issue_number
    args.issue_number = resolved_issue_number

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
        # Route the render through the templates registry so
        # `--newsletter pulpo-free-general` produces the free-tier weekly
        # (plain masthead, "Sign up to Pro" on ranks 04-10, Pro-locked
        # spotlight). Default + any unknown id falls back to the Pro
        # General master, preserving the prior behaviour.
        _render = TEMPLATES.get(args.newsletter) or render_html
        html = _render(issue)
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
                # Audit signal: True when --allow-all-subscribers bypassed
                # the PR-NL-9 Pro/Agency gate. Dashboards can alert when
                # this is True across multiple consecutive sends (would
                # indicate the launch flag was accidentally left on).
                "audience_gate_bypassed": bool(args.allow_all_subscribers),
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
                "audience_gate_bypassed": bool(args.allow_all_subscribers),
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
        "audience_gate_bypassed": bool(args.allow_all_subscribers),
    })
    print(f"[send] done sent={sent} failed={failed} elapsed={elapsed_ms}ms")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
