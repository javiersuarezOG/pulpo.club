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
// Reuse the homepage's welcome-back dispatcher so a token-link resubscribe
// re-engages the reader exactly like re-entering their email would. Requiring
// newsletter.js has no import-time side effects (no server, no network).
const { fireFreeWelcome } = require("./newsletter.js");

const UNSUB_SECRET_ENV = "PULPO_UNSUBSCRIBE_SECRET";
const RESEND_API_KEY_ENV = "RESEND_API_KEY";
const RESEND_AUDIENCE_ID_ENV = "RESEND_AUDIENCE_ID";

// Reverse-lookup key for a Resend contact. MUST byte-for-byte match
// automation/newsletter/store.py `email_hash` — the unsubscribe/resubscribe
// link's `r=` IS that Python hash (salted sha256, first 24 hex chars), and
// lookupContactByHash reverses it by re-hashing each contact's email.
//
// The prior implementation (unsalted sha256, 16 chars) never matched a real
// recipient hash, so the Resend `unsubscribed` flip silently no-op'd
// (`not_in_audience`) on EVERY unsubscribe — masked only because the PostHog
// cron filter still excluded the reader from the next send. Resubscribe
// exposed it: with the contact never found, `wasUnsubscribed` was always
// false and the welcome-back never fired. Keep the salt env var + fallback
// literal identical to store.py or this silently breaks again.
const NEWSLETTER_SALT_ENV = "PULPO_NEWSLETTER_SALT";
const NEWSLETTER_DEV_SALT = "pulpo-newsletter-dev-salt";

function hashEmail(email) {
  const salt = process.env[NEWSLETTER_SALT_ENV] || NEWSLETTER_DEV_SALT;
  return crypto.createHash("sha256")
    .update(`${salt}:${String(email || "").trim().toLowerCase()}`)
    .digest("hex")
    .slice(0, 24);
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
  // action: "resub" flips the contact back to subscribed and renders the
  // "you're back" confirmation. Default "unsub". Set only on the in-page
  // Resubscribe link we render ourselves — it carries the SAME signed
  // token (HMAC over r|i has no expiry), so no separate secret is needed
  // and a tampered `action` can't forge anything the token doesn't cover.
  const action = q.action === "resub" ? "resub" : "unsub";
  return { r, issueNumber, t, edition: e, locale: l, action };
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
      return { email, contactId: c.id || null, unsubscribed: !!c.unsubscribed };
    }
  }
  return null;
}

// Bounded retry for the Resend mirror write (P0-2). The PostHog
// suppression event — fired + flushed by the caller — is the durable
// source of truth that excludes the reader from future Pulpo sends; this
// update only keeps Resend's own `unsubscribed` flag in sync. A single
// transient 5xx / network blip used to leave that mirror stale forever;
// retry the transient failures so a hiccup self-heals within the request.
const RESEND_UPDATE_MAX_ATTEMPTS = 3;
const RESEND_UPDATE_BACKOFF_MS = 300;

async function updateContactWithRetry(client, { audienceId, email, unsubscribed }) {
  let lastErr;
  for (let attempt = 1; attempt <= RESEND_UPDATE_MAX_ATTEMPTS; attempt++) {
    try {
      await client.contacts.update({ audienceId, email, unsubscribed });
      return { ok: true, attempts: attempt };
    } catch (err) {
      lastErr = err;
      if (attempt < RESEND_UPDATE_MAX_ATTEMPTS) {
        await new Promise((res) => setTimeout(res, RESEND_UPDATE_BACKOFF_MS * attempt));
      }
    }
  }
  return { ok: false, attempts: RESEND_UPDATE_MAX_ATTEMPTS, error: lastErr && lastErr.message };
}

// Two side effects per unsubscribe:
//   1. PostHog event — the durable signal the next-issue cron filters on.
//      Fires unconditionally so a Resend hiccup never silently re-includes
//      the user in the next blast.
//   2. Resend audience update — the user's expectation when they click
//      "unsubscribe." Retried (updateContactWithRetry); if it still can't
//      be synced (Resend down, contact missing), we surface a
//      `newsletter.unsubscribe_resend_unsynced` telemetry event so the
//      drift is observable + reconcilable instead of silently swallowed.
//      The reader is already suppressed via side-effect (1), so we still
//      200 the confirmation page — it is honest about the outcome that
//      matters (no future Pulpo mail), and honest in telemetry about the
//      mirror.
//
// Returns the resolution shape so the response can be honest about
// whether the Resend mutation actually happened.
async function recordUnsubscribe(recipientHash, issueNumber, { resendImpl } = {}) {
  capture(`user:${recipientHash}`, "newsletter.unsubscribed", {
    recipient_hash: recipientHash,
    issue_number: issueNumber,
    source: "one_click",
  });

  const apiKey     = process.env[RESEND_API_KEY_ENV];
  const audienceId = process.env[RESEND_AUDIENCE_ID_ENV];
  if (!resendImpl && (!apiKey || !audienceId)) {
    return { resend_status: "not_configured" };
  }

  const client = resendImpl || new Resend(apiKey);
  let contact;
  try {
    contact = await lookupContactByHash(client, audienceId, recipientHash);
  } catch (err) {
    // Transient Resend list failure — the mirror is unsynced. Suppression
    // is durable via the flushed PostHog event; make the drift observable.
    capture(`user:${recipientHash}`, "newsletter.unsubscribe_resend_unsynced", {
      recipient_hash: recipientHash,
      issue_number: issueNumber,
      resend_status: "lookup_failed",
    });
    return { resend_status: "lookup_failed", error: err && err.message };
  }
  if (!contact) {
    return { resend_status: "not_in_audience" };
  }

  const upd = await updateContactWithRetry(client, {
    audienceId,
    email: contact.email,
    unsubscribed: true,
  });
  if (upd.ok) {
    return { resend_status: "updated", contact_id: contact.contactId, attempts: upd.attempts };
  }
  // Retries exhausted — Resend mirror stale. The reader IS suppressed from
  // Pulpo's own sends via the flushed PostHog event; emit an observable
  // signal so provider-side drift can be reconciled rather than swallowed.
  capture(`user:${recipientHash}`, "newsletter.unsubscribe_resend_unsynced", {
    recipient_hash: recipientHash,
    issue_number: issueNumber,
    resend_status: "update_failed",
    attempts: upd.attempts,
  });
  return {
    resend_status: "update_failed",
    contact_id: contact.contactId,
    error: upd.error,
  };
}

// Pro reader re-enabling the weekly digest → Pulpo Pro welcome-back
// (pulpo_pro_welcome_back), the Pro-branded analogue of the free path.
// POSTs to the Pro dispatcher /api/internal/welcome-send with
// variant=welcome_back. Best-effort + awaited; a slow/failed/unconfigured
// dispatch never breaks the resubscribe.
//
// Two safety properties:
//   • No subscription_id is passed, so the dispatcher stamps only the
//     audit timestamp (resubscribe_welcome_sent_at) and NOT the Stripe
//     re-acquisition dedup key (resubscribe_welcome_subscription_id) —
//     this digest re-enable can't interfere with that separate funnel
//     (automation/newsletter/welcome_dispatch.py).
//   • The Pro dispatcher gates on the reader being a plan=pro Clerk user
//     (find_clerk_user_by_email + plan check), so a non-Pro or
//     account-less contact resolves to a clean skip, not a mis-send.
const PRO_WELCOME_PATH = "/api/internal/welcome-send";
const PRO_WELCOME_TIMEOUT_MS = 8000;

function internalBaseUrl() {
  return process.env.PULPO_SITE_ROOT || "https://pulpo.club";
}

async function fireProWelcomeBack({ email, locale, fetchImpl } = {}) {
  const token = (process.env.PULPO_INTERNAL_TOKEN || "").trim();
  if (!token) {
    logApi({ pro_welcome_back: "skipped", reason: "internal_token_unset" });
    return { fired: false, reason: "internal_token_unset" };
  }
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), PRO_WELCOME_TIMEOUT_MS);
  try {
    const r = await (fetchImpl || fetch)(`${internalBaseUrl()}${PRO_WELCOME_PATH}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "pulpo-unsubscribe-pro-welcome-back",
      },
      body: JSON.stringify({
        email,
        variant: "welcome_back",
        source: "unsubscribe_page_resub",
        locale,
      }),
      signal: controller.signal,
    });
    let body = null;
    try { body = await r.json(); } catch { /* best-effort */ }
    logApi({
      pro_welcome_back: (body && body.status) || `http_${r.status}`,
      reason: (body && body.reason) || "-",
      dry_run: !!(body && body.dry_run),
    });
    return { fired: true, status: body && body.status, httpStatus: r.status };
  } catch (err) {
    const reason = err && err.name === "AbortError"
      ? "timeout"
      : `fetch_failed:${(err && err.message) || "unknown"}`;
    logApi({ pro_welcome_back: "error", reason });
    return { fired: false, reason };
  } finally {
    clearTimeout(tid);
  }
}

// The inverse of recordUnsubscribe — flip the Resend contact back to
// subscribed, fire the durable PostHog signal, and re-engage the reader
// with the welcome-back email. Reached only via the in-page Resubscribe
// link (same signed token). Best-effort + honest about whether the Resend
// mutation landed, exactly like the unsub path.
//
// The `unsubscribe?r=<hash>` link only carries the recipient HASH — but the
// audience lookup recovers the plaintext email, which both welcome
// dispatchers need. A token-link resubscribe fires the edition-matched
// welcome-back:
//   • FREE → free_welcome_back via fireFreeWelcome (api/newsletter.js), the
//     same email re-entering the address on the homepage sends.
//   • PRO  → pulpo_pro_welcome_back via fireProWelcomeBack (the Pro
//     dispatcher), Pro-branded, gated Clerk-side on plan=pro.
// One guard keeps it honest: wasUnsubscribed — only a contact that was
// actually unsubscribed gets a welcome-back. A repeat click (already
// subscribed) flips nothing new and sends no email. The dispatchers'
// own idempotency (stamps) is the belt-and-suspenders layer.
async function recordResubscribe(
  recipientHash,
  issueNumber,
  { edition = "free", locale = "en", fetchImpl, resendImpl } = {},
) {
  capture(`user:${recipientHash}`, "newsletter.resubscribed", {
    recipient_hash: recipientHash,
    issue_number: issueNumber,
    source: "confirmation_page",
  });

  const apiKey     = process.env[RESEND_API_KEY_ENV];
  const audienceId = process.env[RESEND_AUDIENCE_ID_ENV];
  const client = resendImpl || (apiKey ? new Resend(apiKey) : null);
  if (!client || !audienceId) {
    return { resend_status: "not_configured" };
  }

  let contact;
  try {
    contact = await lookupContactByHash(client, audienceId, recipientHash);
  } catch (err) {
    return { resend_status: "lookup_failed", error: err && err.message };
  }
  if (!contact) {
    return { resend_status: "not_in_audience" };
  }

  const wasUnsubscribed = !!contact.unsubscribed;
  try {
    await client.contacts.update({
      audienceId,
      email: contact.email,
      unsubscribed: false,
    });
  } catch (err) {
    return {
      resend_status: "update_failed",
      contact_id: contact.contactId,
      error: err && err.message,
    };
  }

  // Genuine re-subscribe → edition-matched welcome-back (best-effort;
  // never break the resubscribe on a slow / failed / unconfigured dispatch).
  let welcome = { fired: false, reason: "already_subscribed" };
  if (wasUnsubscribed) {
    try {
      welcome = edition === "pro"
        ? await fireProWelcomeBack({ email: contact.email, locale, fetchImpl })
        : await fireFreeWelcome({
            email: contact.email,
            locale,
            variant: "free_welcome_back",
            source: "unsubscribe_page_resub",
            fetchImpl,
          });
    } catch (err) {
      welcome = { fired: false, reason: `welcome_threw:${err && err.message}` };
    }
  }

  return {
    resend_status: "updated",
    contact_id: contact.contactId,
    was_unsubscribed: wasUnsubscribed,
    welcome,
  };
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
    resub_title: "Resubscribed — Pulpo",
    resub_h1_free: "You're back on the list.",
    resub_h1_pro: "You're back on the weekly.",
    resub_lede_free: "Welcome back — we'll start sending the weekly Pulpo newsletter to this address again.",
    resub_lede_pro: "Welcome back — we'll start sending the Pulpo Pro weekly digest to this address again.",
    resub_primary_free: "Browse Pulpo",
    resub_ghost_free: "See Pulpo Pro",
    resub_primary_pro: "Go to account",
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
    resub_title: "Suscripción reactivada — Pulpo",
    resub_h1_free: "Estás de vuelta en la lista.",
    resub_h1_pro: "Estás de vuelta en el resumen semanal.",
    resub_lede_free: "Bienvenido de nuevo — volveremos a enviar el boletín semanal de Pulpo a esta dirección.",
    resub_lede_pro: "Bienvenido de nuevo — volveremos a enviar el resumen semanal de Pulpo Pro a esta dirección.",
    resub_primary_free: "Explorar Pulpo",
    resub_ghost_free: "Ver Pulpo Pro",
    resub_primary_pro: "Ir a mi cuenta",
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

function renderConfirmationHtml({
  edition = "free",
  locale = "en",
  mode = "unsub",
  resubHref = "https://pulpo.club/",
} = {}) {
  const c = CONFIRM_COPY[locale] || CONFIRM_COPY.en;
  const isPro = edition === "pro";
  const isResub = mode === "resub";
  const proPill = isPro ? '<span class="pro-pill">PRO</span>' : "";
  const footPill = isPro ? '<span class="foot-pill">PRO</span>' : "";
  const kicker = isPro ? c.kicker_pro : c.kicker_free;
  const copyright = isPro ? c.copyright_pro : c.copyright_free;

  const title = isResub ? c.resub_title : c.title;
  const h1 = isResub
    ? (isPro ? c.resub_h1_pro : c.resub_h1_free)
    : (isPro ? c.h1_pro : c.h1_free);
  const lede = isResub
    ? (isPro ? c.resub_lede_pro : c.resub_lede_free)
    : (isPro ? c.lede_pro : c.lede_free);

  // Middle panel varies by mode + edition.
  //   resub  → simple "welcome back" CTA row (no upsell/retention pitch).
  //   unsub  → Free = upsell, Pro = retention. Both offer a one-click,
  //            token-authenticated Resubscribe that lands on the resub
  //            confirmation page (mode=resub) — NOT a bare bounce to `/`.
  let panel;
  if (isResub) {
    panel = isPro
      ? `
        <div class="row">
          <a class="btn btn-primary" href="https://pulpo.club/account">${c.resub_primary_pro}</a>
        </div>`
      : `
        <div class="row">
          <a class="btn btn-primary" href="https://pulpo.club/">${c.resub_primary_free}</a>
          <a class="btn btn-ghost" href="https://pulpo.club/start">${c.resub_ghost_free}</a>
        </div>`;
  } else if (isPro) {
    panel = `
        <div class="panel">
          <p class="eyebrow eyebrow-mute">${c.keep_eyebrow}</p>
          <div class="keep-line">${CHECK_SVG}<span>${c.keep_membership}</span></div>
          <div class="keep-line">${CHECK_SVG}<span>${c.keep_billing}</span></div>
          <p>${c.keep_resub_line}</p>
          <div class="row">
            <a class="btn btn-primary" href="${resubHref}">${c.keep_primary}</a>
            <a class="btn btn-ghost" href="https://pulpo.club/account">${c.keep_ghost}</a>
          </div>
        </div>`;
  } else {
    panel = `
        <p class="fine">${c.fine_free}</p>
        <div class="panel">
          <p class="eyebrow eyebrow-gold">${c.upsell_eyebrow}</p>
          <h2>${c.upsell_h2}</h2>
          <p>${c.upsell_body}</p>
          <div class="row">
            <a class="btn btn-primary" href="https://pulpo.club/start">${c.upsell_primary}</a>
            <a class="btn btn-ghost" href="${resubHref}">${c.upsell_ghost}</a>
          </div>
        </div>`;
  }

  return `<!doctype html>
<html lang="${locale}">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${title}</title>
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

  const { r, issueNumber, t, edition, locale, action } = readParams(req);
  const isResub = action === "resub";
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
    resendResult = isResub
      ? await recordResubscribe(r, issueNumber, { edition, locale })
      : await recordUnsubscribe(r, issueNumber);
    await flush();
  } catch (err) {
    logApi({
      status: 500, ms: Date.now() - t0, reason: "record_failed", action,
      recipient_hash: r, issue_number: issueNumber,
      error_class: err && err.constructor ? err.constructor.name : "Error",
    });
    // Don't surface the failure to the user — the intent was captured
    // (or attempted); the audit trail catches the followup.
  }

  logApi({
    status: 200, ms: Date.now() - t0, action,
    recipient_hash: r, issue_number: issueNumber, method: req.method,
    resend_status: resendResult.resend_status,
    resend_contact_id: resendResult.contact_id || "",
    welcome_fired: resendResult.welcome ? (resendResult.welcome.fired ? "y" : "n") : "-",
    welcome_status: (resendResult.welcome && (resendResult.welcome.status || resendResult.welcome.reason)) || "-",
  });

  if (req.method === "POST") {
    // RFC 8058 one-click — provider expects 200, no body required.
    return res.status(200).json({ ok: true });
  }

  // One-click Resubscribe link rendered on the unsub confirmation page:
  // same r|i|t token, plus action=resub and the cosmetic e/l so the resub
  // page keeps the reader's edition + language.
  const resubHref =
    `https://pulpo.club/api/unsubscribe?r=${encodeURIComponent(r)}` +
    `&i=${issueNumber}&t=${encodeURIComponent(t)}&e=${edition}&l=${locale}&action=resub`;

  // Browser click → in-brand confirmation page (unsub or resub × free/pro).
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  return res.status(200).send(renderConfirmationHtml({
    edition, locale, mode: isResub ? "resub" : "unsub", resubHref,
  }));
};

// Exposed for unit tests — Vercel won't import these in production.
module.exports.expectedToken = expectedToken;
module.exports.verifyToken = verifyToken;
module.exports.hashEmail = hashEmail;
module.exports.lookupContactByHash = lookupContactByHash;
module.exports.recordResubscribe = recordResubscribe;
module.exports.recordUnsubscribe = recordUnsubscribe;
