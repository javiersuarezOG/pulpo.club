// In-memory per-IP+email rate limiter for the public /start checkout
// endpoint. No external service; the limit is per-Vercel-function-instance
// which is "good enough" for launch traffic. If we ever see real abuse
// in the logs (high non-200 rates without matching payments) the right
// upgrade is Upstash Redis behind the same hit() interface.
//
// Limit: 15 attempts per 60 seconds per (ip, email) key. Trips return 429.
// The key combines both axes because a single home IP can have multiple
// legitimate household members signing up, and a single email can have
// legitimate retries from a phone-then-desktop flow.
//
// Why 15 (was 5): starting a checkout is not itself an abuse vector — Stripe
// owns fraud/payment protection downstream. For ANONYMOUS visitors `email`
// is empty (Stripe collects it on the hosted page), so the key collapses to
// `${ip}|` and EVERY visitor behind one NAT / mobile-carrier / office IP
// shared a single 5/60s bucket. QA (and any shared-IP user who clicked
// Unlock → back → Unlock) tripped it in seconds, and once tripped even a
// single legitimate click 429'd for the next minute — blocking the user at
// the exact moment of paying. The client-side in-flight guard now prevents
// the click-flood; this ceiling only needs to stop pathological hammering,
// not normal shared-IP traffic. Real abuse in the logs → Upstash Redis
// behind the same hit() interface.
//
// The Map is bounded — entries older than the window are pruned on each
// hit. Memory is therefore O(active visitors in the last minute) per
// function instance.

const WINDOW_MS = 60 * 1000;
const MAX_ATTEMPTS = 15;

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
