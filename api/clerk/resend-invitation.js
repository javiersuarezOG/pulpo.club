// POST /api/clerk/resend-invitation
//
// Re-fires the Clerk invitation for the user attached to a Stripe
// Checkout Session. Used by the WelcomeModal's "Resend the link"
// button on /account?welcome=1 — gives the user a self-service path
// when the original invitation email didn't arrive (spam, typo'd
// email, Clerk SendGrid throttle).
//
// Idempotency: if a pending Clerk invitation for the same email
// already exists, we **revoke and recreate** (Clerk doesn't expose a
// "resend without recreate" API on createInvitation as of this
// writing). That keeps the user's email content fresh and avoids
// duplicate "you have an invitation" rows in the dashboard.
//
// Auth: no Clerk session required (the user is by definition not
// signed in yet). Authorization comes from the session_id — we verify
// the Stripe Checkout Session exists + is `complete` before doing
// anything; that's the cryptographic-strength gate.

const {
  stripeClient,
  clerkClient,
  logApi,
} = require("../stripe/_stripe");
const posthog = require("../_posthog");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

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

async function findClerkUserByEmail(clerk, email) {
  if (!email) return null;
  const result = await clerk.users.getUserList({ emailAddress: [email], limit: 1 });
  const list = Array.isArray(result) ? result : (result && result.data) || [];
  return list[0] || null;
}

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

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const body = await readJsonBody(req);
  const sessionId = typeof body.session_id === "string" ? body.session_id.trim() : "";
  if (!sessionId) {
    logApi("clerk.resend_invitation", {
      status: 400, ms: Date.now() - t0, reason: "missing_session_id",
    });
    return res.status(400).json({ error: "missing_session_id" });
  }

  // Verify the Stripe session — only honour a resend for a session
  // that actually exists + completed in our Stripe account.
  let session;
  try {
    session = await stripeClient().checkout.sessions.retrieve(sessionId, {
      expand: ["customer_details"],
    });
  } catch (err) {
    logApi("clerk.resend_invitation", {
      status: 404, ms: Date.now() - t0, reason: "session_not_found",
      session_id: sessionId, error: err && err.message,
    });
    return res.status(404).json({ error: "session_not_found" });
  }

  if (!session || session.status !== "complete") {
    logApi("clerk.resend_invitation", {
      status: 400, ms: Date.now() - t0, reason: "session_not_complete",
      session_id: sessionId, status: session && session.status,
    });
    return res.status(400).json({ error: "session_not_complete" });
  }

  const email = (session.customer_details && session.customer_details.email)
    || session.customer_email
    || null;
  if (!email || !EMAIL_RE.test(email)) {
    logApi("clerk.resend_invitation", {
      status: 400, ms: Date.now() - t0, reason: "no_email_on_session",
      session_id: sessionId,
    });
    return res.status(400).json({ error: "no_email_on_session" });
  }

  const distinctId = posthog.emailDistinctId(email);

  // If the user already exists in Clerk (e.g. they signed in
  // separately or this is the auth-gated flow), there's nothing to
  // resend — surface a 200 with a hint so the frontend can show
  // "you're already in" copy if it wants. (Today the modal just
  // shows the generic resend-failed message; we'll iterate.)
  const clerk = clerkClient();
  const existing = await findClerkUserByEmail(clerk, email);
  if (existing) {
    logApi("clerk.resend_invitation", {
      status: 200, ms: Date.now() - t0, path: "user_exists",
      clerk_user_id: existing.id, session_id: sessionId,
    });
    posthog.capture(distinctId, "clerk.invitation_resent", {
      session_id: sessionId, path: "user_exists",
      reason: "noop", ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(200).json({ status: "user_exists" });
  }

  // Revoke any prior pending invitation so we start fresh.
  const pending = await findPendingInvitation(clerk, email);
  if (pending) {
    try {
      await clerk.invitations.revokeInvitation(pending.id);
    } catch (err) {
      logApi("clerk.resend_invitation", {
        status: 500, ms: Date.now() - t0, reason: "revoke_failed",
        invitation_id: pending.id, error: err && err.message,
      });
      // Fall through — Clerk may have already revoked / expired it.
    }
  }

  // Create a fresh invitation. Pull origin from request headers so dev
  // / preview / prod each redirect to themselves.
  const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
  const host = req.headers["x-forwarded-host"] || req.headers.host || "pulpo.club";
  const origin = `${proto}://${host}`;
  try {
    const invitation = await clerk.invitations.createInvitation({
      emailAddress: email,
      redirectUrl:  `${origin}/account?welcome=1`,
      publicMetadata: { plan: "pro" },
      privateMetadata: {
        stripeSessionId: sessionId,
        stripeCustomerId: typeof session.customer === "string"
          ? session.customer
          : (session.customer && session.customer.id) || null,
        stripeSubscriptionId: typeof session.subscription === "string"
          ? session.subscription
          : (session.subscription && session.subscription.id) || null,
        resentAt: new Date().toISOString(),
      },
    });
    logApi("clerk.resend_invitation", {
      status: 200, ms: Date.now() - t0, path: "resent",
      session_id: sessionId, invitation_id: invitation && invitation.id,
      was_dupe: !!pending,
    });
    posthog.capture(distinctId, "clerk.invitation_resent", {
      session_id: sessionId, path: "resent",
      was_dupe: !!pending, ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(200).json({ status: "resent" });
  } catch (err) {
    logApi("clerk.resend_invitation", {
      status: 500, ms: Date.now() - t0, reason: "create_failed",
      session_id: sessionId, error: err && err.message,
    });
    posthog.capture(distinctId, "clerk.invitation_resent", {
      session_id: sessionId, path: "create_failed",
      error_message: err && err.message, ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(500).json({ error: "create_failed" });
  }
};
