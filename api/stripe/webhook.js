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
//   invoice.payment_failed             — first failed retry. Stamp
//                                        payment_failed_at + a 14-day
//                                        grace_period_ends_at. plan
//                                        stays "pro" so the UI can show
//                                        "still Pro — update your card".
//   invoice.payment_succeeded          — successful charge, including
//                                        a recovery after a failure.
//                                        Clears the grace fields.
//   customer.subscription.updated      — status transitions. active /
//                                        trialing → plan=pro & clear
//                                        grace; past_due → keep plan=pro
//                                        and ensure grace is stamped;
//                                        canceled / unpaid → plan=free.
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
const { GRACE_MS } = require("../_plan");
const { auditEnvOverridesOnce } = require("../_env_audit");
const { enrollPaidUserInAudience } = require("../_resend_audience");

const ACTIVE_STATUSES = new Set(["active", "trialing"]);
// Statuses that mean "subscription is finished, not paused": fully
// cancel the user. past_due / unpaid keep the user in grace.
const TERMINAL_STATUSES = new Set(["canceled", "incomplete_expired"]);

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

async function setStripeCustomerPreferredLocale(stripe, customerId, locale, source, distinctId, t0) {
  if (!stripe || !customerId || !locale) return;
  try {
    await stripe.customers.update(customerId, { preferred_locales: [locale] });
    posthog.capture(distinctId, "stripe.customer_locale_set", {
      locale,
      source,
      ms: Date.now() - t0,
    });
  } catch (err) {
    logApi("stripe.webhook", {
      status: 200,
      reason: "customer_locale_failed",
      customer_id: customerId,
      locale,
      source,
      error: err && err.message,
      ms: Date.now() - t0,
    });
  }
}

async function setPlanForClerkUser(clerk, userId, plan, extraPrivate) {
  if (!userId) return;
  await clerk.users.updateUser(userId, {
    publicMetadata:  { plan },
    ...(extraPrivate ? { privateMetadata: extraPrivate } : {}),
  });
}

// Partial publicMetadata patch — Clerk's updateUserMetadata REPLACES
// publicMetadata wholesale, so we have to read the current value,
// shallow-merge the patch, and write it back. Same pattern as
// api/clerk/update-profile.js (which documents the gotcha at length).
// Used by the subscription-lifecycle paths below so a grace-period
// stamp doesn't wipe the user's `profile` blob.
async function patchPublicMetadata(clerk, userId, patch) {
  if (!userId) return;
  const user = await clerk.users.getUser(userId);
  const current = (user && user.publicMetadata) || {};
  const next = { ...current, ...patch };
  // Convert undefined-valued patch keys into explicit deletes; null
  // sticks (we use null to mean "explicitly cleared").
  for (const k of Object.keys(patch)) {
    if (patch[k] === undefined) delete next[k];
  }
  await clerk.users.updateUserMetadata(userId, { publicMetadata: next });
}

// Sibling of patchPublicMetadata for privateMetadata. Needed for the
// /start anonymous-invitation flow: createInvitation embeds
// stripeCustomerId in the invitation's privateMetadata, but Clerk
// does NOT auto-promote those fields onto the User record when the
// invitation is accepted. So the /start path landed users in a state
// where publicMetadata.plan = "pro" (set by subscription-lifecycle
// webhooks via email lookup) but privateMetadata.stripeCustomerId was
// never populated — breaking the Customer Portal endpoint, the
// recovery path for reactivation, and anything else that needs the
// customer ID. Calling this from the subscription-lifecycle handlers
// closes the gap: every customer.subscription.updated event re-stamps
// the customer + sub IDs on the user, idempotently.
async function patchPrivateMetadata(clerk, userId, patch) {
  if (!userId) return;
  const user = await clerk.users.getUser(userId);
  const current = (user && user.privateMetadata) || {};
  const next = { ...current, ...patch };
  for (const k of Object.keys(patch)) {
    if (patch[k] === undefined) delete next[k];
  }
  await clerk.users.updateUserMetadata(userId, { privateMetadata: next });
}

// Pulpo Pro Welcome — instant dispatcher (Vercel Python) with
// GitHub-Actions fallback.
//
// Hot path (default): POST to /api/internal/welcome-send, a Vercel
// Python serverless function that runs `dispatch_welcome` in-process
// and returns in ~1-3s. End-to-end welcome latency from Stripe
// payment to inbox: <5s.
//
// Fallback path: if the Python function is unreachable (deploy in
// progress, Vercel outage, env misconfig), dispatch the
// `pulpo-pro-welcome.yml` GitHub Actions workflow instead. Same
// Python dispatcher runs there; latency 15-75s but reliable across
// Vercel-only outages.
//
// Both paths share the same Clerk idempotency stamp
// (`publicMetadata.welcome_newsletter_sent_at`), so a fallback that
// races with a slow primary is safe — whichever wins the Clerk
// lookup wins the send; the other no-ops with reason=already_sent.
//
// Telemetry surfaces `dispatch_path: "internal" | "github_fallback"`
// so dashboards can track how often the fallback fires (which would
// signal a Vercel Python reliability issue worth investigating).

const WELCOME_INTERNAL_URL_PATH = "/api/internal/welcome-send";
// Vercel function timeout = 30s (configured in vercel.json). We give
// the fetch a tight margin under that so the webhook can still fall
// back inside Stripe's own 30s budget if the Python function hangs.
const WELCOME_INTERNAL_TIMEOUT_MS = 25_000;

// Internal-call helper. Returns:
//   • { ok: true, status, body }   — Python responded (any status code)
//   • { ok: false, reason }         — fetch failed / aborted / timed out
async function callInternalWelcomeSend({
  baseUrl,
  token,
  payload,
  fetchImpl,
  timeoutMs,
}) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), timeoutMs || WELCOME_INTERNAL_TIMEOUT_MS);
  try {
    const r = await (fetchImpl || fetch)(`${baseUrl}${WELCOME_INTERNAL_URL_PATH}`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "pulpo-stripe-webhook-welcome-primary",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    let body = null;
    try { body = await r.json(); } catch { /* best-effort */ }
    return { ok: true, status: r.status, body };
  } catch (err) {
    const reason = (err && err.name === "AbortError")
      ? "timeout"
      : `fetch_failed:${(err && err.message) || "unknown"}`;
    return { ok: false, reason };
  } finally {
    clearTimeout(tid);
  }
}

// Churned-Pro → Free welcome-back. Fires the DB-free internal dispatcher
// (/api/internal/free-welcome-send → free_welcome_dispatch). Best-effort:
// NO GH fallback (unlike the Pro activation welcome, a missed welcome-back
// is low-stakes), never throws, never blocks the subscription lifecycle.
// The caller dedups on the Clerk stamp so this fires once per cancellation.
const FREE_WELCOME_INTERNAL_URL_PATH = "/api/internal/free-welcome-send";

async function fireFreeWelcomeBack({ email, locale, source, distinctId, t0, fetchImpl, internalBaseUrl }) {
  const token = (process.env.PULPO_INTERNAL_TOKEN || "").trim();
  if (!token) {
    logApi("stripe.webhook", { status: 200, reason: "free_welcome_back_no_internal_token" });
    return { fired: false, reason: "internal_token_unset" };
  }
  const baseUrl = internalBaseUrl || process.env.PULPO_SITE_ROOT || "https://pulpo.club";
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), 12_000);
  try {
    const r = await (fetchImpl || fetch)(`${baseUrl}${FREE_WELCOME_INTERNAL_URL_PATH}`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "pulpo-stripe-webhook-free-welcome-back",
      },
      body: JSON.stringify({
        email,
        variant: "free_welcome_back",
        locale: locale || "en",
        source: source || "stripe_downgrade",
        is_new_contact: true,
      }),
      signal: controller.signal,
    });
    let body = null;
    try { body = await r.json(); } catch { /* best-effort */ }
    posthog.capture(distinctId, "newsletter.free_welcome_back_dispatched", {
      http_status: r.status,
      dispatcher_status: body && body.status,
      dispatcher_reason: body && body.reason,
      source: source || "stripe_downgrade",
      dry_run: body && body.dry_run,
      ms: Date.now() - t0,
    });
    return { fired: true, status: r.status, body };
  } catch (err) {
    const reason = (err && err.name === "AbortError") ? "timeout" : `fetch_failed:${(err && err.message) || "unknown"}`;
    logApi("stripe.webhook", { status: 200, reason: "free_welcome_back_unreachable", detail: reason });
    return { fired: false, reason };
  } finally {
    clearTimeout(tid);
  }
}

// Orchestrator: tries the Vercel Python primary, falls back to GH on
// any "Python unreachable" signal (network error, timeout). A Python
// response with status=200 OR 4xx OR 500-with-our-JSON is FINAL —
// the dispatcher attempted send, we trust its outcome and don't
// double-dispatch via GH (which would risk a duplicate Resend call
// when the first send half-succeeded).
async function dispatchProWelcome(args) {
  const {
    clerk, clerkUserId, email, source, distinctId, t0,
    fetchImpl, internalBaseUrl, // injectable for tests
    subscriptionId, allowResubscribe, // resubscribe welcome-back inputs
  } = args;
  if (!clerk || !clerkUserId || !email) {
    return "skipped:missing_input";
  }
  // .trim() — the internal endpoint (welcome-send.py) strips its expected
  // token, so a trailing newline/space on the Vercel env var would make an
  // un-trimmed bearer mismatch → 401 → silent no-welcome. Normalize both ends.
  const token = (process.env.PULPO_INTERNAL_TOKEN || "").trim();
  // When the internal-call token isn't set, we have no choice but
  // GH fallback — the Python endpoint would 401 every call. Common
  // in dev environments where only the GH PAT is configured.
  if (!token) {
    logApi("stripe.webhook", {
      status: 200, reason: "welcome_no_internal_token_skipping_primary",
      clerk_user_id: clerkUserId,
    });
    return await dispatchProWelcomeWorkflow(args);
  }
  // Internal-call base URL. MUST be the PUBLIC production domain, never
  // VERCEL_URL: the *.vercel.app deployment hostname is gated by Vercel
  // Deployment Protection (HTTP 401 with an HTML body), so routing the
  // internal welcome call through it silently 401'd every send — no
  // email, no fallback (a 401 isn't treated as "unreachable"). The
  // public custom domain (pulpo.club) is unprotected and reaches the
  // same function. PULPO_SITE_ROOT (a public domain) wins; else
  // pulpo.club. `internalBaseUrl` stays injectable for tests.
  const baseUrl = internalBaseUrl
    || process.env.PULPO_SITE_ROOT
    || "https://pulpo.club";

  const result = await callInternalWelcomeSend({
    baseUrl,
    token,
    payload: {
      email,
      source: source || "stripe",
      force: false,
      // Resubscribe re-acquisition: when the recipient already carries a
      // welcome stamp, the Python dispatcher auto-routes to the
      // welcome-back template and dedups on subscription_id. First-time
      // buyers (no stamp) get the first-time welcome regardless.
      allow_resubscribe: !!allowResubscribe,
      subscription_id: subscriptionId || undefined,
    },
    fetchImpl,
    timeoutMs: WELCOME_INTERNAL_TIMEOUT_MS,
  });

  if (!result.ok) {
    // Python unreachable — fall back to GH so the welcome still
    // delivers (just slower). Tag the telemetry so dashboards
    // surface the fallback rate.
    posthog.capture(distinctId, "newsletter.welcome_internal_unreachable", {
      reason: result.reason,
      source: source || "stripe.checkout",
      clerk_user_id: clerkUserId,
      ms: Date.now() - t0,
    });
    logApi("stripe.webhook", {
      status: 200, reason: "welcome_internal_unreachable_falling_back",
      clerk_user_id: clerkUserId, internal_reason: result.reason,
    });
    return await dispatchProWelcomeWorkflow(args);
  }

  // Python responded. status=200 = sent OR skipped; status=500 =
  // dispatcher returned status="failed". Either way, the dispatcher
  // attempted send and the outcome is final — DO NOT fall back, the
  // Clerk stamp may have been set or the Resend call may have
  // partially completed and a second attempt would risk a duplicate.
  posthog.capture(distinctId, "newsletter.welcome_internal_responded", {
    http_status: result.status,
    dispatcher_status: result.body && result.body.status,
    dispatcher_reason: result.body && result.body.reason,
    source: source || "stripe.checkout",
    clerk_user_id: clerkUserId,
    latency_ms: result.body && result.body.latency_ms,
    ms: Date.now() - t0,
  });
  logApi("stripe.webhook", {
    status: 200, reason: "welcome_internal_responded",
    clerk_user_id: clerkUserId, http_status: result.status,
    dispatcher_status: (result.body && result.body.status) || "(none)",
    dispatcher_reason: (result.body && result.body.reason) || "-",
    latency_ms: (result.body && result.body.latency_ms) || 0,
  });
  if (result.status === 200) {
    const body = result.body || {};
    if (body.status === "sent") return "internal:sent";
    if (body.status === "skipped") return `internal:skipped:${body.reason || "unknown"}`;
    return "internal:ok";
  }
  return `internal:http_${result.status}`;
}


// Pulpo Pro Welcome — GitHub-Actions fallback dispatcher.
//
// Fires the `pulpo-pro-welcome.yml` GitHub Actions workflow against
// the recipient who just completed first-checkout. The Python
// dispatcher (`automation/newsletter/welcome_dispatch.py`) does the
// actual render + Resend send + Clerk metadata stamp.
//
// Webhook-side idempotency: read `publicMetadata.welcome_newsletter_sent_at`
// FIRST and skip the GH dispatch entirely when already set. The
// dispatcher would skip again on the Python side, but a workflow
// dispatch still costs ~30s of GH runtime — every Stripe retry on an
// already-welcomed user wastes a slot in the per-recipient concurrency
// queue, delaying legitimate sends.
//
// Race-safe: the workflow's `concurrency.group:
// pulpo-pro-welcome-${recipient_email}` enforces serial execution per
// email, so even if two webhook invocations race past the
// publicMetadata read, the second workflow run queues behind the first
// and finds the stamp set by the time it dispatches.
//
// Never throws. Stripe must always get its 200; a failed welcome
// dispatch is a marketing failure, not a payment failure. All errors
// log + PostHog and fall through.
//
// Returns one of: "dispatched" | "skipped:already_sent" |
// "skipped:no_github_token" | "skipped:no_clerk_user" | "error:<reason>".
const WELCOME_WORKFLOW_FILE = "pulpo-pro-welcome.yml";
const DEFAULT_DISPATCH_REPO = "javiersuarezOG/pulpo.club";
const DEFAULT_DISPATCH_REF = "main";

async function dispatchProWelcomeWorkflow({
  clerk,
  clerkUserId,
  email,
  source,
  distinctId,
  t0,
  fetchImpl,
  allowResubscribe,
}) {
  // Anything missing here is a "skip" outcome, not a webhook failure.
  // Stripe still gets a 200 — the user has paid; their welcome is a
  // best-effort marketing follow-up.
  if (!clerk || !clerkUserId || !email) {
    return "skipped:missing_input";
  }

  // Idempotency check — read the current Clerk user once. The
  // publicMetadata stamp is permanent; locked 2026-06-01, see
  // project_resubscribe_welcome_funnel memory for why we never
  // re-send (resubscribe is a separate funnel, not a welcome).
  let alreadySent = false;
  try {
    const user = await clerk.users.getUser(clerkUserId);
    const md = (user && user.publicMetadata) || {};
    if (md.welcome_newsletter_sent_at) alreadySent = true;
  } catch (err) {
    // Clerk read failure: fail open so we don't strand a user without
    // their welcome. The Python dispatcher's own idempotency check
    // backstops a real duplicate.
    logApi("stripe.webhook", {
      status: 200, reason: "welcome_clerk_read_failed",
      clerk_user_id: clerkUserId, error: (err && err.message) || "(no message)",
    });
  }

  if (alreadySent) {
    // A returning subscriber whose welcome-back fell to the GH fallback
    // (Vercel-Python was unreachable). The GH workflow renders only the
    // first-time welcome, so we correctly skip here rather than mail a
    // "Welcome to Pulpo Pro — your first 10" to someone who's been here
    // before. The welcome-back is intentionally NOT sent on this rare
    // fallback path — surface it so the gap is observable (a reconcile
    // backstop can pick these up later if the rate warrants it).
    if (allowResubscribe) {
      posthog.capture(distinctId, "newsletter.welcome_back_fallback_skipped", {
        reason: "gh_fallback_cannot_send_welcome_back",
        source: source || "stripe.checkout",
        clerk_user_id: clerkUserId,
        ms: Date.now() - t0,
      });
      return "skipped:welcome_back_unsupported_on_gh_fallback";
    }
    posthog.capture(distinctId, "newsletter.welcome_skipped", {
      reason: "already_sent",
      source: source || "stripe.checkout",
      clerk_user_id: clerkUserId,
      ms: Date.now() - t0,
    });
    return "skipped:already_sent";
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN || "";
  if (!token) {
    // Token missing in dev / preview without the secret. Log loudly
    // so the missing config is visible in Vercel logs.
    logApi("stripe.webhook", {
      status: 200, reason: "welcome_no_github_token",
      clerk_user_id: clerkUserId,
    });
    posthog.capture(distinctId, "newsletter.welcome_failed", {
      reason: "no_github_token",
      source: source || "stripe.checkout",
      clerk_user_id: clerkUserId,
      ms: Date.now() - t0,
    });
    return "skipped:no_github_token";
  }

  const repo = process.env.GITHUB_DISPATCH_REPO || DEFAULT_DISPATCH_REPO;
  const ref = process.env.GITHUB_DISPATCH_REF || DEFAULT_DISPATCH_REF;
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${WELCOME_WORKFLOW_FILE}/dispatches`;

  let gh;
  try {
    gh = await (fetchImpl || fetch)(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pulpo-stripe-webhook-welcome",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          recipient_email: email,
          send_mode: "yes",
          // The `source` argument is operator-friendly free text; we
          // restrict the workflow input to the closed set
          // {admin, stripe, test}. Anything Stripe-flavored maps to
          // "stripe" so dashboards can slice cleanly.
          source: "stripe",
          // Stripe path NEVER forces — production path respects the
          // idempotency stamp at the dispatcher layer too.
          force: "no",
        },
      }),
    });
  } catch (err) {
    logApi("stripe.webhook", {
      status: 200, reason: "welcome_github_fetch_failed",
      clerk_user_id: clerkUserId, error: (err && err.message) || "(no message)",
    });
    posthog.capture(distinctId, "newsletter.welcome_failed", {
      reason: "github_fetch_failed",
      source: source || "stripe.checkout",
      clerk_user_id: clerkUserId,
      error: (err && err.message) || "(no message)",
      ms: Date.now() - t0,
    });
    return `error:fetch_failed`;
  }

  if (gh.status !== 204) {
    let detail = "";
    try { detail = await gh.text(); } catch { /* best-effort */ }
    logApi("stripe.webhook", {
      status: 200, reason: "welcome_github_non_204",
      clerk_user_id: clerkUserId, github_status: gh.status,
    });
    posthog.capture(distinctId, "newsletter.welcome_failed", {
      reason: "github_dispatch_rejected",
      source: source || "stripe.checkout",
      clerk_user_id: clerkUserId,
      github_status: gh.status,
      github_detail: (detail || "").slice(0, 200),
      ms: Date.now() - t0,
    });
    return `error:github_${gh.status}`;
  }

  // Dispatch accepted. We do NOT poll the runs API here — the Stripe
  // webhook has a tight latency budget (Stripe gives up after ~30s
  // and retries the event), and the per-recipient concurrency group
  // on the workflow makes a missed dispatch self-healing on retry.
  logApi("stripe.webhook", {
    status: 200, reason: "welcome_dispatched",
    clerk_user_id: clerkUserId, repo, ref,
  });
  posthog.capture(distinctId, "newsletter.welcome_dispatched", {
    source: source || "stripe.checkout",
    clerk_user_id: clerkUserId,
    ms: Date.now() - t0,
  });
  return "dispatched";
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
  await auditEnvOverridesOnce();
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
    provider: "stripe",
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
        const stripe = stripeClient();
        await setStripeCustomerPreferredLocale(stripe, customerId, clerkLocale, "checkout", distinctId, t0);

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
          // Resend audience enrollment — newsletter is a Pro feature
          // per paywall copy. Best-effort: never blocks the payment.
          if (email) {
            await enrollPaidUserInAudience({
              email, locale: stripeLocale || "en",
              source: "stripe.checkout.auth_gated",
            });
          }
          // Pulpo Pro Welcome — fire the one-shot onboarding email
          // through the instant Vercel-Python path with GH-Actions
          // fallback. Best-effort: never blocks the payment.
          // Idempotent — Clerk publicMetadata stamp prevents re-send
          // on retries.
          const welcomeOutcome = email ? await dispatchProWelcome({
            clerk, clerkUserId: explicitUserId, email,
            source: "stripe.checkout.auth_gated",
            distinctId, t0,
            // Returning subscriber → welcome-back; first-timer → welcome.
            // The dispatcher decides based on the existing welcome stamp.
            allowResubscribe: true, subscriptionId,
          }) : "skipped:no_email";
          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "auth_gated", clerk_user_id: explicitUserId,
            welcome: welcomeOutcome,
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
          // Double-billing detection (003). A second checkout by an
          // already-Pro user overwrites stripeSubscriptionId below,
          // orphaning the prior still-billing subscription — which the
          // Customer Portal can't see (it keys off the stored id), so the
          // user can't self-cancel it. Telemetry-only + preserve the
          // prior id for support reconciliation; auto-cancel/refund moves
          // money and is a deliberate manual decision, not a default.
          const priorSubId = (existing.privateMetadata
            && existing.privateMetadata.stripeSubscriptionId) || null;
          const wasAlreadyPro = !!(existing.publicMetadata
            && existing.publicMetadata.plan === "pro");
          const duplicateActiveSub = !!(wasAlreadyPro && priorSubId
            && subscriptionId && priorSubId !== subscriptionId);
          if (duplicateActiveSub) {
            posthog.capture(distinctId, "webhook.duplicate_subscription_detected", {
              ...baseProps,
              path: "anonymous_existing_user",
              clerk_user_id: existing.id,
              existing_subscription_id: priorSubId,
              new_subscription_id: subscriptionId,
            });
          }
          await setPlanForClerkUser(clerk, existing.id, "pro", {
            stripeCustomerId: customerId || undefined,
            stripeSubscriptionId: subscriptionId || undefined,
            // Keep the orphaned prior id discoverable for manual cleanup.
            ...(duplicateActiveSub ? { priorStripeSubscriptionId: priorSubId } : {}),
            acquisitionSource: source || undefined,
            acquisitionUtms: Object.keys(utms).length ? utms : undefined,
          });
          // Resend audience enrollment — newsletter is a Pro feature.
          await enrollPaidUserInAudience({
            email, locale: stripeLocale || "en",
            source: "stripe.checkout.anonymous_existing_user",
          });
          // Pulpo Pro Welcome — same one-shot send as the auth-gated
          // path. Instant Vercel-Python primary with GH-Actions
          // fallback. Idempotent: the Clerk publicMetadata stamp
          // prevents duplicate sends across Stripe retries.
          const welcomeOutcome = await dispatchProWelcome({
            clerk, clerkUserId: existing.id, email,
            source: "stripe.checkout.anonymous_existing_user",
            distinctId, t0,
            // Returning subscriber → welcome-back; first-timer → welcome.
            // The dispatcher decides based on the existing welcome stamp.
            allowResubscribe: true, subscriptionId,
          });
          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "anonymous_existing_user", clerk_user_id: existing.id,
            locale: stripeLocale, welcome: welcomeOutcome,
          });
          // invitation_sent: false on existing-user — Clerk already has
          // a user record for this email, so no new invitation is sent.
          // The WelcomeModal's status-poll surfaces this case as
          // "user_exists" so the user knows to sign in, not check inbox.
          posthog.capture(distinctId, "webhook.checkout_completed", {
            ...baseProps, path: "anonymous_existing_user",
            clerk_user_id: existing.id, invitation_sent: false,
            duplicate_subscription_detected: duplicateActiveSub,
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

          // Resend audience enrollment — newsletter is a Pro feature.
          // Fires AFTER the invitation goes out so the user has an
          // account to sign into before their first newsletter lands.
          await enrollPaidUserInAudience({
            email, locale: stripeLocale || clerkLocale || "en",
            source: "stripe.checkout.anonymous_new_user",
          });

          // Mark the event as processed BEFORE telemetry so a Stripe
          // retry hits the dedup branch above even if the function gets
          // killed mid-handler. Failures are swallowed inside the
          // helper (see comment there) — a missed write means the next
          // retry redoes the work, which is the tolerated failure mode.
          await markStripeEventProcessed(stripe, subscriptionId, event.id);

          // Pulpo Pro Welcome dispatch — DEFERRED to invitation
          // acceptance time, not fired here. At this point no Clerk
          // user exists yet (only an invitation row), so the
          // dispatcher's Clerk lookup would skip with
          // reason=clerk_lookup_failed. Phase 2 wired the welcome
          // to the Clerk `user.created` webhook handler at
          // api/clerk/webhook.js — when the user accepts the
          // invitation and Clerk mints the user record, that hook
          // sees `publicMetadata.plan === "pro"` (set on the
          // invitation here, line 854) and dispatches the welcome
          // through the same `dispatchProWelcome` orchestrator.
          // No follow-up needed — the gap is closed.
          logApi("stripe.webhook", {
            status: 200, ms: Date.now() - t0, type: event.type,
            path: "anonymous_invitation_created", session_id: session.id,
            invitation_id: invitationId,
            locale: stripeLocale,
            resend_ok: sendResult.ok,
            resend_message_id: sendResult.message_id || "",
            resend_error: sendResult.error || "",
            welcome: "pending:awaits_invitation_acceptance",
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
              // Resend audience enrollment — newsletter is a Pro feature.
              await enrollPaidUserInAudience({
                email, locale: stripeLocale || "en",
                source: "stripe.checkout.anonymous_race_recovered",
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

        // Three buckets of Stripe status → Pulpo metadata patch:
        //   active / trialing → plan="pro", status="active", clear
        //                        grace fields (a successful recovery
        //                        after past_due routes through here).
        //   past_due / unpaid → plan="pro" (still!), status="past_due",
        //                        stamp grace fields if not already set
        //                        so the 14-day countdown is anchored
        //                        on the first failure, not on every
        //                        subscription.updated retry that fires
        //                        while we're still past_due.
        //   canceled / expired / deleted → plan="free", status="canceled",
        //                                  clear grace fields.
        const status = sub.status;
        const isDeleted = event.type === "customer.subscription.deleted";
        const isActive = !isDeleted && ACTIVE_STATUSES.has(status);
        const isTerminal = isDeleted || TERMINAL_STATUSES.has(status);
        const isPastDue = !isTerminal && (status === "past_due" || status === "unpaid");

        // Subscription period + cancellation state — captured for every
        // bucket so the account-page subscription block can render the
        // correct copy ("Renews on {date}" vs "Cancels on {date}" vs
        // "Ended on {date}") without falling back to a hardcoded
        // placeholder. Stripe sends seconds; we store ms to match the
        // existing payment_failed_at / grace_period_ends_at fields.
        const currentPeriodEnd = typeof sub.current_period_end === "number"
          ? sub.current_period_end * 1000
          : null;
        const cancelAtPeriodEnd = sub.cancel_at_period_end === true;
        const canceledAtMs = typeof sub.canceled_at === "number"
          ? sub.canceled_at * 1000
          : null;
        const pauseCollection = sub.pause_collection && typeof sub.pause_collection === "object"
          ? sub.pause_collection
          : null;
        const defaultPaymentMethod = typeof sub.default_payment_method === "string"
          ? sub.default_payment_method
          : (sub.default_payment_method && sub.default_payment_method.id) || null;

        let patch = null;
        if (isActive) {
          patch = {
            plan: "pro",
            subscription_status: "active",
            payment_failed_at: undefined,
            grace_period_ends_at: undefined,
            current_period_end: currentPeriodEnd,
            cancel_at_period_end: cancelAtPeriodEnd,
            pause_collection: pauseCollection,
            default_payment_method: defaultPaymentMethod,
            // Pending cancellation = preserve canceled_at if Stripe set
            // one; otherwise clear so a reactivation reads clean.
            canceled_at: canceledAtMs,
          };
        } else if (isPastDue) {
          // Read current metadata so we don't reset the grace clock on
          // every retry — past_due fires repeatedly while Stripe is
          // attempting Smart Retries.
          let existingGrace = null;
          let existingFailedAt = null;
          if (userId) {
            try {
              const u = await clerk.users.getUser(userId);
              const meta = (u && u.publicMetadata) || {};
              if (typeof meta.grace_period_ends_at === "number") existingGrace = meta.grace_period_ends_at;
              if (typeof meta.payment_failed_at === "number") existingFailedAt = meta.payment_failed_at;
            } catch { /* fall through — we'll stamp fresh */ }
          }
          const failedAt = existingFailedAt || ((event.created || Math.floor(Date.now() / 1000)) * 1000);
          const graceEndsAt = existingGrace || (failedAt + GRACE_MS);
          patch = {
            plan: "pro",
            subscription_status: "past_due",
            payment_failed_at: failedAt,
            grace_period_ends_at: graceEndsAt,
            current_period_end: currentPeriodEnd,
            cancel_at_period_end: cancelAtPeriodEnd,
            pause_collection: pauseCollection,
            default_payment_method: defaultPaymentMethod,
            canceled_at: canceledAtMs,
          };
        } else {
          // Terminal (canceled / expired / deleted): drop the user to
          // free and clear grace bookkeeping. Keep period_end +
          // canceled_at so the account page can render "Ended on {date}".
          patch = {
            plan: "free",
            subscription_status: "canceled",
            payment_failed_at: undefined,
            grace_period_ends_at: undefined,
            current_period_end: currentPeriodEnd,
            cancel_at_period_end: false,
            pause_collection: pauseCollection,
            default_payment_method: defaultPaymentMethod,
            canceled_at: canceledAtMs
              || ((event.created || Math.floor(Date.now() / 1000)) * 1000),
          };
        }

        if (userId) {
          // Churned Pro → Free: keep them in the audience as a FREE reader
          // (two-state — a canceled member IS a Free subscriber and should
          // keep getting the free weekly), and send the free welcome-back
          // ONCE. We deliberately DON'T unsubscribe on cancel anymore: the
          // Pro Sunday send is already gated to the Pro cohort, so a free
          // contact can't receive Pro issues; dropping the unsubscribe is
          // what lets them flow into the free digest. Dedup on the
          // subscription id so repeated subscription.updated/deleted
          // redeliveries don't re-send. Stamp BEFORE dispatch (at-most-once:
          // a rare dispatch failure means no welcome-back — never a
          // duplicate to a churned customer).
          let sendWelcomeBack = false;
          let welcomeLocale = "en";
          if (isTerminal && subEmail) {
            try {
              const u = await clerk.users.getUser(userId);
              const md = (u && u.publicMetadata) || {};
              if (md.downgrade_welcome_sub_id !== sub.id) sendWelcomeBack = true;
              const profLocale = md.profile && md.profile.locale;
              if (profLocale === "es" || profLocale === "en") welcomeLocale = profLocale;
            } catch {
              // Couldn't read the dedup stamp — favor NOT spamming a churned
              // customer over a possible duplicate; a later Stripe redelivery
              // can retry the read.
              sendWelcomeBack = false;
            }
            if (sendWelcomeBack) patch.downgrade_welcome_sub_id = sub.id;
          }

          await patchPublicMetadata(clerk, userId, patch);

          if (sendWelcomeBack) {
            await fireFreeWelcomeBack({
              email: subEmail,
              locale: welcomeLocale,
              source: "stripe_downgrade",
              distinctId: posthog.emailDistinctId(subEmail),
              t0,
            });
          }
          // Also stamp privateMetadata.stripeCustomerId + stripeSubscriptionId
          // so the Customer Portal endpoint can find them. The /start
          // anonymous-invitation flow never gets these onto the User
          // (only onto the invitation), so without this stamp the user
          // sees "We couldn't find your billing details" forever.
          // Idempotent: same IDs on every redelivery — safe to re-run.
          const subCustomerId = typeof sub.customer === "string"
            ? sub.customer
            : (sub.customer && sub.customer.id) || null;
          if (!subCustomerId && isActive) {
            posthog.capture(posthog.emailDistinctId(subEmail), "webhook.invitation_metadata_missing", {
              source: "stripe_webhook",
              subscription_id: sub.id,
              clerk_user_id: userId,
              status: status || "",
              ms: Date.now() - t0,
            });
          }
          if (subCustomerId || sub.id) {
            await patchPrivateMetadata(clerk, userId, {
              ...(subCustomerId ? { stripeCustomerId: subCustomerId } : {}),
              ...(sub.id ? { stripeSubscriptionId: sub.id } : {}),
            });
          }
          // Re-stamp Stripe Customer preferred_locales from the locale we
          // captured at checkout (lives on sub.metadata.locale). Without
          // this, a user who signed up in Spanish but never touched the
          // Stripe Customer record afterwards gets English dunning +
          // receipt emails the first time preferred_locales gets cleared
          // by another integration or by Stripe Dashboard edits.
          // Idempotent — same value on every webhook redelivery — and
          // non-fatal so a Stripe API hiccup never blocks the
          // subscription lifecycle.
          const subLocale = clerkLocaleFromStripe(sub.metadata && sub.metadata.locale);
          if (subCustomerId && subLocale) {
            // `stripe` is declared inside the checkout.session.completed case
            // block, which is out of scope here; this case needs its own
            // client or it throws a ReferenceError → HTTP 500 on every
            // locale-stamped subscription event (Stripe then retries ~3 days
            // and subscription_changed telemetry below never fires).
            const stripe = stripeClient();
            await setStripeCustomerPreferredLocale(
              stripe, subCustomerId, subLocale, "subscription_updated",
              posthog.emailDistinctId(subEmail), t0,
            );
          }
        }
        // Self-heal Resend audience membership for active Pro subs. The
        // ONLY other enrollment path is checkout.session.completed, whose
        // enrollPaidUserInAudience call is best-effort + NON-retried: a
        // transient Resend failure (or any non-checkout route to Pro —
        // e.g. a 100%-off friend-coupon redemption that hiccuped at
        // enroll time) leaves a paying user plan=pro in Clerk but absent
        // from the newsletter audience, so they silently never receive the
        // Pro weekly. subscription.updated fires on the original checkout
        // AND on every renewal/recovery, so enrolling here gives every
        // active Pro repeated, idempotent chances to land in the audience.
        // enrollPaidUserInAudience dedups on "already exists" (flipping
        // unsubscribed=false as a side effect) and is best-effort, so this
        // is safe to run on every redelivery and never blocks the webhook.
        let audienceEnroll = "skipped";
        if (isActive && subEmail) {
          const enrolled = await enrollPaidUserInAudience({
            email: subEmail,
            locale: (sub.metadata && sub.metadata.locale) || "en",
            source: "stripe.subscription.active_self_heal",
          });
          audienceEnroll = enrolled.ok
            ? (enrolled.dedup ? "dedup" : "ok")
            : (enrolled.reason || "fail");
        }
        posthog.capture(posthog.emailDistinctId(subEmail), "webhook.subscription_changed", {
          event_id: event.id,
          subscription_id: sub.id,
          type: event.type,
          status: status || "",
          is_active: isActive,
          is_past_due: isPastDue,
          is_terminal: isTerminal,
          clerk_user_id: userId || "",
          grace_period_ends_at: patch.grace_period_ends_at || 0,
          source: (sub.metadata && sub.metadata.source) ? String(sub.metadata.source) : "",
          // ok = a Pro who was MISSING from the audience just got enrolled
          // (a silently-dropped user healed); dedup = already present.
          // A stream of `ok` on renewals is the signal that the
          // checkout-time enroll is dropping users — investigate upstream.
          audience_enroll: audienceEnroll,
          ms: Date.now() - t0,
        });
        break;
      }
      case "invoice.payment_failed": {
        // Fires on each failed charge attempt. We anchor the 14-day
        // grace clock on the FIRST failure of the current dunning cycle
        // — subsequent retries don't reset it. customer.subscription.updated
        // (status=past_due) usually fires alongside this and would
        // also stamp the same fields; we leave both wired so a missed
        // subscription.updated still produces a grace stamp.
        const inv = event.data.object;
        const subId = typeof inv.subscription === "string"
          ? inv.subscription
          : (inv.subscription && inv.subscription.id);
        const invEmail = (inv.customer_email)
          || (inv.customer_address && inv.customer_address.email)
          || null;
        let userId = null;
        let subMeta = {};
        if (subId) {
          try {
            const sub = await stripeClient().subscriptions.retrieve(subId);
            subMeta = (sub && sub.metadata) || {};
            userId = subMeta.clerkUserId || null;
          } catch { /* fall back to email lookup */ }
        }
        const fallbackEmail = invEmail || subMeta.email || null;
        if (!userId && fallbackEmail) {
          const user = await findClerkUserByEmail(clerk, fallbackEmail);
          if (user) userId = user.id;
        }
        if (userId) {
          // Read first so we don't reset the clock on retries.
          let existingGrace = null;
          let existingFailedAt = null;
          try {
            const u = await clerk.users.getUser(userId);
            const meta = (u && u.publicMetadata) || {};
            if (typeof meta.grace_period_ends_at === "number") existingGrace = meta.grace_period_ends_at;
            if (typeof meta.payment_failed_at === "number") existingFailedAt = meta.payment_failed_at;
          } catch { /* stamp fresh */ }
          const failedAt = existingFailedAt || ((event.created || Math.floor(Date.now() / 1000)) * 1000);
          const graceEndsAt = existingGrace || (failedAt + GRACE_MS);
          await patchPublicMetadata(clerk, userId, {
            plan: "pro",
            subscription_status: "past_due",
            payment_failed_at: failedAt,
            grace_period_ends_at: graceEndsAt,
          });
          posthog.capture(posthog.emailDistinctId(fallbackEmail), "webhook.invoice_payment_failed", {
            event_id: event.id,
            invoice_id: inv.id,
            subscription_id: subId || "",
            clerk_user_id: userId,
            grace_period_ends_at: graceEndsAt,
            attempt_count: typeof inv.attempt_count === "number" ? inv.attempt_count : 0,
            ms: Date.now() - t0,
          });
        }
        break;
      }
      case "invoice.payment_succeeded": {
        // Successful charge — including recovery from a past_due state.
        // Always clear the grace fields so a recovered customer goes
        // back to a clean "active" view.
        const inv = event.data.object;
        const subId = typeof inv.subscription === "string"
          ? inv.subscription
          : (inv.subscription && inv.subscription.id);
        const invEmail = (inv.customer_email)
          || (inv.customer_address && inv.customer_address.email)
          || null;
        let userId = null;
        let subMeta = {};
        if (subId) {
          try {
            const sub = await stripeClient().subscriptions.retrieve(subId);
            subMeta = (sub && sub.metadata) || {};
            userId = subMeta.clerkUserId || null;
          } catch { /* fall back */ }
        }
        const fallbackEmail = invEmail || subMeta.email || null;
        if (!userId && fallbackEmail) {
          const user = await findClerkUserByEmail(clerk, fallbackEmail);
          if (user) userId = user.id;
        }
        if (userId) {
          await patchPublicMetadata(clerk, userId, {
            plan: "pro",
            subscription_status: "active",
            payment_failed_at: undefined,
            grace_period_ends_at: undefined,
          });
          posthog.capture(posthog.emailDistinctId(fallbackEmail), "webhook.invoice_payment_succeeded", {
            event_id: event.id,
            invoice_id: inv.id,
            subscription_id: subId || "",
            clerk_user_id: userId,
            // Distinguish first invoice (initial purchase already handled
            // by checkout.session.completed) from a recovery — useful
            // for funnel attribution.
            billing_reason: typeof inv.billing_reason === "string" ? inv.billing_reason : "",
            ms: Date.now() - t0,
          });
        }
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
module.exports.dispatchProWelcomeWorkflow = dispatchProWelcomeWorkflow;
module.exports.dispatchProWelcome = dispatchProWelcome;
module.exports.callInternalWelcomeSend = callInternalWelcomeSend;
module.exports.fireFreeWelcomeBack = fireFreeWelcomeBack;
