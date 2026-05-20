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
const { sendActivationEmail } = require("../_activation_email");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Normalize Pulpo's Stripe-flavored locale ("es-419"/"en") to the
// BCP-47 root Clerk's invitation API expects. Mirrored from webhook.js
// — duplicated rather than shared because the api/clerk module
// shouldn't reach into api/stripe internals.
function clerkLocaleFromStripe(stripeLocale) {
  if (!stripeLocale || typeof stripeLocale !== "string") return undefined;
  const lc = stripeLocale.trim().toLowerCase();
  if (!lc) return undefined;
  if (lc === "es" || lc.startsWith("es-")) return "es";
  if (lc === "en" || lc.startsWith("en-")) return "en";
  return undefined;
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

  // Pulpo stamps the user's UI locale onto session.metadata in
  // start-checkout.js; re-read it here so the resent email matches
  // the original language even if Clerk Dashboard has multi-locale
  // templates configured.
  const stripeLocale = (session.metadata && session.metadata.locale)
    ? String(session.metadata.locale) : "";
  const clerkLocale = clerkLocaleFromStripe(stripeLocale);

  const distinctId = posthog.emailDistinctId(email);

  // If the user already exists in Clerk (e.g. they signed in
  // separately or this is the auth-gated flow), there's nothing to
  // resend — surface a 200 with status: "user_exists" so the
  // WelcomeModal can show the "refresh this page" copy instead of
  // lying with "check your inbox".
  const clerk = clerkClient();
  const existing = await findClerkUserByEmail(clerk, email);
  if (existing) {
    logApi("clerk.resend_invitation", {
      status: 200, ms: Date.now() - t0, path: "user_exists",
      clerk_user_id: existing.id, session_id: sessionId,
      locale: stripeLocale,
    });
    posthog.capture(distinctId, "clerk.invitation_resent", {
      session_id: sessionId, path: "user_exists",
      reason: "noop", locale: stripeLocale, ms: Date.now() - t0,
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
        locale: stripeLocale,
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
    // notify: false so Clerk creates the invitation row but skips its
    // own email send. We send via Resend below — Pulpo's verified
    // mail.pulpo.club sender — because Clerk's pipeline holds at
    // status=queued indefinitely on this account. Same rationale as
    // api/stripe/webhook.js. ?lang=<locale> locks the post-click
    // landing to the email's language; see webhook.js for context.
    const invitation = await clerk.invitations.createInvitation({
      emailAddress: email,
      notify: false,
      // welcome=1 + activation=1 marker — see api/stripe/webhook.js
      // for the rationale (deterministic URL signal, not SDK state).
      redirectUrl: `${origin}/account?welcome=1&activation=1${clerkLocale ? `&lang=${clerkLocale}` : ""}`,
      ...(clerkLocale ? { locale: clerkLocale } : {}),
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
    const invitationId = invitation && invitation.id;
    const actionUrl = (invitation && invitation.url) || `${origin}/account?welcome=1`;

    // Fire the Resend send. Same shape as webhook.js — keeps the
    // "Resend my invitation" button using the same successful pipeline.
    const sendResult = await sendActivationEmail({
      email,
      locale: stripeLocale || clerkLocale,
      actionUrl,
      sessionId,
    });

    logApi("clerk.resend_invitation", {
      status: sendResult.ok ? 200 : 502, ms: Date.now() - t0,
      path: sendResult.ok ? "resent" : "resend_send_failed",
      session_id: sessionId, invitation_id: invitationId,
      was_dupe: !!pending, locale: stripeLocale,
      resend_message_id: sendResult.message_id || "",
      resend_error: sendResult.error || "",
    });
    posthog.capture(distinctId, "clerk.invitation_resent", {
      session_id: sessionId,
      path: sendResult.ok ? "resent" : "resend_send_failed",
      was_dupe: !!pending, locale: stripeLocale,
      resend_status_code: sendResult.status_code || 0,
      resend_error: sendResult.error || "",
      ms: Date.now() - t0,
    });
    await posthog.flush();
    if (!sendResult.ok) {
      // Surface Resend failure to the client so the modal can show a
      // useful error rather than the lying "we just sent" copy.
      return res.status(502).json({
        status: "resend_send_failed",
        error: sendResult.error || "resend_failed",
      });
    }
    return res.status(200).json({ status: "resent" });
  } catch (err) {
    logApi("clerk.resend_invitation", {
      status: 500, ms: Date.now() - t0, reason: "create_failed",
      session_id: sessionId, error: err && err.message,
      locale: stripeLocale,
    });
    posthog.capture(distinctId, "clerk.invitation_resent", {
      session_id: sessionId, path: "create_failed",
      error_message: err && err.message, locale: stripeLocale, ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(500).json({ error: "create_failed" });
  }
};
