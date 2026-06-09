// GET/POST /api/unsubscribe
//
// One-click unsubscribe for the weekly newsletter. Two entry points:
//
//   GET /api/unsubscribe?r=<recipient_hash>&i=<issue_number>&t=<token>
//       Browser navigation from the footer link. Renders a small HTML
//       confirmation page so the user knows it worked.
//
//   POST /api/unsubscribe?r=...&i=...&t=...
//       RFC 8058 one-click. Mail providers (Gmail, Yahoo) POST this
//       directly from the inbox header — body is List-Unsubscribe=One-Click.
//       Returns 200 with no UI; provider parses the status code.
//
// Token validation:
//   HMAC-SHA256(secret = PULPO_UNSUBSCRIBE_SECRET, msg = `${r}|${i}`),
//   first 32 hex chars. Matches automation/newsletter/send.py.unsubscribe_token.
//   Constant-time compare. No JWT, no key rotation logic — we don't
//   need either for this surface (tokens are single-purpose, single-issue).
//
// On valid token:
//   1. Flip the Resend contact's `unsubscribed=true` (best-effort; we
//      proceed even if the API call fails — the audit log + telemetry
//      capture the failure for follow-up).
//   2. PostHog newsletter.unsubscribed event with the recipient hash.
//
// On invalid token / missing fields: 400 with a generic "invalid_link"
// error. Don't leak which axis was wrong — that helps token-guessing.

const crypto = require("crypto");
const { Resend } = require("resend");
const { capture, flush } = require("./_posthog");

const UNSUB_SECRET_ENV = "PULPO_UNSUBSCRIBE_SECRET";
const RESEND_API_KEY_ENV = "RESEND_API_KEY";
const RESEND_AUDIENCE_ID_ENV = "RESEND_AUDIENCE_ID";

function hashEmail(email) {
  return crypto.createHash("sha256")
    .update(String(email || "").trim().toLowerCase())
    .digest("hex")
    .slice(0, 16);
}

function logApi(fields) {
  const parts = ["[api]", "unsubscribe"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

function expectedToken(recipientHash, issueNumber) {
  const secret = process.env[UNSUB_SECRET_ENV] || "";
  if (!secret) return null;
  const msg = `${recipientHash}|${issueNumber}`;
  return crypto
    .createHmac("sha256", secret)
    .update(msg)
    .digest("hex")
    .slice(0, 32);
}

function verifyToken(recipientHash, issueNumber, token) {
  const expected = expectedToken(recipientHash, issueNumber);
  if (!expected || !token || token.length !== expected.length) return false;
  try {
    return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(token));
  } catch {
    return false;
  }
}

function readParams(req) {
  // Vercel parses ?…&… into req.query for both GET and POST.
  const q = req.query || {};
  const r = typeof q.r === "string" ? q.r : "";
  const i = typeof q.i === "string" ? q.i : "";
  const t = typeof q.t === "string" ? q.t : "";
  // Edition (`e`) and locale (`l`) are cosmetic — they only pick which
  // confirmation copy renders. They are NOT part of the HMAC (which signs
  // r|i only), so a tampered `e`/`l` can change copy but never forge an
  // unsubscribe. Defaults: free edition, English. Older in-flight emails
  // (sent before the stamp) and the RFC 8058 POST path (no UI) both fall
  // through to the free/en default harmlessly.
  const e = q.e === "pro" ? "pro" : "free";
  const l = q.l === "es" ? "es" : "en";
  const issueNumber = Number.parseInt(i, 10);
  return { r, issueNumber, t, edition: e, locale: l };
}

// Map the URL's recipient_hash back to an email by scanning the Resend
// audience and matching hash(email) for each contact. Resend's audience
// is the source of truth for who's subscribed; we own that list, so
// scanning it is honest (vs storing a parallel hash→email PII index in
// our repo). Cost: one `contacts.list` call per unsub, ~200ms.
//
// Returns { email, contactId } on hit, null on miss. Network / API
// failures bubble up as exceptions — caller treats them as soft and
// still fires the PostHog event so the cron's PostHog-based filter
// catches the unsub even if Resend hiccupped.
async function lookupContactByHash(client, audienceId, recipientHash) {
  const resp = await client.contacts.list({ audienceId });
  // Resend SDK shape variance across versions — tolerate { data: { data: [] } }
  // and { data: [] } and bare arrays.
  const contacts = (resp && resp.data && Array.isArray(resp.data.data) ? resp.data.data
                  : resp && Array.isArray(resp.data) ? resp.data
                  : []);
  for (const c of contacts) {
    const email = c && c.email;
    if (!email) continue;
    if (hashEmail(email) === recipientHash) {
      return { email, contactId: c.id || null };
    }
  }
  return null;
}

// Two side effects per unsubscribe:
//   1. PostHog event — the durable signal the next-issue cron filters on.
//      Fires unconditionally so a Resend hiccup never silently re-includes
//      the user in the next blast.
//   2. Resend audience update — the user's expectation when they click
//      "unsubscribe." Without this, our confirmation page lies. Best
//      effort: if Resend can't be reached or the contact isn't in the
//      audience (already-unsubscribed, deleted, etc.), we still 200 the
//      user with the confirmation copy and the PostHog event covers it.
//
// Returns the resolution shape so the response can be honest about
// whether the Resend mutation actually happened.
async function recordUnsubscribe(recipientHash, issueNumber) {
  capture(`user:${recipientHash}`, "newsletter.unsubscribed", {
    recipient_hash: recipientHash,
    issue_number: issueNumber,
    source: "one_click",
  });

  const apiKey     = process.env[RESEND_API_KEY_ENV];
  const audienceId = process.env[RESEND_AUDIENCE_ID_ENV];
  if (!apiKey || !audienceId) {
    return { resend_status: "not_configured" };
  }

  const client = new Resend(apiKey);
  let contact;
  try {
    contact = await lookupContactByHash(client, audienceId, recipientHash);
  } catch (err) {
    return { resend_status: "lookup_failed", error: err && err.message };
  }
  if (!contact) {
    return { resend_status: "not_in_audience" };
  }

  try {
    await client.contacts.update({
      audienceId,
      email: contact.email,
      unsubscribed: true,
    });
    return { resend_status: "updated", contact_id: contact.contactId };
  } catch (err) {
    return {
      resend_status: "update_failed",
      contact_id: contact.contactId,
      error: err && err.message,
    };
  }
}

// ── In-brand confirmation page ────────────────────────────────────────
// Free and Pro readers get different copy on the SAME brand chrome:
//   • Free  → plain `pulpo` masthead, soft "the full shortlist lives in
//             Pulpo Pro" upsell. The unsub is a chance to convert.
//   • Pro   → `pulpo` + gold PRO badge, RETENTION not upsell: reassure
//             that the paid membership + billing emails are untouched
//             (the #1 fear when a paying member clicks unsubscribe),
//             then offer a one-click resubscribe.
// Both EN + ES. Tokens mirror the email template (automation/newsletter
// /render_html.py): #F4EFE6 paper, #1F3D31 green, #D4A04A gold, Instrument
// Serif headers + Inter body, hosted octopus PNG. Rendered inline so the
// 200 response is a finished page — no SPA bounce.
const LOGO_URL = "https://pulpo.club/assets/email-logo-32@2x.png";

// Closed-set copy table. Adding a locale = add a sibling block; adding an
// edition = add a key under each locale. No raw strings in the markup.
const CONFIRM_COPY = {
  en: {
    title: "Unsubscribed — Pulpo",
    kicker_free: "Newsletter",
    kicker_pro: "Weekly digest",
    h1_free: "You're unsubscribed.",
    h1_pro: "You're off the weekly.",
    lede_free: "We'll stop sending the weekly Pulpo newsletter to this address. That's it — no more emails from the list.",
    lede_pro: "We'll stop sending the Pulpo Pro weekly digest to this address.",
    fine_free: "Changed your mind by accident? You can resubscribe any time from the Pulpo homepage.",
    upsell_eyebrow: "Before you go",
    upsell_h2: "The full shortlist lives in Pulpo Pro.",
    upsell_body: "The free email shows the top deals with the rest locked. Pulpo Pro unlocks every ranked listing, saved searches, and price-drop alerts — the part that actually helps you buy.",
    upsell_primary: "See Pulpo Pro",
    upsell_ghost: "Resubscribe",
    keep_eyebrow: "What this didn't change",
    keep_membership: "Your <strong>Pulpo Pro membership</strong> is still active — full ranked access, saved searches, and price-drop alerts all work as before.",
    keep_billing: "Account &amp; billing emails (receipts, renewals) still send normally.",
    keep_resub_line: "Changed your mind? You can turn the weekly digest back on any time from your account.",
    keep_primary: "Resubscribe",
    keep_ghost: "Go to account",
    tagline: "Every beach and lake home in El Salvador, ranked by value.",
    copyright_free: "© 2026 Pulpo · pulpo.club · San Salvador, El Salvador",
    copyright_pro: "© 2026 Pulpo Pro · pulpo.club · San Salvador, El Salvador",
  },
  es: {
    title: "Suscripción cancelada — Pulpo",
    kicker_free: "Boletín",
    kicker_pro: "Resumen semanal",
    h1_free: "Cancelaste tu suscripción.",
    h1_pro: "Saliste del resumen semanal.",
    lede_free: "Dejaremos de enviar el boletín semanal de Pulpo a esta dirección. Listo — no más correos de la lista.",
    lede_pro: "Dejaremos de enviar el resumen semanal de Pulpo Pro a esta dirección.",
    fine_free: "¿Te diste de baja por error? Puedes volver a suscribirte cuando quieras desde la página de inicio de Pulpo.",
    upsell_eyebrow: "Antes de irte",
    upsell_h2: "La lista completa está en Pulpo Pro.",
    upsell_body: "El correo gratis muestra las mejores oportunidades y bloquea el resto. Pulpo Pro desbloquea cada propiedad rankeada, búsquedas guardadas y alertas de bajada de precio — lo que de verdad te ayuda a comprar.",
    upsell_primary: "Ver Pulpo Pro",
    upsell_ghost: "Volver a suscribirme",
    keep_eyebrow: "Lo que esto no cambió",
    keep_membership: "Tu <strong>membresía Pulpo Pro</strong> sigue activa — acceso completo al ranking, búsquedas guardadas y alertas de precio funcionan igual que antes.",
    keep_billing: "Los correos de cuenta y facturación (recibos, renovaciones) se siguen enviando con normalidad.",
    keep_resub_line: "¿Cambiaste de opinión? Puedes reactivar el resumen semanal cuando quieras desde tu cuenta.",
    keep_primary: "Volver a suscribirme",
    keep_ghost: "Ir a mi cuenta",
    tagline: "Cada casa de playa y lago en El Salvador, ordenada por valor.",
    copyright_free: "© 2026 Pulpo · pulpo.club · San Salvador, El Salvador",
    copyright_pro: "© 2026 Pulpo Pro · pulpo.club · San Salvador, El Salvador",
  },
};

const CONFIRM_CSS = `
  :root{--paper:#F4EFE6;--card:#FFFFFF;--ink:#1A1916;--ink-3:#888780;--ink-2:#5A5650;--green:#1F3D31;--gold:#D4A04A;--line:rgba(0,0,0,0.08);}
  *{box-sizing:border-box;}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;line-height:1.6;-webkit-font-smoothing:antialiased;}
  .wrap{max-width:560px;margin:0 auto;padding:40px 20px 56px;}
  .frame{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;}
  .mast{display:flex;align-items:center;justify-content:space-between;padding:16px 28px;border-bottom:1px solid var(--line);}
  .mast-brand{display:flex;align-items:center;gap:10px;}
  .mast-brand img{width:26px;height:26px;display:block;}
  .mast-word{font-size:24px;font-weight:700;letter-spacing:-0.035em;color:var(--green);line-height:1;}
  .pro-pill{display:inline-block;font-size:9px;font-weight:700;letter-spacing:0.14em;padding:3px 6px;background:var(--gold);color:var(--green);border-radius:3px;vertical-align:middle;line-height:1;}
  .mast-kicker{font-size:11px;color:var(--ink-3);letter-spacing:0.08em;text-transform:uppercase;}
  .body{padding:40px 28px 32px;}
  .check{width:44px;height:44px;border-radius:999px;background:rgba(31,61,49,0.08);display:flex;align-items:center;justify-content:center;margin:0 0 20px;}
  .check svg{width:22px;height:22px;}
  h1{font-family:"Instrument Serif",Georgia,serif;font-weight:400;font-size:36px;line-height:1.08;margin:0 0 14px;letter-spacing:-0.01em;color:var(--ink);}
  p{font-size:15px;color:var(--ink-2);margin:0 0 14px;}
  .fine{font-size:13px;color:var(--ink-3);}
  .panel{margin:26px 0 8px;background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:20px;}
  .panel .eyebrow{font-size:11px;letter-spacing:0.12em;text-transform:uppercase;font-weight:700;margin:0 0 8px;}
  .eyebrow-gold{color:var(--gold);}
  .eyebrow-mute{color:var(--ink-3);}
  .panel h2{font-family:"Instrument Serif",Georgia,serif;font-weight:400;font-size:21px;margin:0 0 6px;color:var(--ink);letter-spacing:-0.01em;}
  .panel p{font-size:13.5px;margin:0 0 14px;color:var(--ink-2);}
  .keep-line{display:flex;align-items:flex-start;gap:9px;margin:0 0 10px;}
  .keep-line svg{width:16px;height:16px;flex:0 0 16px;margin-top:2px;}
  .keep-line span{font-size:13.5px;color:var(--ink-2);}
  .row{display:flex;flex-wrap:wrap;gap:10px;margin-top:4px;}
  .btn{display:inline-block;padding:11px 18px;border-radius:999px;font-size:13px;font-weight:600;text-decoration:none;}
  .btn-primary{background:var(--green);color:var(--paper);}
  .btn-ghost{background:transparent;color:var(--ink);border:1px solid rgba(0,0,0,0.18);}
  .foot{padding:22px 28px 26px;background:var(--paper);border-top:1px solid var(--line);}
  .foot-brand{display:flex;align-items:center;gap:8px;}
  .foot-brand img{width:20px;height:20px;display:block;}
  .foot-word{font-size:16px;font-weight:700;letter-spacing:-0.03em;color:var(--green);}
  .foot-pill{display:inline-block;font-size:9px;font-weight:700;letter-spacing:0.14em;padding:2px 5px;background:var(--gold);color:var(--green);border-radius:3px;margin-left:5px;vertical-align:middle;line-height:1;}
  .foot p{font-size:11px;color:var(--ink-3);letter-spacing:0.04em;margin:12px 0 0;}`;

const CHECK_SVG = '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M5 12.5l4.2 4.2L19 7" stroke="#1F3D31" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function renderConfirmationHtml(edition = "free", locale = "en") {
  const c = CONFIRM_COPY[locale] || CONFIRM_COPY.en;
  const isPro = edition === "pro";
  const proPill = isPro ? '<span class="pro-pill">PRO</span>' : "";
  const footPill = isPro ? '<span class="foot-pill">PRO</span>' : "";
  const kicker = isPro ? c.kicker_pro : c.kicker_free;
  const h1 = isPro ? c.h1_pro : c.h1_free;
  const lede = isPro ? c.lede_pro : c.lede_free;
  const copyright = isPro ? c.copyright_pro : c.copyright_free;

  // Edition-specific middle panel. Free = upsell; Pro = retention.
  const panel = isPro
    ? `
        <div class="panel">
          <p class="eyebrow eyebrow-mute">${c.keep_eyebrow}</p>
          <div class="keep-line">${CHECK_SVG}<span>${c.keep_membership}</span></div>
          <div class="keep-line">${CHECK_SVG}<span>${c.keep_billing}</span></div>
          <p>${c.keep_resub_line}</p>
          <div class="row">
            <a class="btn btn-primary" href="https://pulpo.club/account/newsletter">${c.keep_primary}</a>
            <a class="btn btn-ghost" href="https://pulpo.club/account">${c.keep_ghost}</a>
          </div>
        </div>`
    : `
        <p class="fine">${c.fine_free}</p>
        <div class="panel">
          <p class="eyebrow eyebrow-gold">${c.upsell_eyebrow}</p>
          <h2>${c.upsell_h2}</h2>
          <p>${c.upsell_body}</p>
          <div class="row">
            <a class="btn btn-primary" href="https://pulpo.club/start">${c.upsell_primary}</a>
            <a class="btn btn-ghost" href="https://pulpo.club/">${c.upsell_ghost}</a>
          </div>
        </div>`;

  return `<!doctype html>
<html lang="${locale}">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${c.title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet" />
<style>${CONFIRM_CSS}</style>
</head>
<body>
  <div class="wrap">
    <div class="frame">
      <div class="mast">
        <div class="mast-brand">
          <img src="${LOGO_URL}" width="26" height="26" alt="Pulpo" />
          <span class="mast-word">pulpo</span>${proPill}
        </div>
        <span class="mast-kicker">${kicker}</span>
      </div>
      <div class="body">
        <div class="check">${CHECK_SVG}</div>
        <h1>${h1}</h1>
        <p>${lede}</p>${panel}
      </div>
      <div class="foot">
        <div class="foot-brand">
          <img src="${LOGO_URL}" width="20" height="20" alt="Pulpo" />
          <span class="foot-word">pulpo</span>${footPill}
        </div>
        <p>${c.tagline}</p>
        <p>${copyright}</p>
      </div>
    </div>
  </div>
</body>
</html>`;
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "GET" && req.method !== "POST") {
    res.setHeader("Allow", "GET, POST");
    logApi({ status: 405, ms: Date.now() - t0, reason: "method", method: req.method });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const { r, issueNumber, t, edition, locale } = readParams(req);
  if (!r || !Number.isInteger(issueNumber) || !t) {
    logApi({
      status: 400, ms: Date.now() - t0, reason: "missing_params",
      has_r: r ? "y" : "n", has_i: Number.isInteger(issueNumber) ? "y" : "n", has_t: t ? "y" : "n",
    });
    return res.status(400).json({ error: "invalid_link" });
  }

  if (!verifyToken(r, issueNumber, t)) {
    logApi({
      status: 400, ms: Date.now() - t0, reason: "bad_token",
      recipient_hash: r, issue_number: issueNumber,
    });
    return res.status(400).json({ error: "invalid_link" });
  }

  let resendResult = { resend_status: "skipped" };
  try {
    resendResult = await recordUnsubscribe(r, issueNumber);
    await flush();
  } catch (err) {
    logApi({
      status: 500, ms: Date.now() - t0, reason: "record_failed",
      recipient_hash: r, issue_number: issueNumber,
      error_class: err && err.constructor ? err.constructor.name : "Error",
    });
    // Don't surface the failure to the user — the unsub intent was
    // captured (or attempted); the audit trail catches the followup.
  }

  logApi({
    status: 200, ms: Date.now() - t0,
    recipient_hash: r, issue_number: issueNumber, method: req.method,
    resend_status: resendResult.resend_status,
    resend_contact_id: resendResult.contact_id || "",
  });

  if (req.method === "POST") {
    // RFC 8058 one-click — provider expects 200, no body required.
    return res.status(200).json({ ok: true });
  }
  // Browser click → in-brand confirmation page, free or pro edition.
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  return res.status(200).send(renderConfirmationHtml(edition, locale));
};

// Exposed for unit tests — Vercel won't import these in production.
module.exports.expectedToken = expectedToken;
module.exports.verifyToken = verifyToken;
module.exports.hashEmail = hashEmail;
module.exports.lookupContactByHash = lookupContactByHash;
