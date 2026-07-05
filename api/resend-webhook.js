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
const { _setUnsubscribed } = require("./_resend_audience");
const { verifySvixSignature: sharedVerifySvixSignature, readRawBody: sharedReadRawBody } = require("./_svix");

const SVIX_SECRET_ENV = "RESEND_WEBHOOK_SECRET";
// Constants kept here for the existing test export contract; the live
// values now come from api/_svix.js which is the single source of truth.
const TIMESTAMP_TOLERANCE_S = 300;          // ±5 minutes
const MAX_BODY_SIZE = 64 * 1024;            // 64 KB

// GUARDRAIL: activation and newsletter sends BOTH route lifecycle events
// through this handler. Event names stay `newsletter.*` for back-compat
// with existing PostHog dashboards/funnels; the `email_type` prop
// (extracted by pickPostHogProps below, sourced from the `email_type`
// tag and `x-pulpo-email-type` header stamped by the sender) is the
// discriminator. Filter `email_type = "newsletter"` to exclude
// activations from deliverability dashboards. See docs/email-audit.md.
const EVENT_MAP = {
  "email.sent":              "newsletter.sent",
  "email.delivered":         "newsletter.delivered",
  "email.opened":            "newsletter.opened",
  "email.clicked":           "newsletter.clicked",
  "email.bounced":           "newsletter.bounced",
  "email.complained":        "newsletter.complained",
  "email.delivery_delayed":  "newsletter.delivery_delayed",
};

// Valid values the upstream senders stamp. Anything else (or missing)
// becomes "unknown" so dashboards still get a non-null axis.
const KNOWN_EMAIL_TYPES = new Set(["newsletter", "activation", "contact", "admin_test"]);

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
  // Audit 2026-06-02 (PRD P0-3): Resend preserves the casing of header
  // keys as the sender stamped them. The newsletter dispatcher stamps
  // `X-Pulpo-Recipient` capitalized but the parser was reading the
  // lowercase variant, so the header fallback never matched. Normalize
  // all header keys to lowercase before lookup — keeps the lookup form
  // ergonomic and tolerant of both casings.
  const rawHeaders = (data.headers && typeof data.headers === "object") ? data.headers : {};
  const headers = {};
  for (const [k, v] of Object.entries(rawHeaders)) {
    if (typeof k === "string") headers[k.toLowerCase()] = v;
  }
  // classification_source lets dashboards distinguish "stamped via tags"
  // from "stamped via headers" from "unstamped/unknown". Useful for
  // catching senders that forgot one branch (the contact-form bug class).
  let recipientSource = null;
  let recipient_hash = tag("recipient_hash");
  if (recipient_hash != null) {
    recipientSource = "tags";
  } else if (typeof headers["x-pulpo-recipient"] === "string") {
    recipient_hash = headers["x-pulpo-recipient"];
    recipientSource = "headers";
  }
  const issue_raw = tag("issue_number") || headers["x-pulpo-issue"] || null;
  const issue_number = issue_raw ? Number.parseInt(issue_raw, 10) : null;
  const message_id = data.email_id || data.id || null;
  // LEARNING: `email_type` discriminates activation vs newsletter lifecycle.
  // Stamped by api/_activation_email.js (activation) and the newsletter
  // dispatcher (newsletter). Filterable downstream in PostHog so existing
  // newsletter.* dashboards can exclude activation pollution without
  // event renames. See docs/email-audit.md for the full audit.
  let emailTypeSource = null;
  const tagEmailType = tag("email_type");
  const headerEmailType = headers["x-pulpo-email-type"];
  let email_type_raw = null;
  if (tagEmailType != null) {
    email_type_raw = tagEmailType;
    emailTypeSource = "tags";
  } else if (typeof headerEmailType === "string") {
    email_type_raw = headerEmailType;
    emailTypeSource = "headers";
  }
  const email_type = email_type_raw && KNOWN_EMAIL_TYPES.has(email_type_raw)
    ? email_type_raw
    : "unknown";
  // classification_source surfaces *why* the parser could/couldn't infer
  // a value. "tags" beats "headers" beats "unknown"; if both axes were
  // present but disagreed, the tag wins (most senders agree, this is
  // belt-and-suspenders for the few that don't).
  let classification_source = "unknown";
  if (emailTypeSource && recipientSource) {
    classification_source = emailTypeSource === recipientSource
      ? emailTypeSource
      : "mixed";
  } else if (emailTypeSource) {
    classification_source = emailTypeSource;
  } else if (recipientSource) {
    classification_source = recipientSource;
  }
  const props = {
    resend_event: event,
    message_id,
    recipient_hash,
    issue_number: Number.isFinite(issue_number) ? issue_number : null,
    email_type,
    classification_source,
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

function pickRecipientEmail(body) {
  const data = (body && body.data) || {};
  const candidates = [
    data.to,
    data.email,
    data.recipient,
    data.recipient_email,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.includes("@")) {
      return candidate.trim();
    }
    if (Array.isArray(candidate)) {
      const first = candidate.find((v) => typeof v === "string" && v.includes("@"));
      if (first) return first.trim();
    }
  }
  return null;
}

// PostHog person id for the recipient. The activation email stamps
// recipient_hash = sha256(email)[:16] — byte-identical to
// api/_posthog.js#emailDistinctId — so its lifecycle events (sent/opened/
// clicked) belong on the SAME person as the post-Stripe conversion funnel
// (webhook.checkout_completed, welcome_modal.shown, signin.completed). Emit
// them under the canonical `email:` prefix so they actually stitch; the
// previous unconditional `user:` prefix orphaned activation events on a
// SEPARATE person despite the identical hash — the activation email → activation
// funnel was unmeasurable (2026-06-30 audit P1-4). Newsletter uses a SALTED,
// 24-char recipient_hash (automation/newsletter/store.py) — a different id
// space that can't be reversed to the funnel person here — so it stays `user:`.
function distinctIdFor(props) {
  if (!props || !props.recipient_hash) return "server:resend_webhook";
  if (props.email_type === "activation") return `email:${props.recipient_hash}`;
  return `user:${props.recipient_hash}`;
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
  const props = pickPostHogProps(eventType, body);
  const distinctId = distinctIdFor(props);

  // Audit 2026-06-02 (PRD P0-4): emit a dedicated, always-on heartbeat
  // event for *every* verified Resend webhook delivery, independent of
  // EVENT_MAP. This is the denominator the webhook-health heartbeat
  // should rely on — `startsWith(event, 'newsletter.')` was matching
  // internal cron events (newsletter.commentary_generated etc.) and
  // keeping the Resend heartbeat green when the actual webhook stopped.
  const heartbeatProps = {
    resend_event: eventType,
    mapped: Boolean(EVENT_MAP[eventType]),
    email_type: props.email_type,
    classification_source: props.classification_source,
  };

  const phEvent = EVENT_MAP[eventType];
  if (!phEvent) {
    // Resend may add new event types we haven't mapped — ack but skip
    // the lifecycle capture. The heartbeat still fires so an unmapped
    // event doesn't masquerade as a webhook outage.
    try {
      capture(distinctId, "resend.webhook_received", heartbeatProps);
      await flush();
    } catch (_err) {
      // Telemetry must not block the webhook.
    }
    logApi({ status: 200, ms: Date.now() - t0, reason: "unmapped_event", type: eventType });
    return res.status(200).json({ ok: true, ignored: true });
  }

  if (eventType === "email.bounced" || eventType === "email.complained") {
    const email = pickRecipientEmail(body);
    const bounceType = props.bounce_type || "";
    const shouldSuppress = eventType === "email.complained"
      || !bounceType
      || /hard|permanent/i.test(String(bounceType));
    if (email && shouldSuppress) {
      try {
        await _setUnsubscribed({
          email,
          unsubscribed: true,
          source: `resend.${eventType}`,
        });
      } catch (err) {
        logApi({
          status: 200, ms: Date.now() - t0,
          reason: "suppression_failed",
          type: eventType,
          error: err && err.message,
        });
      }
    }
  }

  try {
    capture(distinctId, "resend.webhook_received", heartbeatProps);
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
    email_type: props.email_type,
    classification_source: props.classification_source,
  });
  return res.status(200).json({ ok: true });
};

// Test seam exports — Vercel doesn't import these in prod.
module.exports.config = { api: { bodyParser: false } };
module.exports.verifySvixSignature = verifySvixSignature;
module.exports.pickPostHogProps = pickPostHogProps;
module.exports.EVENT_MAP = EVENT_MAP;
module.exports.distinctIdFor = distinctIdFor;
// KNOWN_EMAIL_TYPES is the single source of truth for the discriminator
// allowlist. The producer-tag contract test (tests/api/email_type_contract.test.js)
// imports this and asserts every literal stamped by an outbound sender
// is in the set, so a new sender can't silently land with an unmapped
// email_type that downstream dashboards then bucket as "unknown".
module.exports.KNOWN_EMAIL_TYPES = KNOWN_EMAIL_TYPES;
