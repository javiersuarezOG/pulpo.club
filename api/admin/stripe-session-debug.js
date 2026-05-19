// GET /api/admin/stripe-session-debug?session_id=cs_…
//
// Read-only diagnostic. For a given Stripe Checkout Session it
// returns the server's view of why an activation email did (or
// didn't) get sent. Solves a recurring "I paid but no email"
// support pattern where the right answer is one of six webhook
// branches (see api/stripe/webhook.js) and the existing telemetry
// (PostHog `webhook.checkout_completed`) is the only place to look,
// which is operator-hostile when triaging a single user's case.
//
// Output is the inputs the webhook would have seen (Stripe session
// state + email) and the current Clerk-side state (user-exists,
// pending-invitations). The "expected_webhook_path" field is the
// branch that webhook.js WOULD take on a fresh delivery of the same
// session — a hint, not a guarantee, since the actual branch may
// differ if e.g. the user got created between the original webhook
// and this diagnostic call.
//
// Auth: bearer token in `Authorization: Bearer <PULPO_ADMIN_DEBUG_TOKEN>`.
// Constant-time compare on the token to avoid timing leaks. Returns
// 401 with no body if the token is missing, malformed, or wrong.
//
// Side effects: emits a PostHog event so we can see frequency / who
// is calling this and from where. Does NOT call any Clerk mutation
// or Stripe mutation API.

const crypto = require("crypto");
const {
  stripeClient,
  clerkClient,
  logApi,
} = require("../stripe/_stripe");
const posthog = require("../_posthog");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function readToken(req) {
  const header = req.headers && (req.headers.authorization || req.headers.Authorization);
  if (!header || typeof header !== "string") return "";
  if (!header.startsWith("Bearer ")) return "";
  return header.slice(7).trim();
}

function tokensMatch(given, expected) {
  if (!given || !expected) return false;
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

async function findClerkUserByEmail(clerk, email) {
  if (!email) return null;
  const result = await clerk.users.getUserList({ emailAddress: [email], limit: 1 });
  const list = Array.isArray(result) ? result : (result && result.data) || [];
  return list[0] || null;
}

async function findPendingInvitationsForEmail(clerk, email) {
  if (!email) return [];
  try {
    const result = await clerk.invitations.getInvitationList({ status: "pending" });
    const list = Array.isArray(result) ? result : (result && result.data) || [];
    return list
      .filter((inv) => (inv.emailAddress || "").toLowerCase() === email.toLowerCase())
      .map((inv) => ({
        id: inv.id,
        created_at: inv.createdAt
          ? new Date(inv.createdAt).toISOString()
          : null,
      }));
  } catch {
    return [];
  }
}

// Mirror of the branch logic in api/stripe/webhook.js. Kept in this file
// rather than imported so the diagnostic stays a pure read — if the
// webhook gets restructured this becomes a slightly-stale hint, which
// is fine for a triage tool. Keep the branch names in sync by hand.
function expectedWebhookPath({
  hasClientReferenceId,
  hasEmail,
  clerkUserExists,
  pendingCount,
}) {
  if (hasClientReferenceId) return "auth_gated";
  if (!hasEmail) return "anonymous_no_email";
  if (clerkUserExists) return "anonymous_existing_user";
  if (pendingCount > 0) return "anonymous_dupe_invitation_skipped";
  return "anonymous_invitation_created";
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const expected = (process.env.PULPO_ADMIN_DEBUG_TOKEN || "").trim();
  if (!expected) {
    logApi("admin.stripe_session_debug", {
      status: 503, reason: "token_not_configured", ms: Date.now() - t0,
    });
    return res.status(503).json({ error: "debug_token_not_configured" });
  }
  const given = readToken(req);
  if (!tokensMatch(given, expected)) {
    logApi("admin.stripe_session_debug", {
      status: 401, reason: "bad_token", ms: Date.now() - t0,
    });
    return res.status(401).end();
  }

  const sessionId = typeof req.query.session_id === "string"
    ? req.query.session_id.trim()
    : "";
  if (!sessionId) {
    return res.status(400).json({ error: "missing_session_id" });
  }

  let session;
  try {
    session = await stripeClient().checkout.sessions.retrieve(sessionId, {
      expand: ["customer_details"],
    });
  } catch (err) {
    logApi("admin.stripe_session_debug", {
      status: 200, ms: Date.now() - t0, path: "session_not_found",
      session_id: sessionId, error: err && err.message,
    });
    return res.status(200).json({
      session_id: sessionId,
      session: null,
      finding: "session_not_found",
    });
  }

  const email = (session.customer_details && session.customer_details.email)
    || session.customer_email
    || null;
  const validEmail = !!email && EMAIL_RE.test(email);
  const hasClientReferenceId = !!session.client_reference_id;

  const clerk = clerkClient();
  let clerkUser = null;
  let pendingInvitations = [];
  if (validEmail) {
    [clerkUser, pendingInvitations] = await Promise.all([
      findClerkUserByEmail(clerk, email),
      findPendingInvitationsForEmail(clerk, email),
    ]);
  }

  const expectedPath = expectedWebhookPath({
    hasClientReferenceId,
    hasEmail: validEmail,
    clerkUserExists: !!clerkUser,
    pendingCount: pendingInvitations.length,
  });

  logApi("admin.stripe_session_debug", {
    status: 200, ms: Date.now() - t0,
    session_id: sessionId,
    stripe_status: session.status,
    clerk_user_exists: !!clerkUser,
    pending_count: pendingInvitations.length,
    expected_path: expectedPath,
  });
  posthog.capture(posthog.emailDistinctId(email), "admin.stripe_session_debug_viewed", {
    session_id: sessionId,
    stripe_status: session.status,
    clerk_user_exists: !!clerkUser,
    pending_count: pendingInvitations.length,
    expected_path: expectedPath,
    ms: Date.now() - t0,
  });
  await posthog.flush();

  return res.status(200).json({
    session_id: sessionId,
    session: {
      status: session.status,
      payment_status: session.payment_status,
      amount_total: typeof session.amount_total === "number" ? session.amount_total : null,
      currency: session.currency || null,
      customer_email: email,
      email_is_valid: validEmail,
      client_reference_id: session.client_reference_id || null,
      metadata_locale: (session.metadata && session.metadata.locale) || null,
      metadata_source: (session.metadata && session.metadata.source) || null,
    },
    clerk_user: clerkUser
      ? {
          exists: true,
          id: clerkUser.id,
          plan: (clerkUser.publicMetadata && clerkUser.publicMetadata.plan) || null,
        }
      : { exists: false, id: null, plan: null },
    pending_invitations_for_email: pendingInvitations,
    // The branch webhook.js WOULD take on a fresh redelivery. Mirrors
    // api/stripe/webhook.js exactly — keep in sync.
    expected_webhook_path: expectedPath,
    // Operator hint — which branches emit an activation email.
    sends_email: expectedPath === "anonymous_invitation_created",
    // Pointers for follow-up triage.
    posthog_hint: `Search PostHog for event "webhook.checkout_completed" where session_id="${sessionId}" — the historical record of what actually ran.`,
  });
};
