"""POST /api/internal/welcome-send — Vercel Python serverless function.

Instant-delivery path for the Pulpo Pro Welcome. Replaces the
GitHub-Actions-based dispatch in the hot path:

  Stripe webhook (Vercel Node)
    → POST here (Vercel Python, same project, no cold queue)
      → dispatch_welcome() (the same Python that the GH workflow runs)
        → render → Resend → Clerk stamp → PostHog

Latency: ~1-3s end-to-end vs. 15-75s through GitHub Actions.

The webhook keeps the GH Actions dispatcher as a fallback for the
narrow window when this function is unavailable (deploy in progress,
Vercel function outage, etc.). Both paths share the same Clerk
idempotency stamp, so a race is safe — whoever wins the lookup wins
the send; the other no-ops.

Auth: shared secret via `Authorization: Bearer ${PULPO_INTERNAL_TOKEN}`.
The token is also held by the Stripe webhook (Vercel project env);
external callers without the token get a 401 and the function early-
exits before importing the dispatch tree.

Response shape:
  { status: "sent" | "skipped" | "failed",
    reason: "<skip/fail reason>" | null,
    message_id: "<resend id>" | null,
    recipient_hash: "<hash>" | null,
    dry_run: bool,
    latency_ms: int }

Status codes:
  • 200 — sent OR skipped (skip is an expected outcome, not a failure)
  • 400 — bad request body (missing email, malformed JSON)
  • 401 — missing or wrong Authorization header
  • 500 — dispatcher returned status="failed" (caller should fall back)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Vercel's Python runtime adds the deployment root to sys.path
# automatically — `from automation.newsletter.welcome_dispatch import …`
# resolves through the import tracer without any sys.path manipulation
# here. (A manual `sys.path.insert` would defeat the static-analysis
# bundler: the tracer can't follow dynamic path edits, so it would
# fail to detect the import chain and skip bundling the modules.)
#
# Module-level import — runs once per cold start. Cold-start cost:
# ~500ms (httpx + posthog + automation/newsletter source). Warm: <50ms.
from automation.newsletter.welcome_dispatch import dispatch_welcome

# Absolute path to web/data/ranked.json. The default in
# `welcome_dispatch.dispatch_welcome` is the relative form
# "web/data/ranked.json" which resolves against CWD — fine on the GH
# Actions runner (CWD = repo root) but NOT in the Vercel function
# (CWD differs). Resolving once at module load lets every per-request
# call pass the absolute path.
#
# `ranked.json` must be pinned in the function bundle via
# `includeFiles` in vercel.json — the import tracer doesn't see it
# (it's a JSON read, not a Python import). Without that pin, the
# dispatcher exits cleanly with reason=ranked_missing.
_ROOT = Path(__file__).resolve().parents[2]
_RANKED_JSON = str(_ROOT / "web" / "data" / "ranked.json")


_EMAIL_RE = __import__("re").compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_VALID_SOURCES = {"stripe", "stripe.checkout.auth_gated",
                  "stripe.checkout.anonymous_existing_user",
                  "stripe.checkout.anonymous_invitation",
                  "clerk.user_created", "admin", "test"}


def _log(fields: dict) -> None:
    """Single-line stdout log Vercel captures into the function logs.
    Mirror of the JS-side `logApi` shape so the operator can grep by
    the same field names across both runtimes."""
    parts = ["[api]", "internal.welcome-send"]
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    print(" ".join(parts), flush=True)


class handler(BaseHTTPRequestHandler):
    """Vercel Python entry point. Class name `handler` is the runtime
    convention; instances are created per-request by the platform."""

    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject(self, status_code: int, error: str, **extra) -> None:
        self._send_json(status_code, {"error": error, **extra})

    # Silence the default BaseHTTPRequestHandler.log_message — it writes
    # `127.0.0.1 - - [date] "POST ..."` to stderr which Vercel surfaces
    # as a separate log line for every request, polluting the captured
    # output. We log structured fields via `_log` instead.
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:
        t0 = time.monotonic()

        # ── Auth ──────────────────────────────────────────────────────
        # PULPO_INTERNAL_TOKEN is shared with the Stripe webhook via
        # the Vercel project env. Reject anything without it BEFORE
        # parsing the body so an attacker can't probe internals.
        expected_token = (os.environ.get("PULPO_INTERNAL_TOKEN") or "").strip()
        if not expected_token:
            _log({"status": 503, "reason": "internal_token_unset"})
            return self._reject(503, "internal_token_unset",
                                hint="Set PULPO_INTERNAL_TOKEN in Vercel env.")
        provided = self.headers.get("Authorization", "")
        if provided != f"Bearer {expected_token}":
            _log({"status": 401, "reason": "bad_token"})
            return self._reject(401, "unauthorized")

        # ── Body parse ────────────────────────────────────────────────
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0 or content_length > 4096:
            _log({"status": 400, "reason": "bad_content_length",
                  "content_length": content_length})
            return self._reject(400, "bad_content_length")
        try:
            raw = self.rfile.read(content_length).decode("utf-8")
            body = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            _log({"status": 400, "reason": "bad_json"})
            return self._reject(400, "bad_json")
        if not isinstance(body, dict):
            return self._reject(400, "bad_json")

        # ── Validate inputs ───────────────────────────────────────────
        email = body.get("email")
        if not isinstance(email, str):
            return self._reject(400, "missing_email")
        email = email.strip().lower()
        if not _EMAIL_RE.match(email):
            return self._reject(400, "invalid_email")

        source = body.get("source") or "admin"
        if not isinstance(source, str) or source not in _VALID_SOURCES:
            _log({"status": 400, "reason": "invalid_source", "source": source})
            return self._reject(400, "invalid_source",
                                hint=f"source must be one of: {sorted(_VALID_SOURCES)}")

        locale = body.get("locale")
        if locale is not None and locale not in ("en", "es"):
            return self._reject(400, "invalid_locale")

        force = bool(body.get("force", False))

        # Resubscribe re-acquisition (welcome-back) inputs. `variant`
        # lets an admin/test caller pin the welcome-back template;
        # `allow_resubscribe` lets the Stripe checkout path auto-route a
        # returning subscriber to welcome-back; `subscription_id` is the
        # welcome-back dedup key. All optional — absent = first-time
        # welcome behavior, unchanged.
        variant = body.get("variant") or "welcome"
        if not isinstance(variant, str) or variant not in ("welcome", "welcome_back"):
            return self._reject(400, "invalid_variant",
                                hint="variant must be 'welcome' or 'welcome_back'")
        allow_resubscribe = bool(body.get("allow_resubscribe", False))
        subscription_id = body.get("subscription_id")
        if subscription_id is not None and not isinstance(subscription_id, str):
            return self._reject(400, "invalid_subscription_id")

        # ── Dispatch ──────────────────────────────────────────────────
        # dispatch_welcome handles its own Clerk lookup, idempotency
        # check, render, send, stamp, telemetry. We just translate
        # the result shape into a JSON response + status code.
        try:
            result = dispatch_welcome(
                email=email,
                locale=locale,
                source=source,
                force=force,
                ranked_path=_RANKED_JSON,
                variant=variant,
                allow_resubscribe=allow_resubscribe,
                subscription_id=subscription_id,
            )
        except Exception as exc:                                     # noqa: BLE001
            # Unhandled dispatcher exception. Log the traceback for
            # debugging but return 500 so the webhook falls back to
            # GH Actions — the welcome still has a path to delivery.
            tb = traceback.format_exc()
            _log({
                "status": 500, "reason": "dispatcher_exception",
                "error": str(exc).replace("\n", " ")[:200],
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            })
            print(f"[api] internal.welcome-send traceback:\n{tb}", flush=True)
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
        # status="sent" + status="skipped" both map to 200 (skips are
        # expected outcomes — already_sent, not_pro, etc.). status=
        # "failed" maps to 500 so the webhook caller knows to invoke
        # the GH Actions fallback.
        if result.status == "failed":
            _log({
                "status": 500, "result": "failed", "reason": result.reason,
                "elapsed_ms": elapsed_ms,
            })
            return self._send_json(500, payload)

        _log({
            "status": 200, "result": result.status, "reason": result.reason or "-",
            "elapsed_ms": elapsed_ms, "dry_run": result.dry_run,
        })
        return self._send_json(200, payload)

    def do_GET(self) -> None:
        # Health-check surface. Returns 200 with the function metadata
        # so an external monitor (or a manual `curl`) can confirm
        # the Python function is deployed and reachable WITHOUT
        # sending an actual welcome.
        self._send_json(200, {
            "ok": True,
            "function": "internal.welcome-send",
            "runtime": f"python{sys.version_info.major}.{sys.version_info.minor}",
        })
