// GET /api/admin/newsletter/audience-count
//
// Returns the live count of Pro/Agency subscribers eligible for the
// personalized newsletter — i.e. the size of:
//
//   (Resend audience contacts where !unsubscribed) ∩ (Clerk users where plan ∈ {pro, agency})
//
// Powers the "Send to everyone" confirmation modal in NewsletterWidget.
// The operator clicks "Send to everyone" → this endpoint runs → the
// modal shows "Send Issue N to <count> readers?" before the type-to-
// confirm gate.
//
// Auth: deliberately none beyond rate-limiting. Mirrors the
// trigger-preview.js posture — admin endpoints are not user-facing,
// the security perimeter is the GitHub PAT not exposed here. The
// number itself is non-sensitive (it's already visible in workflow
// logs after every send).
//
// Rate limit: 30 reads / 60s per IP — generous; this is a cheap GET
// the modal calls once per open. Strict enough to kill a script loop.

const {
  RESEND_API_KEY,
  RESEND_AUDIENCE_ID,
  CLERK_SECRET_KEY,
} = process.env;

const RESEND_API_BASE = "https://api.resend.com";
const CLERK_API_BASE = "https://api.clerk.com/v1";
const CLERK_PAGE_SIZE = 100;

const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");

const limiter = makeRateLimiter({
  windowMs: 60_000,
  maxAttempts: 30,
  name: "admin_newsletter_audience_count",
});

function logApi(fields) {
  const parts = ["[api]", "admin_newsletter_audience_count"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

async function getJSON(url, headers) {
  const r = await fetch(url, { headers });
  if (!r.ok) {
    throw new Error(`${url} → ${r.status}`);
  }
  return r.json();
}

async function listResendAudienceEmails() {
  if (!RESEND_API_KEY || !RESEND_AUDIENCE_ID) return [];
  const url = `${RESEND_API_BASE}/audiences/${RESEND_AUDIENCE_ID}/contacts`;
  const payload = await getJSON(url, {
    Authorization: `Bearer ${RESEND_API_KEY}`,
  });
  const rows = Array.isArray(payload && payload.data) ? payload.data : [];
  const out = new Set();
  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    if (r.unsubscribed) continue;
    const email = typeof r.email === "string" ? r.email.trim().toLowerCase() : "";
    if (email && email.includes("@")) out.add(email);
  }
  return out;
}

async function listClerkProEmails() {
  if (!CLERK_SECRET_KEY) return new Set();
  const headers = {
    Authorization: `Bearer ${CLERK_SECRET_KEY}`,
  };
  const out = new Set();
  let offset = 0;
  // Pulpo audience is small enough that paginating ~100 users at a
  // time per request adds up to ~5s in the worst case. Acceptable for
  // a modal that gates an audience send.
  for (let page = 0; page < 50; page++) {
    const params = new URLSearchParams({
      limit: String(CLERK_PAGE_SIZE),
      offset: String(offset),
    });
    const payload = await getJSON(
      `${CLERK_API_BASE}/users?${params.toString()}`,
      headers,
    );
    const rows = Array.isArray(payload) ? payload : (payload && payload.data) || [];
    if (!Array.isArray(rows) || rows.length === 0) break;
    for (const u of rows) {
      if (!u || typeof u !== "object") continue;
      const publicMd = u.public_metadata || u.publicMetadata || {};
      const plan = typeof publicMd.plan === "string" ? publicMd.plan : null;
      if (plan !== "pro" && plan !== "agency") continue;
      // Resolve primary email — mirrors automation/newsletter/subscribers.py
      const addresses = u.email_addresses || u.emailAddresses || [];
      const primaryId = u.primary_email_address_id || u.primaryEmailAddressId;
      let email = "";
      if (primaryId && Array.isArray(addresses)) {
        for (const a of addresses) {
          if (a && a.id === primaryId) {
            email = a.email_address || a.emailAddress || "";
            break;
          }
        }
      }
      if (!email && Array.isArray(addresses)) {
        for (const a of addresses) {
          email = (a && (a.email_address || a.emailAddress)) || "";
          if (email) break;
        }
      }
      email = typeof email === "string" ? email.trim().toLowerCase() : "";
      if (email && email.includes("@")) out.add(email);
    }
    if (rows.length < CLERK_PAGE_SIZE) break;
    offset += CLERK_PAGE_SIZE;
  }
  return out;
}

module.exports = async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    logApi({ status: 405, ms: Date.now() - t0, reason: "method", method: req.method });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const ip = ipFromRequest(req);
  const rl = limiter.hit(ip);
  if (!rl.allowed) {
    logApi({ status: 429, ms: Date.now() - t0, reason: "rate_limited" });
    return send429(res, rl, "admin_newsletter_audience_count");
  }

  try {
    const [resendEmails, clerkProEmails] = await Promise.all([
      listResendAudienceEmails(),
      listClerkProEmails(),
    ]);
    // Intersection: only Pro/Agency users who are still in the Resend
    // audience (haven't unsubscribed) actually receive the newsletter.
    let count = 0;
    for (const email of clerkProEmails) {
      if (resendEmails.has(email)) count += 1;
    }
    const elapsedMs = Date.now() - t0;
    logApi({
      status: 200,
      ms: elapsedMs,
      count,
      resend: resendEmails.size,
      clerk_pro: clerkProEmails.size,
    });
    return res.status(200).json({
      count,
      resend_total: resendEmails.size,
      clerk_pro_total: clerkProEmails.size,
      computed_at: new Date().toISOString(),
      source: "live",
    });
  } catch (err) {
    logApi({
      status: 500,
      ms: Date.now() - t0,
      error: err && err.message,
    });
    return res.status(500).json({ error: "lookup_failed" });
  }
};
