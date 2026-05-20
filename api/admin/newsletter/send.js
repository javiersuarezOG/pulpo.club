// POST /api/admin/newsletter/send
//
// Body: { cohort, locale, issue_number, recipients: string[], preference: {...} }
//
// Same filter + render as /api/admin/newsletter/preview, then dispatches
// the rendered HTML to up to 5 recipients via Resend. The subject is
// hard-coded with a `[PULPO ADMIN TEST]` prefix so a misdelivered email
// is unambiguously not the production newsletter.
//
// No auth (the /admin page is open by design — see AdminShell.jsx). The
// 5-recipient cap is the load-bearing blast-radius guard; audience-wide
// sends remain in the `pulpo-newsletter` GitHub Actions workflow.
//
// Rate limit: 10 sends per IP per hour (reuses api/_rate_limit.js).
// PostHog: fires `admin.newsletter.test_sent` with recipient hashes
// (not raw addresses) + filter trace for audit.

const crypto = require("crypto");
const { Resend } = require("resend");
const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");
const posthog = require("../../_posthog");
const { loadRanked, normalizePreference, applyPreference, selectPicks } = require("./_filter");
const { renderAdminIssue } = require("./_render");

const COHORTS = new Set(["pro_prefs", "free_prefs", "logged_no_prefs", "anonymous"]);
const LOCALES = new Set(["en", "es"]);
const MAX_RECIPIENTS = 5;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const limiter = makeRateLimiter({
  windowMs: 60 * 60 * 1000,         // 1 hour
  maxAttempts: 10,                  // 10 calls/hr/IP × 5 recipients = 50 emails/hr ceiling
  name: "admin_newsletter_send",
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

function logApi(name, fields) {
  const parts = ["[api]", name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

function emailHash(email) {
  return crypto.createHash("sha256")
    .update(String(email || "").trim().toLowerCase())
    .digest("hex")
    .slice(0, 16);
}

function emailDomainOnly(email) {
  const at = String(email || "").indexOf("@");
  return at >= 0 ? email.slice(at + 1).toLowerCase() : "";
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    logApi("admin.newsletter_send", { status: 429, ms: Date.now() - t0, reason: "rate_limited" });
    return send429(res, rl, "admin_newsletter_send");
  }

  const body = await readJsonBody(req);

  // Validate recipients first — cheapest failure case.
  const rawList = Array.isArray(body.recipients) ? body.recipients : [];
  const recipients = [];
  const seen = new Set();
  for (const r of rawList) {
    const v = typeof r === "string" ? r.trim().toLowerCase() : "";
    if (!v || !EMAIL_RE.test(v)) continue;
    if (seen.has(v)) continue;
    seen.add(v);
    recipients.push(v);
  }
  if (recipients.length === 0) {
    return res.status(400).json({ error: "no_valid_recipients" });
  }
  if (recipients.length > MAX_RECIPIENTS) {
    return res.status(400).json({
      error: "too_many_recipients",
      max: MAX_RECIPIENTS,
      hint: "Audience-wide sends stay in the pulpo-newsletter GitHub Actions workflow.",
    });
  }

  const cohort = COHORTS.has(body.cohort) ? body.cohort : "pro_prefs";
  const locale = LOCALES.has(body.locale) ? body.locale : "en";
  const issueNumber = Number.isInteger(body.issue_number) && body.issue_number > 0
    ? body.issue_number
    : 1;
  const preference = normalizePreference(body.preference);

  const data = loadRanked();
  if (!data || !Array.isArray(data)) {
    return res.status(503).json({ error: "ranked_not_available" });
  }
  const sorted = [...data].sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999));
  const filtered = applyPreference(sorted, preference);
  const { kept } = selectPicks(filtered, 10);

  const html = renderAdminIssue({
    picks: kept,
    cohort,
    locale,
    issueNumber,
    filterTrace: preference,
  });
  const subject = locale === "es"
    ? `[PULPO ADMIN TEST] Edición ${String(issueNumber).padStart(2, "0")} · ${kept.length} selecciones`
    : `[PULPO ADMIN TEST] Issue ${String(issueNumber).padStart(2, "0")} · ${kept.length} picks`;

  // Resend send. We don't fan out via Resend's `to` array because we want
  // a separate `message_id` per recipient for traceability.
  const apiKey = process.env.RESEND_API_KEY;
  if (!apiKey) {
    logApi("admin.newsletter_send", {
      status: 503, ms: Date.now() - t0, reason: "resend_not_configured",
      recipients: recipients.length, cohort, picks_total: kept.length,
    });
    return res.status(503).json({
      error: "resend_not_configured",
      hint: "Set RESEND_API_KEY + RESEND_FROM_EMAIL in Vercel env to enable real sends.",
    });
  }
  const from = process.env.RESEND_FROM_EMAIL || "Pulpo <hello@mail.pulpo.club>";
  const replyTo = process.env.RESEND_REPLY_TO_EMAIL || undefined;
  const resend = new Resend(apiKey);

  let sent = 0;
  let failed = 0;
  const messageIds = [];
  const errors = [];
  for (const to of recipients) {
    try {
      const result = await resend.emails.send({
        from,
        to,
        reply_to: replyTo,
        subject,
        html,
        headers: {
          "X-Pulpo-Admin-Test": "1",
          "X-Pulpo-Cohort": cohort,
        },
      });
      const id = (result && result.data && result.data.id) || (result && result.id) || null;
      messageIds.push(id);
      sent++;
      posthog.capture(`email:${emailHash(to)}`, "admin.newsletter.test_sent", {
        cohort, locale, issue_number: issueNumber,
        picks_total: kept.length,
        email_domain_only: emailDomainOnly(to),
        message_id: id,
        filter_trace: preference,
      });
    } catch (err) {
      failed++;
      const msg = (err && err.message) || "(no message)";
      errors.push({ to_domain: emailDomainOnly(to), error: msg });
      logApi("admin.newsletter_send", {
        status: "partial_fail", to_domain: emailDomainOnly(to), error: msg,
      });
    }
  }
  await posthog.flush();

  logApi("admin.newsletter_send", {
    status: failed === 0 ? 200 : 207, ms: Date.now() - t0,
    sent, failed, recipients: recipients.length,
    cohort, locale, issue: issueNumber, picks_total: kept.length,
  });

  return res.status(failed === 0 ? 200 : 207).json({
    sent,
    failed,
    message_ids: messageIds,
    errors,
    picks_total: kept.length,
    cohort,
    filter_trace: preference,
  });
};
