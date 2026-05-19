// POST /api/resend-webhook
//
// Receives Resend's email lifecycle webhooks (sent / delivered / opened /
// clicked / bounced / complained / delivery_delayed) and re-emits them as
// PostHog events keyed on the recipient hash + issue id stamped in the
// outbound `headers.x-pulpo-issue` + `tags.recipient_hash`.
//
// Signature verification:
//   Resend signs with Svix. Headers carry `svix-id`, `svix-timestamp`,
//   `svix-signature`. We verify HMAC-SHA256 over `${id}.${ts}.${body}`
//   using `RESEND_WEBHOOK_SECRET`. Constant-time compare. Timestamp
//   freshness gate: ±5 minutes.
//
// Event mapping:
//   email.sent              → newsletter.sent
//   email.delivered         → newsletter.delivered
//   email.opened            → newsletter.opened
//   email.clicked           → newsletter.clicked
//   email.bounced           → newsletter.bounced
//   email.complained        → newsletter.complained
//   email.delivery_delayed  → newsletter.delivery_delayed
//
// All events carry: issue_number, recipient_hash, message_id, resend_event,
// (clicked-only) target_url.

const crypto = require("crypto");
const { capture, flush } = require("./_posthog");
const { verifySvixSignature: sharedVerifySvixSignature, readRawBody: sharedReadRawBody } = require("./_svix");

const SVIX_SECRET_ENV = "RESEND_WEBHOOK_SECRET";
// Constants kept here for the existing test export contract; the live
// values now come from api/_svix.js which is the single source of truth.
const TIMESTAMP_TOLERANCE_S = 300;          // ±5 minutes
const MAX_BODY_SIZE = 64 * 1024;            // 64 KB

const EVENT_MAP = {
  "email.sent":              "newsletter.sent",
  "email.delivered":         "newsletter.delivered",
  "email.opened":            "newsletter.opened",
  "email.clicked":           "newsletter.clicked",
  "email.bounced":           "newsletter.bounced",
  "email.complained":        "newsletter.complained",
  "email.delivery_delayed":  "newsletter.delivery_delayed",
};

function logApi(fields) {
  const parts = ["[api]", "resend_webhook"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

// Backwards-compatible re-exports — the test seam still pulls these
// names off this module. Implementation lives in api/_svix.js as the
// shared source of truth across webhook handlers (Resend, Clerk, etc).
const readRawBody = sharedReadRawBody;
const verifySvixSignature = sharedVerifySvixSignature;

function pickPostHogProps(event, body) {
  const data = (body && body.data) || {};
  const tags = Array.isArray(data.tags) ? data.tags : [];
  const tag = (name) => {
    const row = tags.find(t => t && t.name === name);
    return row && typeof row.value === "string" ? row.value : null;
  };
  const headers = (data.headers && typeof data.headers === "object") ? data.headers : {};
  const recipient_hash = tag("recipient_hash") || headers["x-pulpo-recipient"] || null;
  const issue_raw = tag("issue_number") || headers["x-pulpo-issue"] || null;
  const issue_number = issue_raw ? Number.parseInt(issue_raw, 10) : null;
  const message_id = data.email_id || data.id || null;
  const props = {
    resend_event: event,
    message_id,
    recipient_hash,
    issue_number: Number.isFinite(issue_number) ? issue_number : null,
  };
  if (event === "email.clicked") {
    const click = (data.click && typeof data.click === "object") ? data.click : {};
    props.target_url = click.link || null;
  }
  if (event === "email.bounced") {
    props.bounce_type = (data.bounce && data.bounce.type) || null;
  }
  return props;
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi({ status: 405, ms: Date.now() - t0, reason: "method", method: req.method });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const secret = process.env[SVIX_SECRET_ENV] || "";
  if (!secret) {
    // Degrade to 503 rather than 500 — operator hasn't wired the env yet.
    logApi({ status: 503, ms: Date.now() - t0, reason: "no_secret" });
    return res.status(503).json({ error: "not_configured" });
  }

  const raw = await readRawBody(req);
  const svixId        = req.headers["svix-id"]        || req.headers["Svix-Id"]        || "";
  const svixTimestamp = req.headers["svix-timestamp"] || req.headers["Svix-Timestamp"] || "";
  const svixSignature = req.headers["svix-signature"] || req.headers["Svix-Signature"] || "";

  const ok = verifySvixSignature({
    secret,
    svixId: String(svixId),
    svixTimestamp: String(svixTimestamp),
    svixSignature: String(svixSignature),
    body: raw,
  });
  if (!ok) {
    logApi({
      status: 401, ms: Date.now() - t0, reason: "bad_signature",
      svix_id: String(svixId).slice(0, 12),
    });
    return res.status(401).json({ error: "bad_signature" });
  }

  let body;
  try { body = JSON.parse(raw); } catch { body = null; }
  if (!body || typeof body !== "object") {
    logApi({ status: 400, ms: Date.now() - t0, reason: "bad_json" });
    return res.status(400).json({ error: "bad_json" });
  }

  const eventType = typeof body.type === "string" ? body.type : "";
  const phEvent = EVENT_MAP[eventType];
  if (!phEvent) {
    // Resend may add new event types we haven't mapped — ack but skip.
    logApi({ status: 200, ms: Date.now() - t0, reason: "unmapped_event", type: eventType });
    return res.status(200).json({ ok: true, ignored: true });
  }

  const props = pickPostHogProps(eventType, body);
  const distinctId = props.recipient_hash ? `user:${props.recipient_hash}` : "server:resend_webhook";
  try {
    capture(distinctId, phEvent, props);
    await flush();
  } catch (err) {
    // Telemetry must not block the webhook — Resend retries on 5xx.
    logApi({
      status: 200, ms: Date.now() - t0, reason: "posthog_failed",
      event: phEvent, error: err && err.message,
    });
    return res.status(200).json({ ok: true, telemetry: "failed" });
  }

  logApi({
    status: 200, ms: Date.now() - t0,
    event: phEvent, recipient_hash: props.recipient_hash || "anon",
    issue_number: props.issue_number != null ? props.issue_number : "?",
  });
  return res.status(200).json({ ok: true });
};

// Test seam exports — Vercel doesn't import these in prod.
module.exports.verifySvixSignature = verifySvixSignature;
module.exports.pickPostHogProps = pickPostHogProps;
module.exports.EVENT_MAP = EVENT_MAP;
