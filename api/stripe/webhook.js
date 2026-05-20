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
const { sendActivationEmail } = require("../_activation_email");

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

// Normalize the locale Pulpo stamps onto Stripe session metadata into
// the BCP-47 root Clerk's invitation API expects. Stripe carries
// "es-419" (the Latin-American Spanish flavor that Stripe's hosted UI
// uses) but Clerk's locale templates key off "es". "en" is identical
// on both sides. Empty/missing returns undefined so we don't override
// Clerk's default with a bogus value.
function clerkLocaleFromStripe(stripeLocale) {
  if (!stripeLocale || typeof stripeLocale !== "string") return undefined;
  const lc = stripeLocale.trim().toLowerCase();
  if (!lc) return undefined;
  if (lc === "es" || lc.startsWith("es-")) return "es";
  if (lc === "en" || lc.startsWith("en-")) return "en";
  return undefined;
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

// Find a pending Clerk invitation for this email, if one exists. Used by
// the anonymous_invitation_created branch to revoke-and-recreate, so a
// repeat checkout on the same email (e.g. user paid twice before
// activating) always produces a fresh outbound email rather than
// silently skipping. List-API failures return null (caller treats as
// "no pending" and proceeds to create) — the old "pessimistic skip" was
// itself a silent-no-send failure mode.
async function findPendingInvitation(clerk, email) {
  if (!email) return null;
  try {
    const result = await clerk.invitations.getInvitationList({ status: "pending" });
    const list = Array.isArray(result) ? result : (result && result.data) || [];
    return list.find((inv) => (inv.emailAddress || "").toLowerCase() === email.toLowerCase()) || null;
  } catch {
    return null;
  }
}

// Stripe retries webhook delivery on any non-2xx response and on missed
// ACKs (network blip between Stripe and Vercel). A retry carries the
// SAME event.id as the original. Most paths in this handler are already
// idempotent — setPlanForClerkUser writes plan="pro" the same way on the
// nth call — but the anonymous_invitation_created path is not:
// createInvitation produces a new row each time, and sendActivationEmail
// sends another email. The user sees duplicate "set up your Pulpo Pro
// account" inboxes, which is a real production-visible failure.
//
// Dedup strategy: use Stripe's own subscription.metadata as the dedup
// store. We retrieve the subscription, check whether
// metadata.pulpo_last_event_id matches the current event.id, and skip
// the side-effecting path if so. After successful processing we write
// the new event.id into the same metadata field.
//
// Why subscription metadata and not a separate store:
//   - No new infrastructure (no Vercel KV / Upstash / Postgres).
//   - Stripe is already the source of truth for the subscription.
//   - Cross-instance retries are covered: any warm or cold function
//     invocation reads the same subscription state.
// Trade-off: 1 extra Stripe API call per webhook on the anonymous path
// (~50ms). Acceptable at our event volume.
async function isStripeEventAlreadyProcessed(stripe, subscriptionId, eventId) {
  if (!subscriptionId || !eventId) return false;
  try {
    const sub = await stripe.subscriptions.retrieve(subscriptionId);
    const lastId = sub && sub.metadata && sub.metadata.pulpo_last_event_id;
    return lastId === eventId;
  } catch {
    // Read failure: fall through and process. Worst case is a duplicate
    // email; better than silently skipping a legitimate first delivery
    // because Stripe was momentarily unreachable.
    return false;
  }
}

async function markStripeEventProcessed(stripe, subscriptionId, eventId) {
  if (!subscriptionId || !eventId) return;
  try {
    await stripe.subscriptions.update(subscriptionId, {
      metadata: { pulpo_last_event_id: eventId },
    });
  } catch {
    // Non-fatal: the event was processed correctly; we just couldn't
    // store the dedup marker. On retry we'd reprocess (duplicate email),
    // which is the tolerated failure mode of this safety net.
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

  // Fires the moment we've successfully verified the Stripe signature
  // and parsed the event, BEFORE any branching. Lets PostHog answer
  // "did Stripe deliver this event to us at all?" — absence in the
  // funnel for a given event_id means the webhook never reached us
  // (misconfigured URL, network failure between Stripe and Vercel,
  // signature secret mismatch caught above). Distinct from
  // webhook.checkout_completed which fires per-path after processing.
  posthog.capture(null, "webhook.received", {
    event_id: event.id,
    type: event.type,
    ms: Date.now() - t0,
  });

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
        // start-checkout.js stamps this so the activation email matches
        // the language the user was browsing in.
        const stripeLocale = session.metadata && session.metadata.locale ? String(session.metadata.locale) : "";
        const clerkLocale = clerkLocaleFromStripe(stripeLocale);

        // Shared props for every webhook.checkout_completed event. PostHog
        // funnels can break down by path / source / utm_* / country / locale.
        const baseProps = {
          event_id: event.id,
          session_id: session.id,
          source: source || "",
          country,
          currency,
          amount_total: amountTotal,
          has_discount: hasDiscount,
          locale: stripeLocale,
          utm_source: utms.utm_source || "",
          utm_medium: utms.utm_medium || "",
          utm_campaign: utms.utm_campaign || "",
          utm_term: utms.utm_term || "",
          utm_content: utms.utm_content || "",
        };
        const distinctId = posthog.emailDistinctId(email);

        // Alias the client-side anonymous PostHog distinct_id (carried
        // through Stripe session metadata by start-checkout.js) to the
        // server-side email-derived id. This stitches the anon→paid
        // funnel so PostHog sees one person for the full sequence:
        //   $pageview → free_month_modal.shown → ... → webhook.checkout_completed.
        // Tolerates missing/equal/empty ids — alias is a no-op then.
        const posthogAnonId = session.metadata && session.metadata.posthog_anon_id
          ? String(session.metadata.posthog_anon_id) : "";
        if (posthogAnonId && distinctId && posthogAnonId !== distinctId) {
          try {
            posthog.alias(posthogAnonId, distinctId);
          } catch (err) {
            // Never let an alias failure block the webhook — it's
            // funnel-attribution sugar, not a payment correctness gate.
            logApi("stripe.webhook", {
              status: 200, type: event.type, alias_failed: true,
              error: err && err.message,
            });
          }
        }

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
          // invitation_sent: false on auth_gated — the user was
          // already signed in pre-checkout, so no activation email
          // is needed or sent. Funnel-side this is the
          // "% of paying users who actually receive activation
          // email" denominator clarifier.
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "auth_gated",
            clerk_user_id: explicitUserId, invitation_sent: false,
            ms: Date.now() - t0,
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
            ...baseProps, path: "anonymous_no_email",
            invitation_sent: false, ms: Date.now() - t0,
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
            locale: stripeLocale,
          });
          // invitation_sent: false on existing-user — Clerk already has
          // a user record for this email, so no new invitation is sent.
          // The WelcomeModal's status-poll surfaces this case as
          // "user_exists" so the user knows to sign in, not check inbox.
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "anonymous_existing_user",
            clerk_user_id: existing.id, invitation_sent: false,
            ms: Date.now() - t0,
          });
          break;
        }

        // Idempotency gate: if Stripe is retrying this exact event.id
        // (transient 5xx or missed-ACK on a prior attempt), the previous
        // attempt may have already created the invitation and sent the
        // email. Re-running the side effects produces a duplicate inbox
        // for the user. Skip with a 200 if subscription.metadata says
        // we've already processed this event.id. See helpers above for
        // the design rationale.
        const stripe = stripeClient();
        if (await isStripeEventAlreadyProcessed(stripe, subscriptionId, event.id)) {
          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "anonymous_duplicate_skip",
            session_id: session.id, subscription_id: subscriptionId,
            event_id: event.id,
          });
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "anonymous_duplicate_skip",
            invitation_sent: false, ms: Date.now() - t0,
          });
          break;
        }

        // If a pending invitation already exists for this email, revoke
        // it before creating a fresh one. This guarantees a fresh
        // activation email goes out on every checkout (as long as the
        // user hasn't activated yet — the `existing` lookup above
        // already caught that case). The pre-PR behavior was to skip
        // entirely, which was a silent-no-send when the user paid twice.
        const pendingPrev = await findPendingInvitation(clerk, email);
        if (pendingPrev) {
          try {
            await clerk.invitations.revokeInvitation(pendingPrev.id);
          } catch (err) {
            // Non-fatal: maybe Clerk already revoked / expired it. Log
            // + continue; createInvitation below will tell us if the
            // revoke didn't actually clear the row.
            logApi("stripe.webhook", {
              status: 200, ms: Date.now() - t0, type: event.type,
              path: "anonymous_prev_revoke_failed",
              prev_invitation_id: pendingPrev.id,
              error: err && err.message,
            });
          }
        }

        // Build the redirect URL from the request's host header so dev /
        // preview / prod each land on themselves. Falls back to a generic
        // origin if header parsing fails.
        const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
        const host = req.headers["x-forwarded-host"] || req.headers.host || "pulpo.club";
        const origin = `${proto}://${host}`;

        try {
          // notify: false → Clerk creates the invitation row but does
          // NOT trigger its own email send. We send the email
          // ourselves via Resend below (sendActivationEmail) because
          // Clerk's pipeline holds activation emails at status=queued
          // indefinitely on this account — confirmed via Svix
          // telemetry (PR #341). DNS is fully verified Clerk-side;
          // the gate is somewhere in Clerk's account/billing config
          // and is outside our control. The Resend path uses Pulpo's
          // already-verified mail.pulpo.club sending domain.
          const invitation = await clerk.invitations.createInvitation({
            emailAddress: email,
            notify: false,
            // After Clerk completes the invitation sign-up (password
            // set), the user lands on /account?welcome=1[&lang=…] so
            // the signed-in WelcomeModal renders and auto-dismisses.
            //
            // We do NOT append our own activation=1 marker — Clerk's
            // /v1/tickets/accept redirect strips invitation redirectUrl
            // query params and substitutes its own (__clerk_status +
            // __clerk_ticket). PR #363 tried activation=1; it never
            // reached the browser (Sebas 2026-05-20). Frontend detects
            // the activation landing on __clerk_ticket directly
            // (web/app/app.jsx hasClerkTicket).
            redirectUrl: `${origin}/account?welcome=1${clerkLocale ? `&lang=${clerkLocale}` : ""}`,
            // locale kept for downstream parity even though Clerk's
            // own template no longer renders — our Resend templates
            // also branch on it.
            ...(clerkLocale ? { locale: clerkLocale } : {}),
            publicMetadata: { plan: "pro" },
            privateMetadata: {
              stripeCustomerId: customerId || undefined,
              stripeSubscriptionId: subscriptionId || undefined,
              acquisitionSource: source || undefined,
              acquisitionUtms: Object.keys(utms).length ? utms : undefined,
            },
          });
          const invitationId = (invitation && invitation.id) || "";
          const actionUrl = (invitation && invitation.url) || `${origin}/account?welcome=1`;

          // Send the activation email via Resend. Failures are logged
          // + reported via PostHog but do NOT throw — the invitation
          // row exists, so the user can retry via the WelcomeModal's
          // "Resend my invitation" button. Throwing here would make
          // Stripe retry the whole webhook, which would create yet
          // another invitation row in a loop.
          const sendResult = await sendActivationEmail({
            email,
            locale: stripeLocale || clerkLocale,
            actionUrl,
            sessionId: session.id,
          });

          // Mark the event as processed BEFORE telemetry so a Stripe
          // retry hits the dedup branch above even if the function gets
          // killed mid-handler. Failures are swallowed inside the
          // helper (see comment there) — a missed write means the next
          // retry redoes the work, which is the tolerated failure mode.
          await markStripeEventProcessed(stripe, subscriptionId, event.id);

          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "anonymous_invitation_created", session_id: session.id,
            invitation_id: invitationId,
            locale: stripeLocale,
            resend_ok: sendResult.ok,
            resend_message_id: sendResult.message_id || "",
            resend_error: sendResult.error || "",
          });
          // invitation_sent: true means we ASKED Resend to send. The
          // truer delivered/bounced signal comes from api/resend-webhook
          // events (newsletter.sent / .delivered / .bounced) keyed on
          // the same recipient_hash as this event's distinctId.
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "anonymous_invitation_created",
            invitation_id: invitationId,
            invitation_sent: sendResult.ok,
            resend_status_code: sendResult.status_code || 0,
            ms: Date.now() - t0,
          });
          if (!sendResult.ok) {
            posthog.capture(distinctId, "webhook.activation_email_failed", {
              ...baseProps, invitation_id: invitationId,
              error: sendResult.error || "unknown",
              status_code: sendResult.status_code || 0,
              ms: Date.now() - t0,
            });
          }
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
                locale: stripeLocale,
              });
              // invitation_sent: false on race_recovered — we found
              // an existing Clerk user mid-invitation-create, bumped
              // their plan, and skipped re-creating the invitation.
              posthog.capture(distinctId, "webhook.checkout_completed", {
                ...baseProps, path: "anonymous_race_recovered",
                clerk_user_id: racedUser.id, invitation_sent: false,
                ms: Date.now() - t0,
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

// Test seam — pure helpers exported for unit tests. Vercel doesn't
// import these in prod; the bundler tree-shakes them out.
module.exports.isStripeEventAlreadyProcessed = isStripeEventAlreadyProcessed;
module.exports.markStripeEventProcessed = markStripeEventProcessed;
