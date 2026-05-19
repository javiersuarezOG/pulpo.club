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

const SVIX_SECRET_ENV = "RESEND_WEBHOOK_SECRET";
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

async function readRawBody(req) {
  // Vercel may have already parsed body; we need the RAW string for HMAC.
  if (typeof req.body === "string") {
    return req.body.slice(0, MAX_BODY_SIZE);
  }
  if (req.body && typeof req.body === "object") {
    // Vercel parsed the JSON — reserialize. This is brittle (key order
    // differences invalidate the signature), so the configured Vercel
    // function should set `bodyParser: false` for this route in
    // vercel.json. As a fallback, do a string-stable serialise.
    try {
      return JSON.stringify(req.body);
    } catch {
      return "";
    }
  }
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    const buf = typeof chunk === "string" ? Buffer.from(chunk) : chunk;
    chunks.push(buf);
    total += buf.length;
    if (total > MAX_BODY_SIZE) break;
  }
  return Buffer.concat(chunks).toString("utf8").slice(0, MAX_BODY_SIZE);
}

// Svix sends one or more signatures comma-separated; format is
// `v1,<base64>` per signature. Verify if any one matches.
function verifySvixSignature({ secret, svixId, svixTimestamp, svixSignature, body }) {
  if (!secret || !svixId || !svixTimestamp || !svixSignature || !body) return false;

  // Timestamp freshness.
  const ts = Number.parseInt(svixTimestamp, 10);
  if (!Number.isFinite(ts)) return false;
  const nowS = Math.floor(Date.now() / 1000);
  if (Math.abs(nowS - ts) > TIMESTAMP_TOLERANCE_S) return false;

  // Secret can be passed as `whsec_<base64>` (Svix convention) or as a
  // raw base64 / hex string. Try base64 first; fall back to raw bytes.
  let secretBytes;
  const stripped = secret.startsWith("whsec_") ? secret.slice(6) : secret;
  try {
    secretBytes = Buffer.from(stripped, "base64");
    if (secretBytes.length === 0) secretBytes = Buffer.from(secret, "utf8");
  } catch {
    secretBytes = Buffer.from(secret, "utf8");
  }

  const toSign = `${svixId}.${svixTimestamp}.${body}`;
  const expected = crypto
    .createHmac("sha256", secretBytes)
    .update(toSign)
    .digest("base64");

  const candidates = svixSignature.split(" ").map(s => s.trim()).filter(Boolean);
  for (const c of candidates) {
    // Format: "v1,<sig>"
    const idx = c.indexOf(",");
    if (idx < 0) continue;
    const sig = c.slice(idx + 1);
    if (sig.length === 0) continue;
    if (sig.length !== expected.length) continue;
    try {
      if (crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) {
        return true;
      }
    } catch {
      continue;
    }
  }
  return false;
}

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
