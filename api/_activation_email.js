// Pulpo-owned activation email pipeline.
//
// GUARDRAIL: this is the INVITATION flow. Newsletter sends live at
// automation/newsletter/send.py + api/admin/newsletter/send.js. We share
// one Resend project (RESEND_API_KEY) but separate `from:` envs, no
// audience overlap, and distinct PostHog event prefixes — see
// docs/email-audit.md for the full topology.
//
// Background: Clerk's own email pipeline accepts our invitation send
// requests but holds them indefinitely at `status: queued` (confirmed
// via the Svix webhook telemetry in PR #341). DNS + DKIM are all
// verified on Clerk's side; nothing we can do at the wire layer fixes
// it — the gate is somewhere inside Clerk's account/billing config.
//
// Rather than wait for Clerk Support, this helper sends activation
// emails directly via Resend (which Pulpo already uses for the
// newsletter pipeline — proven path, verified `mail.pulpo.club`
// sending domain, full lifecycle telemetry via api/resend-webhook.js).
//
// Caller flow:
//   1. webhook.js calls clerk.invitations.createInvitation({ notify:false })
//      → Clerk creates the row but skips its own send.
//   2. webhook.js receives the invitation with its `url` field.
//   3. webhook.js calls sendActivationEmail({ email, locale, actionUrl, sessionId }).
//   4. Resend sends the email with stamped tags so the existing Resend
//      webhook handler (newsletter.*) joins it back into the post-Stripe
//      activation funnel in PostHog.
//
// This module never throws — failures return { ok: false, error } so
// the webhook can keep going (the invitation row still exists; the
// WelcomeModal's "Resend my invitation" button is the user recovery).

const crypto = require("crypto");
const posthog = require("./_posthog");

const RESEND_API = "https://api.resend.com/emails";
const DEFAULT_FROM = "Pulpo Club <hello@mail.pulpo.club>";

// LEARNING: cross-flow telemetry events. The audit task asks for
// `email.invitation.sent { invitee_email, resend_message_id, flow }` and
// `email.send.failed { flow, error_code, error_message, recipient }`. Both
// "invitee_email" and "recipient" are persisted as their PII-safe SHA256
// hash (recipientHash) — same approach the rest of the codebase takes
// (see api/_posthog.js#emailDistinctId, api/unsubscribe.js#hashEmail).
// PostHog dashboards that need to join across flows do so on the hashed
// identifier; the raw address never leaves the Vercel function.
const EVENT_INVITATION_SENT = "email.invitation.sent";
const EVENT_SEND_FAILED = "email.send.failed";
const FLOW_INVITATION = "invitation";

// PII-safe recipient hash — same algorithm as api/_posthog.js's
// emailDistinctId. Stamped on the outbound mail as a tag so Resend's
// lifecycle webhook can join its events to the post-Stripe funnel
// in PostHog. 16 hex chars = 64 bits, plenty of entropy.
function recipientHash(email) {
  if (!email || typeof email !== "string") return "";
  return crypto.createHash("sha256")
    .update(email.trim().toLowerCase())
    .digest("hex")
    .slice(0, 16);
}

// Single emission point for `email.send.failed`. Telemetry must never
// throw — posthog.capture is already non-throwing, but route every
// failure exit through here so we cannot accidentally skip an emission
// in a future branch.
function captureSendFailed({ email, errorCode, errorMessage, statusCode }) {
  const hash = recipientHash(email);
  posthog.capture(
    hash ? `email:${hash}` : "server:activation_email",
    EVENT_SEND_FAILED,
    {
      flow: FLOW_INVITATION,
      error_code: errorCode || "",
      error_message: errorMessage || "",
      recipient: hash || "anon",
      status_code: typeof statusCode === "number" ? statusCode : 0,
    },
  );
}

// Locale → template selector. Mirrors what Clerk's locale-aware
// invitation template would have done. Fallback to English on any
// unknown locale (matches the broader app default).
function pickLocale(stripeLocale) {
  if (!stripeLocale || typeof stripeLocale !== "string") return "en";
  const lc = stripeLocale.trim().toLowerCase();
  if (lc === "es" || lc.startsWith("es-")) return "es";
  return "en";
}

// EN + ES copies. Verbatim from docs/clerk-invitation-setup.md Item A
// (already drafted, just lifted into code). HTML keeps Clerk-compatible
// inline styles so the email renders identically across Gmail/Outlook/
// Apple Mail clients regardless of CSS support.
//
// Brand header uses a hosted PNG mark rather than inline SVG. Several
// email clients strip SVG entirely, and Resend surfaced that as a
// deliverability warning during the 2026-05-27 activation incident.
const BRAND_HEADER_HTML = `
<div style="text-align:center;padding:8px 0 20px;border-bottom:1px solid #e6e6e6;margin-bottom:24px;">
  <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto;border-collapse:collapse;">
    <tr>
      <td style="vertical-align:middle;padding-right:10px;line-height:0;">
        <img src="https://pulpo.club/assets/email-logo-32@2x.png" width="32" height="32" alt="" style="display:block;border:0;outline:none;text-decoration:none;border-radius:8px;" />
      </td>
      <td style="vertical-align:middle;">
        <span style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;font-size:22px;font-weight:700;letter-spacing:-0.035em;color:#1F3D31;line-height:1;">pulpo</span>
      </td>
    </tr>
  </table>
</div>`;

const TEMPLATES = {
  en: {
    subject: "Set up your Pulpo Pro account — your subscription is active",
    preheader: "One step left: set your password and start exploring.",
    html: (actionUrl) => `<!doctype html>
<html><head><meta charset="utf-8"></head><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;color:#1a1a1a;line-height:1.5;max-width:560px;margin:0 auto;padding:24px;">
${BRAND_HEADER_HTML}
<p>Hi there,</p>
<p>Thanks for joining Pulpo Pro — your subscription is active.</p>
<p>One step left to access your account: set a password so you can sign in from any device.</p>
<p style="margin:24px 0;">
  <a href="${actionUrl}" style="background:#1a1a1a;color:#ffffff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">Set up my Pulpo Pro account →</a>
</p>
<p>This link is unique to your account and expires in 24 hours. If it expires, request a new one from the activation modal on <a href="https://pulpo.club/account">pulpo.club/account</a>.</p>
<p>If this lands in Promotions, drag it to Primary so the next Pulpo email finds you faster.</p>
<p>Questions? Reply to this email or write to <a href="mailto:hello@pulpo.club">hello@pulpo.club</a>.</p>
<p>— The Pulpo Club team</p>
</body></html>`,
    text: (actionUrl) => `Hi there,

Thanks for joining Pulpo Pro — your subscription is active.

One step left to access your account: set a password so you can sign in from any device.

Set up my Pulpo Pro account:
${actionUrl}

This link is unique to your account and expires in 24 hours.

If this lands in Promotions, drag it to Primary so the next Pulpo email finds you faster.

Questions? Reply to this email or write to hello@pulpo.club.

— The Pulpo Club team`,
  },
  es: {
    subject: "Configura tu cuenta Pulpo Pro — tu suscripción está activa",
    preheader: "Solo falta un paso: elige tu contraseña y empieza a explorar.",
    html: (actionUrl) => `<!doctype html>
<html><head><meta charset="utf-8"></head><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;color:#1a1a1a;line-height:1.5;max-width:560px;margin:0 auto;padding:24px;">
${BRAND_HEADER_HTML}
<p>Hola,</p>
<p>Gracias por sumarte a Pulpo Pro — tu suscripción está activa.</p>
<p>Solo queda un paso para acceder a tu cuenta: elige una contraseña para iniciar sesión desde cualquier dispositivo.</p>
<p style="margin:24px 0;">
  <a href="${actionUrl}" style="background:#1a1a1a;color:#ffffff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">Configurar mi cuenta Pulpo Pro →</a>
</p>
<p>Este enlace es único para tu cuenta y expira en 24 horas. Si expira, solicita uno nuevo desde la ventana de activación en <a href="https://pulpo.club/account">pulpo.club/account</a>.</p>
<p>Si este correo llega a Promociones, muévelo a Principal para que el próximo email de Pulpo te encuentre más rápido.</p>
<p>¿Dudas? Responde a este correo o escribe a <a href="mailto:hello@pulpo.club">hello@pulpo.club</a>.</p>
<p>— El equipo de Pulpo Club</p>
</body></html>`,
    text: (actionUrl) => `Hola,

Gracias por sumarte a Pulpo Pro — tu suscripción está activa.

Solo queda un paso para acceder a tu cuenta: elige una contraseña para iniciar sesión desde cualquier dispositivo.

Configurar mi cuenta Pulpo Pro:
${actionUrl}

Este enlace es único para tu cuenta y expira en 24 horas.

Si este correo llega a Promociones, muévelo a Principal para que el próximo email de Pulpo te encuentre más rápido.

¿Dudas? Responde a este correo o escribe a hello@pulpo.club.

— El equipo de Pulpo Club`,
  },
};

// POST the email to Resend. The fetch is bare so we don't add a new
// dependency — Pulpo's package.json already vendors Resend's SDK for
// the newsletter, but using fetch keeps this module self-contained
// and avoids dual SDK invocation paths during the migration window.
//
// Returns { ok, message_id, error, status_code }:
//   ok=true   → Resend accepted the send (200/202). Lifecycle events
//               will flow via /api/resend-webhook → PostHog as
//               newsletter.sent / .delivered / .bounced.
//   ok=false  → Send rejected. Caller logs + telemetry, but the
//               invitation row still exists so the user can hit
//               "Resend my invitation" to retry.
//
// Never throws. Telemetry-failure-is-not-handler-failure: a webhook
// returning 500 because Resend was briefly down would cause Stripe to
// retry the webhook, which would create another invitation + try to
// send again. That's the wrong loop.
async function sendActivationEmail({ email, locale, actionUrl, sessionId }) {
  const apiKey = (process.env.RESEND_API_KEY || "").trim();
  if (!apiKey) {
    captureSendFailed({
      email, errorCode: "missing_api_key",
      errorMessage: "RESEND_API_KEY not set", statusCode: 0,
    });
    return { ok: false, error: "RESEND_API_KEY not set", status_code: 0 };
  }
  if (!email || !actionUrl) {
    const errorMessage = "missing required field (email/actionUrl)";
    captureSendFailed({
      email, errorCode: "missing_required_field",
      errorMessage, statusCode: 0,
    });
    return { ok: false, error: errorMessage, status_code: 0 };
  }

  const from = (process.env.PULPO_ACTIVATION_FROM_EMAIL || DEFAULT_FROM).trim();
  const lc = pickLocale(locale);
  const tpl = TEMPLATES[lc];
  const hash = recipientHash(email);

  const payload = {
    from,
    to: [email],
    subject: tpl.subject,
    html: tpl.html(actionUrl),
    text: tpl.text(actionUrl),
    // Tags + headers are how the lifecycle events at /api/resend-webhook
    // join back to the post-Stripe funnel in PostHog. The resend-webhook
    // handler's pickPostHogProps reads tags.recipient_hash and the
    // x-pulpo-* headers; same names here.
    //
    // LEARNING: `email_type=activation` is the single discriminator
    // /api/resend-webhook uses (post-2026-05-28) to distinguish activation
    // lifecycle from newsletter lifecycle in PostHog. Both flows share the
    // single Resend webhook endpoint. Keeping the existing `newsletter.*`
    // event names plus an `email_type` prop preserves all existing
    // dashboards while letting them filter activations out of the
    // newsletter deliverability numerator. See docs/email-audit.md.
    tags: [
      { name: "recipient_hash", value: hash || "anon" },
      { name: "email_type", value: "activation" },
      ...(sessionId ? [{ name: "session_id", value: String(sessionId).slice(0, 90) }] : []),
      { name: "locale", value: lc },
    ],
    headers: {
      "x-pulpo-recipient": hash || "anon",
      "x-pulpo-email-type": "activation",
      ...(sessionId ? { "x-pulpo-session": String(sessionId).slice(0, 200) } : {}),
    },
    // Preheader is rendered by some clients as the snippet under the
    // subject in the inbox list. Set via the standard `headers` of the
    // Resend API isn't supported — embed as a visually-hidden div in
    // the HTML body. (Skipping for simplicity; subject + sender are
    // doing the work.)
  };

  let res;
  try {
    res = await fetch(RESEND_API, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${apiKey}`,
      },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    const errorMessage = `fetch_failed: ${err && err.message ? err.message : "unknown"}`;
    captureSendFailed({
      email, errorCode: "fetch_failed", errorMessage, statusCode: 0,
    });
    return { ok: false, error: errorMessage, status_code: 0 };
  }

  let body;
  try { body = await res.json(); } catch { body = null; }

  if (!res.ok) {
    const errorMessage = (body && (body.message || body.error)) || `http_${res.status}`;
    captureSendFailed({
      email, errorCode: `http_${res.status}`,
      errorMessage, statusCode: res.status,
    });
    return { ok: false, error: errorMessage, status_code: res.status };
  }
  const messageId = (body && body.id) || "";
  posthog.capture(
    `email:${hash}`,
    EVENT_INVITATION_SENT,
    {
      flow: FLOW_INVITATION,
      invitee_email: hash || "anon",  // hashed per PII rule; see LEARNING above
      resend_message_id: messageId,
      locale: lc,
      from,
    },
  );
  return { ok: true, message_id: messageId, status_code: res.status };
}

module.exports = {
  sendActivationEmail,
  // Test seam.
  recipientHash,
  pickLocale,
  TEMPLATES,
  DEFAULT_FROM,
};
