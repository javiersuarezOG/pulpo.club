// Backend source of truth for "what plan is this user actually on?".
//
// Two distinct mechanisms feed into the answer:
//
//  1. Stripe subscription lifecycle, captured by api/stripe/webhook.js
//     into the Clerk user's `publicMetadata`:
//       plan                    — "pro" | "free" | "agency" (canonical)
//       subscription_status     — "active" | "past_due" | "canceled"
//       payment_failed_at       — unix ms; set on first invoice failure
//       grace_period_ends_at    — unix ms; payment_failed_at + 14 days
//
//     A past_due subscription keeps `plan = "pro"` in metadata so the UI
//     can show "you're still Pro — but update your card" during grace.
//     Once `grace_period_ends_at` passes, Pulpo treats the user as Free
//     even though Stripe may still be retrying — explicit 14-day
//     enforcement on our side independent of Stripe's retry schedule.
//
//  2. Founder-email allowlist, read from FOUNDER_EMAILS (or
//     VITE_FOUNDER_EMAILS as a fallback — Vercel exposes Vite-prefixed
//     env vars to serverless functions too, same pattern as
//     api/_clerk.js's publishable-key fallback). Comma list of
//     addresses promoted to Pro without ever paying — used for founders
//     / team / comped accounts.
//
// Both mechanisms only ever promote. agency stays agency, a webhook-set
// pro stays pro, and a free user never becomes "less free."

const GRACE_DAYS = 14;
const GRACE_MS = GRACE_DAYS * 24 * 60 * 60 * 1000;

function readFounderEmails() {
  const raw = process.env.FOUNDER_EMAILS || process.env.VITE_FOUNDER_EMAILS || "";
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

// Evaluated once at module load — env vars are static for the
// lifetime of the serverless function instance.
const FOUNDER_EMAILS = readFounderEmails();

function isFounderEmail(email) {
  if (!email) return false;
  return FOUNDER_EMAILS.has(String(email).toLowerCase());
}

// Pure: takes a publicMetadata-shaped object and returns the derived
// subscription view used by both the gating helper and the UI.
// Separating this from `effectivePlan` keeps the helper testable
// without constructing a full Clerk user shape, and lets the frontend
// twin (web/app/lib/subscription.ts) keep parity with one diff.
//
// Returned shape:
//   plan                    — raw metadata plan ("pro" | "free" | "agency")
//   effective               — what the user effectively gets right now
//                             after grace + founder rules ("pro" |
//                             "free" | "agency")
//   status                  — "active" | "past_due" | "canceled"
//                             (defaults "active" for legacy users that
//                             pre-date the subscription_status field)
//   in_grace                — true iff status is past_due and we're
//                             still within grace_period_ends_at
//   grace_period_ends_at    — unix ms (or null)
//   payment_failed_at       — unix ms (or null)
function deriveSubscriptionState(meta, now) {
  const m = meta || {};
  const rawPlan = m.plan === "pro" || m.plan === "agency" ? m.plan : "free";
  const status = m.subscription_status === "past_due" || m.subscription_status === "canceled"
    ? m.subscription_status
    : "active";
  const graceEndsAt = typeof m.grace_period_ends_at === "number" ? m.grace_period_ends_at : null;
  const paymentFailedAt = typeof m.payment_failed_at === "number" ? m.payment_failed_at : null;
  const t = typeof now === "number" ? now : Date.now();
  const inGrace = status === "past_due" && graceEndsAt !== null && t < graceEndsAt;

  let effective;
  if (rawPlan === "agency") {
    effective = "agency";
  } else if (rawPlan === "pro") {
    // past_due past the grace window → demote to free (Pulpo-enforced;
    // Stripe may still be retrying its own dunning schedule).
    if (status === "past_due" && graceEndsAt !== null && t >= graceEndsAt) {
      effective = "free";
    } else if (status === "canceled") {
      // A subscription.deleted webhook should set plan=free, so this is
      // a transient state we can still represent honestly.
      effective = "free";
    } else {
      effective = "pro";
    }
  } else {
    effective = "free";
  }

  return {
    plan: rawPlan,
    effective,
    status,
    in_grace: inGrace,
    grace_period_ends_at: graceEndsAt,
    payment_failed_at: paymentFailedAt,
  };
}

// Apply the founder-email override on top of the derived state. The
// override only ever promotes — it cannot demote a paying customer
// who's been deactivated for some other reason.
function applyFounderToState(state, email) {
  if (state.effective === "free" && isFounderEmail(email)) {
    return { ...state, effective: "pro" };
  }
  return state;
}

// Resolve the effective plan for a Clerk user object (as returned by
// `clerkClient().users.getUser(userId)`). Compatible with the pre-grace
// callers that just want a string answer.
function effectivePlan(clerkUser) {
  if (!clerkUser) return "free";
  const meta = clerkUser.publicMetadata || {};
  const state = deriveSubscriptionState(meta);
  if (state.effective !== "free") return state.effective;
  const emailObj = clerkUser.primaryEmailAddress;
  const email = emailObj && emailObj.emailAddress ? emailObj.emailAddress : null;
  return isFounderEmail(email) ? "pro" : "free";
}

// Full subscription view for the Account page and any caller that
// needs to know about grace / past_due / cancellation in addition to
// the effective plan.
function effectiveSubscriptionState(clerkUser) {
  if (!clerkUser) {
    return {
      plan: "free",
      effective: "free",
      status: "active",
      in_grace: false,
      grace_period_ends_at: null,
      payment_failed_at: null,
    };
  }
  const meta = clerkUser.publicMetadata || {};
  const state = deriveSubscriptionState(meta);
  const emailObj = clerkUser.primaryEmailAddress;
  const email = emailObj && emailObj.emailAddress ? emailObj.emailAddress : null;
  return applyFounderToState(state, email);
}

module.exports = {
  effectivePlan,
  effectiveSubscriptionState,
  deriveSubscriptionState,
  isFounderEmail,
  GRACE_DAYS,
  GRACE_MS,
};
