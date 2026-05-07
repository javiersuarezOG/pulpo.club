// Shared Clerk Backend client for /api/* endpoints.
//
// Lives at the api/ root because both the Stripe webhook and the
// saves endpoint need it. Lazy: the client is only constructed on
// first use, so an endpoint that never touches Clerk doesn't pay the
// init cost.
//
// Required env var: CLERK_SECRET_KEY (sk_test_… / sk_live_…), Backend
// API key from https://dashboard.clerk.com/~/api-keys.

const { createClerkClient } = require("@clerk/backend");

let _clerk = null;
function clerkClient() {
  if (_clerk) return _clerk;
  const key = process.env.CLERK_SECRET_KEY;
  if (!key) throw new Error("CLERK_SECRET_KEY not set");
  _clerk = createClerkClient({ secretKey: key });
  return _clerk;
}

// Verify the Clerk session on an inbound request. Returns the userId
// or null when the request is unauthenticated. Wraps Clerk's
// authenticateRequest so call sites don't need to know the exact API.
async function authenticateClerkRequest(req) {
  const requestState = await clerkClient().authenticateRequest({ request: req });
  if (!requestState.isSignedIn) return null;
  const auth = requestState.toAuth();
  return auth.userId || null;
}

module.exports = { clerkClient, authenticateClerkRequest };
