// POST /api/admin/newsletter/trigger-free-welcome-test
//
// Body: { email, by?, variant?: "free_welcome"|"free_welcome_back",
//         locale?: "en"|"es" }
//
// Operator surface for the DB-free Pulpo Free Welcome / Welcome-back
// templates. Calls /api/internal/free-welcome-send synchronously and
// returns the real sent / skipped / failed outcome.

const { requireAdminAuth } = require("../../_admin_auth");
const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");
const posthog = require("../../_posthog");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const INTERNAL_PATH = "/api/internal/free-welcome-send";
const INTERNAL_TIMEOUT_MS = 25_000;

function internalBaseUrl() {
  return process.env.PULPO_SITE_ROOT || "https://pulpo.club";
}

async function emitTriggerEvent({ to, by, variant, locale, result, reason }) {
  try {
    posthog.capture(
      posthog.emailDistinctId(by || to),
      "admin.newsletter_test_triggered",
      {
        to,
        by: by || null,
        newsletter_id: variant === "free_welcome_back" ? "free-welcome-back" : "free-welcome",
        variant: variant || "free_welcome",
        locale: locale || null,
        force: true,
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
  name: "admin_newsletter_trigger_free_welcome_test",
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
  const parts = ["[api]", "admin.newsletter_trigger_free_welcome_test"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

async function callInternalFreeWelcomeSend({ baseUrl, token, payload, fetchImpl, timeoutMs }) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), timeoutMs || INTERNAL_TIMEOUT_MS);
  try {
    const r = await (fetchImpl || fetch)(`${baseUrl}${INTERNAL_PATH}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "pulpo-admin-free-welcome-test",
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
  if (!requireAdminAuth(req, res)) return;

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    logApi({ status: 429, ms: Date.now() - t0 });
    return send429(res, rl, "admin_newsletter_trigger_free_welcome_test");
  }

  const body = await readJsonBody(req);
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!email || !EMAIL_RE.test(email)) {
    return res.status(400).json({ status: "error", reason: "invalid_email" });
  }
  const by = typeof body.by === "string" && EMAIL_RE.test(body.by.trim().toLowerCase())
    ? body.by.trim().toLowerCase()
    : null;
  const variant = body.variant === "free_welcome_back" ? "free_welcome_back" : "free_welcome";
  const locale = (body.locale === "en" || body.locale === "es") ? body.locale : "en";

  const token = (process.env.PULPO_INTERNAL_TOKEN || "").trim();
  if (!token) {
    logApi({ status: 503, ms: Date.now() - t0, reason: "internal_token_missing" });
    await emitTriggerEvent({ to: email, by, variant, locale, result: "error", reason: "internal_token_missing" });
    return res.status(200).json({
      status: "error",
      reason: "internal_endpoint_not_configured",
      hint: "Set PULPO_INTERNAL_TOKEN in Vercel env so the admin test can run the real dispatcher.",
    });
  }

  const result = await callInternalFreeWelcomeSend({
    baseUrl: internalBaseUrl(),
    token,
    payload: { email, source: "admin", force: true, is_new_contact: true, variant, locale },
    fetchImpl,
    timeoutMs: INTERNAL_TIMEOUT_MS,
  });

  if (!result.ok) {
    logApi({ status: 502, ms: Date.now() - t0, reason: result.reason });
    await emitTriggerEvent({ to: email, by, variant, locale, result: "error", reason: result.reason });
    return res.status(200).json({ status: "error", reason: result.reason });
  }

  const b = result.body || {};
  let status = b.status;
  if (status !== "sent" && status !== "skipped" && status !== "failed") {
    status = "error";
  }
  const reason = b.reason || (status === "error" ? (b.error || `http_${result.httpStatus}`) : null);

  logApi({
    status: 200, ms: Date.now() - t0, result: status, reason: reason || "-",
    variant, locale, dry_run: !!b.dry_run,
  });
  await emitTriggerEvent({ to: email, by, variant, locale, result: status, reason });

  return res.status(200).json({
    status,
    reason,
    message_id: b.message_id || null,
    dry_run: !!b.dry_run,
    variant,
    locale,
    latency_ms: typeof b.latency_ms === "number" ? b.latency_ms : Date.now() - t0,
  });
}

module.exports = (req, res) => handler(req, res);
module.exports.handler = handler;
module.exports.callInternalFreeWelcomeSend = callInternalFreeWelcomeSend;
