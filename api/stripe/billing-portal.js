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
const posthog = require("../_posthog");
const { auditEnvOverridesOnce } = require("../_env_audit");

const SUPPORTED_PORTAL_LOCALES = new Set(["en", "es"]);

function safeStr(v) {
  return typeof v === "string" ? v : "";
}

function normalizePortalLocale(value) {
  const lc = safeStr(value).trim().toLowerCase();
  return SUPPORTED_PORTAL_LOCALES.has(lc) ? lc : "auto";
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
  await auditEnvOverridesOnce();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi("stripe.billing_portal", {
      status: 405, ms: Date.now() - t0, reason: "method", locale: "auto",
    });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const body = await readJsonBody(req);
  const locale = normalizePortalLocale(body.locale);

  let userId = null;
  let stripeCustomerId = null;
  let userEmail = null;
  let userPrivateMetadata = null;
  let userPublicMetadata = null;
  try {
    const clerk = clerkClient();
    const requestState = await clerk.authenticateRequest(toWebRequest(req));
    if (!requestState.isSignedIn) {
      logApi("stripe.billing_portal", {
        status: 401, ms: Date.now() - t0, reason: "unauthenticated", locale,
      });
      return res.status(401).json({ error: "sign_in_required" });
    }
    const auth = requestState.toAuth();
    userId = auth.userId;
    const user = await clerk.users.getUser(userId);
    userPrivateMetadata = user.privateMetadata || {};
    userPublicMetadata = user.publicMetadata || {};
    stripeCustomerId = userPrivateMetadata.stripeCustomerId || null;
    // Email is the load-bearing fallback identifier for the self-heal
    // lookup below. Clerk stores email on emailAddresses[].emailAddress;
    // the primary one matches user.primaryEmailAddressId.
    const primaryId = user.primaryEmailAddressId;
    const primary = Array.isArray(user.emailAddresses)
      ? user.emailAddresses.find((e) => e && e.id === primaryId)
      : null;
    userEmail = (primary && primary.emailAddress)
      || (Array.isArray(user.emailAddresses) && user.emailAddresses[0] && user.emailAddresses[0].emailAddress)
      || null;
  } catch (err) {
    logApi("stripe.billing_portal", {
      status: 500, ms: Date.now() - t0, reason: "auth_failed", error: err.message, locale,
    });
    return res.status(500).json({ error: "auth_failed" });
  }

  // Self-heal — when stripeCustomerId is missing on Clerk privateMetadata
  // (the /start anonymous-invitation flow doesn't promote invitation
  // metadata onto the User record on acceptance), look the customer up
  // by email and stamp the result back so subsequent calls are fast +
  // every downstream Stripe operation can find the customer.
  //
  // Why we can't just rely on the webhook: customer.subscription.updated
  // fires at billing-cycle boundaries (≥30 days), not on invitation
  // acceptance. Without this self-heal, a freshly-activated Pulpo Pro
  // user can't reach the Customer Portal for up to a month after paying.
  if (!stripeCustomerId && userEmail) {
    try {
      const stripe = stripeClient();
      const result = await stripe.customers.list({ email: userEmail, limit: 1 });
      const customer = result && result.data && result.data[0];
      let stamped = false;
      if (customer && customer.id) {
        stripeCustomerId = customer.id;
        const clerk = clerkClient();
        const subId = (customer.subscriptions && customer.subscriptions.data
          && customer.subscriptions.data[0] && customer.subscriptions.data[0].id) || null;
        const nextPrivate = {
          ...userPrivateMetadata,
          stripeCustomerId: customer.id,
          ...(subId ? { stripeSubscriptionId: subId } : {}),
        };
        await clerk.users.updateUserMetadata(userId, { privateMetadata: nextPrivate });
        stamped = true;
        logApi("stripe.billing_portal", {
          status: 200, ms: Date.now() - t0, user_id: userId,
          reason: "self_heal_ok", customer_id: customer.id, locale,
        });
      }
      posthog.capture(userId ? `user:${userId}` : "server:billing_portal", "billing_portal.self_heal", {
        had_email: Boolean(userEmail),
        lookup_ok: Boolean(customer && customer.id),
        stamped,
        ms: Date.now() - t0,
      });
      await posthog.flush();
    } catch (err) {
      // Non-fatal: if Stripe lookup fails we still want to fall through
      // to the 409 below so the user sees a graceful error rather than 500.
      logApi("stripe.billing_portal", {
        status: 200, ms: Date.now() - t0, user_id: userId,
        reason: "self_heal_failed", error: err.message, locale,
      });
    }
  }

  if (!stripeCustomerId) {
    // Defensive — UI gates the button on plan === "pro", which only
    // becomes true after the webhook stamps the customer ID. If we
    // get here, either metadata is out of sync or someone hit the
    // endpoint directly. Surface a distinct error so the client can
    // show "contact support" instead of silently failing.
    logApi("stripe.billing_portal", {
      status: 409, ms: Date.now() - t0, user_id: userId, reason: "no_customer", locale,
    });
    posthog.capture(userId ? `user:${userId}` : "server:billing_portal", "webhook.invitation_metadata_missing", {
      source: "billing_portal",
      had_email: Boolean(userEmail),
      ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(409).json({ error: "no_customer" });
  }

  const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
  const host = req.headers["x-forwarded-host"] || req.headers.host;
  const origin = `${proto}://${host}`;

  let session;
  try {
    const stripe = stripeClient();
    if (locale !== "auto") {
      try {
        await stripe.customers.update(stripeCustomerId, { preferred_locales: [locale] });
        posthog.capture(posthog.emailDistinctId(userEmail), "stripe.customer_locale_set", {
          locale,
          source: "portal",
        });
      } catch (err) {
        logApi("stripe.billing_portal", {
          status: 200, ms: Date.now() - t0, reason: "customer_locale_failed",
          user_id: userId, locale, error: err && err.message,
        });
      }
    }
    session = await stripe.billingPortal.sessions.create({
      customer: stripeCustomerId,
      // Land directly on the subscription tab. `?from=portal` is the
      // signal that the SubscriptionSection effect uses to force a
      // Clerk `user.reload()` — without that, the just-updated
      // publicMetadata.cancel_at_period_end / canceled_at stays
      // invisible to the browser until the user hard-refreshes (the
      // post-2026-05-27 follow-up bug to #513).
      return_url: `${origin}/account/subscription?from=portal`,
      locale,
    });
    posthog.capture(posthog.emailDistinctId(userEmail), "stripe.billing_portal_session_created", {
      locale,
      has_period_end: Boolean(userPublicMetadata && typeof userPublicMetadata.current_period_end === "number"),
      session_id: session.id,
      ms: Date.now() - t0,
    });
    await posthog.flush();
  } catch (err) {
    logApi("stripe.billing_portal", {
      status: 500, ms: Date.now() - t0, reason: "stripe_error", error: err.message, locale,
    });
    return res.status(500).json({ error: "stripe_error", message: err.message });
  }

  logApi("stripe.billing_portal", {
    status: 200, ms: Date.now() - t0, user_id: userId, session_id: session.id, locale,
  });
  return res.status(200).json({ url: session.url, sessionId: session.id });
};

module.exports.normalizePortalLocale = normalizePortalLocale;
