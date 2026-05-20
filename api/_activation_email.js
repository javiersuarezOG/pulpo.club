// Pulpo-owned activation email pipeline.
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

const RESEND_API = "https://api.resend.com/emails";
const DEFAULT_FROM = "Pulpo Club <noreply@mail.pulpo.club>";

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
// Brand header (inline SVG + wordmark) renders the new Pulpo mark at
// the top of every activation email. Hex literals only — most email
// clients strip CSS vars. Outlook desktop is the weak link for inline
// SVG; it gracefully falls back to nothing, leaving the wordmark
// to carry brand identity.
const BRAND_HEADER_HTML = `
<div style="text-align:center;padding:8px 0 20px;border-bottom:1px solid #e6e6e6;margin-bottom:24px;">
  <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto;border-collapse:collapse;">
    <tr>
      <td style="vertical-align:middle;padding-right:10px;line-height:0;">
        <svg width="26" height="26" viewBox="-50 -50 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M -38 0 C -38 -21, -21 -38, 0 -38 C 21 -38, 38 -21, 38 0 C 38 17, 24 30, 7 30 C -8 30, -18 18, -18 4 C -18 -8, -8 -18, 4 -18 C 12 -18, 18 -12, 18 -4" stroke="#1F3D31" stroke-width="8.5" stroke-linecap="round" fill="none"/>
          <circle cx="18" cy="-4" r="9.5" fill="#1F3D31"/>
          <circle cx="18" cy="-4" r="5.5" fill="#D4A04A"/>
        </svg>
      </td>
      <td style="vertical-align:middle;">
        <span style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;font-size:22px;font-weight:700;letter-spacing:-0.035em;color:#1F3D31;line-height:1;">pulpo</span>
      </td>
    </tr>
  </table>
</div>`;

const TEMPLATES = {
  en: {
    subject: "Your Pulpo Pro subscription is active — set up your account",
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
<p>Questions? Reply to this email or write to <a href="mailto:hello@pulpo.club">hello@pulpo.club</a>.</p>
<p>— The Pulpo Club team</p>
</body></html>`,
    text: (actionUrl) => `Hi there,

Thanks for joining Pulpo Pro — your subscription is active.

One step left to access your account: set a password so you can sign in from any device.

Set up my Pulpo Pro account:
${actionUrl}

This link is unique to your account and expires in 24 hours.

Questions? Reply to this email or write to hello@pulpo.club.

— The Pulpo Club team`,
  },
  es: {
    subject: "Tu suscripción de Pulpo Pro está activa — configura tu cuenta",
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
<p>¿Dudas? Responde a este correo o escribe a <a href="mailto:hello@pulpo.club">hello@pulpo.club</a>.</p>
<p>— El equipo de Pulpo Club</p>
</body></html>`,
    text: (actionUrl) => `Hola,

Gracias por sumarte a Pulpo Pro — tu suscripción está activa.

Solo queda un paso para acceder a tu cuenta: elige una contraseña para iniciar sesión desde cualquier dispositivo.

Configurar mi cuenta Pulpo Pro:
${actionUrl}

Este enlace es único para tu cuenta y expira en 24 horas.

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
    return { ok: false, error: "RESEND_API_KEY not set", status_code: 0 };
  }
  if (!email || !actionUrl) {
    return { ok: false, error: "missing required field (email/actionUrl)", status_code: 0 };
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
    return {
      ok: false,
      error: `fetch_failed: ${err && err.message ? err.message : "unknown"}`,
      status_code: 0,
    };
  }

  let body;
  try { body = await res.json(); } catch { body = null; }

  if (!res.ok) {
    return {
      ok: false,
      error: (body && (body.message || body.error)) || `http_${res.status}`,
      status_code: res.status,
    };
  }
  return {
    ok: true,
    message_id: (body && body.id) || "",
    status_code: res.status,
  };
}

module.exports = {
  sendActivationEmail,
  // Test seam.
  recipientHash,
  pickLocale,
  TEMPLATES,
  DEFAULT_FROM,
};
