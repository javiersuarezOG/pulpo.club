// In-memory per-IP+email rate limiter for the public /start checkout
// endpoint. No external service; the limit is per-Vercel-function-instance
// which is "good enough" for launch traffic. If we ever see real abuse
// in the logs (high non-200 rates without matching payments) the right
// upgrade is Upstash Redis behind the same hit() interface.
//
// Limit: 5 attempts per 60 seconds per (ip, email) key. Trips return 429.
// The key combines both axes because a single home IP can have multiple
// legitimate household members signing up, and a single email can have
// legitimate retries from a phone-then-desktop flow.
//
// The Map is bounded — entries older than the window are pruned on each
// hit. Memory is therefore O(active visitors in the last minute) per
// function instance.

const WINDOW_MS = 60 * 1000;
const MAX_ATTEMPTS = 5;

const HISTORY = new Map(); // key -> Array<timestamp>

function ipFromRequest(req) {
  // Vercel sets x-forwarded-for; first hop is the originating client.
  const xff = req && req.headers && req.headers["x-forwarded-for"];
  if (typeof xff === "string" && xff.length > 0) {
    return xff.split(",")[0].trim();
  }
  // Fall back to socket address (dev-server path). Never null — we still
  // want a key so unkeyed traffic shares one bucket.
  return (req && req.socket && req.socket.remoteAddress) || "unknown";
}

// hit() returns { allowed, remaining, retryAfterMs }. The caller decides
// how to respond — for /start we 429 on !allowed, with Retry-After set.
function hit(req, email) {
  const ip = ipFromRequest(req);
  const key = `${ip}|${(email || "").toLowerCase()}`;
  const now = Date.now();
  const cutoff = now - WINDOW_MS;

  const prior = HISTORY.get(key) || [];
  const fresh = prior.filter((t) => t > cutoff);

  if (fresh.length >= MAX_ATTEMPTS) {
    const oldest = fresh[0];
    return {
      allowed: false,
      remaining: 0,
      retryAfterMs: Math.max(0, (oldest + WINDOW_MS) - now),
    };
  }

  fresh.push(now);
  HISTORY.set(key, fresh);

  // Opportunistic eviction — clear entries with no recent hits so the Map
  // doesn't grow unbounded across cold-start lifetimes. Cheap because we
  // only walk on every Nth call.
  if (HISTORY.size > 5000 && Math.random() < 0.01) {
    for (const [k, ts] of HISTORY) {
      if (ts.length === 0 || ts[ts.length - 1] < cutoff) HISTORY.delete(k);
    }
  }

  return {
    allowed: true,
    remaining: MAX_ATTEMPTS - fresh.length,
    retryAfterMs: 0,
  };
}

module.exports = { hit, WINDOW_MS, MAX_ATTEMPTS };
