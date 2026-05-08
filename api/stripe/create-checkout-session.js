// POST /api/stripe/create-checkout-session
//
// Creates a Managed Payments Checkout Session for the signed-in Clerk
// user and returns the hosted-checkout URL. The frontend redirects to
// that URL; Stripe handles card entry, tax, and the success/cancel
// routing back to /preview/.
//
// Auth: requires a valid Clerk session cookie on the request. Uses
// Clerk Backend's authenticateRequest() — no token parsing in our code.
//
// Webhook → Clerk metadata sync lives in api/stripe/webhook.js.
// `client_reference_id` and `subscription_data.metadata.clerkUserId`
// embed the Clerk user ID so the webhook can update the right user
// without trusting the client.

const {
  MANAGED_PAYMENTS_VERSION,
  stripeClient,
  clerkClient,
  logApi,
} = require("./_stripe");
const { toWebRequest } = require("../_clerk");

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi("stripe.create_checkout_session", {
      status: 405, ms: Date.now() - t0, reason: "method",
    });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const priceId = process.env.STRIPE_PRICE_ID_PRO;
  if (!priceId) {
    logApi("stripe.create_checkout_session", {
      status: 500, ms: Date.now() - t0, reason: "missing_price_id",
    });
    return res.status(500).json({ error: "stripe_not_configured" });
  }

  let userId = null;
  let userEmail = null;
  let existingCustomerId = null;
  try {
    const clerk = clerkClient();
    const requestState = await clerk.authenticateRequest(toWebRequest(req));
    if (!requestState.isSignedIn) {
      logApi("stripe.create_checkout_session", {
        status: 401, ms: Date.now() - t0, reason: "unauthenticated",
      });
      return res.status(401).json({ error: "sign_in_required" });
    }
    const auth = requestState.toAuth();
    userId = auth.userId;
    const user = await clerk.users.getUser(userId);
    userEmail = user.primaryEmailAddress
      ? user.primaryEmailAddress.emailAddress
      : null;
    existingCustomerId = user.privateMetadata
      ? user.privateMetadata.stripeCustomerId
      : null;
  } catch (err) {
    logApi("stripe.create_checkout_session", {
      status: 500, ms: Date.now() - t0, reason: "auth_failed", error: err.message,
    });
    return res.status(500).json({ error: "auth_failed" });
  }

  const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
  const host = req.headers["x-forwarded-host"] || req.headers.host;
  const origin = `${proto}://${host}`;

  let session;
  try {
    session = await stripeClient().checkout.sessions.create({
      mode: "subscription",
      managed_payments: { enabled: true },
      line_items: [{ price: priceId, quantity: 1 }],
      // client_reference_id surfaces on the Session for webhook lookups;
      // subscription metadata persists for renewal / cancel events that
      // reference the Subscription rather than the Session.
      client_reference_id: userId,
      subscription_data: {
        metadata: { clerkUserId: userId },
      },
      // If we already have a Stripe customer for this user, reuse it
      // so card-on-file + billing history stay attached. Otherwise let
      // Stripe create one based on the email we collected from Clerk.
      customer:       existingCustomerId || undefined,
      customer_email: existingCustomerId ? undefined : (userEmail || undefined),
      success_url: `${origin}/preview/?upgrade=success&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url:  `${origin}/preview/?upgrade=cancelled`,
    }, {
      apiVersion: MANAGED_PAYMENTS_VERSION,
    });
  } catch (err) {
    logApi("stripe.create_checkout_session", {
      status: 500, ms: Date.now() - t0, reason: "stripe_error", error: err.message,
    });
    return res.status(500).json({ error: "stripe_error", message: err.message });
  }

  logApi("stripe.create_checkout_session", {
    status: 200, ms: Date.now() - t0, user_id: userId, session_id: session.id,
  });
  return res.status(200).json({ url: session.url, sessionId: session.id });
};
