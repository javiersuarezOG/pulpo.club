// Access-option registry — single source of truth for the three ways into
// Pulpo: ① Join free (email), ② Go Pro (Stripe), ③ Sign in (Clerk).
//
// Built for INDEPENDENCE (Javi, 2026-06-12): each option can be enabled,
// disabled, or reordered later — per surface — by editing this file ONLY,
// with no change to AccessBlock/AccessModal and no effect on the other
// options' flows. Each option's action is self-contained (see AccessBlock):
// free → Resend, pro → Stripe, sign_in → Clerk. Nothing downstream keys off
// which option was used — only off the resulting state (isFreeMember/isPaid).

export type AccessOptionId = "free_email" | "go_pro" | "sign_in";

// Where the access surface renders. Each surface picks its own ordered
// subset below, so e.g. a Free member who already gave their email never
// sees "Join free" again.
export type AccessSurface = "hero" | "gate_anon" | "gate_member" | "plans";

// Master enable switch per option. Flip one to false to remove it
// everywhere at once (or wire to a flag later). Disabling one never
// touches the others.
const ENABLED: Record<AccessOptionId, boolean> = {
  free_email: true,
  go_pro: true,
  sign_in: true,
};

// Ordered options per surface. Add / remove / reorder freely — this is the
// only edit needed to change a surface's funnel.
const SURFACES: Record<AccessSurface, AccessOptionId[]> = {
  hero: ["free_email", "go_pro", "sign_in"],
  gate_anon: ["free_email", "go_pro", "sign_in"],
  // Already a Free member: offer Pro, or sign in to an existing Pro account.
  gate_member: ["go_pro", "sign_in"],
  plans: ["free_email", "go_pro", "sign_in"],
};

// The enabled, ordered option ids a surface should render.
export function accessOptionsFor(surface: AccessSurface): AccessOptionId[] {
  return (SURFACES[surface] || []).filter((id) => ENABLED[id]);
}

export function isAccessOptionEnabled(id: AccessOptionId): boolean {
  return !!ENABLED[id];
}
