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
//                                        and persist customer + sub IDs.
//                                        Two paths:
//                                          (a) `client_reference_id` set →
//                                              existing in-app upgrade
//                                              (auth-gated /api/stripe/
//                                              create-checkout-session).
//                                          (b) no client_reference_id →
//                                              anonymous /start flow.
//                                              Look up by email; create
//                                              a Clerk invitation if no
//                                              user exists.
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
const posthog = require("../_posthog");

const ACTIVE_STATUSES = new Set(["active", "trialing"]);

// UTM keys we propagate from Stripe metadata onto the Clerk user — used
// downstream by PostHog Person properties for per-channel LTV slicing.
const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];

function pickUtms(metadata) {
  if (!metadata) return {};
  const out = {};
  for (const k of UTM_KEYS) {
    if (typeof metadata[k] === "string" && metadata[k]) out[k] = metadata[k];
  }
  return out;
}

async function setPlanForClerkUser(clerk, userId, plan, extraPrivate) {
  if (!userId) return;
  await clerk.users.updateUser(userId, {
    publicMetadata:  { plan },
    ...(extraPrivate ? { privateMetadata: extraPrivate } : {}),
  });
}

// Look up an existing Clerk user by email. Returns the user object or
// null. Clerk's getUserList API shape changes between SDK versions
// (sometimes Array, sometimes { data: Array }) — tolerate both.
async function findClerkUserByEmail(clerk, email) {
  if (!email) return null;
  const result = await clerk.users.getUserList({ emailAddress: [email], limit: 1 });
  const list = Array.isArray(result) ? result : (result && result.data) || [];
  return list[0] || null;
}

// Check whether a pending Clerk invitation for this email already exists,
// so the same Stripe event being retried doesn't create duplicates.
async function hasPendingInvitation(clerk, email) {
  if (!email) return false;
  try {
    const result = await clerk.invitations.getInvitationList({ status: "pending" });
    const list = Array.isArray(result) ? result : (result && result.data) || [];
    return list.some((inv) => (inv.emailAddress || "").toLowerCase() === email.toLowerCase());
  } catch (err) {
    // Pessimistic: if the list call fails, prefer to NOT create a possible
    // duplicate. The user will not be silently locked out — the next
    // webhook retry (or a manual replay) will go through.
    return true;
  }
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
    posthog.capture(null, "webhook.verify_failed", {
      ms: Date.now() - t0, error_message: err.message,
    });
    await posthog.flush();
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }

  try {
    const clerk = clerkClient();
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object;
        const explicitUserId = session.client_reference_id;
        const customerId = typeof session.customer === "string"
          ? session.customer : (session.customer && session.customer.id);
        const subscriptionId = typeof session.subscription === "string"
          ? session.subscription : (session.subscription && session.subscription.id);
        const email = (session.customer_details && session.customer_details.email)
          || session.customer_email
          || (session.metadata && session.metadata.email)
          || null;
        const source = session.metadata && session.metadata.source ? String(session.metadata.source) : null;
        const country = session.metadata && session.metadata.country ? String(session.metadata.country) : "";
        const currency = typeof session.currency === "string" ? session.currency : "";
        const amountTotal = typeof session.amount_total === "number" ? session.amount_total : 0;
        const hasDiscount = Array.isArray(session.discounts) && session.discounts.length > 0;
        const utms = pickUtms(session.metadata);

        // Shared props for every webhook.checkout_completed event. PostHog
        // funnels can break down by path / source / utm_* / country.
        const baseProps = {
          event_id: event.id,
          session_id: session.id,
          source: source || "",
          country,
          currency,
          amount_total: amountTotal,
          has_discount: hasDiscount,
          utm_source: utms.utm_source || "",
          utm_medium: utms.utm_medium || "",
          utm_campaign: utms.utm_campaign || "",
          utm_term: utms.utm_term || "",
          utm_content: utms.utm_content || "",
        };
        const distinctId = posthog.emailDistinctId(email);

        // Path A — existing auth-gated upgrade. client_reference_id was
        // set by /api/stripe/create-checkout-session.js, so we know the
        // Clerk user up front. Unchanged behaviour.
        if (explicitUserId) {
          await setPlanForClerkUser(clerk, explicitUserId, "pro", {
            stripeCustomerId: customerId || undefined,
            stripeSubscriptionId: subscriptionId || undefined,
          });
          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "auth_gated", clerk_user_id: explicitUserId,
          });
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "auth_gated",
            clerk_user_id: explicitUserId, ms: Date.now() - t0,
          });
          break;
        }

        // Path B — anonymous /start flow. Resolve user via email; create
        // an invitation if no user exists. Either way carries the UTM
        // attribution onto Clerk private metadata for downstream LTV.
        if (!email) {
          // Nothing actionable — log + return 200 so Stripe doesn't retry.
          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "anonymous_no_email", session_id: session.id,
          });
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "anonymous_no_email", ms: Date.now() - t0,
          });
          break;
        }
        const existing = await findClerkUserByEmail(clerk, email);
        if (existing) {
          await setPlanForClerkUser(clerk, existing.id, "pro", {
            stripeCustomerId: customerId || undefined,
            stripeSubscriptionId: subscriptionId || undefined,
            acquisitionSource: source || undefined,
            acquisitionUtms: Object.keys(utms).length ? utms : undefined,
          });
          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "anonymous_existing_user", clerk_user_id: existing.id,
          });
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "anonymous_existing_user",
            clerk_user_id: existing.id, ms: Date.now() - t0,
          });
          break;
        }

        const dupe = await hasPendingInvitation(clerk, email);
        if (dupe) {
          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "anonymous_dupe_invitation_skipped", session_id: session.id,
          });
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "anonymous_dupe_invitation_skipped",
            ms: Date.now() - t0,
          });
          break;
        }

        // Build the redirect URL from the request's host header so dev /
        // preview / prod each land on themselves. Falls back to a generic
        // origin if header parsing fails.
        const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
        const host = req.headers["x-forwarded-host"] || req.headers.host || "pulpo.club";
        const origin = `${proto}://${host}`;

        try {
          const invitation = await clerk.invitations.createInvitation({
            emailAddress: email,
            // After accepting the Clerk magic-link, land back on
            // /account?welcome=1 — same surface as the post-Stripe
            // redirect. The WelcomeModal re-renders in its signed-in
            // variant for a brief acknowledgement, then auto-dismisses
            // leaving the user on a fully signed-in /account page.
            redirectUrl:  `${origin}/account?welcome=1`,
            publicMetadata: { plan: "pro" },
            privateMetadata: {
              stripeCustomerId: customerId || undefined,
              stripeSubscriptionId: subscriptionId || undefined,
              acquisitionSource: source || undefined,
              acquisitionUtms: Object.keys(utms).length ? utms : undefined,
            },
          });
          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "anonymous_invitation_created", session_id: session.id,
            invitation_id: (invitation && invitation.id) || "",
          });
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "anonymous_invitation_created",
            invitation_id: (invitation && invitation.id) || "",
            ms: Date.now() - t0,
          });
        } catch (err) {
          // Race recovery: if a Clerk user was created in parallel (e.g.
          // the user signed up via /signin while the webhook was inflight),
          // Clerk returns form_identifier_exists. Re-lookup and upgrade.
          const code = err && err.clerkError && err.errors && err.errors[0] && err.errors[0].code;
          if (code === "form_identifier_exists" || code === "duplicate_record") {
            const racedUser = await findClerkUserByEmail(clerk, email);
            if (racedUser) {
              await setPlanForClerkUser(clerk, racedUser.id, "pro", {
                stripeCustomerId: customerId || undefined,
                stripeSubscriptionId: subscriptionId || undefined,
                acquisitionSource: source || undefined,
                acquisitionUtms: Object.keys(utms).length ? utms : undefined,
              });
              logApi("stripe.webhook", {
                status: 200, ms: Date.now() - t0, type: event.type,
                path: "anonymous_race_recovered", clerk_user_id: racedUser.id,
              });
              posthog.capture(distinctId, "webhook.checkout_completed", {
                ...baseProps, path: "anonymous_race_recovered",
                clerk_user_id: racedUser.id, ms: Date.now() - t0,
              });
              break;
            }
          }
          // Genuine failure — fire an explicit telemetry event before the
          // throw so PostHog catches it even though Stripe will retry.
          posthog.capture(distinctId, "webhook.checkout_completed_failed", {
            ...baseProps, path: "anonymous_invitation_failed",
            error_code: code || "", error_message: (err && err.message) || "",
            ms: Date.now() - t0,
          });
          throw err; // re-throw — let Stripe retry on 500
        }
        break;
      }
      case "customer.subscription.updated":
      case "customer.subscription.deleted": {
        const sub = event.data.object;
        // Primary link: clerkUserId stamped on the subscription when it
        // was created via the auth-gated endpoint. For /start sessions
        // the link is the email on the subscription metadata (stamped by
        // start-checkout.js) — fall back to email lookup when the
        // clerkUserId isn't present.
        let userId = sub.metadata && sub.metadata.clerkUserId;
        const subEmail = (sub.metadata && sub.metadata.email) || null;
        if (!userId && subEmail) {
          const user = await findClerkUserByEmail(clerk, subEmail);
          if (user) userId = user.id;
        }
        const isActive = event.type === "customer.subscription.deleted"
          ? false
          : ACTIVE_STATUSES.has(sub.status);
        await setPlanForClerkUser(clerk, userId, isActive ? "pro" : "free");
        posthog.capture(posthog.emailDistinctId(subEmail), "webhook.subscription_changed", {
          event_id: event.id,
          subscription_id: sub.id,
          type: event.type,
          status: sub.status,
          is_active: isActive,
          clerk_user_id: userId || "",
          source: (sub.metadata && sub.metadata.source) ? String(sub.metadata.source) : "",
          ms: Date.now() - t0,
        });
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
    posthog.capture(null, "webhook.handler_error", {
      event_id: event.id,
      type: event.type,
      error_message: err && err.message,
      ms: Date.now() - t0,
    });
    await posthog.flush();
    // 500 makes Stripe retry, which is what we want for transient Clerk
    // failures. Stripe gives up after ~3 days of retries.
    return res.status(500).end();
  }

  logApi("stripe.webhook", {
    status: 200, ms: Date.now() - t0, type: event.type, event_id: event.id,
  });
  await posthog.flush();
  return res.status(200).json({ received: true });
};

// Disable Vercel's default JSON body parser — signature verification
// requires the raw bytes off the wire.
module.exports.config = { api: { bodyParser: false } };
