// POST /api/newsletter  { email, source, locale? } -> 200 { ok: true }
// GET  /api/newsletter                              -> 405
//
// Subscribes an email to the Resend Audience that powers the
// rewrite's hero "Get the 10 best" form (NewHomePage / Hero.jsx).
//
// `locale` (optional, ∈ {"en","es"}, default "en") is persisted on the
// Resend contact via the `first_name` field using the strict prefix
// "pulpo-locale:<lc>". The newsletter dispatcher parses this back so
// anonymous subscribers (no matching Clerk user) receive the issue in
// the language they signed up in instead of always defaulting to English.
// Resend's `first_name` is not rendered in our newsletter templates —
// see docs/email-audit.md and automation/newsletter/subscribers.py.
//
// Required env vars (set in Vercel project settings):
//   RESEND_API_KEY      — re_… secret from https://resend.com/api-keys
//   RESEND_AUDIENCE_ID  — UUID of the audience the homepage feeds into
//
// Graceful degrade: when either env var is missing, the endpoint
// returns 503 service_unavailable. Hero.jsx maps that to the generic
// error toast so the form looks "down" rather than crashing — useful
// during the rollout window before ops finishes the Vercel env setup.
//
// PII rule (rewrite plan §10e): NEVER log the raw email address. The
// log line carries email_domain_only so we can debug provider issues
// (gmail vs hotmail accept/reject patterns) without writing
// addresses to Vercel runtime logs.
//
// Rate limiting: 5 attempts per IP per 5-min window. Same pattern as
// api/login.js (#212). In-memory Map; Vercel cold starts reset the
// counter — fine for the kind of opportunistic abuse this guards
// against. Operators paste the same email twice and want a clean
// "already subscribed" toast, not a 429.

const { Resend } = require("resend");

// ── Rate limit (in-memory, per-IP) ────────────────────────────────────
//
// Tighter than /api/login (5 vs 10 per window) because newsletter
// signup has no legitimate reason to fire repeatedly from one IP.
// Same auto-prune-at-1k pattern.

const RATE_LIMIT_WINDOW_MS    = 5 * 60 * 1000;
const RATE_LIMIT_MAX_ATTEMPTS = 5;
const RATE_LIMIT_PRUNE_AT     = 1000;

const _rateLimitMap = new Map();

function clientIp(req) {
  const xff = req.headers["x-forwarded-for"];
  if (typeof xff === "string" && xff.length > 0) {
    const first = xff.split(",")[0].trim();
    if (first) return first;
  }
  return (req.socket && req.socket.remoteAddress) || "unknown";
}

function pruneExpired(now) {
  if (_rateLimitMap.size < RATE_LIMIT_PRUNE_AT) return;
  for (const [ip, entry] of _rateLimitMap) {
    if (now - entry.windowStart >= RATE_LIMIT_WINDOW_MS) {
      _rateLimitMap.delete(ip);
    }
  }
}

function checkRateLimit(ip) {
  const now = Date.now();
  pruneExpired(now);
  let entry = _rateLimitMap.get(ip);
  if (!entry || now - entry.windowStart >= RATE_LIMIT_WINDOW_MS) {
    entry = { count: 1, windowStart: now };
    _rateLimitMap.set(ip, entry);
    return { allowed: true };
  }
  entry.count += 1;
  if (entry.count > RATE_LIMIT_MAX_ATTEMPTS) {
    const retryAfterSec = Math.max(
      1,
      Math.ceil((entry.windowStart + RATE_LIMIT_WINDOW_MS - now) / 1000),
    );
    return { allowed: false, retryAfterSec };
  }
  return { allowed: true };
}

// ── Email validation ─────────────────────────────────────────────────
//
// Permissive regex — accepts what Hero.jsx already accepts client-side
// (mirror with the same shape so server + client agree on "invalid"
// shape detection). The Resend SDK itself does stricter validation;
// this gate is the cheap pre-check so we don't burn API quota on
// obvious typos.

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Locales the newsletter dispatcher knows how to render. Anything outside
// this set is coerced back to "en" at subscribe time so the side-channel
// can never persist garbage into the Resend contact first_name field.
const SUPPORTED_LOCALES = new Set(["en", "es"]);

function pickLocale(raw) {
  if (typeof raw !== "string") return "en";
  const lc = raw.trim().toLowerCase();
  if (!lc) return "en";
  if (lc === "es" || lc.startsWith("es-")) return "es";
  if (lc === "en" || lc.startsWith("en-")) return "en";
  return SUPPORTED_LOCALES.has(lc) ? lc : "en";
}

function emailDomain(email) {
  const at = email.lastIndexOf("@");
  if (at < 0) return "unknown";
  return email.slice(at + 1).toLowerCase();
}

// ── Resend client (lazy-init) ────────────────────────────────────────

let _resend = null;
function resendClient() {
  if (_resend) return _resend;
  const key = process.env.RESEND_API_KEY;
  if (!key) return null;
  _resend = new Resend(key);
  return _resend;
}

// ── Log helper ───────────────────────────────────────────────────────

function logApi(fields) {
  const parts = ["[api]", "newsletter"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

// ── Free welcome trigger ──────────────────────────────────────────────
//
// After a successful subscribe we fire the DB-free welcome email via the
// internal Python dispatcher (api/internal/free-welcome-send.py → the same
// free_welcome_dispatch the admin test uses). New contact → "free_welcome";
// a re-subscribe (was unsubscribed) → "free_welcome_back" (the re-engaged
// path). `is_new_contact: true` is the dispatcher's idempotency signal:
// we only call this on a genuine create / re-subscribe.
//
// Best-effort + AWAITED. Best-effort: a slow / failed / unconfigured
// dispatch must NEVER fail the subscribe — the Resend contact already
// exists, the welcome is secondary, and the caller already saw success.
// Awaited (not fire-and-forget) because Vercel can freeze the function the
// instant the response is sent, dropping a detached promise. Short timeout
// caps the added latency. Skips silently when PULPO_INTERNAL_TOKEN is unset
// (e.g. a preview deploy without the secret) — logged, not thrown.

const FREE_WELCOME_PATH = "/api/internal/free-welcome-send";
const FREE_WELCOME_TIMEOUT_MS = 8000;

function freeWelcomeBaseUrl() {
  return process.env.PULPO_SITE_ROOT || "https://pulpo.club";
}

async function fireFreeWelcome({ email, locale, variant, source, fetchImpl } = {}) {
  const token = (process.env.PULPO_INTERNAL_TOKEN || "").trim();
  if (!token) {
    logApi({ free_welcome: "skipped", reason: "internal_token_unset", variant, domain: emailDomain(email) });
    return { fired: false, reason: "internal_token_unset" };
  }
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), FREE_WELCOME_TIMEOUT_MS);
  try {
    const r = await (fetchImpl || fetch)(`${freeWelcomeBaseUrl()}${FREE_WELCOME_PATH}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "pulpo-newsletter-signup",
      },
      body: JSON.stringify({ email, source, variant, locale, is_new_contact: true }),
      signal: controller.signal,
    });
    let body = null;
    try { body = await r.json(); } catch { /* best-effort */ }
    logApi({
      free_welcome: (body && body.status) || `http_${r.status}`,
      reason: (body && body.reason) || "-",
      variant, dry_run: !!(body && body.dry_run), domain: emailDomain(email),
    });
    return { fired: true, status: body && body.status, httpStatus: r.status };
  } catch (err) {
    const reason = err && err.name === "AbortError"
      ? "timeout"
      : `fetch_failed:${(err && err.message) || "unknown"}`;
    logApi({ free_welcome: "error", reason, variant, domain: emailDomain(email) });
    return { fired: false, reason };
  } finally {
    clearTimeout(tid);
  }
}

// ── Handler ──────────────────────────────────────────────────────────

async function handler(req, res, { fetchImpl, resendImpl } = {}) {
  const t0 = Date.now();

  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi({ status: 405, ms: Date.now() - t0, reason: "method" });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const ip = clientIp(req);
  const rl = checkRateLimit(ip);
  if (!rl.allowed) {
    res.setHeader("Retry-After", String(rl.retryAfterSec));
    logApi({
      status: 429, ms: Date.now() - t0,
      reason: "rate_limited", retry_after_s: rl.retryAfterSec,
    });
    return res.status(429).json({ error: "rate_limited", retry_after_s: rl.retryAfterSec });
  }

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { body = {}; }
  }
  body = body || {};
  const email = typeof body.email === "string" ? body.email.trim() : "";
  const source = typeof body.source === "string" ? body.source : "unknown";
  const locale = pickLocale(body.locale);

  if (!email || !EMAIL_RE.test(email)) {
    logApi({
      status: 400, ms: Date.now() - t0, reason: "invalid_email",
      // domain may exist even on rejected emails (e.g. user typed
      // "javier@gmail" — no TLD). emailDomain returns "unknown" when
      // the @ is missing entirely.
      domain: emailDomain(email),
    });
    return res.status(400).json({ error: "invalid_email" });
  }

  // ── Env var degrade gate ────────────────────────────────────────
  // Returns 503 (not 500) so monitoring tells "feature not configured"
  // apart from "feature crashed." Vercel ops sets the env vars and
  // the endpoint comes online without a redeploy of the FE.
  const client = resendImpl || resendClient();
  const audienceId = process.env.RESEND_AUDIENCE_ID;
  if (!client || !audienceId) {
    logApi({
      status: 503, ms: Date.now() - t0,
      reason: "not_configured",
      has_key: client ? "yes" : "no",
      has_audience: audienceId ? "yes" : "no",
      domain: emailDomain(email),
      source,
    });
    return res.status(503).json({ error: "service_unavailable" });
  }

  // ── Resend Audiences contact create ─────────────────────────────
  // Resend's contacts.create handles dedup server-side — sending the
  // same email twice returns 200 the first time and a structured
  // error the second. On dedup we attempt an update to flip
  // `unsubscribed: false`; without that step, a previously-unsubscribed
  // contact who re-enters their email at the homepage form would stay
  // unsubscribed (the create no-ops on dup, the previous state sticks)
  // and the "Changed your mind?" CTA on the unsubscribe page would be
  // a lie. Falling back to 409 only when the update itself fails.
  try {
    // LEARNING: locale side-channel via the Resend `first_name` field.
    // Pulpo's newsletter templates render `display_name` from Clerk's
    // first_name, NOT from Resend's — so this field is free for us to
    // use as a structured tag. The strict prefix "pulpo-locale:<lc>" is
    // parsed by automation/newsletter/subscribers.py to set the anonymous
    // recipient's locale. Contacts predating this change carry an empty
    // first_name and default to "en" exactly as before. See
    // docs/email-audit.md "Anonymous-subscriber locale gap".
    const result = await client.contacts.create({
      audienceId,
      email,
      first_name: `pulpo-locale:${locale}`,
      unsubscribed: false,
    });
    // SDK error shape: { data: null, error: { name, message } } per
    // Resend's contract. Successful create returns { data: { id, ... },
    // error: null }.
    if (result.error) {
      const errName    = result.error.name    || "unknown";
      const errMessage = result.error.message || "";
      // Resend returns "Contact already exists" on dedup. Match loosely
      // — the exact message has changed across SDK versions.
      const isDup =
        errName === "validation_error" &&
        /already exists|already subscribed|duplicate/i.test(errMessage);
      if (isDup) {
        // Distinguish a genuine re-subscribe (contact was unsubscribed)
        // from an already-active subscriber re-submitting the form. The
        // create no-ops on dup, so without this check we'd fire a
        // "welcome back" email on EVERY resubmit — spamming people who
        // never left. One contacts.list (~200ms); shape-tolerant per
        // api/unsubscribe.js. Best-effort: if the lookup throws we fall
        // through to the resubscribe path (prior behaviour) rather than
        // block a legitimate re-subscribe.
        let wasUnsubscribed = true;
        try {
          // O(1) direct lookup by email (GET /audiences/:id/contacts/:email).
          // Replaces a full contacts.list + linear scan: that scan reads only
          // the first page, so once the audience outgrew one page an existing
          // ACTIVE subscriber could go unmatched → wasUnsubscribed stayed true
          // → we fired "welcome back" at people who never left. get-by-email
          // has no pagination surface, so the active-vs-resubscribe split is
          // correct at any audience size.
          const got = await client.contacts.get({ audienceId, email });
          const contact = got && got.data;
          if (contact) wasUnsubscribed = !!contact.unsubscribed;
        } catch { /* lookup failed — treat as re-subscribe (prior behaviour) */ }

        if (!wasUnsubscribed) {
          // Already an active subscriber. Idempotent no-op — no state
          // change, no email. (Resend's create already no-op'd.)
          logApi({
            status: 200, ms: Date.now() - t0,
            reason: "already_subscribed_noop",
            domain: emailDomain(email),
            source,
          });
          return res.status(200).json({ ok: true, already_subscribed: true });
        }
        try {
          await client.contacts.update({
            audienceId,
            email,
            unsubscribed: false,
          });
          // Re-engaged free subscriber → welcome-back (best-effort).
          await fireFreeWelcome({ email, locale, variant: "free_welcome_back", source: "resend_resubscribe", fetchImpl });
          logApi({
            status: 200, ms: Date.now() - t0,
            reason: "resubscribed",
            domain: emailDomain(email),
            source,
            locale,
          });
          return res.status(200).json({ ok: true, resubscribed: true });
        } catch (updateErr) {
          logApi({
            status: 409, ms: Date.now() - t0,
            reason: "already_subscribed_update_failed",
            err_name: updateErr && updateErr.name,
            domain: emailDomain(email),
            source,
          });
          return res.status(409).json({ error: "already_subscribed" });
        }
      }
      logApi({
        status: 502, ms: Date.now() - t0,
        reason: "resend_error",
        err_name: errName,
        domain: emailDomain(email),
        source,
      });
      return res.status(502).json({ error: "upstream_error" });
    }
    // New free subscriber → welcome (best-effort; never fails the subscribe).
    await fireFreeWelcome({ email, locale, variant: "free_welcome", source: "signup", fetchImpl });
    logApi({
      status: 200, ms: Date.now() - t0,
      domain: emailDomain(email),
      source,
      locale,
    });
    return res.status(200).json({ ok: true });
  } catch (err) {
    // Network / SDK throw — never let it bubble. Log the error class
    // (not the message — Resend SDK errors sometimes echo the email).
    logApi({
      status: 500, ms: Date.now() - t0,
      reason: "exception",
      err_class: err && err.constructor ? err.constructor.name : "Error",
      domain: emailDomain(email),
      source,
    });
    return res.status(500).json({ error: "internal_error" });
  }
}

module.exports = (req, res) => handler(req, res);
module.exports.handler = handler;
module.exports.fireFreeWelcome = fireFreeWelcome;
