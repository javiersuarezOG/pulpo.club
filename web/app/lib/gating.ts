// Single source of truth for "what can this user see?".
//
// Anything paywall-adjacent flows through here. Components should never
// read `app.user` directly to decide what to render — that's how we
// shipped the cap-mismatch bug where the listing detail capped USPs at
// 1 for anonymous users while the discover-page card showed 2. New
// gates: add a constant + a helper, then update consumers.
//
// `tier` is the canonical plan label. Stored on `app.user.plan` as one
// of "free" | "pro" | "agency" | undefined. Anonymous users have no
// `app.user`, so they map to the "anonymous" tier here.

export type Tier = "anonymous" | "free" | "pro" | "agency";

export type GatingUser = {
  plan?: string | null;
  // Explicit marker set ONLY by app.becomeFreeMember — an email-only Free
  // member (no Clerk account). Don't infer this from provider/plan: canceled
  // Pro users also read as plan:"free" and the test seeds use provider:"email".
  email_member?: boolean;
  provider?: string | null;
  // app.user has more fields (email, etc.) — we only need these here.
} | null | undefined;

export function tierFor(user: GatingUser): Tier {
  if (!user) return "anonymous";
  const plan = user.plan ?? "free";
  if (plan === "pro" || plan === "agency") return plan;
  return "free";
}

export function isPaid(user: GatingUser): boolean {
  const t = tierFor(user);
  return t === "pro" || t === "agency";
}

export function needsSignup(user: GatingUser): boolean {
  return tierFor(user) === "anonymous";
}

// Email-first Free model: a "free member" gave their email (no Clerk
// login) — `app.user = { provider:"email", plan:"free", email }`. They can
// open the top-3 in full; Pro-gated actions (rank 4+, saves) route them to
// the Go-Pro modal, while anonymous (no email yet) visitors route to the
// start-free email-capture modal. Pro/Clerk users are never "free members".
export function isFreeMember(user: GatingUser): boolean {
  return !!user && (user as { email_member?: boolean }).email_member === true && !isPaid(user);
}

// ── Per-surface caps ─────────────────────────────────────────────────
//
// One entry per gated thing. Each maps tier → numeric cap (or boolean
// for binary access). Components import the cap they need rather than
// re-deriving the rule each time.
//
// To gate something new: add a constant here, then have the rendering
// component call its helper. Don't sprinkle `if (!app.user)` checks.

const USPS_VISIBLE_BY_TIER: Record<Tier, number> = {
  // Anonymous teases 1; free gets 2 as a meaningful step up from
  // anonymous (otherwise signup is invisible value); paid sees all.
  // The detail panel renders an "upgrade to Pro to see N more"
  // prompt for free users when there are hidden USPs — see
  // pages.jsx where this cap is consumed.
  anonymous: 1,
  free:      2,
  pro:       Infinity,
  agency:    Infinity,
};

const GALLERY_THUMBS_UNLOCKED_BY_TIER: Record<Tier, number> = {
  // Indices 0..N-1 are unlocked. The detail panel renders thumbs[0..4];
  // anonymous + free see the first 2, paid see all 4 plus a "view all"
  // overflow tile.
  anonymous: 2,
  free:      2,
  pro:       Infinity,
  agency:    Infinity,
};

export function uspsVisibleFor(user: GatingUser): number {
  return USPS_VISIBLE_BY_TIER[tierFor(user)];
}

export function galleryThumbsUnlockedFor(user: GatingUser): number {
  return GALLERY_THUMBS_UNLOCKED_BY_TIER[tierFor(user)];
}

// Off-market source-URL access — paid only.
export function canSeeOffMarketSource(user: GatingUser): boolean {
  return isPaid(user);
}
