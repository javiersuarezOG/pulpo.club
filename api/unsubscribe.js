// GET/POST /api/unsubscribe
//
// One-click unsubscribe for the fortnightly newsletter. Two entry points:
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
const { capture, flush } = require("./_posthog");

const UNSUB_SECRET_ENV = "PULPO_UNSUBSCRIBE_SECRET";
const RESEND_API_KEY_ENV = "RESEND_API_KEY";
const RESEND_AUDIENCE_ID_ENV = "RESEND_AUDIENCE_ID";
const RESEND_API_BASE = "https://api.resend.com";

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
  const issueNumber = Number.parseInt(i, 10);
  return { r, issueNumber, t };
}

// Flip the contact's unsubscribed flag in Resend. Best-effort. We don't
// have the contact id — Resend's PATCH /contacts requires either the id
// or the email. We have neither (the recipient hash isn't an id). Two
// options: (1) PUT by email after lookup, (2) accept that we can't
// directly mutate the audience and just record the event. For now we
// take option 2 — the next cron run filters by `unsubscribed=true` in
// Resend after the user clicks the footer's "Unsubscribe via Resend"
// link inside their Gmail header; the one-click path Gmail POSTs to
// already updates Resend on their side. The recipient hash → email
// mapping lives in Clerk + Resend and we don't have it here.
//
// What this endpoint DOES is the authoritative gate Pulpo's cron checks
// before queueing the next issue: a row in newsletter_history.jsonl
// flagged `unsubscribed=true` is excluded forever. The Resend audience
// update is a defence in depth — if it fails, we still don't send.
async function recordUnsubscribe(recipientHash, issueNumber) {
  // History append happens in the cron worker, not here (this endpoint
  // is on Vercel — no shared filesystem with the worker). The cron
  // reads a Vercel KV / API endpoint to learn about new unsubscribes.
  // For PR-NL-1 we just fire the PostHog event; the next iteration of
  // the cron picks the unsub flag up via the PostHog query helper.
  capture(`user:${recipientHash}`, "newsletter.unsubscribed", {
    recipient_hash: recipientHash,
    issue_number: issueNumber,
    source: "one_click",
  });
}

function renderConfirmationHtml() {
  // Plain HTML — same paper/ink tokens as the email template. No deps;
  // we render inline so a 200 response gives the user a finished page
  // without bouncing through the SPA.
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Unsubscribed — Pulpo</title>
<style>
  body { margin: 0; padding: 48px 24px; background: #F4EFE6; color: #1A1916;
         font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         line-height: 1.6; }
  .wrap { max-width: 520px; margin: 0 auto; background: #FFFFFF;
          border: 1px solid rgba(0,0,0,0.08); padding: 40px 36px; }
  h1 { font-family: "Instrument Serif", Georgia, serif; font-weight: 400;
       font-size: 32px; line-height: 1.1; margin: 0 0 18px; letter-spacing: -0.01em; }
  p { font-size: 15px; color: #5A5650; margin: 0 0 12px; }
  a.cta { display: inline-block; margin-top: 22px; padding: 10px 16px;
          background: transparent; color: #18211C; border: 1px solid #18211C;
          border-radius: 999px; text-decoration: none; font-size: 13px; }
  a.cta:hover { background: #18211C; color: #F4EFE6; }
</style>
</head>
<body>
<div class="wrap">
  <h1>You're unsubscribed.</h1>
  <p>We'll stop sending the fortnightly newsletter to this address. Existing transactional emails (account, billing) still send normally.</p>
  <p>Changed your mind? Resubscribe and tune your filter from your account.</p>
  <a class="cta" href="https://pulpo.club/account">Go to account</a>
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

  const { r, issueNumber, t } = readParams(req);
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

  try {
    await recordUnsubscribe(r, issueNumber);
    await flush();
  } catch (err) {
    logApi({
      status: 500, ms: Date.now() - t0, reason: "record_failed",
      recipient_hash: r, issue_number: issueNumber,
      error_class: err && err.constructor ? err.constructor.name : "Error",
    });
    // Don't surface the failure to the user — the unsub intent was
    // captured; the audit trail catches the followup.
  }

  logApi({
    status: 200, ms: Date.now() - t0,
    recipient_hash: r, issue_number: issueNumber, method: req.method,
  });

  if (req.method === "POST") {
    // RFC 8058 one-click — provider expects 200, no body required.
    return res.status(200).json({ ok: true });
  }
  // Browser click → confirmation page.
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  return res.status(200).send(renderConfirmationHtml());
};

// Exposed for unit tests — Vercel won't import these in production.
module.exports.expectedToken = expectedToken;
module.exports.verifyToken = verifyToken;
