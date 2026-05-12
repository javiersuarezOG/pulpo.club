// POST /api/newsletter  { email, source } -> 200 { ok: true }
// GET  /api/newsletter                    -> 405
//
// Subscribes an email to the Resend Audience that powers the
// rewrite's hero "Get the 10 best" form (NewHomePage / Hero.jsx).
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

// ── Handler ──────────────────────────────────────────────────────────

module.exports = async (req, res) => {
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
  const client = resendClient();
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
  // error the second. We map the dedup error to a friendly
  // already_subscribed response so the Hero shows the "welcome back"
  // success copy.
  try {
    const result = await client.contacts.create({
      audienceId,
      email,
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
        logApi({
          status: 409, ms: Date.now() - t0,
          reason: "already_subscribed",
          domain: emailDomain(email),
          source,
        });
        return res.status(409).json({ error: "already_subscribed" });
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
    logApi({
      status: 200, ms: Date.now() - t0,
      domain: emailDomain(email),
      source,
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
};
