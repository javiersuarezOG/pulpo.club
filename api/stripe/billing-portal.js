// POST /api/stripe/billing-portal
//
// Creates a Stripe Customer Portal session for the signed-in Pro user
// and returns the hosted URL. The frontend redirects to it; Stripe
// handles card updates, plan changes, cancellation, invoice history.
//
// Auth: requires a valid Clerk session cookie on the request. Same
// Clerk Backend pattern as create-checkout-session.js, so the auth
// shim in api/_clerk.js applies.
//
// Pre-req: the user must already be a paying customer — i.e. the
// Stripe webhook has stamped privateMetadata.stripeCustomerId during
// checkout.session.completed (see api/stripe/webhook.js). Free users
// shouldn't see the "Manage plan" button at all; if they somehow hit
// this endpoint we return 409 no_customer.
//
// Stripe Dashboard prereq: enable Customer Portal at
// Settings → Billing → Customer portal. Pulpo runs against either the
// default config or a customized one — the API call doesn't care.

const {
  stripeClient,
  clerkClient,
  logApi,
} = require("./_stripe");
const { toWebRequest } = require("../_clerk");

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi("stripe.billing_portal", {
      status: 405, ms: Date.now() - t0, reason: "method",
    });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  let userId = null;
  let stripeCustomerId = null;
  try {
    const clerk = clerkClient();
    const requestState = await clerk.authenticateRequest(toWebRequest(req));
    if (!requestState.isSignedIn) {
      logApi("stripe.billing_portal", {
        status: 401, ms: Date.now() - t0, reason: "unauthenticated",
      });
      return res.status(401).json({ error: "sign_in_required" });
    }
    const auth = requestState.toAuth();
    userId = auth.userId;
    const user = await clerk.users.getUser(userId);
    stripeCustomerId = user.privateMetadata
      ? user.privateMetadata.stripeCustomerId
      : null;
  } catch (err) {
    logApi("stripe.billing_portal", {
      status: 500, ms: Date.now() - t0, reason: "auth_failed", error: err.message,
    });
    return res.status(500).json({ error: "auth_failed" });
  }

  if (!stripeCustomerId) {
    // Defensive — UI gates the button on plan === "pro", which only
    // becomes true after the webhook stamps the customer ID. If we
    // get here, either metadata is out of sync or someone hit the
    // endpoint directly. Surface a distinct error so the client can
    // show "contact support" instead of silently failing.
    logApi("stripe.billing_portal", {
      status: 409, ms: Date.now() - t0, user_id: userId, reason: "no_customer",
    });
    return res.status(409).json({ error: "no_customer" });
  }

  const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
  const host = req.headers["x-forwarded-host"] || req.headers.host;
  const origin = `${proto}://${host}`;

  let session;
  try {
    session = await stripeClient().billingPortal.sessions.create({
      customer: stripeCustomerId,
      return_url: `${origin}/preview/?account=subscription`,
    });
  } catch (err) {
    logApi("stripe.billing_portal", {
      status: 500, ms: Date.now() - t0, reason: "stripe_error", error: err.message,
    });
    return res.status(500).json({ error: "stripe_error", message: err.message });
  }

  logApi("stripe.billing_portal", {
    status: 200, ms: Date.now() - t0, user_id: userId, session_id: session.id,
  });
  return res.status(200).json({ url: session.url, sessionId: session.id });
};
