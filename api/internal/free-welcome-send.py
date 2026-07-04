"""POST /api/internal/free-welcome-send — Vercel Python serverless function.

Internal instant-delivery path for the free welcome / welcome-back emails.
It mirrors api/internal/welcome-send.py but uses the DB-free free dispatcher:
no Clerk lookup, caller-provided idempotency, and force=true for admin tests.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from automation.newsletter.free_welcome_dispatch import dispatch_free_welcome

_ROOT = Path(__file__).resolve().parents[2]
_RANKED_JSON = str(_ROOT / "web" / "data" / "ranked.json")
_EMAIL_RE = __import__("re").compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# Producers that may call this endpoint. Each is a telemetry discriminator,
# not just a gate — keep it in sync with every caller of fireFreeWelcome:
#   signup / resend_resubscribe → api/newsletter.js (homepage form)
#   unsubscribe_page_resub      → api/unsubscribe.js (one-click Resubscribe
#                                 on the unsubscribe confirmation page)
#   stripe_downgrade            → Pro→free churn welcome-back
#   admin / test                → admin trigger + tests
# Adding a new caller = add its source here in the SAME PR, or the endpoint
# 400s `invalid_source` and the email silently never sends.
_VALID_SOURCES = {
    "signup",
    "stripe_downgrade",
    "resend_resubscribe",
    "unsubscribe_page_resub",
    "admin",
    "test",
}


def _log(fields: dict) -> None:
    parts = ["[api]", "internal.free-welcome-send"]
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    print(" ".join(parts), flush=True)


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject(self, status_code: int, error: str, **extra) -> None:
        self._send_json(status_code, {"error": error, **extra})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:
        t0 = time.monotonic()

        expected_token = (os.environ.get("PULPO_INTERNAL_TOKEN") or "").strip()
        if not expected_token:
            _log({"status": 503, "reason": "internal_token_unset"})
            return self._reject(503, "internal_token_unset")
        provided = self.headers.get("Authorization", "")
        if provided != f"Bearer {expected_token}":
            _log({"status": 401, "reason": "bad_token"})
            return self._reject(401, "unauthorized")

        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0 or content_length > 4096:
            return self._reject(400, "bad_content_length")
        try:
            raw = self.rfile.read(content_length).decode("utf-8")
            body = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._reject(400, "bad_json")
        if not isinstance(body, dict):
            return self._reject(400, "bad_json")

        email = body.get("email")
        if not isinstance(email, str):
            return self._reject(400, "missing_email")
        email = email.strip().lower()
        if not _EMAIL_RE.match(email):
            return self._reject(400, "invalid_email")

        variant = body.get("variant") or "free_welcome"
        if variant not in ("free_welcome", "free_welcome_back"):
            return self._reject(400, "invalid_variant",
                                hint="variant must be 'free_welcome' or 'free_welcome_back'")
        locale = body.get("locale") or "en"
        if locale not in ("en", "es"):
            return self._reject(400, "invalid_locale")
        source = body.get("source") or "admin"
        if not isinstance(source, str) or source not in _VALID_SOURCES:
            return self._reject(400, "invalid_source",
                                hint=f"source must be one of: {sorted(_VALID_SOURCES)}")
        force = bool(body.get("force", False))
        display_name = body.get("display_name")
        if display_name is not None and not isinstance(display_name, str):
            return self._reject(400, "invalid_display_name")
        is_new_contact = bool(body.get("is_new_contact", True))

        try:
            result = dispatch_free_welcome(
                email=email,
                variant=variant,
                locale=locale,
                display_name=display_name.strip() if isinstance(display_name, str) else None,
                source=source,
                ranked_path=_RANKED_JSON,
                is_new_contact=is_new_contact,
                force=force,
            )
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            _log({
                "status": 500, "reason": "dispatcher_exception",
                "error": str(exc).replace("\n", " ")[:200],
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            })
            print(f"[api] internal.free-welcome-send traceback:\n{tb}", flush=True)
            return self._reject(500, "dispatcher_exception", detail=str(exc)[:200])

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        payload = {
            "status": result.status,
            "reason": result.reason,
            "message_id": result.message_id,
            "recipient_hash": result.recipient_hash,
            "dry_run": result.dry_run,
            "latency_ms": elapsed_ms,
        }
        if result.status == "failed":
            _log({"status": 500, "result": "failed", "reason": result.reason,
                  "elapsed_ms": elapsed_ms})
            return self._send_json(500, payload)

        _log({"status": 200, "result": result.status, "reason": result.reason or "-",
              "elapsed_ms": elapsed_ms, "dry_run": result.dry_run})
        return self._send_json(200, payload)

    def do_GET(self) -> None:
        self._send_json(200, {
            "ok": True,
            "function": "internal.free-welcome-send",
            "runtime": f"python{sys.version_info.major}.{sys.version_info.minor}",
        })
