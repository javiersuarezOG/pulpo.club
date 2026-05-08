// Shared Clerk Backend client for /api/* endpoints.
//
// Lives at the api/ root because both the Stripe webhook and the
// saves endpoint need it. Lazy: the client is only constructed on
// first use, so an endpoint that never touches Clerk doesn't pay the
// init cost.
//
// Required env var: CLERK_SECRET_KEY (sk_test_… / sk_live_…), Backend
// API key from https://dashboard.clerk.com/~/api-keys.
//
// `@clerk/backend` v3 expects a Web Fetch `Request` as the argument to
// `authenticateRequest`. Vercel hands the handler a Node
// `IncomingMessage` instead, so we have to translate. Without this
// translation, Clerk silently fails to read the session cookie and
// every signed-in request comes back as `unauthenticated`. That's the
// 500 / `sign_in_required` regression that hit /api/saves and
// /api/stripe/create-checkout-session in dev.

const { createClerkClient } = require("@clerk/backend");

let _clerk = null;
function clerkClient() {
  if (_clerk) return _clerk;
  const key = process.env.CLERK_SECRET_KEY;
  if (!key) throw new Error("CLERK_SECRET_KEY not set");
  _clerk = createClerkClient({ secretKey: key });
  return _clerk;
}

// Convert a Vercel/Node `IncomingMessage` into a Web Fetch `Request`
// so Clerk can read cookies + headers off it. We only need
// method/URL/headers for session validation — the body is irrelevant
// to authenticateRequest, so a `null` body keeps the conversion cheap.
function toWebRequest(req) {
  const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
  const host = req.headers["x-forwarded-host"] || req.headers.host || "localhost";
  const url = `${proto}://${host}${req.url || "/"}`;
  // Clone headers — duplicates and array-valued entries are flattened
  // by the Headers constructor to the comma-joined form Clerk expects.
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers || {})) {
    if (v == null) continue;
    if (Array.isArray(v)) {
      for (const item of v) headers.append(k, String(item));
    } else {
      headers.set(k, String(v));
    }
  }
  return new Request(url, { method: req.method || "GET", headers });
}

// Verify the Clerk session on an inbound request. Returns the userId
// or null when the request is unauthenticated. Wraps Clerk's
// authenticateRequest so call sites don't need to know the exact API.
async function authenticateClerkRequest(req) {
  const webRequest = toWebRequest(req);
  const requestState = await clerkClient().authenticateRequest(webRequest);
  if (!requestState.isSignedIn) return null;
  const auth = requestState.toAuth();
  return auth.userId || null;
}

module.exports = { clerkClient, authenticateClerkRequest, toWebRequest };
