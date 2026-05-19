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
const posthog = require("../_posthog");

const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];

function safeStr(v) {
  return typeof v === "string" ? v : "";
}

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return {};
  try { return JSON.parse(raw); } catch { return {}; }
}

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
      status: 500, ms: Date.now() - t0, reason: "auth_failed",
      error_class: err && err.constructor ? err.constructor.name : "Error",
      error: err && err.message,
    });
    return res.status(500).json({
      error: "auth_failed",
      detail: err && err.message,
      class: err && err.constructor ? err.constructor.name : undefined,
    });
  }

  const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
  const host = req.headers["x-forwarded-host"] || req.headers.host;
  const origin = `${proto}://${host}`;

  // Wave-2: read Body for forwarded promo code + UTMs. Signed-in flow
  // is intentionally more lenient than /start: on an invalid code we
  // fall through silently (no 4xx) so the user lands on Stripe at full
  // price rather than seeing a wall during a paid-conversion moment.
  // Telemetry records `succeeded: false` so the funnel still sees it.
  const body = await readJsonBody(req);
  const promoCode = safeStr(body.promoCode).trim().toUpperCase();
  const utms = {};
  for (const k of UTM_KEYS) {
    const v = safeStr(body[k]).slice(0, 100);
    if (v) utms[k] = v;
  }

  let discounts = null;
  let promoSucceeded = null; // null = not attempted, true/false = lookup result
  if (promoCode) {
    try {
      const codes = await stripeClient().promotionCodes.list({
        code: promoCode,
        active: true,
        limit: 1,
      });
      if (codes.data && codes.data.length > 0) {
        discounts = [{ promotion_code: codes.data[0].id }];
        promoSucceeded = true;
      } else {
        promoSucceeded = false;
      }
    } catch (err) {
      // Don't fail the checkout because Stripe's promotion-code endpoint
      // hiccupped. Log + proceed at full price; the user keeps moving.
      logApi("stripe.create_checkout_session", {
        status: 0, ms: Date.now() - t0, reason: "promo_lookup_failed_soft",
        error: err && err.message,
      });
      promoSucceeded = false;
    }
  }

  const sessionParams = {
    mode: "subscription",
    managed_payments: { enabled: true },
    line_items: [{ price: priceId, quantity: 1 }],
    // client_reference_id surfaces on the Session for webhook lookups;
    // subscription metadata persists for renewal / cancel events that
    // reference the Subscription rather than the Session.
    client_reference_id: userId,
    subscription_data: {
      // Stamp UTMs into subscription metadata so cohort attribution
      // survives renewals. clerkUserId is always present.
      metadata: { clerkUserId: userId, ...utms },
    },
    // If we already have a Stripe customer for this user, reuse it
    // so card-on-file + billing history stay attached. Otherwise let
    // Stripe create one based on the email we collected from Clerk.
    customer:       existingCustomerId || undefined,
    customer_email: existingCustomerId ? undefined : (userEmail || undefined),
    // PR-10 cutover: returns to `/` (the new app at the canonical
    // root). The /preview/ rewrite is kept as a one-week fallback,
    // so existing in-flight checkout sessions still resolve.
    success_url: `${origin}/?upgrade=success&session_id={CHECKOUT_SESSION_ID}`,
    cancel_url:  `${origin}/?upgrade=cancelled`,
    // Audit P0-5 — render the mandatory Terms checkbox on the Stripe
    // Checkout page. See api/stripe/start-checkout.js for the full
    // rationale; this is the auth-gated in-app upgrade flow's twin.
    consent_collection: {
      terms_of_service: "required",
    },
  };
  // Stripe rejects `discounts` and `allow_promotion_codes: true` set
  // together — pick one. Pre-applied code wins; otherwise surface the
  // hosted-checkout "Add promotion code" link.
  if (discounts) {
    sessionParams.discounts = discounts;
  } else {
    sessionParams.allow_promotion_codes = true;
  }

  let session;
  try {
    session = await stripeClient().checkout.sessions.create(sessionParams, {
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
    has_promo: discounts ? 1 : 0,
    promo_succeeded: promoSucceeded === null ? "" : (promoSucceeded ? 1 : 0),
  });

  // Wave-2: fire promo_code_applied server-side when a code was
  // attempted (regardless of outcome). distinctId is the Clerk userId
  // so the event chains with the client-side identify() that already
  // ran when the user signed in.
  if (promoCode) {
    posthog.capture(userId, "promo_code_applied", {
      code: promoCode,
      succeeded: promoSucceeded === true,
      source: "create_checkout_session",
    });
    await posthog.flush();
  }

  return res.status(200).json({ url: session.url, sessionId: session.id });
};
