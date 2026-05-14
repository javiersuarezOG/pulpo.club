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

// Flag map controlling the registry's filter behavior. Each wave adds
// its own flag here so the consumer can read both without breaking
// older call sites.
export type RegistryFlags = {
  // Wave 4: filter by tier (paid users skip upsell blocks).
  paid_home_variant_v1: boolean;
  // Wave 5#8: remove the usps block from the homepage (it migrates to
  // a triggered popup mounted at the page root).
  usp_popup_v1: boolean;
  // Wave 5#7+#9: white photo-led hero. The new hero "owns" the
  // featured listing visually, so the standalone `featured` block is
  // suppressed when the flag is on.
  hero_v4: boolean;
};

// Resolve the rendered block list for the current user.
//
// The flag map governs which filters apply. When every flag is off the
// returned list is HOME_BLOCKS in author order — byte-for-byte
// equivalent to pre-Wave-4 behavior. Filters compose:
//   * paid_home_variant_v1 → paid users see only ALL_TIERS blocks
//   * usp_popup_v1         → `usps` is excluded for every tier
//   * hero_v4              → `featured` is excluded (absorbed into hero)
export function visibleBlocksFor(
  user: GatingUser,
  flags: RegistryFlags,
): readonly BlockId[] {
  let blocks: readonly BlockEntry[] = HOME_BLOCKS;
  if (flags.paid_home_variant_v1) {
    const tier = tierFor(user);
    blocks = blocks.filter((b) => b.visibleFor.includes(tier));
  }
  if (flags.usp_popup_v1) {
    blocks = blocks.filter((b) => b.id !== "usps");
  }
  if (flags.hero_v4) {
    blocks = blocks.filter((b) => b.id !== "featured");
  }
  return blocks.map((b) => b.id);
}
