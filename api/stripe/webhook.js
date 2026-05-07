// POST /api/stripe/webhook
//
// Stripe → Pulpo. Verifies the signature on every event, then maps a
// small whitelist of subscription lifecycle events onto the Clerk
// user's `publicMetadata.plan` ("pro" | "free"). The frontend reads
// that field via PR-9b's ClerkUserSync, so a successful payment shows
// up in the app on next session refresh.
//
// Events handled:
//   checkout.session.completed         — initial purchase, set plan=pro
//                                        and persist customer + sub IDs
//   customer.subscription.updated      — renewals, plan changes, paused
//                                        / past_due → re-derive plan
//   customer.subscription.deleted      — fully cancelled, plan=free
//
// The webhook needs the *raw* request body for signature verification
// — Vercel's default JSON body parser is disabled below.

const {
  stripeClient,
  clerkClient,
  readRawBody,
  logApi,
} = require("./_stripe");

const ACTIVE_STATUSES = new Set(["active", "trialing"]);

async function setPlanForClerkUser(clerk, userId, plan, extraPrivate) {
  if (!userId) return;
  await clerk.users.updateUser(userId, {
    publicMetadata:  { plan },
    ...(extraPrivate ? { privateMetadata: extraPrivate } : {}),
  });
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi("stripe.webhook", { status: 405, ms: Date.now() - t0, reason: "method" });
    return res.status(405).end();
  }

  const sig = req.headers["stripe-signature"];
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!sig || !secret) {
    logApi("stripe.webhook", {
      status: 400, ms: Date.now() - t0, reason: "missing_sig_or_secret",
    });
    return res.status(400).send("Webhook secret not configured");
  }

  let event;
  try {
    const raw = await readRawBody(req);
    event = stripeClient().webhooks.constructEvent(raw, sig, secret);
  } catch (err) {
    logApi("stripe.webhook", {
      status: 400, ms: Date.now() - t0, reason: "verify_failed", error: err.message,
    });
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }

  try {
    const clerk = clerkClient();
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object;
        const userId = session.client_reference_id;
        const customerId = typeof session.customer === "string"
          ? session.customer : (session.customer && session.customer.id);
        const subscriptionId = typeof session.subscription === "string"
          ? session.subscription : (session.subscription && session.subscription.id);
        await setPlanForClerkUser(clerk, userId, "pro", {
          stripeCustomerId: customerId || undefined,
          stripeSubscriptionId: subscriptionId || undefined,
        });
        break;
      }
      case "customer.subscription.updated":
      case "customer.subscription.deleted": {
        const sub = event.data.object;
        // We embedded clerkUserId in subscription metadata when the
        // session was created — that's the trustable link from a
        // subscription back to the Clerk user.
        const userId = sub.metadata && sub.metadata.clerkUserId;
        const isActive = event.type === "customer.subscription.deleted"
          ? false
          : ACTIVE_STATUSES.has(sub.status);
        await setPlanForClerkUser(clerk, userId, isActive ? "pro" : "free");
        break;
      }
      default:
        // Ignore — every other event is not material to plan state.
        break;
    }
  } catch (err) {
    logApi("stripe.webhook", {
      status: 500, ms: Date.now() - t0, type: event.type, error: err.message,
    });
    // 500 makes Stripe retry, which is what we want for transient Clerk
    // failures. Stripe gives up after ~3 days of retries.
    return res.status(500).end();
  }

  logApi("stripe.webhook", {
    status: 200, ms: Date.now() - t0, type: event.type, event_id: event.id,
  });
  return res.status(200).json({ received: true });
};

// Disable Vercel's default JSON body parser — signature verification
// requires the raw bytes off the wire.
module.exports.config = { api: { bodyParser: false } };
