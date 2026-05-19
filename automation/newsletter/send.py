"""Send a rendered newsletter Issue via the Resend HTTP API.

Dry-run gate (default ON):
    PULPO_NEWSLETTER_DRY_RUN unset or "1" / "true" / "yes" → no HTTP call;
    returns a fake message_id and fires the same PostHog telemetry as a
    real send so dashboards can verify wiring without burning Resend quota.

Real send:
    PULPO_NEWSLETTER_DRY_RUN=0 + RESEND_API_KEY + RESEND_FROM_EMAIL set.
    Returns the Resend message id.

Graceful degrade — every failure shape returns a SendResult with `error`
set rather than raising. The fortnightly orchestrator can then PostHog a
`newsletter.send_failed` event and continue with the rest of the batch.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

# ── Env contract ──────────────────────────────────────────────────────────
DRY_RUN_ENV = "PULPO_NEWSLETTER_DRY_RUN"
API_KEY_ENV = "RESEND_API_KEY"
FROM_EMAIL_ENV = "RESEND_FROM_EMAIL"
REPLY_TO_ENV = "RESEND_REPLY_TO_EMAIL"          # optional
UNSUBSCRIBE_SECRET_ENV = "PULPO_UNSUBSCRIBE_SECRET"
SITE_ROOT_ENV = "PULPO_SITE_ROOT"               # defaults to https://pulpo.club

RESEND_API_BASE = "https://api.resend.com"
TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS = 3                                # 1 initial + 2 retries
BACKOFF_SECONDS = 1.5                           # exponential


def is_dry_run() -> bool:
    """Default to TRUE when the env var is missing — safer to no-op than
    accidentally send. Only explicit `0` / `false` / `no` enables real send."""
    v = os.environ.get(DRY_RUN_ENV, "").strip().lower()
    if v in ("0", "false", "no"):
        return False
    return True


def _site_root() -> str:
    return os.environ.get(SITE_ROOT_ENV, "https://pulpo.club").rstrip("/")


# ── Unsubscribe + List-Unsubscribe headers ───────────────────────────────
# RFC 8058 one-click is what Gmail / Yahoo grade-A senders need. The
# header is a POST URL; the body Resend posts is `List-Unsubscribe=One-Click`.
# /api/unsubscribe consumes both that and the GET form for in-app clicks.
def unsubscribe_token(recipient_hash: str, issue_number: int, secret: str) -> str:
    msg = f"{recipient_hash}|{issue_number}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:32]


def unsubscribe_url(recipient_hash: str, issue_number: int) -> str:
    secret = os.environ.get(UNSUBSCRIBE_SECRET_ENV, "")
    token = unsubscribe_token(recipient_hash, issue_number, secret) if secret else ""
    base = _site_root()
    return f"{base}/api/unsubscribe?r={recipient_hash}&i={issue_number}&t={token}"


def list_unsubscribe_headers(recipient_hash: str, issue_number: int) -> dict[str, str]:
    """RFC 2369 + RFC 8058 headers — improves inbox placement materially."""
    url = unsubscribe_url(recipient_hash, issue_number)
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


# ── Plain-text fallback ───────────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    """Cheap HTML → text. Good enough for the plain-text MIME part Gmail
    uses for snippets; not a full conversion. We trade fidelity for zero
    new deps — the email's editorial value is in the HTML version."""
    # Drop <style> and <head> contents — they leak CSS into the text part.
    html = re.sub(r"<head\b.*?</head>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style\b.*?</style>", "", html, flags=re.S | re.I)
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    # Block-level tags → newlines so paragraphs separate.
    html = re.sub(r"</(p|tr|li|h1|h2|h3|h4|div|br|table)>", "\n", html, flags=re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = _TAG_RE.sub("", html)
    text = text.replace("&nbsp;", " ").replace("&middot;", "·")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = _WS_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


# ── Result type ───────────────────────────────────────────────────────────
@dataclass
class SendResult:
    ok: bool
    dry_run: bool
    message_id: Optional[str]
    error: Optional[str]
    error_detail: Optional[str]
    latency_ms: int
    attempt: int


# ── HTTP client (httpx, already a pulpo dep) ─────────────────────────────
def _post_json(url: str, *, headers: dict, body: dict, timeout: float = TIMEOUT_SECONDS):
    """Single-shot HTTP POST. Imported lazily so unit tests can monkeypatch
    this module-level function and never touch httpx."""
    import httpx  # type: ignore
    return httpx.post(url, headers=headers, json=body, timeout=timeout)


# ── Send ──────────────────────────────────────────────────────────────────
def send_issue(
    *,
    to_email: str,
    recipient_hash: str,
    issue_number: int,
    subject: str,
    html: str,
    text: Optional[str] = None,
    headers_extra: Optional[dict] = None,
    tags: Optional[dict] = None,
    post_override: Any = None,
) -> SendResult:
    """Send one rendered issue to one address.

    `post_override` is a test seam — pass a callable matching the signature
    of `_post_json` to bypass httpx entirely. Tests use this to assert on
    the outgoing payload without making network calls.
    """
    t0 = time.monotonic()
    dry = is_dry_run()

    if not to_email or "@" not in to_email:
        return SendResult(False, dry, None, "invalid_email", to_email,
                          int((time.monotonic() - t0) * 1000), 0)

    if dry:
        # Deterministic fake message_id so dashboards can chain events for
        # dry-run sends. Hash of recipient + issue, prefixed `dry_`.
        fake_id = "dry_" + hashlib.sha256(
            f"{recipient_hash}|{issue_number}".encode()
        ).hexdigest()[:24]
        return SendResult(True, True, fake_id, None, None,
                          int((time.monotonic() - t0) * 1000), 1)

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    from_email = os.environ.get(FROM_EMAIL_ENV, "").strip()
    if not api_key:
        return SendResult(False, False, None, "missing_api_key", None,
                          int((time.monotonic() - t0) * 1000), 0)
    if not from_email:
        return SendResult(False, False, None, "missing_from_email", None,
                          int((time.monotonic() - t0) * 1000), 0)

    body = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html,
        "text": text or html_to_text(html),
        "headers": {
            **list_unsubscribe_headers(recipient_hash, issue_number),
            **(headers_extra or {}),
        },
    }
    reply_to = os.environ.get(REPLY_TO_ENV, "").strip()
    if reply_to:
        body["reply_to"] = reply_to
    if tags:
        # Resend tags: list of {name, value} dicts, name + value must be
        # ASCII letters/digits/underscore/dash (no `:` or spaces).
        body["tags"] = [
            {"name": _safe_tag(k), "value": _safe_tag(str(v))}
            for k, v in tags.items()
        ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    poster = post_override or _post_json
    last_error: Optional[str] = None
    last_detail: Optional[str] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = poster(
                f"{RESEND_API_BASE}/emails",
                headers=headers,
                body=body,
                timeout=TIMEOUT_SECONDS,
            )
        except Exception as e:                            # noqa: BLE001
            last_error = type(e).__name__
            last_detail = str(e)[:200]
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue
            return SendResult(False, False, None, last_error, last_detail,
                              int((time.monotonic() - t0) * 1000), attempt)

        status = getattr(resp, "status_code", 0)
        if status in (200, 201, 202):
            try:
                payload = resp.json() if callable(getattr(resp, "json", None)) else {}
            except Exception:                             # noqa: BLE001
                payload = {}
            message_id = payload.get("id") if isinstance(payload, dict) else None
            return SendResult(True, False, message_id, None, None,
                              int((time.monotonic() - t0) * 1000), attempt)

        # Treat 429 + 5xx as retryable; everything else as fatal.
        last_error = f"http_{status}"
        last_detail = _safe_body(getattr(resp, "text", ""))[:200]
        if status == 429 or 500 <= status < 600:
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue
        return SendResult(False, False, None, last_error, last_detail,
                          int((time.monotonic() - t0) * 1000), attempt)

    return SendResult(False, False, None, last_error or "exhausted_retries",
                      last_detail, int((time.monotonic() - t0) * 1000), MAX_ATTEMPTS)


_TAG_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


def _safe_tag(s: str) -> str:
    # Resend tag names + values must be ASCII letters/digits/underscore/dash.
    return _TAG_NAME_RE.sub("_", s)[:64] or "x"


def _safe_body(b: Any) -> str:
    if isinstance(b, str):
        return b
    if isinstance(b, (bytes, bytearray)):
        try:
            return b.decode("utf-8", errors="replace")
        except Exception:                                 # noqa: BLE001
            return ""
    try:
        return json.dumps(b)
    except Exception:                                     # noqa: BLE001
        return str(b)
