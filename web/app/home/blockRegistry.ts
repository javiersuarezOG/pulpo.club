// Wave-4: home-page block registry. Single source of truth for which
// homepage sections render for each user tier.
//
// Authoring order = render order. Adding a block: add a row + map the
// id to a Component in NewHomePage.jsx's lookup table.
//
// Why a registry rather than inline conditionals: when Wave-4 ships,
// paid users see ~half the blocks. Wave-5 may add or reorder blocks.
// Touching one file rather than chasing if-tier-then-render branches
// across NewHomePage keeps the surface tractable.
//
// Wave-4 semantics: anon + free see every block (today's behavior).
// Paid users skip upsell-oriented blocks (hero CTAs, featured deal,
// USP pitch). They get straight to the catalog carousels.

import { tierFor, type GatingUser, type Tier } from "../lib/gating";

// Block ids match the existing telemetry vocabulary:
//   * homepage.section_viewed.section enum (events.ts)
//   * ErrorBoundary `section` prop passed to PostHog captureException
// Keep them in sync so dashboards don't need a translation table.
export type BlockId =
  | "hero"
  | "featured"
  | "usps"
  | "shoreline"
  | "top_10"
  | "price_drops"
  | "new_this_week";

export type BlockEntry = {
  id: BlockId;
  // Tiers that see this block. A block hidden from a tier doesn't
  // mount at all — no DOM, no telemetry, no chance of an inadvertent
  // upsell click.
  visibleFor: readonly Tier[];
};

const ALL_TIERS: readonly Tier[] = ["anonymous", "free", "pro", "agency"];
const NON_PAID: readonly Tier[] = ["anonymous", "free"];

export const HOME_BLOCKS: readonly BlockEntry[] = [
  { id: "hero",          visibleFor: NON_PAID  }, // upsell-oriented
  { id: "featured",      visibleFor: NON_PAID  }, // upsell-oriented
  { id: "usps",          visibleFor: NON_PAID  }, // upsell-oriented
  { id: "shoreline",     visibleFor: ALL_TIERS },
  { id: "top_10",        visibleFor: ALL_TIERS },
  { id: "price_drops",   visibleFor: ALL_TIERS },
  { id: "new_this_week", visibleFor: ALL_TIERS },
];

// Resolve the rendered block list for the current user.
//
// `flagEnabled` controls whether the registry filters by tier at all.
// When false (Wave-4 ship default + rollback path), every tier sees
// every block — byte-for-byte identical to pre-Wave-4 behavior.
// When true, paid users get the upsell-free homepage.
export function visibleBlocksFor(
  user: GatingUser,
  flagEnabled: boolean,
): readonly BlockId[] {
  if (!flagEnabled) return HOME_BLOCKS.map((b) => b.id);
  const tier = tierFor(user);
  return HOME_BLOCKS.filter((b) => b.visibleFor.includes(tier)).map((b) => b.id);
}
