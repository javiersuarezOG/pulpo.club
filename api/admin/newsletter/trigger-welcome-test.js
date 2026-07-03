// POST /api/admin/newsletter/trigger-welcome-test
//
// Body: { email, by?, force?: boolean, variant?: "welcome"|"welcome_back",
//         locale?: "en"|"es" }
//
// Operator surface for the Pulpo Pro Welcome / Welcome-back templates.
//
// This calls the SYNCHRONOUS internal dispatcher
// (`/api/internal/welcome-send`) and returns its REAL outcome — so the
// admin widget only ever confirms "Sent" when the email actually sent.
// It used to fire a GitHub Actions workflow and return 202 ("dispatch
// accepted") which looked like success even when the send then silently
// skipped (e.g. the recipient wasn't a Clerk Pro user). The internal
// endpoint runs `dispatch_welcome` in-process (~1-3s) and reports
// sent / skipped:<reason> / failed:<reason>.
//
//   • `variant`  — "welcome" (first-time) | "welcome_back" (resubscribe).
//   • `locale`   — EN/ES override (the tool's Language toggle). Empty →
//     the dispatcher uses the recipient's Clerk locale (prod behavior).
//   • `force`    — defaults TRUE for admin (re-render past the idempotency
//     stamp). Pass false to exercise the idempotency path.
//
// Response (always HTTP 200 so the widget can read the body): {
//   status: "sent" | "skipped" | "failed" | "error",
//   reason: string | null, message_id: string | null,
//   dry_run: bool, variant, locale }
//
// Auth: none on the admin wrapper — the /admin surface is intentionally
// open (operator decision 2026-06-10 — the PULPO_ADMIN_DEBUG_TOKEN gate
// was removed); the rate-limit is the only throttle. Auth to the
// internal endpoint still uses Bearer PULPO_INTERNAL_TOKEN (shared with
// the Stripe webhook). When it's unset we return status:"error" — never
// a false "sent".

const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");
const posthog = require("../../_posthog");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const INTERNAL_PATH = "/api/internal/welcome-send";
const INTERNAL_TIMEOUT_MS = 25_000;

function internalBaseUrl() {
  // PUBLIC domain only — never VERCEL_URL. The *.vercel.app deployment
  // URL is gated by Vercel Deployment Protection (HTML 401), which made
  // this admin call (and the Stripe-webhook welcome) surface as http_401.
  // The custom domain reaches the same function, unprotected.
  return process.env.PULPO_SITE_ROOT || "https://pulpo.club";
}

async function emitTriggerEvent({ to, by, force, variant, locale, result, reason }) {
  try {
    posthog.capture(
      posthog.emailDistinctId(by || to),
      "admin.newsletter_test_triggered",
      {
        to,
        by: by || null,
        newsletter_id: variant === "welcome_back" ? "pro-welcome-back" : "pro-welcome",
        variant: variant || "welcome",
        locale: locale || null,
        force,
        result,
        detail: reason || null,
        dispatched_at: new Date().toISOString(),
      },
    );
    await posthog.flush();
  } catch {
    /* never let telemetry block the dispatch response */
  }
}

const limiter = makeRateLimiter({
  windowMs: 60 * 60 * 1000,
  maxAttempts: 5,
  name: "admin_newsletter_trigger_welcome_test",
});

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try {
    const chunks = [];
    for await (const chunk of req) chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
    const raw = Buffer.concat(chunks).toString("utf8");
    if (!raw) return {};
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function logApi(fields) {
  const parts = ["[api]", "admin.newsletter_trigger_welcome_test"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

// Exported for unit tests — injectable fetch.
async function callInternalWelcomeSend({ baseUrl, token, payload, fetchImpl, timeoutMs }) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), timeoutMs || INTERNAL_TIMEOUT_MS);
  try {
    const r = await (fetchImpl || fetch)(`${baseUrl}${INTERNAL_PATH}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "pulpo-admin-welcome-test",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    let body = null;
    try { body = await r.json(); } catch { /* best-effort */ }
    return { ok: true, httpStatus: r.status, body };
  } catch (err) {
    const reason = err && err.name === "AbortError"
      ? "timeout"
      : `fetch_failed:${(err && err.message) || "unknown"}`;
    return { ok: false, reason };
  } finally {
    clearTimeout(tid);
  }
}

async function handler(req, res, { fetchImpl } = {}) {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }
  // No auth gate — admin surface is open by design (see header).

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    logApi({ status: 429, ms: Date.now() - t0 });
    return send429(res, rl, "admin_newsletter_trigger_welcome_test");
  }

  const body = await readJsonBody(req);
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!email || !EMAIL_RE.test(email)) {
    return res.status(400).json({ status: "error", reason: "invalid_email" });
  }
  const by = typeof body.by === "string" && EMAIL_RE.test(body.by.trim().toLowerCase())
    ? body.by.trim().toLowerCase()
    : null;
  const force = body.force === false ? false : true;
  const variant = body.variant === "welcome_back" ? "welcome_back" : "welcome";
  const locale = (body.locale === "en" || body.locale === "es") ? body.locale : "";

  // .trim() to match the internal endpoint's stripped token — a trailing
  // newline on the env var otherwise mismatches → 401 (the http_401 the
  // admin tool surfaced; the Stripe webhook hit the same bug).
  const token = (process.env.PULPO_INTERNAL_TOKEN || "").trim();
  if (!token) {
    // Honest failure — never pretend the email sent.
    logApi({ status: 503, ms: Date.now() - t0, reason: "internal_token_missing" });
    await emitTriggerEvent({ to: email, by, force, variant, locale, result: "error", reason: "internal_token_missing" });
    return res.status(200).json({
      status: "error",
      reason: "internal_endpoint_not_configured",
      hint: "Set PULPO_INTERNAL_TOKEN in Vercel env so the admin test can run the real dispatcher.",
    });
  }

  const payload = { email, source: "admin", force, variant };
  if (locale) payload.locale = locale;

  const result = await callInternalWelcomeSend({
    baseUrl: internalBaseUrl(),
    token,
    payload,
    fetchImpl,
    timeoutMs: INTERNAL_TIMEOUT_MS,
  });

  if (!result.ok) {
    logApi({ status: 502, ms: Date.now() - t0, reason: result.reason });
    await emitTriggerEvent({ to: email, by, force, variant, locale, result: "error", reason: result.reason });
    return res.status(200).json({ status: "error", reason: result.reason });
  }

  // Internal endpoint: 200 = sent|skipped, 500 = failed, 4xx = bad request.
  const b = result.body || {};
  let status = b.status;
  if (status !== "sent" && status !== "skipped" && status !== "failed") {
    status = "error";
  }
  const reason = b.reason || (status === "error" ? (b.error || `http_${result.httpStatus}`) : null);

  logApi({
    status: 200, ms: Date.now() - t0, result: status, reason: reason || "-",
    variant, locale: locale || "clerk", dry_run: !!b.dry_run,
  });
  await emitTriggerEvent({ to: email, by, force, variant, locale, result: status, reason });

  return res.status(200).json({
    status,
    reason,
    message_id: b.message_id || null,
    dry_run: !!b.dry_run,
    variant,
    locale: locale || null,
    latency_ms: typeof b.latency_ms === "number" ? b.latency_ms : Date.now() - t0,
  });
}

module.exports = (req, res) => handler(req, res);
module.exports.handler = handler;
module.exports.callInternalWelcomeSend = callInternalWelcomeSend;
