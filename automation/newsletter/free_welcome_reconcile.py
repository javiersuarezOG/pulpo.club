"""Free-welcome reconcile backstop.

The free welcome email is a single best-effort send on signup
(api/newsletter.js → /api/internal/free-welcome-send → dispatch_free_welcome)
with NO retry. If that dispatch hiccups (network, timeout, internal-token
blip), the welcome is silently lost. This hourly cron is the backstop —
the free-tier equivalent of the Pro `welcome_reconcile` cron.

Free members are email-only (NO Clerk account): they live in the Resend
audience and there is no per-contact "welcome sent" stamp (no DB, no Clerk).
So "was this contact welcomed?" is answered from PostHog — the dispatch
fires `newsletter.free_welcome_sent{recipient_hash}` on a REAL send. We:

  1. List recent free contacts from the Resend audience (created in the
     window [now-max_age_days, now-min_age_hours]).
  2. Query PostHog for the set of recipient_hashes already welcomed by a
     REAL send (dry_run=false) in the recent past.
  3. Re-send to the recent contacts NOT in that set (oldest-first, capped).

SAFETY — the PostHog welcomed-set is the only dedup, so getting it wrong
means spamming people. Three guards:

  * PostHog query FAILURE aborts the run. We NEVER treat "query failed" as
    "nobody welcomed" — that would blast everyone. (The asymmetry that bit
    the webhook-health rate checks; here it's load-bearing.)
  * Dark-path sanity guard: if an implausibly large fraction of recent
    contacts look unwelcomed, the welcome PATH is probably dark (not
    isolated drops) — we do NOT mass-send; we alert and skip. The cron is a
    backstop for rare misses, not a substitute for the live path.
  * Per-run cap bounds blast radius even if both guards are wrong.

Dry-run by default on manual runs; live only on the scheduled cron
(PULPO_NEWSLETTER_DRY_RUN, same contract as the Pro reconcile).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .free_welcome_dispatch import dispatch_free_welcome
from .store import email_hash
from .subscribers import ResendContact, list_audience
from .welcome_dispatch import _capture

DEFAULT_MIN_AGE_HOURS = 1     # grace window so we don't race the live dispatch
DEFAULT_MAX_AGE_DAYS = 7      # don't chase ancient signups
DEFAULT_MAX_CONTACTS = 10     # per-run cap (Resend rate-limit + blast-radius headroom)
WELCOMED_LOOKBACK_DAYS = 8    # query window for "already welcomed" — slightly wider than max age

# Dark-path guard: if >= this many recent contacts are in the window AND the
# unwelcomed fraction exceeds the ratio, assume the welcome path is dark
# (nothing is sending) rather than isolated drops, and refuse to mass-send.
DARK_PATH_MIN_RECENT = 8
DARK_PATH_MAX_UNWELCOMED_RATIO = 0.6

WELCOMED_EVENTS = ("newsletter.free_welcome_sent", "newsletter.free_welcome_back_sent")


class PostHogUnavailable(RuntimeError):
    """Raised when the welcomed-set query can't be trusted (creds missing or
    query errored). Callers MUST abort rather than treat as 'nobody welcomed'."""


@dataclass
class ReconcileResult:
    found_recent: int = 0
    unwelcomed: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    dry_run: bool = True
    aborted_reason: Optional[str] = None  # None | "posthog_unavailable" | "welcome_path_dark"
    elapsed_ms: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def query_welcomed_hashes(
    *,
    now: Optional[datetime] = None,
    lookback_days: int = WELCOMED_LOOKBACK_DAYS,
    post_override: Any = None,
) -> set[str]:
    """Set of recipient_hashes that received a REAL free welcome in the
    lookback window. Raises PostHogUnavailable on missing creds / query error
    — the caller must abort, never assume an empty set means 'nobody welcomed'.
    """
    # The PostHog QUERY API (/api/projects/.../query/) lives on the app host
    # (eu.posthog.com), NOT the ingest host (eu.i.posthog.com) that
    # POSTHOG_HOST / posthog_client.capture use. Read a dedicated var so the
    # two never collide when both run in the same job.
    host = (os.environ.get("POSTHOG_QUERY_HOST") or "https://eu.posthog.com").rstrip("/")
    project = os.environ.get("POSTHOG_PROJECT_ID")
    key = os.environ.get("POSTHOG_PERSONAL_API_KEY")
    if post_override is None and (not project or not key):
        raise PostHogUnavailable("POSTHOG_PROJECT_ID and POSTHOG_PERSONAL_API_KEY are required")

    events = ", ".join(f"'{e}'" for e in WELCOMED_EVENTS)
    hogql = (
        "SELECT DISTINCT properties.recipient_hash AS rh FROM events "
        f"WHERE event IN ({events}) "
        f"AND timestamp > now() - toIntervalDay({int(lookback_days)}) "
        "AND properties.dry_run = false "
        "AND notEmpty(properties.recipient_hash)"
    )
    body = {"query": {"kind": "HogQLQuery", "query": hogql}}
    try:
        if post_override is not None:
            data = post_override(host, project, key, body)
        else:
            req = urllib.request.Request(
                f"{host}/api/projects/{project}/query/",
                data=json.dumps(body).encode("utf-8"),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                data = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PostHogUnavailable(f"welcomed-set query failed: {exc}") from exc

    rows = (data or {}).get("results") or []
    welcomed: set[str] = set()
    for row in rows:
        if row and row[0]:
            welcomed.add(str(row[0]))
    return welcomed


def fetch_recent_free_contacts(
    *,
    now: Optional[datetime] = None,
    min_age_hours: int = DEFAULT_MIN_AGE_HOURS,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    get_override: Any = None,
) -> list[ResendContact]:
    """Subscribed Resend contacts created in [now-max_age_days, now-min_age_hours],
    oldest-first (FIFO drain)."""
    now = now or _now()
    newest = now - timedelta(hours=min_age_hours)
    oldest = now - timedelta(days=max_age_days)
    out: list[tuple[datetime, ResendContact]] = []
    for c in list_audience(get_override=get_override):
        if c.unsubscribed:
            continue
        created = _parse_iso(c.created_at)
        if created is None or not (oldest <= created <= newest):
            continue
        out.append((created, c))
    out.sort(key=lambda t: t[0])  # FIFO
    return [c for _, c in out]


def run_reconcile(
    *,
    dry_run: bool = True,
    max_contacts: int = DEFAULT_MAX_CONTACTS,
    now: Optional[datetime] = None,
    ranked_path: str = "web/data/ranked.json",
    get_override: Any = None,
    post_override: Any = None,
) -> ReconcileResult:
    now = now or _now()
    started = now
    res = ReconcileResult(dry_run=dry_run)

    recent = fetch_recent_free_contacts(now=now, get_override=get_override)
    res.found_recent = len(recent)
    if not recent:
        res.elapsed_ms = int((_now() - started).total_seconds() * 1000)
        _emit(res, max_contacts)
        return res

    # Welcomed-set — abort the whole run if we can't trust it.
    try:
        welcomed = query_welcomed_hashes(now=now, post_override=post_override)
    except PostHogUnavailable as exc:
        print(f"[free-reconcile] ABORT — {exc}", file=sys.stderr)
        res.aborted_reason = "posthog_unavailable"
        res.elapsed_ms = int((_now() - started).total_seconds() * 1000)
        _emit(res, max_contacts)
        return res

    unwelcomed = [c for c in recent if email_hash(c.email) not in welcomed]
    res.unwelcomed = len(unwelcomed)

    # Dark-path guard: a large unwelcomed fraction means the live path is
    # probably down — don't mass-send a backstop's worth, alert instead.
    if (
        res.found_recent >= DARK_PATH_MIN_RECENT
        and res.unwelcomed / res.found_recent > DARK_PATH_MAX_UNWELCOMED_RATIO
    ):
        print(
            f"[free-reconcile] ABORT — welcome path likely dark: "
            f"{res.unwelcomed}/{res.found_recent} recent contacts unwelcomed",
            file=sys.stderr,
        )
        res.aborted_reason = "welcome_path_dark"
        res.elapsed_ms = int((_now() - started).total_seconds() * 1000)
        _emit(res, max_contacts)
        return res

    targets = unwelcomed[:max_contacts]
    for c in targets:
        if dry_run:
            res.skipped += 1
            print(f"[free-reconcile] DRY-RUN would re-send free welcome → {email_hash(c.email)}")
            continue
        try:
            out = dispatch_free_welcome(
                email=c.email,
                variant="free_welcome",
                locale=c.locale or "en",
                source="free_reconcile_cron",
                ranked_path=ranked_path,
                is_new_contact=False,
                force=True,  # PostHog already confirmed no real welcome exists
            )
            if out.status == "sent":
                res.sent += 1
            elif out.status == "failed":
                res.failed += 1
            else:
                res.skipped += 1
        except Exception as exc:  # noqa: BLE001
            res.failed += 1
            print(f"[free-reconcile] dispatch threw for {email_hash(c.email)}: {exc}", file=sys.stderr)

    res.elapsed_ms = int((_now() - started).total_seconds() * 1000)
    _emit(res, max_contacts)
    return res


def _emit(res: ReconcileResult, max_contacts: int) -> None:
    _capture(
        "newsletter.free_welcome_reconcile_completed",
        {
            "found_recent": res.found_recent,
            "unwelcomed": res.unwelcomed,
            "sent": res.sent,
            "skipped": res.skipped,
            "failed": res.failed,
            "dry_run": res.dry_run,
            "aborted_reason": res.aborted_reason or "",
            "elapsed_ms": res.elapsed_ms,
            "max_contacts": max_contacts,
        },
    )


def main() -> int:
    """CLI for the GH Actions cron + manual runs.

    Exit codes:
      0 — clean (sent/skipped only, dry-run, or a safe abort)
      1 — at least one dispatch failed
      2 — pre-flight failure (missing Resend / PostHog query creds)
    """
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--send-mode", choices=("no", "yes"), default="no",
                   help="`no` (default) = dry-run; `yes` = live re-sends.")
    p.add_argument("--max-contacts", type=int, default=DEFAULT_MAX_CONTACTS,
                   help=f"Cap per run. Default {DEFAULT_MAX_CONTACTS}.")
    p.add_argument("--ranked", default="web/data/ranked.json")
    args = p.parse_args()

    if not (os.environ.get("RESEND_AUDIENCE_ID") and os.environ.get("RESEND_API_KEY")):
        print("[free-reconcile] RESEND_AUDIENCE_ID / RESEND_API_KEY not set", file=sys.stderr)
        return 2
    if not (os.environ.get("POSTHOG_PROJECT_ID") and os.environ.get("POSTHOG_PERSONAL_API_KEY")):
        print("[free-reconcile] POSTHOG_PROJECT_ID / POSTHOG_PERSONAL_API_KEY not set "
              "(needed for the welcomed-set query)", file=sys.stderr)
        return 2

    result = run_reconcile(
        dry_run=(args.send_mode != "yes"),
        max_contacts=args.max_contacts,
        ranked_path=args.ranked,
    )
    print(
        f"[free-reconcile] found_recent={result.found_recent} unwelcomed={result.unwelcomed} "
        f"sent={result.sent} skipped={result.skipped} failed={result.failed} "
        f"dry_run={result.dry_run} aborted={result.aborted_reason or '-'} "
        f"elapsed_ms={result.elapsed_ms}"
    )
    return 1 if result.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
