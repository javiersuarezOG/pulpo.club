// GET /api/clerk/invitation-status?session_id=cs_…
//
// Read-only sibling of /api/clerk/resend-invitation. Returns the
// CURRENT post-Stripe activation state for a given Stripe Checkout
// Session, so the WelcomeModal can render copy that's honest about
// what's actually happening on the server side instead of the
// generic "we just sent an invitation to your inbox" lie that covered
// every webhook outcome equally.
//
// Discriminated response — `status` is one of:
//   - "invitation_pending":  Clerk has a pending invitation for this
//                            session's email. Activation email was
//                            (or is being) sent. Modal should keep
//                            its "check your inbox" copy.
//   - "user_exists":         Clerk already has a user record for
//                            this email. The webhook's
//                            `anonymous_existing_user` branch bumped
//                            their plan to pro silently — no email
//                            was sent. Modal should tell the user
//                            to sign in.
//   - "no_email":            Stripe session has no customer email
//                            (rare — Stripe normally collects it).
//                            Webhook took `anonymous_no_email` path
//                            and did nothing.
//   - "session_not_found":   The session_id is bogus or doesn't
//                            belong to our Stripe account.
//   - "session_not_complete": Session exists but isn't `complete` —
//                            e.g. cancelled or still expanding.
//   - "webhook_pending":     Session is complete + has an email, but
//                            Clerk has neither a user nor a pending
//                            invitation for it yet. Likely the
//                            webhook hasn't fired (or is still
//                            inflight). Client polls again.
//
// Auth: no Clerk session required — by definition the user is
// pre-auth. Authorization comes from session_id; we verify it exists
// + matches `status=complete` in Stripe before returning any data.
// The email returned to the client is the domain only (PII gate).

const {
  stripeClient,
  clerkClient,
  logApi,
} = require("../stripe/_stripe");
const posthog = require("../_posthog");
const withTiming = require("../_perf");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

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

function emailDomain(email) {
  if (!email || typeof email !== "string") return "";
  const at = email.lastIndexOf("@");
  return at < 0 ? "" : email.slice(at + 1).toLowerCase();
}

// PR-perf-5a — withTiming wraps every response with Server-Timing.
// This endpoint is polled by WelcomeModal on the post-Stripe-return
// flow, so its latency directly impacts the user-perceived gap
// between Stripe redirect-back and the "you're all set" modal.
module.exports = withTiming(async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const sessionId = typeof req.query.session_id === "string"
    ? req.query.session_id.trim()
    : "";
  if (!sessionId) {
    logApi("clerk.invitation_status", {
      status: 400, ms: Date.now() - t0, reason: "missing_session_id",
    });
    return res.status(400).json({ error: "missing_session_id" });
  }

  let session;
  try {
    session = await stripeClient().checkout.sessions.retrieve(sessionId, {
      expand: ["customer_details"],
    });
  } catch (err) {
    logApi("clerk.invitation_status", {
      status: 200, ms: Date.now() - t0, path: "session_not_found",
      session_id: sessionId, error: err && err.message,
    });
    return res.status(200).json({ status: "session_not_found" });
  }

  if (!session || session.status !== "complete") {
    logApi("clerk.invitation_status", {
      status: 200, ms: Date.now() - t0, path: "session_not_complete",
      session_id: sessionId, stripe_status: session && session.status,
    });
    return res.status(200).json({ status: "session_not_complete" });
  }

  const email = (session.customer_details && session.customer_details.email)
    || session.customer_email
    || null;
  if (!email || !EMAIL_RE.test(email)) {
    logApi("clerk.invitation_status", {
      status: 200, ms: Date.now() - t0, path: "no_email",
      session_id: sessionId,
    });
    return res.status(200).json({ status: "no_email" });
  }

  const stripeLocale = (session.metadata && session.metadata.locale)
    ? String(session.metadata.locale) : "";
  const domain = emailDomain(email);
  const distinctId = posthog.emailDistinctId(email);
  const clerk = clerkClient();

  // Check user first — `user_exists` short-circuits both the
  // invitation lookup AND the webhook_pending fallback (a Clerk user
  // with a pending invitation can exist when the webhook is mid-flight
  // mid-create; user-existence is the more definitive signal).
  const existing = await findClerkUserByEmail(clerk, email);
  if (existing) {
    logApi("clerk.invitation_status", {
      status: 200, ms: Date.now() - t0, path: "user_exists",
      session_id: sessionId, clerk_user_id: existing.id,
      locale: stripeLocale,
    });
    posthog.capture(distinctId, "clerk.invitation_status_resolved", {
      session_id: sessionId, status: "user_exists",
      locale: stripeLocale, ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(200).json({
      status: "user_exists",
      email_domain: domain,
    });
  }

  const pending = await findPendingInvitation(clerk, email);
  if (pending) {
    logApi("clerk.invitation_status", {
      status: 200, ms: Date.now() - t0, path: "invitation_pending",
      session_id: sessionId, invitation_id: pending.id,
      locale: stripeLocale,
    });
    posthog.capture(distinctId, "clerk.invitation_status_resolved", {
      session_id: sessionId, status: "invitation_pending",
      locale: stripeLocale, ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(200).json({
      status: "invitation_pending",
      email_domain: domain,
      // ISO 8601 string so the client can render "sent 30s ago"
      // copy if it wants. Clerk's `createdAt` is unix-ms; safer to
      // pass an ISO string than a number the client might
      // mis-parse.
      sent_at: pending.createdAt
        ? new Date(pending.createdAt).toISOString()
        : null,
      locale: stripeLocale,
    });
  }

  // No user, no pending invitation, session is complete + has an
  // email. The webhook either hasn't fired yet (Stripe webhook
  // delivery latency) or failed before reaching the invitation
  // create. Client should poll again — usually resolves within a
  // second or two on warm Vercel; up to 30s on a cold-start.
  logApi("clerk.invitation_status", {
    status: 200, ms: Date.now() - t0, path: "webhook_pending",
    session_id: sessionId, locale: stripeLocale,
  });
  posthog.capture(distinctId, "clerk.invitation_status_resolved", {
    session_id: sessionId, status: "webhook_pending",
    locale: stripeLocale, ms: Date.now() - t0,
  });
  await posthog.flush();
  return res.status(200).json({
    status: "webhook_pending",
    email_domain: domain,
  });
});
