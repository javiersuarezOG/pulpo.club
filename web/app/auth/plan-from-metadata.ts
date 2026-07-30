// Pure mapper: Clerk publicMetadata.plan → client plan tier.
//
// Extracted from clerk-bundle.jsx (which imports the Clerk SDK at module
// level) so this can be unit-tested in isolation. This is the ONE spot that
// maps the Clerk-ON production path, which CI never exercises — CI seeds the
// plan via localStorage with Clerk OFF. An earlier inline version returned
// `v === "pro" ? "pro" : "free"`, silently collapsing `agency → free` and
// reinstating the €4.99 upsell for agency users even though isPaid() /
// deriveSubscriptionState / tierFor all cover agency downstream. BOTH paid
// tiers must survive here or every paid gate is defeated for agency.

export type PlanTier = "free" | "pro" | "agency";

export function planFromMetadata(metadata: { plan?: unknown } | null | undefined): PlanTier {
  const v = metadata && (metadata as { plan?: unknown }).plan;
  return v === "pro" || v === "agency" ? v : "free";
}
