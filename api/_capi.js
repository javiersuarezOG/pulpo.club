// Server-side conversion API (CAPI) dispatch — fires Purchase conversions to
// ad networks from the Stripe webhook, where the email + amount + UTMs already
// land. Chosen over browser pixels (2026-06-30 audit P0-2) because it needs no
// new "marketing" cookie-consent category, is ad-blocker proof, and keeps any
// pixel off the client CSP.
//
// Identity: the email is hashed (SHA-256, normalized) before it leaves this
// module — the raw address never reaches Meta/Google. The Stripe event id is
// reused as the CAPI event_id so a future browser pixel firing the same
// Purchase would be de-duplicated by the network.
//
// Everything here is ENV-GATED and best-effort: with no credentials set each
// sender returns { skipped: "unconfigured" } and the webhook is unaffected.
// Ships DARK until the tokens are provisioned in Vercel.
//
// Meta Conversions API (works with just a pixel id + token — no click id):
//   META_PIXEL_ID           — the Meta Pixel / dataset id
//   META_CAPI_ACCESS_TOKEN  — a system-user token with ads_management
//   META_CAPI_API_VERSION   — optional, defaults to v21.0
//   META_CAPI_TEST_CODE     — optional, Events Manager "Test events" code
//
// Google Ads (Enhanced Conversions for Web via uploadClickConversions):
//   GOOGLE_ADS_DEVELOPER_TOKEN
//   GOOGLE_ADS_CUSTOMER_ID          — digits only (dashes stripped)
//   GOOGLE_ADS_CONVERSION_ACTION_ID — the conversion action's numeric id
//   GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET / GOOGLE_ADS_REFRESH_TOKEN
//   GOOGLE_ADS_LOGIN_CUSTOMER_ID    — optional MCC id
//   Google also needs a `gclid` on the conversion, which start-checkout.js does
//   not yet forward into Stripe metadata — until it does, sendGoogleConversion
//   no-ops with { skipped: "no_gclid" }. Follow-up: capture gclid in
//   campaign.ts → checkout metadata (Meta CAPI needs no click id, so it works
//   as soon as its two env vars are set).

const crypto = require("crypto");

const DEFAULT_TIMEOUT_MS = 4000; // bound the webhook-response latency impact

function sha256Hex(s) {
  return crypto.createHash("sha256").update(String(s)).digest("hex");
}

// Meta/Google hashing rule: trim + lowercase, then SHA-256. Email only (we
// don't collect phone/name). Returns null for empty so we never send an empty
// hash (which the networks reject / mis-attribute).
function hashEmail(email) {
  if (!email || typeof email !== "string") return null;
  const norm = email.trim().toLowerCase();
  if (!norm) return null;
  return sha256Hex(norm);
}

async function fetchWithTimeout(fetchImpl, url, opts, ms) {
  const f = fetchImpl || fetch;
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), ms || DEFAULT_TIMEOUT_MS);
  try {
    return await f(url, { ...opts, signal: controller.signal });
  } finally {
    clearTimeout(tid);
  }
}

// ── Meta Conversions API ──────────────────────────────────────────────────

const META_API_VERSION = process.env.META_CAPI_API_VERSION || "v21.0";

// Pure — build the Meta Conversions API request body for a Purchase. Exported
// for unit tests (no network). `valueCents` is Stripe's integer minor unit;
// Meta wants the major-unit value.
function buildMetaPurchasePayload({ email, valueCents, currency, eventId, eventSourceUrl, fbc, fbp, clientIp, userAgent, eventTime } = {}) {
  const em = hashEmail(email);
  const userData = {};
  if (em) userData.em = [em];
  if (fbc) userData.fbc = fbc;
  if (fbp) userData.fbp = fbp;
  if (clientIp) userData.client_ip_address = clientIp;
  if (userAgent) userData.client_user_agent = userAgent;
  const evt = {
    event_name: "Purchase",
    event_time: eventTime || Math.floor(Date.now() / 1000),
    action_source: "website",
    user_data: userData,
    custom_data: {
      currency: (currency || "usd").toLowerCase(),
      value: typeof valueCents === "number" ? Math.round(valueCents) / 100 : 0,
    },
  };
  if (eventId) evt.event_id = eventId;              // de-dup key for a paired pixel
  if (eventSourceUrl) evt.event_source_url = eventSourceUrl;
  return { data: [evt] };
}

// Fire the Meta Purchase conversion. Best-effort, never throws.
async function sendMetaConversion(args, { fetchImpl } = {}) {
  const pixelId = (process.env.META_PIXEL_ID || "").trim();
  const token = (process.env.META_CAPI_ACCESS_TOKEN || "").trim();
  if (!pixelId || !token) return { skipped: "unconfigured" };
  const hasIdentifier = hashEmail(args && args.email) || (args && (args.fbc || args.fbp));
  if (!hasIdentifier) return { skipped: "no_identifier" };
  const payload = buildMetaPurchasePayload(args);
  const testCode = (process.env.META_CAPI_TEST_CODE || "").trim();
  if (testCode) payload.test_event_code = testCode;
  const url = `https://graph.facebook.com/${META_API_VERSION}/${encodeURIComponent(pixelId)}/events?access_token=${encodeURIComponent(token)}`;
  try {
    const r = await fetchWithTimeout(fetchImpl, url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return {
      sent: r.ok, status: r.status, network: "meta",
      fbtrace_id: body && body.fbtrace_id,
      error: r.ok ? undefined : (body && body.error && body.error.message) || `http_${r.status}`,
    };
  } catch (err) {
    return { sent: false, network: "meta", error: (err && err.message) || "fetch_failed" };
  }
}

// ── Google Ads (Enhanced Conversions for Web) ─────────────────────────────

// Exchange the long-lived refresh token for a short-lived access token.
async function googleAccessToken(fetchImpl) {
  const client_id = (process.env.GOOGLE_ADS_CLIENT_ID || "").trim();
  const client_secret = (process.env.GOOGLE_ADS_CLIENT_SECRET || "").trim();
  const refresh_token = (process.env.GOOGLE_ADS_REFRESH_TOKEN || "").trim();
  if (!client_id || !client_secret || !refresh_token) return null;
  try {
    const r = await fetchWithTimeout(fetchImpl, "https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ client_id, client_secret, refresh_token, grant_type: "refresh_token" }).toString(),
    });
    if (!r.ok) return null;
    const body = await r.json().catch(() => null);
    return body && body.access_token ? body.access_token : null;
  } catch {
    return null;
  }
}

// Pure — build the uploadClickConversions body. `conversionDateTime` must be
// "yyyy-mm-dd hh:mm:ss+|-hh:mm" per the Google Ads API.
function buildGoogleClickConversion({ gclid, conversionActionResource, valueCents, currency, conversionDateTime, orderId } = {}) {
  const conv = {
    gclid,
    conversionAction: conversionActionResource,
    conversionDateTime,
    conversionValue: typeof valueCents === "number" ? Math.round(valueCents) / 100 : 0,
    currencyCode: (currency || "USD").toUpperCase(),
  };
  if (orderId) conv.orderId = orderId;
  return { conversions: [conv], partialFailure: true };
}

async function sendGoogleConversion(args, { fetchImpl } = {}) {
  const customerId = (process.env.GOOGLE_ADS_CUSTOMER_ID || "").replace(/-/g, "").trim();
  const actionId = (process.env.GOOGLE_ADS_CONVERSION_ACTION_ID || "").trim();
  const devToken = (process.env.GOOGLE_ADS_DEVELOPER_TOKEN || "").trim();
  if (!customerId || !actionId || !devToken) return { skipped: "unconfigured" };
  // Click-conversion upload requires a gclid; start-checkout.js does not yet
  // forward it into Stripe metadata (only the 5 UTMs). Until it does, no-op.
  if (!args || !args.gclid) return { skipped: "no_gclid" };
  if (!args.conversionDateTime) return { skipped: "no_conversion_time" };
  const accessToken = await googleAccessToken(fetchImpl);
  if (!accessToken) return { skipped: "no_access_token" };
  const payload = buildGoogleClickConversion({
    gclid: args.gclid,
    conversionActionResource: `customers/${customerId}/conversionActions/${actionId}`,
    valueCents: args.valueCents,
    currency: args.currency,
    conversionDateTime: args.conversionDateTime,
    orderId: args.eventId,
  });
  const headers = {
    "content-type": "application/json",
    authorization: `Bearer ${accessToken}`,
    "developer-token": devToken,
  };
  const loginCid = (process.env.GOOGLE_ADS_LOGIN_CUSTOMER_ID || "").replace(/-/g, "").trim();
  if (loginCid) headers["login-customer-id"] = loginCid;
  try {
    const r = await fetchWithTimeout(fetchImpl, `https://googleads.googleapis.com/v17/customers/${customerId}:uploadClickConversions`, {
      method: "POST", headers, body: JSON.stringify(payload),
    });
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return {
      sent: r.ok, status: r.status, network: "google",
      error: r.ok ? undefined : String((body && body.error && body.error.message) || `http_${r.status}`).slice(0, 300),
    };
  } catch (err) {
    return { sent: false, network: "google", error: (err && err.message) || "fetch_failed" };
  }
}

// Orchestrator — fire every configured network for one purchase, concurrently.
// Best-effort: each sender no-ops when unconfigured and never throws, so this
// NEVER rejects and NEVER blocks the Stripe webhook beyond the bounded fetch
// timeout. Returns per-network results for the caller to log to PostHog.
async function sendPurchaseConversions(args, opts) {
  const [meta, google] = await Promise.all([
    sendMetaConversion(args, opts).catch((e) => ({ sent: false, network: "meta", error: (e && e.message) || "threw" })),
    sendGoogleConversion(args, opts).catch((e) => ({ sent: false, network: "google", error: (e && e.message) || "threw" })),
  ]);
  return { meta, google };
}

// True when at least one network is fully credentialed — lets the caller skip
// the whole block (and its PostHog event) when the feature is dark.
function isAnyConfigured() {
  const meta = Boolean(process.env.META_PIXEL_ID && process.env.META_CAPI_ACCESS_TOKEN);
  const google = Boolean(
    process.env.GOOGLE_ADS_CUSTOMER_ID
    && process.env.GOOGLE_ADS_CONVERSION_ACTION_ID
    && process.env.GOOGLE_ADS_DEVELOPER_TOKEN,
  );
  return meta || google;
}

// Compact per-network status string for the PostHog `conversion.capi_sent`
// event: "sent" | the skip reason | "error".
function resultStatus(r) {
  if (!r) return "none";
  if (r.sent) return "sent";
  if (r.skipped) return r.skipped;
  return "error";
}

module.exports = {
  sendPurchaseConversions,
  sendMetaConversion,
  sendGoogleConversion,
  buildMetaPurchasePayload,
  buildGoogleClickConversion,
  hashEmail,
  isAnyConfigured,
  resultStatus,
};
