// POST /api/contact
//
// Public contact form. Validates the submission, looks up the correct
// inbox for the chosen topic from env vars (falling back to a founder
// fan-out so submissions never get lost while DNS is being set up),
// sends via Resend, and fires a sanitised PostHog event.
//
// Topical inboxes (per audit plan + legal_documents/05-data-subject-
// rights.md):
//   general → contact@pulpo.club
//   billing → contact@pulpo.club (alias)
//   privacy → privacy@pulpo.club    (DSR workflow inbox)
//   legal   → legal@pulpo.club      (takedown / disputes)
//   press   → contact@pulpo.club (alias)
//   abuse   → legal@pulpo.club (DMCA / takedown overlaps legal)
//
// Sebastian's runbook Task 3 sets up the topical inboxes via Resend
// inbound on pulpo.club. Until then, every PULPO_INBOX_<TOPIC> env
// var is unset and the FOUNDER_FAN_OUT below catches everything.
//
// Env vars (all optional — fan-out fallback handles the unset case):
//   RESEND_API_KEY            — re_… (required for the actual send)
//   PULPO_INBOX_GENERAL       — comma-separated recipient list
//   PULPO_INBOX_PRIVACY
//   PULPO_INBOX_LEGAL
//   PULPO_INBOX_ABUSE
//   PULPO_INBOX_PRESS
//   PULPO_INBOX_BILLING
//   RESEND_FROM_NOREPLY       — `Pulpo <noreply@pulpo.club>` (defaults
//                                 to the audit-plan baseline value)
//
// PII rule: never log the raw email or message body. The PostHog event
// payload carries topic + status only — no email, no name, no body
// content. Vercel runtime log only carries email_domain_only and
// message_chars.
//
// Rate limiting: 5 attempts per IP per 5-min window via api/_rate_limit.js.

const { Resend } = require("resend");
const { makeRateLimiter, send429, ipFromRequest } = require("./_rate_limit");
const posthog = require("./_posthog");
const withTiming = require("./_perf");

const FOUNDER_FAN_OUT = [
  "sebastian.honores@gmail.com",
  "javier@suarez.ventures",
];

const TOPIC_INBOX_ENV = {
  general:  "PULPO_INBOX_GENERAL",
  billing:  "PULPO_INBOX_BILLING",
  privacy:  "PULPO_INBOX_PRIVACY",
  legal:    "PULPO_INBOX_LEGAL",
  press:    "PULPO_INBOX_PRESS",
  abuse:    "PULPO_INBOX_ABUSE",
};

const TOPIC_KEYS = Object.keys(TOPIC_INBOX_ENV);
const TOPIC_SET = new Set(TOPIC_KEYS);

const limiter = makeRateLimiter({
  windowMs: 5 * 60 * 1000,
  maxAttempts: 5,
  name: "contact",
});

const MAX_MESSAGE_LEN = 5000;
const MAX_SUBJECT_LEN = 200;
const MAX_NAME_LEN = 100;
const MAX_EMAIL_LEN = 254;

// Loose RFC 5321 email check.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function safeStr(v) {
  return typeof v === "string" ? v : "";
}

function truncate(s, max) {
  return s.length > max ? s.slice(0, max) : s;
}

function resolveInbox(topic) {
  const envKey = TOPIC_INBOX_ENV[topic];
  const raw = (envKey && process.env[envKey]) || "";
  if (raw.trim()) {
    return raw.split(",").map((s) => s.trim()).filter(Boolean);
  }
  return [...FOUNDER_FAN_OUT];
}

function emailDomainOnly(email) {
  const at = email.indexOf("@");
  return at >= 0 ? email.slice(at + 1).toLowerCase() : "";
}

function logApi(name, fields) {
  const parts = ["[api]", name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try {
    const chunks = [];
    for await (const chunk of req) {
      chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
    }
    const raw = Buffer.concat(chunks).toString("utf8");
    if (!raw) return {};
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function buildEmail({ name, email, topic, subject, message }) {
  const subj = `[Pulpo Contact: ${topic}] ${subject || "(no subject)"}`;
  const safeName = escapeHtml(name || "(no name)");
  const safeEmail = escapeHtml(email);
  const safeSubject = escapeHtml(subject || "");
  const safeMessage = escapeHtml(message).replace(/\n/g, "<br>");
  const html = [
    `<p><strong>Topic:</strong> ${escapeHtml(topic)}</p>`,
    `<p><strong>From:</strong> ${safeName} &lt;${safeEmail}&gt;</p>`,
    `<p><strong>Subject:</strong> ${safeSubject}</p>`,
    `<hr>`,
    `<p>${safeMessage}</p>`,
    `<hr>`,
    `<p style="font-size:12px;color:#666">Sent via the pulpo.club /contact form. Reply-To is set to the user's address; replying from your inbox goes straight to them.</p>`,
  ].join("\n");
  const text = [
    `Topic: ${topic}`,
    `From: ${name || "(no name)"} <${email}>`,
    `Subject: ${subject || "(no subject)"}`,
    "----",
    message,
    "----",
    "Sent via the pulpo.club /contact form.",
  ].join("\n");
  return { subject: subj, html, text };
}

// PR-perf-5a — withTiming wraps every response with Server-Timing +
// X-Vercel-Region so the Geo Latency dashboard can split server vs
// network ms by region.
module.exports = withTiming(async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi("contact", { status: 405, ms: Date.now() - t0, reason: "method" });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  // Rate-limit per IP. Done BEFORE body parsing so abuse can't waste
  // function CPU on JSON parsing + email validation.
  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    logApi("contact", {
      status: 429, ms: Date.now() - t0, reason: "rate_limited",
      retry_ms: rl.retryAfterMs,
    });
    posthog.capture(null, "contact.form_submitted", {
      topic: "", status: "rate_limit",
    });
    await posthog.flush();
    return send429(res, rl, "contact");
  }

  const body = await readJsonBody(req);

  // Honeypot: bots fill every field; humans don't see this one. If it
  // has any content, ack 200 silently so the bot thinks it succeeded.
  const honeypot = safeStr(body.honeypot).trim();
  if (honeypot) {
    logApi("contact", {
      status: 200, ms: Date.now() - t0, reason: "honeypot_tripped",
    });
    // Don't fire telemetry — bots would inflate the count.
    return res.status(200).json({ ok: true });
  }

  const topic = safeStr(body.topic).toLowerCase();
  const email = truncate(safeStr(body.email).trim().toLowerCase(), MAX_EMAIL_LEN);
  const name = truncate(safeStr(body.name).trim(), MAX_NAME_LEN);
  const subject = truncate(safeStr(body.subject).trim(), MAX_SUBJECT_LEN);
  const message = truncate(safeStr(body.message).trim(), MAX_MESSAGE_LEN);

  // Validation.
  if (!TOPIC_SET.has(topic)) {
    logApi("contact", { status: 400, ms: Date.now() - t0, reason: "invalid_topic" });
    posthog.capture(null, "contact.form_submitted", { topic, status: "validation_error" });
    await posthog.flush();
    return res.status(400).json({ error: "invalid_topic" });
  }
  if (!email || !EMAIL_RE.test(email)) {
    logApi("contact", { status: 400, ms: Date.now() - t0, reason: "invalid_email" });
    posthog.capture(null, "contact.form_submitted", { topic, status: "validation_error" });
    await posthog.flush();
    return res.status(400).json({ error: "invalid_email" });
  }
  if (message.length < 5) {
    logApi("contact", { status: 400, ms: Date.now() - t0, reason: "message_too_short" });
    posthog.capture(null, "contact.form_submitted", { topic, status: "validation_error" });
    await posthog.flush();
    return res.status(400).json({ error: "message_too_short" });
  }

  // Send via Resend. Graceful degrade: if the API key is missing, log
  // + 503 so the form shows the generic error toast (matches the
  // newsletter endpoint's degrade behaviour).
  const apiKey = process.env.RESEND_API_KEY;
  if (!apiKey) {
    logApi("contact", {
      status: 503, ms: Date.now() - t0, reason: "resend_not_configured",
      topic, email_domain_only: emailDomainOnly(email),
    });
    posthog.capture(null, "contact.form_submitted", { topic, status: "server_error" });
    await posthog.flush();
    return res.status(503).json({ error: "service_unavailable" });
  }

  const inbox = resolveInbox(topic);
  const from = process.env.RESEND_FROM_NOREPLY || "Pulpo <noreply@pulpo.club>";
  const built = buildEmail({ name, email, topic, subject, message });

  try {
    const resend = new Resend(apiKey);
    await resend.emails.send({
      from,
      to: inbox,
      reply_to: email,
      subject: built.subject,
      html: built.html,
      text: built.text,
    });
  } catch (err) {
    logApi("contact", {
      status: 502, ms: Date.now() - t0, reason: "resend_error",
      topic, email_domain_only: emailDomainOnly(email),
      error: (err && err.message) || "(no message)",
    });
    posthog.capture(null, "contact.form_submitted", { topic, status: "server_error" });
    await posthog.flush();
    return res.status(502).json({ error: "upstream_error" });
  }

  logApi("contact", {
    status: 200, ms: Date.now() - t0, topic,
    email_domain_only: emailDomainOnly(email),
    message_chars: message.length,
    recipients: inbox.length,
    used_fallback: process.env[TOPIC_INBOX_ENV[topic]] ? 0 : 1,
  });
  posthog.capture(null, "contact.form_submitted", { topic, status: "success" });
  await posthog.flush();

  return res.status(200).json({ ok: true });
});
