// POST /api/login   { code }   -> 200 { ok: true } + Set-Cookie
// GET  /api/login              -> 405

const { checkPassword, issueToken, buildCookie } = require("./_auth");

// Grep-able single-line log so Vercel Runtime Logs can be filtered.
// No PII — only request shape + outcome + duration. Real PostHog auth
// events (signup.completed) fire from the FE side.
function logApi(name, { status, ms, extra }) {
  const parts = [`[api]`, name, `status=${status}`, `ms=${ms}`];
  if (extra) {
    for (const [k, v] of Object.entries(extra)) parts.push(`${k}=${v}`);
  }
  console.log(parts.join(" "));
}

// In-memory per-IP rate limit for /api/login. Cap brute-force attempts
// against the shared bcrypt ACCESS_HASH on the legacy paywall.
//
// Limit: 10 attempts per IP per 5-minute window.
//
// Storage: Map keyed by IP. Resets on Vercel cold start (so a determined
// attacker can wait it out), but kills opportunistic scans for free. For
// stronger protection (durable across cold starts), swap this for
// Upstash Redis or Vercel KV — same per-IP shape.
//
// Memory: pruned lazily — when the map exceeds RATE_LIMIT_PRUNE_AT
// entries, expired windows are evicted on the next write.
const RATE_LIMIT_WINDOW_MS = 5 * 60 * 1000;
const RATE_LIMIT_MAX_ATTEMPTS = 10;
const RATE_LIMIT_PRUNE_AT = 1000;

const _rateLimitMap = new Map();

function clientIp(req) {
  const xff = req.headers["x-forwarded-for"];
  if (typeof xff === "string" && xff.length > 0) {
    // x-forwarded-for is a comma-separated chain; the leftmost entry is
    // the original client. Take the first non-empty token.
    const first = xff.split(",")[0].trim();
    if (first) return first;
  }
  // Last-resort fallbacks. socket.remoteAddress is set on Node sockets;
  // "unknown" buckets everything-else into a shared limit (intentionally —
  // a misconfigured proxy that strips x-forwarded-for shouldn't grant
  // unlimited attempts).
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

// Returns { allowed: true } or { allowed: false, retryAfterSec }. Increments
// the counter on every call (so even successful logins eat one slot — fine
// for the brute-force model, and a legit user only logs in once per session).
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

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi("login", { status: 405, ms: Date.now() - t0, extra: { reason: "method" } });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const ip = clientIp(req);
  const rl = checkRateLimit(ip);
  if (!rl.allowed) {
    res.setHeader("Retry-After", String(rl.retryAfterSec));
    logApi("login", {
      status: 429, ms: Date.now() - t0,
      extra: { reason: "rate_limited", retry_after_s: rl.retryAfterSec },
    });
    return res.status(429).json({ error: "rate_limited", retry_after_s: rl.retryAfterSec });
  }

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { body = {}; }
  }
  body = body || {};
  const code = (body.code || "").toString();

  if (!code) {
    logApi("login", { status: 400, ms: Date.now() - t0, extra: { reason: "no_code" } });
    return res.status(400).json({ error: "missing_code" });
  }

  const ok = await checkPassword(code);
  if (!ok) {
    logApi("login", { status: 401, ms: Date.now() - t0, extra: { reason: "bad_code" } });
    return res.status(401).json({ error: "invalid_code" });
  }

  const token = issueToken();
  res.setHeader("Set-Cookie", buildCookie(token));
  logApi("login", { status: 200, ms: Date.now() - t0 });
  return res.status(200).json({ ok: true });
};
