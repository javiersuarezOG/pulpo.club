// Shared in-memory rate limiter for /api/* endpoints.
//
// Factory pattern — each caller builds its own limiter with its own
// (windowMs, maxAttempts) tuning, and the per-key history maps stay
// isolated from each other. State lives in the Vercel function instance
// memory; a cold start resets the counters but kills opportunistic
// scans for free. If we ever see real abuse in the logs (high non-200
// rates), the right upgrade is Upstash Redis behind the same hit()
// interface — none of the callers need to change.
//
// A separate per-endpoint limiter at api/stripe/_rate_limit.js predates
// this module and stays in place (start-checkout has a bespoke
// per-(ip,email) keying). New endpoints should use this generalized
// version.
//
// Tunings (set by each caller):
//   /api/saves        30 writes / 60s per user        (script-loop killer)
//   /api/geo          60 reads  / 60s per IP          (very generous)
//   /api/login        already has its own 10/300s     (auth-flow specific)

function ipFromRequest(req) {
  // Vercel sets x-forwarded-for; first hop is the originating client.
  const xff = req && req.headers && req.headers["x-forwarded-for"];
  if (typeof xff === "string" && xff.length > 0) {
    const first = xff.split(",")[0].trim();
    if (first) return first;
  }
  // Last-resort fallback. A misconfigured proxy that strips XFF
  // shouldn't grant unlimited attempts — bucket every such request
  // under "unknown" so they share one limit.
  return (req && req.socket && req.socket.remoteAddress) || "unknown";
}

function makeRateLimiter({ windowMs, maxAttempts, name = "default" }) {
  if (!Number.isFinite(windowMs) || windowMs <= 0) {
    throw new Error(`[rate_limit] ${name}: windowMs must be positive`);
  }
  if (!Number.isInteger(maxAttempts) || maxAttempts <= 0) {
    throw new Error(`[rate_limit] ${name}: maxAttempts must be a positive integer`);
  }

  const history = new Map(); // key -> Array<timestamp>

  function hit(key) {
    const k = (key == null ? "unknown" : String(key));
    const now = Date.now();
    const cutoff = now - windowMs;

    const prior = history.get(k) || [];
    const fresh = prior.filter((t) => t > cutoff);

    if (fresh.length >= maxAttempts) {
      const oldest = fresh[0];
      return {
        allowed: false,
        remaining: 0,
        retryAfterMs: Math.max(0, (oldest + windowMs) - now),
      };
    }

    fresh.push(now);
    history.set(k, fresh);

    // Opportunistic eviction — clear stale buckets so memory stays
    // O(active keys in the last window) per function instance.
    if (history.size > 5000 && Math.random() < 0.01) {
      for (const [hk, ts] of history) {
        if (ts.length === 0 || ts[ts.length - 1] < cutoff) history.delete(hk);
      }
    }

    return {
      allowed: true,
      remaining: maxAttempts - fresh.length,
      retryAfterMs: 0,
    };
  }

  // Exposed for tests — wipes all keys for this limiter instance.
  function reset() {
    history.clear();
  }

  return { hit, reset, windowMs, maxAttempts, name };
}

// Default 429 response shape. Sets Retry-After per spec and returns a
// JSON body consistent with the rest of the /api surface.
function send429(res, result, name) {
  const retryAfterSec = Math.max(1, Math.ceil(result.retryAfterMs / 1000));
  res.setHeader("Retry-After", String(retryAfterSec));
  return res.status(429).json({
    error: "rate_limited",
    retry_after_s: retryAfterSec,
    limiter: name,
  });
}

module.exports = { makeRateLimiter, ipFromRequest, send429 };
