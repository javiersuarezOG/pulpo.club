// POST /api/clerk/webhook
//
// Receives Clerk's Svix-signed lifecycle webhooks and re-emits them as
// PostHog events, keyed on an email hash so the post-Stripe activation
// funnel auto-joins with `webhook.checkout_completed`:
//
//   webhook.received                       (api/stripe/webhook.js)
//     → webhook.checkout_completed         (api/stripe/webhook.js, invitation_id)
//       → clerk.invitation_created         (this handler — Clerk's own confirmation)
//         → clerk.email_attempted          (this handler — IS Clerk actually sending?)
//           → clerk.invitation_accepted    (this handler — activation success signal)
//             → clerk.user_created         (this handler — user record minted)
//               → signin.completed         (client-side)
//
// The whole point: without this handler we have no server-side signal
// of whether Clerk's send pipeline even attempted to dispatch the
// activation email. Clerk's audit log doesn't surface email events at
// every plan tier, so PostHog becomes the durable observability surface.
//
// Signature verification: Clerk signs with Svix. Headers carry `svix-id`,
// `svix-timestamp`, `svix-signature`. We delegate the HMAC math to the
// shared verifier at api/_svix.js — same path as api/resend-webhook.js.
//
// Auth: `CLERK_WEBHOOK_SECRET` env var (signing secret from Clerk
// Dashboard → Webhooks → endpoint). Without it the handler returns 503
// (gracefully disabled), not 500.
//
// Event mapping:
//   email.created       → clerk.email_attempted
//   invitation.created  → clerk.invitation_created
//   invitation.accepted → clerk.invitation_accepted
//   invitation.revoked  → clerk.invitation_revoked
//   user.created        → clerk.user_created
//
// Anything else returns 200 + ignored:true so Clerk doesn't retry.

const crypto = require("crypto");
const { verifySvixSignature, readRawBody } = require("../_svix");
const { capture, emailDistinctId, flush } = require("../_posthog");

const SVIX_SECRET_ENV = "CLERK_WEBHOOK_SECRET";

const EVENT_MAP = {
  "email.created":       "clerk.email_attempted",
  "invitation.created":  "clerk.invitation_created",
  "invitation.accepted": "clerk.invitation_accepted",
  "invitation.revoked":  "clerk.invitation_revoked",
  "user.created":        "clerk.user_created",
};

function logApi(fields) {
  const parts = ["[api]", "clerk_webhook"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

// PII-safe email hash so PostHog Person identities chain anon→signed-in
// without ever storing a raw address. Mirrors emailDistinctId but returns
// just the hash slice so it can also be stamped as a property (the
// distinctId is the same string with the "email:" prefix). null when no
// email is known on the event.
function hashEmail(email) {
  if (!email || typeof email !== "string") return null;
  const h = crypto.createHash("sha256").update(email.trim().toLowerCase()).digest("hex");
  return h.slice(0, 16);
}

// Map Clerk's event payload to a flat props bag for PostHog. Schema is
// stable across event types where it makes sense (e.g. `email_hash`,
// `invitation_id`); event-specific props get added on top. Reference for
// payload shape: https://clerk.com/docs/integrations/webhooks/overview
function pickPostHogProps(eventType, body) {
  const data = (body && body.data) || {};
  const props = { clerk_event: eventType };

  if (eventType === "email.created") {
    const toEmail = data.to_email_address || (data.email_address && data.email_address.email_address) || null;
    props.slug = data.slug || data.email_address_id || null;
    props.delivered_by_clerk = typeof data.delivered_by_clerk === "boolean"
      ? data.delivered_by_clerk
      : null;
    props.status = data.status || null;
    props.email_hash = hashEmail(toEmail);
    props.message_subject = typeof data.subject === "string" ? data.subject.slice(0, 200) : null;
    props.message_id = data.id || data.email_id || null;
    return props;
  }

  if (eventType === "invitation.created" || eventType === "invitation.accepted" || eventType === "invitation.revoked") {
    props.invitation_id = data.id || data.invitation_id || null;
    props.email_hash = hashEmail(data.email_address);
    if (eventType === "invitation.created") {
      props.expires_at = data.expires_at || null;
      // redirect_url isn't PII; keeping it helps debugging.
      props.redirect_url = data.public_metadata && data.public_metadata.redirect_url
        ? data.public_metadata.redirect_url
        : (data.redirect_url || null);
    }
    if (eventType === "invitation.accepted") {
      props.user_id = data.accepted_by_user_id || null;
    }
    return props;
  }

  if (eventType === "user.created") {
    props.user_id = data.id || null;
    // Clerk's user.created carries a list of email_addresses; pick the
    // primary so we can hash for join.
    const primaryEmailId = data.primary_email_address_id || null;
    const emails = Array.isArray(data.email_addresses) ? data.email_addresses : [];
    const primary = emails.find(e => e && e.id === primaryEmailId) || emails[0] || null;
    const rawEmail = primary && primary.email_address ? primary.email_address : null;
    props.email_hash = hashEmail(rawEmail);
    // Distinguish "user came in via Clerk invitation" from "user came
    // in via direct signup" so we can split the funnel cleanly.
    props.source = data.private_metadata && data.private_metadata.invitation_id
      ? "invitation"
      : (data.external_accounts && data.external_accounts.length ? "oauth" : "direct");
    return props;
  }

  return props;
}

// Pick the best distinctId for a given event so the funnel auto-joins
// with `webhook.checkout_completed` (which uses `email:<hash>` via
// _posthog.emailDistinctId). For user.created without an email match,
// fall back to user:<user_id>. Last resort: server:clerk_webhook.
function distinctIdFor(props) {
  if (props.email_hash) return `email:${props.email_hash}`;
  if (props.user_id) return `user:${props.user_id}`;
  return "server:clerk_webhook";
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
    // Same convention as resend-webhook.js — 503 not 500 so the operator
    // sees it's disabled, not broken. Lets Clerk Dashboard's "test
    // webhook" surface a clear error before the env var is wired.
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
    // Clerk may add event types we haven't mapped — ack but skip.
    logApi({ status: 200, ms: Date.now() - t0, reason: "unmapped_event", type: eventType });
    return res.status(200).json({ ok: true, ignored: true });
  }

  const props = pickPostHogProps(eventType, body);
  const distinctId = distinctIdFor(props);
  try {
    capture(distinctId, phEvent, props);
    await flush();
  } catch (err) {
    // Telemetry must not block the webhook — Svix retries on 5xx and
    // we'd rather drop a PostHog event than have Clerk hammer us.
    logApi({
      status: 200, ms: Date.now() - t0, reason: "posthog_failed",
      event: phEvent, error: err && err.message,
    });
    return res.status(200).json({ ok: true, telemetry: "failed" });
  }

  logApi({
    status: 200, ms: Date.now() - t0,
    event: phEvent,
    email_hash: props.email_hash || "none",
    invitation_id: props.invitation_id || "none",
    delivered_by_clerk: typeof props.delivered_by_clerk === "boolean" ? props.delivered_by_clerk : "n/a",
  });
  return res.status(200).json({ ok: true });
};

// Stripe webhook also uses this — Svix signature verification requires
// the raw bytes off the wire.
module.exports.config = { api: { bodyParser: false } };

// Test seam exports — Vercel doesn't import these in prod.
module.exports.EVENT_MAP = EVENT_MAP;
module.exports.pickPostHogProps = pickPostHogProps;
module.exports.distinctIdFor = distinctIdFor;
module.exports.hashEmail = hashEmail;
