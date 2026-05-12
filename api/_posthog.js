// PostHog server-side client for /api/* endpoints.
//
// Mirrors the interface of automation/posthog_client.py so server-side
// telemetry is consistent across the Python pipeline (nightly enrichment,
// regression guard) and the Node.js Vercel functions (Stripe webhook,
// public checkout endpoint).
//
// Module-level singleton. Reads POSTHOG_PROJECT_TOKEN + POSTHOG_HOST from
// env. When the token is missing or the SDK import fails, capture() is a
// silent no-op — telemetry MUST NOT block a webhook response (Stripe
// would retry on a 5xx).
//
// Identity model:
// - Each capture() takes an explicit distinctId. Most webhook events are
//   keyed on the email (hashed — never raw PII) so subsequent funnel
//   queries chain "start.cta_clicked" (anonymous client-side) → "webhook.
//   checkout_completed" (server-side) via PostHog's alias machinery once
//   the user accepts the Clerk invitation and identify() runs in-app.
// - When no email is available, fall back to "server:webhook" so every
//   anonymous event still buckets somewhere.
//
// Flush model:
// - posthog-node buffers events and flushes periodically (every 20s by
//   default). For a serverless function we need to flush explicitly
//   before the response goes out, otherwise the function instance is
//   frozen mid-buffer and events drop.
//   `flush()` is awaited by the caller after capture() returns.

const crypto = require("crypto");

let _client = null;
let _initAttempted = false;

function _init() {
  if (_initAttempted) return _client;
  _initAttempted = true;
  const token = (process.env.POSTHOG_PROJECT_TOKEN || "").trim();
  if (!token) return null;
  const host = (process.env.POSTHOG_HOST || "https://eu.i.posthog.com").trim();
  try {
    const { PostHog } = require("posthog-node");
    _client = new PostHog(token, {
      host,
      // Tight flush settings so a serverless function doesn't get
      // suspended mid-buffer. The caller's explicit await flush()
      // below is the real gate; these are just safety nets.
      flushAt: 1,
      flushInterval: 0,
    });
  } catch (err) {
    console.warn(`[posthog] init failed (non-fatal): ${err && err.message}`);
    _client = null;
  }
  return _client;
}

// Stable, non-reversible identity for an email. The raw email never
// reaches PostHog (PII minimization). distinctId stays consistent across
// the funnel so events can be chained, but a leaked PostHog dashboard
// won't expose actual addresses.
function emailDistinctId(email) {
  if (!email || typeof email !== "string") return "server:webhook";
  const hash = crypto.createHash("sha256").update(email.trim().toLowerCase()).digest("hex");
  // 16 hex chars = 64 bits, enough entropy for billions of users without
  // collision risk; keeps PostHog Person identifiers compact.
  return `email:${hash.slice(0, 16)}`;
}

// Fire a server-side event. distinctId optional — falls back to a
// generic "server:webhook" bucket. Properties are passed through as-is.
// Never throws; failures log a warning and return silently.
function capture(distinctId, event, properties) {
  const client = _init();
  if (client === null) return;
  try {
    client.capture({
      distinctId: distinctId || "server:webhook",
      event,
      properties: properties || {},
    });
  } catch (err) {
    console.warn(`[posthog] capture failed (non-fatal): ${err && err.message}`);
  }
}

// Await this before the function returns its HTTP response. Without it
// the Vercel runtime suspends the function while events sit in the
// posthog-node buffer, and they're dropped on the next invocation.
async function flush() {
  if (_client === null) return;
  try {
    await _client.flush();
  } catch (err) {
    console.warn(`[posthog] flush failed (non-fatal): ${err && err.message}`);
  }
}

module.exports = {
  capture,
  flush,
  emailDistinctId,
};
