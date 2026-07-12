// GET/POST /api/newsletter-prefs — the login-free "Change filters" page for
// FREE (email-only, non-Clerk) newsletter subscribers.
//
// Reached from the newsletter footer "Change filters" pill, which carries the
// same signed token as the unsubscribe link:
//   ?r=<email_hash>&i=<issue_number>&t=<HMAC(r|i)>&l=<locale>
// The token proves the reader owns the address without any login. GET renders
// a small in-brand form prefilled with the reader's current filter; POST saves
// it. There is NO auth session — the token IS the auth, exactly like
// api/unsubscribe.js (whose token scheme + secret this reuses).
//
// Storage: the filter is written to the Resend contact's `last_name` field as
// a compact side-channel (see api/_prefs_codec.js + automation/newsletter
// /prefs_codec.py). The nightly pipeline reads it back for free from its
// single audience-list call — Resend's list omits custom properties but
// returns last_name, which Pulpo never renders.
//
// Security posture (this is an UNAUTHENTICATED write endpoint — treat with
// care):
//   • Token is verified (constant-time) BEFORE any Resend call, so an invalid
//     link never triggers the O(N) audience scan.
//   • The ONLY mutation is contacts.update({ lastName }). It cannot change the
//     email, the subscription state, or anything else.
//   • Every written value passes through prefs_codec.encode, which drops any
//     char outside [a-z0-9_-] and coerces prices to digits — a tampered form
//     body can't inject separators/markup back into the stored string.

const crypto = require("crypto");
const { Resend } = require("resend");
const { encode, decode } = require("./_prefs_codec.js");

const UNSUB_SECRET_ENV = "PULPO_UNSUBSCRIBE_SECRET"; // shared with unsubscribe
const RESEND_API_KEY_ENV = "RESEND_API_KEY";
const RESEND_AUDIENCE_ID_ENV = "RESEND_AUDIENCE_ID";
const NEWSLETTER_SALT_ENV = "PULPO_NEWSLETTER_SALT";
const NEWSLETTER_DEV_SALT = "pulpo-newsletter-dev-salt";

const LOGO_URL = "https://pulpo.club/assets/email-logo-32@2x.png";

// Closed sets the form exposes. property_types match the Preference slugs
// (land/house/condo); price tiers are a coarse ladder (0 = no cap). Anything
// off these sets is dropped by the codec anyway — this just drives the UI.
const PROPERTY_TYPES = ["land", "house", "condo"];
const PRICE_TIERS = [0, 100000, 250000, 500000, 1000000];

// ── Token (identical scheme + secret to api/unsubscribe.js) ───────────────
function hashEmail(email) {
  const salt = process.env[NEWSLETTER_SALT_ENV] || NEWSLETTER_DEV_SALT;
  return crypto.createHmac("sha256", salt).update(String(email).trim().toLowerCase()).digest("hex").slice(0, 24);
}

function expectedToken(recipientHash, issueNumber) {
  const secret = process.env[UNSUB_SECRET_ENV] || "";
  const msg = `${recipientHash}|${issueNumber}`;
  return crypto.createHmac("sha256", secret).update(msg).digest("hex").slice(0, 32);
}

function verifyToken(recipientHash, issueNumber, token) {
  const expected = expectedToken(recipientHash, issueNumber);
  if (!token || token.length !== expected.length) return false;
  try {
    return crypto.timingSafeEqual(Buffer.from(token), Buffer.from(expected));
  } catch {
    return false;
  }
}

function logApi(fields) {
  const parts = ["[api]", "newsletter-prefs"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

function readParams(req) {
  const q = (req && req.query) || {};
  const r = typeof q.r === "string" ? q.r : "";
  const t = typeof q.t === "string" ? q.t : "";
  const i = typeof q.i === "string" ? q.i : "";
  const issueNumber = Number.parseInt(i, 10);
  const locale = q.l === "es" ? "es" : "en";
  return { r, t, issueNumber, locale };
}

// Recover email + current last_name from the recipient hash by scanning the
// audience (the link only carries the hash — same trade-off as unsubscribe:
// scan the source-of-truth rather than keep a hash→email PII index).
async function lookupContactByHash(client, audienceId, recipientHash) {
  const resp = await client.contacts.list({ audienceId });
  const contacts = (resp && resp.data && Array.isArray(resp.data.data) ? resp.data.data
    : resp && Array.isArray(resp.data) ? resp.data
    : []);
  for (const c of contacts) {
    const email = c && c.email;
    if (!email) continue;
    if (hashEmail(email) === recipientHash) {
      return {
        email,
        contactId: c.id || null,
        lastName: (c.last_name || c.lastName || "") || "",
      };
    }
  }
  return null;
}

// ── Form body → filter object ─────────────────────────────────────────────
// Vercel parses urlencoded + JSON bodies into req.body. Accept either. The
// codec sanitizes everything downstream, so this only needs to shape it.
function filterFromBody(body) {
  body = body || {};
  let pts = body.property_types ?? body["property_types[]"] ?? [];
  if (typeof pts === "string") pts = pts.split(",");
  if (!Array.isArray(pts)) pts = [pts];
  const property_types = pts
    .map((s) => String(s).trim().toLowerCase())
    .filter((s) => PROPERTY_TYPES.includes(s));

  const rawMax = body.max_price_usd ?? body.max_price ?? "";
  const max = Number.parseInt(String(rawMax).replace(/[^\d]/g, ""), 10);
  const pref = {};
  if (property_types.length) pref.property_types = property_types;
  if (Number.isFinite(max) && max > 0) pref.max_price_usd = max;
  return pref;
}

async function saveFilter(recipientHash, pref, { resendImpl } = {}) {
  const apiKey = process.env[RESEND_API_KEY_ENV];
  const audienceId = process.env[RESEND_AUDIENCE_ID_ENV];
  const client = resendImpl || (apiKey ? new Resend(apiKey) : null);
  if (!client || !audienceId) return { status: "not_configured" };

  let contact;
  try {
    contact = await lookupContactByHash(client, audienceId, recipientHash);
  } catch (err) {
    return { status: "lookup_failed", error: err && err.message };
  }
  if (!contact) return { status: "not_in_audience" };

  const lastName = encode(pref); // "" clears the filter
  try {
    await client.contacts.update({ audienceId, email: contact.email, lastName });
  } catch (err) {
    return { status: "update_failed", error: err && err.message };
  }
  return { status: "saved", contactId: contact.contactId, encoded: lastName };
}

async function readFilter(recipientHash, { resendImpl } = {}) {
  const apiKey = process.env[RESEND_API_KEY_ENV];
  const audienceId = process.env[RESEND_AUDIENCE_ID_ENV];
  const client = resendImpl || (apiKey ? new Resend(apiKey) : null);
  if (!client || !audienceId) return { status: "not_configured", pref: {} };
  let contact;
  try {
    contact = await lookupContactByHash(client, audienceId, recipientHash);
  } catch (err) {
    return { status: "lookup_failed", pref: {}, error: err && err.message };
  }
  if (!contact) return { status: "not_in_audience", pref: {} };
  return { status: "ok", pref: decode(contact.lastName), email: contact.email };
}

// ── In-brand HTML (EN/ES, same tokens as the email + unsubscribe page) ────
const COPY = {
  en: {
    title: "Your filters — Pulpo",
    kicker: "Newsletter",
    h1: "Tune your weekly picks.",
    lede: "Choose what Pulpo watches for you. Your next Sunday email leads with the listings that match.",
    types_label: "Property type",
    type_land: "Land", type_house: "House", type_condo: "Condo",
    price_label: "Budget (max)",
    price_any: "No limit",
    save: "Save filters",
    saved_h1: "Saved.",
    saved_lede: "Your next weekly leads with picks that match. Change them any time from the link in any Pulpo email.",
    saved_summary_none: "No filter set — you'll get our broadest weekly shortlist.",
    saved_summary_prefix: "Watching for:",
    invalid_h1: "This link has expired.",
    invalid_lede: "For your security, filter links are tied to a specific email. Open the most recent Pulpo newsletter and tap “Change filters” there.",
    back: "Back to Pulpo",
  },
  es: {
    title: "Tus filtros — Pulpo",
    kicker: "Newsletter",
    h1: "Ajusta tus selecciones semanales.",
    lede: "Elige qué busca Pulpo para ti. Tu próximo correo del domingo abrirá con las propiedades que coincidan.",
    types_label: "Tipo de propiedad",
    type_land: "Terreno", type_house: "Casa", type_condo: "Condominio",
    price_label: "Presupuesto (máx.)",
    price_any: "Sin límite",
    save: "Guardar filtros",
    saved_h1: "Guardado.",
    saved_lede: "Tu próximo semanal abrirá con propiedades que coincidan. Cámbialos cuando quieras desde el enlace en cualquier correo de Pulpo.",
    saved_summary_none: "Sin filtro — recibirás nuestra selección semanal más amplia.",
    saved_summary_prefix: "Buscando:",
    invalid_h1: "Este enlace expiró.",
    invalid_lede: "Por tu seguridad, los enlaces de filtros están ligados a un correo específico. Abre el newsletter más reciente de Pulpo y toca “Cambiar filtros” allí.",
    back: "Volver a Pulpo",
  },
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function shell(locale, inner) {
  const c = COPY[locale] || COPY.en;
  return `<!doctype html><html lang="${locale}"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="robots" content="noindex"/><title>${esc(c.title)}</title>
<style>
  body{margin:0;background:#F4EFE6;color:#1A1916;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.5;}
  .wrap{max-width:520px;margin:0 auto;padding:40px 22px 64px;}
  .mast{display:flex;align-items:center;gap:8px;margin-bottom:28px;}
  .mast img{width:22px;height:22px;display:block;}
  .mast span{font-size:17px;font-weight:700;letter-spacing:-0.03em;color:#1F3D31;}
  .kicker{font-size:11px;font-weight:600;letter-spacing:0.14em;text-transform:uppercase;color:#B8643C;margin:0 0 8px;}
  h1{font-family:'Instrument Serif',Georgia,serif;font-weight:400;font-size:34px;line-height:1.08;letter-spacing:-0.015em;margin:0 0 12px;}
  p.lede{font-size:15.5px;color:#5A5650;margin:0 0 26px;}
  fieldset{border:0;margin:0 0 24px;padding:0;}
  legend{font-size:12px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:#5A5650;margin-bottom:12px;padding:0;}
  label.opt{display:flex;align-items:center;gap:10px;padding:12px 14px;margin-bottom:8px;background:#fff;border:1px solid rgba(0,0,0,0.10);border-radius:10px;font-size:15px;cursor:pointer;}
  label.opt input{width:18px;height:18px;accent-color:#1F3D31;}
  select{width:100%;padding:13px 14px;font-size:15px;border:1px solid rgba(0,0,0,0.14);border-radius:10px;background:#fff;color:#1A1916;-webkit-appearance:none;appearance:none;}
  button{width:100%;padding:15px;font-size:15px;font-weight:600;color:#F4EFE6;background:#18211C;border:0;border-radius:999px;cursor:pointer;letter-spacing:0.01em;}
  .summary{background:#F8F4EC;border-radius:10px;padding:16px 18px;font-size:15px;margin:0 0 26px;}
  a.back{display:inline-block;margin-top:22px;font-size:13px;font-weight:600;color:#1A1916;border-bottom:1px solid #1A1916;text-decoration:none;padding-bottom:1px;}
</style></head><body><div class="wrap">
  <div class="mast"><img src="${LOGO_URL}" alt="Pulpo"/><span>pulpo</span></div>
  ${inner}
</div></body></html>`;
}

function priceLabel(n, locale) {
  const c = COPY[locale] || COPY.en;
  if (!n) return c.price_any;
  return "$" + n.toLocaleString("en-US");
}

function renderForm({ locale, pref, r, t, issueNumber }) {
  const c = COPY[locale] || COPY.en;
  const selected = new Set(pref.property_types || []);
  const curMax = Number(pref.max_price_usd) || 0;
  const typeRows = PROPERTY_TYPES.map((pt) => `
    <label class="opt"><input type="checkbox" name="property_types" value="${pt}"${selected.has(pt) ? " checked" : ""}/> ${esc(c["type_" + pt])}</label>`).join("");
  const priceOpts = PRICE_TIERS.map((n) => `<option value="${n}"${n === curMax ? " selected" : ""}>${esc(priceLabel(n, locale))}</option>`).join("");
  const inner = `
    <p class="kicker">${esc(c.kicker)}</p>
    <h1>${esc(c.h1)}</h1>
    <p class="lede">${esc(c.lede)}</p>
    <form method="POST" action="/api/newsletter-prefs?r=${encodeURIComponent(r)}&i=${issueNumber}&t=${encodeURIComponent(t)}&l=${locale}">
      <fieldset><legend>${esc(c.types_label)}</legend>${typeRows}</fieldset>
      <fieldset><legend>${esc(c.price_label)}</legend><select name="max_price_usd">${priceOpts}</select></fieldset>
      <button type="submit">${esc(c.save)}</button>
    </form>
    <a class="back" href="https://pulpo.club/">${esc(c.back)} &rarr;</a>`;
  return shell(locale, inner);
}

function summarize(pref, locale) {
  const c = COPY[locale] || COPY.en;
  const bits = [];
  if (Array.isArray(pref.property_types) && pref.property_types.length) {
    bits.push(pref.property_types.map((pt) => c["type_" + pt] || pt).join(" / "));
  }
  if (Number(pref.max_price_usd) > 0) {
    bits.push("≤ " + priceLabel(Number(pref.max_price_usd), locale));
  }
  return bits.length ? `${c.saved_summary_prefix} ${bits.join(" · ")}` : c.saved_summary_none;
}

function renderSaved({ locale, pref }) {
  const c = COPY[locale] || COPY.en;
  const inner = `
    <p class="kicker">${esc(c.kicker)}</p>
    <h1>${esc(c.saved_h1)}</h1>
    <div class="summary">${esc(summarize(pref, locale))}</div>
    <p class="lede">${esc(c.saved_lede)}</p>
    <a class="back" href="https://pulpo.club/">${esc(c.back)} &rarr;</a>`;
  return shell(locale, inner);
}

function renderInvalid(locale) {
  const c = COPY[locale] || COPY.en;
  const inner = `
    <p class="kicker">${esc(c.kicker)}</p>
    <h1>${esc(c.invalid_h1)}</h1>
    <p class="lede">${esc(c.invalid_lede)}</p>
    <a class="back" href="https://pulpo.club/">${esc(c.back)} &rarr;</a>`;
  return shell(locale, inner);
}

// ── Handler ───────────────────────────────────────────────────────────────
module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "GET" && req.method !== "POST") {
    res.setHeader("Allow", "GET, POST");
    logApi({ status: 405, reason: "method", method: req.method });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const { r, t, issueNumber, locale } = readParams(req);
  const sendHtml = (code, html) => {
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    return res.status(code).send(html);
  };

  if (!r || !Number.isInteger(issueNumber) || !t || !verifyToken(r, issueNumber, t)) {
    logApi({ status: 403, ms: Date.now() - t0, reason: "bad_token", recipient_hash: r, method: req.method });
    return sendHtml(403, renderInvalid(locale));
  }

  try {
    if (req.method === "POST") {
      const pref = filterFromBody(req.body);
      const result = await saveFilter(r, pref);
      logApi({
        status: 200, ms: Date.now() - t0, action: "save",
        recipient_hash: r, issue_number: issueNumber,
        resend_status: result.status, has_filter: Object.keys(pref).length ? "y" : "n",
      });
      // Re-decode the encoded value so the summary reflects exactly what was
      // stored (post-sanitization), not the raw form body.
      return sendHtml(200, renderSaved({ locale, pref: decode(result.encoded || "") }));
    }
    const { pref } = await readFilter(r);
    logApi({ status: 200, ms: Date.now() - t0, action: "view", recipient_hash: r, issue_number: issueNumber, has_filter: Object.keys(pref).length ? "y" : "n" });
    return sendHtml(200, renderForm({ locale, pref, r, t, issueNumber }));
  } catch (err) {
    logApi({ status: 500, ms: Date.now() - t0, reason: "handler_error", recipient_hash: r, error_class: err && err.constructor ? err.constructor.name : "Error" });
    // Never leak internals; the reader sees the neutral invalid page.
    return sendHtml(200, renderInvalid(locale));
  }
};

// Exposed for unit tests — Vercel won't import these in production.
module.exports.expectedToken = expectedToken;
module.exports.verifyToken = verifyToken;
module.exports.hashEmail = hashEmail;
module.exports.lookupContactByHash = lookupContactByHash;
module.exports.filterFromBody = filterFromBody;
module.exports.saveFilter = saveFilter;
module.exports.readFilter = readFilter;
