#!/usr/bin/env bash
# Local smoke test for /api/clerk/webhook.
#
# Confirms that the handler boots, the env var gating works, and a
# valid Svix-signed event lands a 200. Does NOT call Clerk, PostHog,
# or any other external service — pure local handler exercise.
#
# Use when you want to confirm the deployed handler will work before
# you go configure the Clerk Dashboard webhook endpoint. Run against
# either a local dev server (npm run dev) or a Vercel preview URL.
#
# Usage:
#   bash scripts/clerk_webhook_smoke.sh                       # against http://localhost:5173
#   bash scripts/clerk_webhook_smoke.sh https://your-preview.vercel.app
#
# Requirements: curl, openssl, jq (optional but nicer output).

set -euo pipefail

BASE_URL="${1:-http://localhost:5173}"
ENDPOINT="${BASE_URL%/}/api/clerk/webhook"
echo "Smoke-testing: $ENDPOINT"
echo

have_jq() { command -v jq >/dev/null 2>&1; }
pretty() { if have_jq; then jq -C .; else cat; fi; }

# --- 1. 405 on GET ---
echo "[1/5] GET should return 405:"
status=$(curl -sS -o /tmp/clerk_smoke_1 -w "%{http_code}" "$ENDPOINT")
if [ "$status" = "405" ]; then echo "  OK (405)"; else echo "  FAIL got $status"; cat /tmp/clerk_smoke_1; exit 1; fi
echo

# --- 2. 503 / 401 on POST without signing secret ---
# If CLERK_WEBHOOK_SECRET is unset → 503 not_configured.
# If it's set → handler reaches signature verify which fails → 401.
# Either is a healthy proof that the handler is wired up.
echo "[2/5] POST without Svix headers should return 503 (env unset) or 401 (bad sig):"
status=$(curl -sS -o /tmp/clerk_smoke_2 -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d '{}' "$ENDPOINT")
if [ "$status" = "503" ] || [ "$status" = "401" ]; then
  echo "  OK ($status): $(cat /tmp/clerk_smoke_2)"
else
  echo "  FAIL got $status"; cat /tmp/clerk_smoke_2; exit 1
fi
echo

# --- 3. POST with bogus Svix headers → 401 ---
echo "[3/5] POST with bogus Svix sig should return 401 (when secret is configured):"
status=$(curl -sS -o /tmp/clerk_smoke_3 -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -H "svix-id: msg_test" \
  -H "svix-timestamp: $(date +%s)" \
  -H "svix-signature: v1,bogus" \
  -d '{"type":"invitation.created","data":{}}' "$ENDPOINT")
if [ "$status" = "401" ] || [ "$status" = "503" ]; then
  echo "  OK ($status): $(cat /tmp/clerk_smoke_3)"
else
  echo "  FAIL got $status"; cat /tmp/clerk_smoke_3; exit 1
fi
echo

# --- 4. With a valid signature — only runs if CLERK_WEBHOOK_SECRET is exported ---
if [ -n "${CLERK_WEBHOOK_SECRET:-}" ]; then
  echo "[4/5] CLERK_WEBHOOK_SECRET detected — sending a valid signed email.created event:"
  TS=$(date +%s)
  ID="msg_smoke_$(date +%s)"
  BODY='{"type":"email.created","data":{"id":"ema_smoke","to_email_address":"smoke@example.com","slug":"invitation","delivered_by_clerk":true,"status":"delivered"}}'

  # Strip whsec_ prefix (Svix convention) and base64-decode.
  KEY_B64="${CLERK_WEBHOOK_SECRET#whsec_}"
  # macOS base64 lacks -d; both -d and -D work cross-platform.
  KEY_BIN=$(printf '%s' "$KEY_B64" | base64 -d 2>/dev/null || printf '%s' "$KEY_B64" | base64 -D 2>/dev/null)
  TO_SIGN="${ID}.${TS}.${BODY}"
  SIG=$(printf '%s' "$TO_SIGN" | openssl dgst -sha256 -hmac "$KEY_BIN" -binary | base64)

  status=$(curl -sS -o /tmp/clerk_smoke_4 -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    -H "svix-id: $ID" \
    -H "svix-timestamp: $TS" \
    -H "svix-signature: v1,$SIG" \
    -d "$BODY" "$ENDPOINT")
  if [ "$status" = "200" ]; then
    echo "  OK (200): $(cat /tmp/clerk_smoke_4)"
  else
    echo "  FAIL got $status: $(cat /tmp/clerk_smoke_4)"; exit 1
  fi
else
  echo "[4/5] CLERK_WEBHOOK_SECRET not exported — skipping signed-event test."
  echo "      To exercise: export CLERK_WEBHOOK_SECRET=<your-secret> && re-run."
fi
echo

# --- 5. Tell Sebas what to do next ---
echo "[5/5] Next steps (Sebas):"
echo "  1. Clerk Dashboard → Webhooks → Add Endpoint:"
echo "     URL: ${BASE_URL%/}/api/clerk/webhook"
echo "     Events: email.created, invitation.created, invitation.accepted,"
echo "             invitation.revoked, user.created"
echo "  2. Copy the Signing Secret to Vercel env (all envs): CLERK_WEBHOOK_SECRET"
echo "  3. Click 'Test' in Clerk Dashboard — should produce a clerk.email_attempted"
echo "     event in PostHog within a few seconds."
echo "  4. Trigger a fresh Stripe-sandbox checkout. Watch PostHog for the full"
echo "     sequence ending in clerk.email_attempted[delivered_by_clerk=<bool>]."
echo
echo "All local smoke checks passed."
