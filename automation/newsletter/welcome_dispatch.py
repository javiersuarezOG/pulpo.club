"""Pulpo Pro Welcome — one-shot dispatcher.

End-to-end path: email-in, sent-or-skipped-out. Used by:

  • The CLI smoke / admin "Test send to me" surface (via
    `scripts/send_newsletter.py --newsletter pulpo-pro-welcome
    --welcome-single-email <email>`).
  • The Stripe webhook (future PR) — fired from
    `customer.subscription.created` after the existing
    `enrollPaidUserInAudience()` call. Webhook dispatches the
    `pulpo-pro-welcome.yml` workflow which calls into this module.

Idempotency contract:
  • `publicMetadata.welcome_newsletter_sent_at` on the recipient's
    Clerk user is the dedup stamp. Permanent — never re-sent on
    resubscribe. See `project_resubscribe_welcome_funnel` memory for
    rationale.
  • Backup signal: PostHog `newsletter.welcome_sent` events with
    `recipient_hash`. Queryable if Clerk metadata is suspected stale.

Telemetry contract (matches the General newsletter event shapes so
ops dashboards work with no schema changes):
  • `newsletter.welcome_sent`     — Resend 2xx (or dry-run success).
  • `newsletter.welcome_skipped`  — pre-flight idempotency / gate fail.
  • `newsletter.welcome_failed`   — Resend non-2xx or render exception.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from . import i18n
from .build_issue import build_issue
from .send import send_issue
from .store import email_hash
from .subscribers import (
    CLERK_API_BASE,
    ClerkUser,
    _parse_clerk_user,
    _preference_from_profile,
    _preference_source_from_profile,
    _locale_for,
)
from .templates import pulpo_pro_welcome
from .types import Locale, Recipient, SavedListing


# Skip reasons surfaced in PostHog so dashboards can break down the
# funnel: how many welcome dispatches dropped at which gate.
SKIP_REASONS = (
    "already_sent",
    "not_pro",
    "unsubscribed",
    "clerk_lookup_failed",
    "ranked_missing",
    "no_picks_available",
)


@dataclass
class WelcomeDispatchResult:
    """Outcome of one welcome attempt. `status` is the single source of
    truth — callers branch on it for exit codes and telemetry."""
    status: str                       # "sent" | "skipped" | "failed"
    reason: Optional[str] = None      # populated when status="skipped" or "failed"
    message_id: Optional[str] = None
    recipient_hash: Optional[str] = None
    dry_run: bool = False
    latency_ms: int = 0


def _capture(event: str, props: dict) -> None:
    """PostHog capture with the same forgiving pattern as
    `scripts/send_newsletter.py::_capture`. Telemetry failures must
    never block the actual send."""
    try:
        from automation import posthog_client                            # noqa: PLC0415
        posthog_client.capture(event, props)
    except Exception:                                                    # noqa: BLE001
        pass


def find_clerk_user_by_email(email: str) -> Optional[ClerkUser]:
    """Look up one Clerk user by email. Returns None on any failure
    (missing env, lookup error, no matches) — caller treats that as
    `clerk_lookup_failed` and skips the dispatch.

    Uses Clerk's `email_address[]` query param to avoid paginating
    through every user. Tolerant of both `data: [...]` and bare-array
    response shapes (Clerk SDK versions differ)."""
    secret = (os.environ.get("CLERK_SECRET_KEY") or "").strip()
    if not secret or not email:
        return None
    email_norm = email.strip().lower()
    url = f"{CLERK_API_BASE}/users?email_address[]={email_norm}&limit=1"
    headers = {"Authorization": f"Bearer {secret}"}
    try:
        import httpx                                                     # noqa: PLC0415
        r = httpx.get(url, headers=headers, timeout=10.0)
        r.raise_for_status()
        body = r.json()
    except Exception:                                                    # noqa: BLE001
        return None
    rows = body if isinstance(body, list) else (body.get("data") if isinstance(body, dict) else None)
    if not isinstance(rows, list) or not rows:
        return None
    user = _parse_clerk_user(rows[0])
    return user


def _stamp_welcome_sent_at(user_id: str, iso_ts: str) -> bool:
    """Write `publicMetadata.welcome_newsletter_sent_at` on the Clerk
    user via the partial-patch pattern documented in
    `api/stripe/webhook.js::patchPublicMetadata` — read current
    publicMetadata, shallow-merge, write back.

    Returns True on 2xx; False (with stderr log) on any failure. A
    failed stamp doesn't unwind the send (the email is already in the
    user's inbox) — but the PostHog event still fires so dashboards
    catch the divergence."""
    secret = (os.environ.get("CLERK_SECRET_KEY") or "").strip()
    if not secret or not user_id:
        return False
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }
    try:
        import httpx                                                     # noqa: PLC0415
        r = httpx.get(f"{CLERK_API_BASE}/users/{user_id}", headers=headers, timeout=10.0)
        r.raise_for_status()
        current = r.json()
        existing = current.get("public_metadata") or current.get("publicMetadata") or {}
        if not isinstance(existing, dict):
            existing = {}
        merged = {**existing, "welcome_newsletter_sent_at": iso_ts}
        patch_url = f"{CLERK_API_BASE}/users/{user_id}/metadata"
        r2 = httpx.patch(
            patch_url,
            headers=headers,
            json={"public_metadata": merged},
            timeout=10.0,
        )
        r2.raise_for_status()
        return True
    except Exception as exc:                                             # noqa: BLE001
        print(f"[welcome] clerk metadata stamp failed: {exc}", file=sys.stderr)
        return False


def _build_recipient_from_clerk(user: ClerkUser, *, locale_hint: Optional[Locale]) -> Recipient:
    """Mirror what `join_recipients()` does for a single Clerk user
    without going through Resend audience enumeration. The welcome
    fires immediately after Stripe checkout — the recipient may not
    yet be in the Resend audience by the time this runs."""
    preference = _preference_from_profile(user.profile)
    preference_source = _preference_source_from_profile(user.profile)
    locale = locale_hint or _locale_for(user)
    return Recipient(
        email_hash=email_hash(user.email),
        display_name=user.first_name,
        locale=locale,
        tier=user.plan,
        has_account=True,
        preference=preference,
        saved_count=user.saved_count,
        saves=[
            SavedListing(
                id=s["id"],
                saved_at=s.get("saved_at"),
                price_at_save_usd=s.get("price_at_save_usd"),
                source=s.get("source"),
            )
            for s in user.saves
        ],
        preference_source=preference_source,
    )


def _load_ranked(path: str) -> Optional[list[dict]]:
    """Load + sort ranked.json. Returns None when the file is missing
    so the caller can record `ranked_missing` cleanly."""
    try:
        with open(path) as fh:
            rows = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(rows, list):
        return None
    return sorted(rows, key=lambda x: x.get("rank") or 9_999)


def dispatch_welcome(
    *,
    email: str,
    locale: Optional[Locale] = None,
    source: str = "admin",
    ranked_path: str = "web/data/ranked.json",
    force: bool = False,
) -> WelcomeDispatchResult:
    """Send the Pulpo Pro Welcome to a single recipient (or skip with a
    structured reason).

    Args:
        email: Recipient address. Used for Clerk lookup + Resend `to`.
        locale: Optional override. When unset, reads locale from the
            Clerk user (publicMetadata.profile.locale → "en" fallback).
        source: Telemetry tag — "stripe", "admin", "test", etc.
        ranked_path: Path to the current ranked.json. The welcome's
            10 picks come from the same source as the weekly digest.
        force: Bypass the welcome-already-sent idempotency check. The
            admin "Test send to me" surface uses this so an operator
            can re-render the welcome without manually clearing the
            Clerk metadata. PROD path leaves force=False.
    """
    user = find_clerk_user_by_email(email)
    if user is None:
        _capture("newsletter.welcome_skipped", {
            "recipient": email,
            "reason": "clerk_lookup_failed",
            "source": source,
        })
        return WelcomeDispatchResult(status="skipped", reason="clerk_lookup_failed")

    if user.plan not in ("pro", "agency") and not force:
        _capture("newsletter.welcome_skipped", {
            "recipient_hash": email_hash(email),
            "reason": "not_pro",
            "source": source,
        })
        return WelcomeDispatchResult(status="skipped", reason="not_pro",
                                      recipient_hash=email_hash(email))

    if user.welcome_sent_at and not force:
        _capture("newsletter.welcome_skipped", {
            "recipient_hash": email_hash(email),
            "reason": "already_sent",
            "source": source,
            "previous_sent_at": user.welcome_sent_at,
        })
        return WelcomeDispatchResult(status="skipped", reason="already_sent",
                                      recipient_hash=email_hash(email))

    ranked = _load_ranked(ranked_path)
    if ranked is None:
        _capture("newsletter.welcome_skipped", {
            "recipient_hash": email_hash(email),
            "reason": "ranked_missing",
            "source": source,
            "ranked_path": ranked_path,
        })
        return WelcomeDispatchResult(status="skipped", reason="ranked_missing",
                                      recipient_hash=email_hash(email))

    recipient = _build_recipient_from_clerk(user, locale_hint=locale)
    issue = build_issue(
        recipient=recipient,
        ranked_listings=ranked,
        issue_number=1,
        issue_date=datetime.now(timezone.utc),
        history_rows=None,
    )
    if not issue.picks_top:
        _capture("newsletter.welcome_skipped", {
            "recipient_hash": recipient.email_hash,
            "reason": "no_picks_available",
            "source": source,
        })
        return WelcomeDispatchResult(status="skipped", reason="no_picks_available",
                                      recipient_hash=recipient.email_hash)

    html = pulpo_pro_welcome.render(issue)
    subject = i18n.t("welcome.email.subject", recipient.locale)

    result = send_issue(
        to_email=email,
        recipient_hash=recipient.email_hash,
        issue_number=1,
        subject=subject,
        html=html,
        tags={
            "newsletter": "pulpo-pro-welcome",
            "recipient_hash": recipient.email_hash,
            "locale": recipient.locale,
            "source": source,
            "email_type": "newsletter",
        },
        headers_extra={
            "X-Pulpo-Newsletter": "pulpo-pro-welcome",
            "X-Pulpo-Recipient": recipient.email_hash,
            "X-Pulpo-Email-Type": "newsletter",
        },
    )

    if not result.ok:
        _capture("newsletter.welcome_failed", {
            "recipient_hash": recipient.email_hash,
            "error": result.error,
            "error_detail": result.error_detail,
            "attempt": result.attempt,
            "latency_ms": result.latency_ms,
            "source": source,
        })
        _capture("email.send.failed", {
            "flow": "newsletter_welcome",
            "error_code": result.error or "",
            "error_message": result.error_detail or "",
            "recipient": recipient.email_hash,
            "status_code": 0,
        })
        return WelcomeDispatchResult(
            status="failed",
            reason=result.error or "send_failed",
            recipient_hash=recipient.email_hash,
            dry_run=result.dry_run,
            latency_ms=result.latency_ms,
        )

    iso_ts = datetime.now(timezone.utc).isoformat()
    # Only stamp Clerk on LIVE sends — a dry-run shouldn't burn the
    # idempotency stamp (otherwise the next real attempt would skip).
    stamped = False
    if not result.dry_run:
        stamped = _stamp_welcome_sent_at(user.id, iso_ts)

    _capture("newsletter.welcome_sent", {
        "recipient_hash": recipient.email_hash,
        "locale": recipient.locale,
        "tier": recipient.tier,
        "message_id": result.message_id,
        "dry_run": result.dry_run,
        "latency_ms": result.latency_ms,
        "attempt": result.attempt,
        "source": source,
        "stamped_clerk": stamped,
    })

    return WelcomeDispatchResult(
        status="sent",
        message_id=result.message_id,
        recipient_hash=recipient.email_hash,
        dry_run=result.dry_run,
        latency_ms=result.latency_ms,
    )
