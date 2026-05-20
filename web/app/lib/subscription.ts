// Frontend twin of api/_plan.js's deriveSubscriptionState. Same
// derivation rules, so the Account-page banner and the SiteHeader Pro
// pill agree on whether a past_due user is still effectively Pro.
//
// Source of truth for the underlying fields is Clerk's publicMetadata,
// written by api/stripe/webhook.js on lifecycle events. The hydration
// path (web/app/auth/clerk-bundle.jsx) reads those fields and pushes
// them onto app.user so this helper can run client-side without an
// extra round trip.

export const GRACE_DAYS = 14;
export const GRACE_MS = GRACE_DAYS * 24 * 60 * 60 * 1000;

export type SubscriptionStatus = "active" | "past_due" | "canceled";

// What the frontend stamps onto `app.user` from Clerk publicMetadata.
// All fields optional so legacy users (before this PR) read as "active
// + no grace" and behave exactly as they did pre-grace.
export type UserSubscriptionFields = {
  plan?: "free" | "pro" | "agency" | null;
  subscription_status?: SubscriptionStatus | null;
  payment_failed_at?: number | null;
  grace_period_ends_at?: number | null;
};

export type SubscriptionState = {
  plan: "free" | "pro" | "agency";
  effective: "free" | "pro" | "agency";
  status: SubscriptionStatus;
  in_grace: boolean;
  grace_period_ends_at: number | null;
  payment_failed_at: number | null;
};

export function deriveSubscriptionState(
  user: UserSubscriptionFields | null | undefined,
  now?: number,
): SubscriptionState {
  const u = user || {};
  const rawPlan: SubscriptionState["plan"] =
    u.plan === "pro" || u.plan === "agency" ? u.plan : "free";
  const status: SubscriptionStatus =
    u.subscription_status === "past_due" || u.subscription_status === "canceled"
      ? u.subscription_status
      : "active";
  const graceEndsAt = typeof u.grace_period_ends_at === "number" ? u.grace_period_ends_at : null;
  const paymentFailedAt = typeof u.payment_failed_at === "number" ? u.payment_failed_at : null;
  const t = typeof now === "number" ? now : Date.now();
  const inGrace = status === "past_due" && graceEndsAt !== null && t < graceEndsAt;

  let effective: SubscriptionState["effective"];
  if (rawPlan === "agency") {
    effective = "agency";
  } else if (rawPlan === "pro") {
    if (status === "past_due" && graceEndsAt !== null && t >= graceEndsAt) {
      effective = "free";
    } else if (status === "canceled") {
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

// Days remaining in the grace window (rounded down). Returns 0 if no
// grace is in effect — the Account-page banner uses this to render
// "X days left" copy.
export function graceDaysLeft(
  user: UserSubscriptionFields | null | undefined,
  now?: number,
): number {
  const state = deriveSubscriptionState(user, now);
  if (!state.in_grace || state.grace_period_ends_at === null) return 0;
  const t = typeof now === "number" ? now : Date.now();
  const remainingMs = state.grace_period_ends_at - t;
  if (remainingMs <= 0) return 0;
  return Math.floor(remainingMs / (24 * 60 * 60 * 1000));
}
