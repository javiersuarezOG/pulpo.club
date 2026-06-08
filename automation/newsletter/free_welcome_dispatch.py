"""Free-tier welcome / welcome-back dispatch.

The Pro welcome (welcome_dispatch.py) is Clerk-coupled: it looks the
recipient up in Clerk, gates on plan, and stamps publicMetadata for
idempotency. Free subscribers can't use that path — a homepage signup is
an anonymous email with no Clerk account.

So this dispatcher is deliberately DB-free and Clerk-free:

  • It builds a synthesized FREE recipient (anonymous, tier="free", no
    prefs) and renders the free welcome / welcome-back template
    (render_free_welcome_html / render_free_welcome_back_html) — the same
    free body the weekly uses, only the hero differs.

  • Idempotency is CALLER-PROVIDED. Pulpo has no DB, so "already welcomed"
    can't be tracked here. The chosen model (2026-06-07): the homepage
    subscribe trigger fires this ONLY when the Resend enroll reports a NEW
    contact (`dedup == false`). "New subscriber → welcome once." A
    duplicate/returning subscribe is a no-op at the trigger. The dispatcher
    honours that by skipping when `is_new_contact=False` (unless `force`,
    used by the admin test surface).

  • Dry-run by default (PULPO_NEWSLETTER_DRY_RUN), exactly like every other
    Pulpo send path. No real email goes out until an operator flips the env.

Telemetry mirrors the Pro welcome event shapes so PostHog funnels line up:
  • newsletter.free_welcome_sent / _skipped / _failed
  • newsletter.free_welcome_back_sent / _skipped / _failed
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import i18n
from .build_issue import build_issue
from .render_html import render_free_welcome_html, render_free_welcome_back_html
from .send import send_issue
from .store import email_hash
from .types import Locale, Preference, Recipient
# Reuse the Pro dispatcher's structured result + ranked loader + telemetry
# wrapper so the two paths can't drift on shape.
from .welcome_dispatch import WelcomeDispatchResult, _capture, _load_ranked

# Free onboarding variants. Map each to its render fn + i18n subject +
# template id + telemetry event stem.
_FREE_VARIANTS = {
    "free_welcome": {
        "render": render_free_welcome_html,
        "newsletter_id": "pulpo-free-welcome",
        "flow": "newsletter_free_welcome",
        "ev": "newsletter.free_welcome",
    },
    "free_welcome_back": {
        "render": render_free_welcome_back_html,
        "newsletter_id": "pulpo-free-welcome-back",
        "flow": "newsletter_free_welcome_back",
        "ev": "newsletter.free_welcome_back",
    },
}


def dispatch_free_welcome(
    *,
    email: str,
    variant: str = "free_welcome",
    locale: Locale = "en",
    display_name: Optional[str] = None,
    source: str = "signup",
    ranked_path: str = "web/data/ranked.json",
    is_new_contact: bool = True,
    force: bool = False,
) -> WelcomeDispatchResult:
    """Send the free welcome (or welcome-back) to a single subscriber, or
    skip with a structured reason.

    Args:
        email: Recipient address (also the Resend `to`).
        variant: "free_welcome" (first-time) or "free_welcome_back"
            (re-acquisition — churned Pro→free, or a resubscribing free
            reader). Same template, different hero greeting.
        locale: "en" | "es". Free subscribers carry no Clerk profile, so
            the trigger passes the locale it captured at signup.
        display_name: Optional first name for the hero greeting.
        source: Telemetry tag — "signup", "stripe_downgrade",
            "resend_resubscribe", "admin", ...
        is_new_contact: The DB-free idempotency signal. False → skip
            (`already_subscribed`); the trigger only sets True for a
            genuinely new Resend contact. `force` overrides (admin test).
        force: Bypass the idempotency skip (admin "send test to me").
    """
    if variant not in _FREE_VARIANTS:
        variant = "free_welcome"
    spec = _FREE_VARIANTS[variant]
    ev = spec["ev"]
    rh = email_hash(email)
    lc: Locale = locale if locale in ("en", "es") else "en"

    if not is_new_contact and not force:
        _capture(f"{ev}_skipped", {
            "recipient_hash": rh, "reason": "already_subscribed",
            "source": source, "variant": variant,
        })
        return WelcomeDispatchResult(status="skipped", reason="already_subscribed",
                                     recipient_hash=rh)

    ranked = _load_ranked(ranked_path)
    if ranked is None:
        _capture(f"{ev}_skipped", {
            "recipient_hash": rh, "reason": "ranked_missing",
            "source": source, "variant": variant, "ranked_path": ranked_path,
        })
        return WelcomeDispatchResult(status="skipped", reason="ranked_missing",
                                     recipient_hash=rh)

    # Synthesized FREE recipient — no Clerk, no prefs. Renders the generic
    # free best-of (cohort "anonymous" / "free"). tier="free" is what makes
    # build_issue stamp the free paywall flags the free template reads.
    recipient = Recipient(
        email_hash=rh,
        display_name=(display_name or None),
        locale=lc,
        tier="free",
        has_account=False,
        preference=Preference(),
    )
    issue = build_issue(
        recipient=recipient,
        ranked_listings=ranked,
        issue_number=1,
        issue_date=datetime.now(timezone.utc),
        history_rows=None,
    )
    if not issue.picks_top:
        _capture(f"{ev}_skipped", {
            "recipient_hash": rh, "reason": "no_picks_available",
            "source": source, "variant": variant,
        })
        return WelcomeDispatchResult(status="skipped", reason="no_picks_available",
                                     recipient_hash=rh)

    html = spec["render"](issue)
    subject = i18n.welcome_text("email.subject", lc, variant=variant)
    newsletter_id = spec["newsletter_id"]

    result = send_issue(
        to_email=email,
        recipient_hash=rh,
        issue_number=1,
        subject=subject,
        html=html,
        tags={
            "newsletter": newsletter_id,
            "recipient_hash": rh,
            "locale": lc,
            "source": source,
            "email_type": "newsletter",
        },
        headers_extra={
            "X-Pulpo-Newsletter": newsletter_id,
            "X-Pulpo-Recipient": rh,
            "X-Pulpo-Email-Type": "newsletter",
        },
    )

    if not result.ok:
        _capture(f"{ev}_failed", {
            "recipient_hash": rh, "error": result.error,
            "error_detail": result.error_detail, "attempt": result.attempt,
            "latency_ms": result.latency_ms, "source": source, "variant": variant,
        })
        _capture("email.send.failed", {
            "flow": spec["flow"], "error_code": result.error or "",
            "error_message": result.error_detail or "", "recipient": rh,
            "status_code": 0,
        })
        return WelcomeDispatchResult(status="failed", reason=result.error or "send_failed",
                                     recipient_hash=rh, dry_run=result.dry_run,
                                     latency_ms=result.latency_ms)

    _capture(f"{ev}_sent", {
        "recipient_hash": rh, "locale": lc, "tier": "free",
        "source": source, "variant": variant, "dry_run": result.dry_run,
        "message_id": result.message_id, "latency_ms": result.latency_ms,
    })
    return WelcomeDispatchResult(status="sent", message_id=result.message_id,
                                 recipient_hash=rh, dry_run=result.dry_run,
                                 latency_ms=result.latency_ms)
