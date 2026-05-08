// Shared Clerk Backend client for /api/* endpoints.
//
// Lives at the api/ root because both the Stripe webhook and the
// saves endpoint need it. Lazy: the client is only constructed on
// first use, so an endpoint that never touches Clerk doesn't pay the
// init cost.
//
// Required env vars (both — Clerk Backend v3 needs the publishable key
// for cookie-suffix derivation inside authenticateRequest):
//   CLERK_SECRET_KEY        sk_test_… / sk_live_…
//   CLERK_PUBLISHABLE_KEY   pk_test_… / pk_live_…  (or fall back to
//                           VITE_CLERK_PUBLISHABLE_KEY, which Vercel
//                           also exposes to serverless functions —
//                           lets us reuse the frontend env var so
//                           Sebastian doesn't have to mirror it).
//
// Without the publishable key, every authenticateRequest() call
// throws "Publishable key is missing" deep inside Clerk's
// assertValidPublishableKey, which our endpoints catch as
// `auth_failed` 500. That was the prod regression on /api/saves
// and /api/stripe/* after Clerk-on default-flipped (PR-9d).
//
// `@clerk/backend` v3 expects a Web Fetch `Request` as the argument to
// `authenticateRequest`. Vercel hands the handler a Node
// `IncomingMessage` instead, so we have to translate. Without this
// translation, Clerk silently fails to read the session cookie and
// every signed-in request comes back as `unauthenticated`.

const { createClerkClient } = require("@clerk/backend");

let _clerk = null;
function clerkClient() {
  if (_clerk) return _clerk;
  const secretKey = process.env.CLERK_SECRET_KEY;
  if (!secretKey) throw new Error("CLERK_SECRET_KEY not set");
  // Prefer the explicit server-only var; fall back to the Vite-prefixed
  // one that the frontend reads — Vercel exposes every env var to
  // serverless functions regardless of prefix, so this lets Stripe
  // ship today without needing a second env-var write in the dashboard.
  const publishableKey =
    process.env.CLERK_PUBLISHABLE_KEY || process.env.VITE_CLERK_PUBLISHABLE_KEY;
  if (!publishableKey) {
    throw new Error(
      "CLERK_PUBLISHABLE_KEY (or VITE_CLERK_PUBLISHABLE_KEY) not set",
    );
  }
  _clerk = createClerkClient({ secretKey, publishableKey });
  return _clerk;
}

// Headers the Web Fetch `Headers` constructor either reserves or
// rejects with an InvalidCharacterError. Vercel's IncomingMessage may
// surface HTTP/2 pseudo-headers (`:authority`, `:method`, …) that
// start with a colon — those are invalid header names per the Web
// platform contract. Skip them; Clerk doesn't read them anyway.
function isValidHeaderName(name) {
  if (!name || typeof name !== "string") return false;
  if (name.startsWith(":")) return false;
  // RFC 7230 token: ALPHA / DIGIT / "!" / "#" / "$" / "%" / "&" / "'"
  // / "*" / "+" / "-" / "." / "^" / "_" / "`" / "|" / "~"
  return /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/.test(name);
}

// Convert a Vercel/Node `IncomingMessage` into a Web Fetch `Request`
// so Clerk can read cookies + headers off it. We only need
// method/URL/headers for session validation — the body is irrelevant
// to authenticateRequest, so a `null` body keeps the conversion cheap.
//
// Defensive: any header that fails Headers.set is logged + skipped
// rather than throwing; we'd rather lose one obscure header than
// 500 the whole endpoint.
function toWebRequest(req) {
  const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
  const host = req.headers["x-forwarded-host"] || req.headers.host || "localhost";
  const url = `${proto}://${host}${req.url || "/"}`;
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers || {})) {
    if (v == null) continue;
    if (!isValidHeaderName(k)) continue;
    try {
      if (Array.isArray(v)) {
        for (const item of v) headers.append(k, String(item));
      } else {
        headers.set(k, String(v));
      }
    } catch (err) {
      // Headers.set throws on invalid characters — keep going so a
      // single bad header doesn't fail the whole request.
      if (typeof console !== "undefined" && console.warn) {
        console.warn(`[api] toWebRequest: skipping header ${k}: ${err.message}`);
      }
    }
  }
  return new Request(url, { method: req.method || "GET", headers });
}

// Verify the Clerk session on an inbound request. Returns the Clerk
// userId or null when unauthenticated. Throws if Clerk's auth itself
// fails — caller is responsible for the catch-block.
async function authenticateClerkRequest(req) {
  const webRequest = toWebRequest(req);
  // Diagnostic — without this, a 500 from Clerk's auth path looks
  // identical whether the cookie was missing, the header was
  // mangled, or Clerk rejected the JWT. The single line below
  // separates "we never received a session cookie" from "Clerk said
  // no" in Vercel runtime logs.
  if (typeof console !== "undefined" && console.log) {
    const cookies = req.headers && req.headers.cookie;
    const cookieNames = typeof cookies === "string"
      ? cookies.split(";").map((c) => c.split("=")[0].trim()).filter(Boolean)
      : [];
    const hasSessionCookie = cookieNames.some((n) =>
      n === "__session" || n === "__client" || n.startsWith("__client_") || n.startsWith("__session_"));
    console.log(
      `[api] clerk.authReq cookies=${cookieNames.length} session_cookie=${hasSessionCookie ? "1" : "0"} url=${webRequest.url}`,
    );
  }
  const requestState = await clerkClient().authenticateRequest(webRequest);
  if (!requestState.isSignedIn) return null;
  const auth = requestState.toAuth();
  return auth.userId || null;
}

module.exports = { clerkClient, authenticateClerkRequest, toWebRequest };
