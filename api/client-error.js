// POST /api/client-error
//
// Redundant client-error sink. The audit's P0-7 finding: PostHog is the
// only error pipeline today, so when PostHog is blocked (ad-blockers,
// Brave shields, EU users with declined consent, SDK load failure) we
// lose every client error. CLAUDE.md notes two `/preview` crashes have
// already shipped; the next one needs to land somewhere we can see it.
//
// This endpoint is the dumb backup: receives the error envelope from
// ErrorBoundary + the global window.error / unhandledrejection
// handlers, writes a single grep-friendly log line. Vercel runtime
// logs become the always-on backstop for triage during the first
// 100-users/day window. Once we have Sentry (or equivalent SaaS) we
// can revisit; this endpoint stays as the always-cheap fallback.
//
// Auth: none. Rate-limited per-IP to 60 / 60s (browsers can produce
// error storms — generous but capped so a runaway page can't DoS
// Vercel functions).
//
// Privacy: PII rule — do NOT log message bodies that look email-shaped,
// do NOT log full URLs (path + query stays; hash + sensitive params
// are stripped). Stack traces stay raw — they're function names and
// file paths, not user data.

const { makeRateLimiter, send429, ipFromRequest } = require("./_rate_limit");

const limiter = makeRateLimiter({
  windowMs: 60_000,
  maxAttempts: 60,
  name: "client_error",
});

// Conservative caps — anything bigger is almost certainly noise.
const MAX_MESSAGE_LEN = 2_000;
const MAX_STACK_LEN = 10_000;
const MAX_FIELD_LEN = 500;

function safeStr(v) {
  return typeof v === "string" ? v : "";
}

function truncate(s, max) {
  if (typeof s !== "string") return "";
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

// Strip query strings + fragments from any URL we log so we never
// surface email-in-URL or magic-link-token-in-URL bugs. Returns just
// `pathname` so logs stay greppable but free of secret-ish bits.
function safeUrl(raw) {
  if (typeof raw !== "string" || raw.length === 0) return "";
  try {
    const u = new URL(raw, "https://pulpo.club");
    return u.pathname;
  } catch {
    return "";
  }
}

// Scrub message bodies that look like they carry an email. Replaces
// the `@`-bearing token with `[redacted-email]`. Belt + braces over
// the URL scrubber.
function redactEmails(s) {
  if (typeof s !== "string") return "";
  return s.replace(/[\w.+-]+@[\w.-]+/g, "[redacted-email]");
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

module.exports = async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).end();
  }

  // Rate-limit per-IP — no auth context here.
  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    return send429(res, rl, "client_error");
  }

  const body = await readJsonBody(req);

  const message = redactEmails(truncate(safeStr(body.message), MAX_MESSAGE_LEN));
  const stack = redactEmails(truncate(safeStr(body.stack), MAX_STACK_LEN));
  const kind = truncate(safeStr(body.kind), MAX_FIELD_LEN);
  const section = truncate(safeStr(body.section), MAX_FIELD_LEN);
  const url = safeUrl(safeStr(body.url));
  const ua = truncate(safeStr(body.ua), MAX_FIELD_LEN);
  const lineno = Number.isFinite(body.lineno) ? body.lineno : "";
  const colno = Number.isFinite(body.colno) ? body.colno : "";
  const source = safeUrl(safeStr(body.source));

  // Single grep-friendly line. Field order matches the existing
  // server log convention (`[api] <name> status=… ms=… …`).
  // Newlines in stack are escaped so the log row stays single-line —
  // Vercel runtime-log search is line-oriented.
  const escapedStack = stack ? stack.replace(/\n/g, " \\n ") : "";
  console.error(
    `[api] client.error status=200 ms=${Date.now() - t0}`,
    `kind=${kind || "unknown"}`,
    `section=${section || "-"}`,
    `url=${url || "-"}`,
    `lineno=${lineno}`,
    `colno=${colno}`,
    source ? `source=${source}` : "",
    `ua="${ua.replace(/"/g, "'")}"`,
    `message="${message.replace(/"/g, "'")}"`,
    escapedStack ? `stack="${escapedStack.replace(/"/g, "'")}"` : "",
  );

  // 204 — no body needed; clients fire-and-forget via sendBeacon.
  return res.status(204).end();
};
