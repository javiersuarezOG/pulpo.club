// Wave-4: home-page block registry. Single source of truth for which
// homepage sections render for each user tier.
//
// Authoring order in the VISIBILITY matrix = render order. Adding a
// block: append a row to the matrix + map the id to a Component in
// NewHomePage.jsx's lookup table.
//
// Why a registry rather than inline conditionals: paid users see
// ~half the blocks; adding/reordering blocks should touch one file
// rather than chasing if-tier-then-render branches across NewHomePage.

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

// ╭───────────────────────────────────────────────────────────────────╮
// │ HOME PAGE BLOCK VISIBILITY MATRIX                                  │
// │                                                                    │
// │ Edit a cell to change who sees what. No other code needs to        │
// │ change. Each row = a block. Each column = a user tier.             │
// │                                                                    │
// │ Authoring order = render order — drag a row to reorder visually.   │
// ╰───────────────────────────────────────────────────────────────────╯
const VISIBILITY: Record<BlockId, Record<Tier, boolean>> = {
  // block          anon    free    pro     agency
  hero:          { anonymous: true,  free: true,  pro: true,  agency: true  }, // CTA gated in component for paid
  featured:      { anonymous: true,  free: true,  pro: false, agency: false },
  usps:          { anonymous: true,  free: true,  pro: false, agency: false },
  shoreline:     { anonymous: true,  free: true,  pro: false, agency: false }, // post-Wave-5: upsell surface, hidden from paid
  top_10:        { anonymous: true,  free: true,  pro: true,  agency: true  },
  price_drops:   { anonymous: true,  free: true,  pro: true,  agency: true  },
  new_this_week: { anonymous: true,  free: true,  pro: true,  agency: true  },
};

// Render order — authoring order in the matrix is the rendered order.
// Keep this in sync with VISIBILITY's key order.
const BLOCK_ORDER: readonly BlockId[] = [
  "hero",
  "featured",
  "usps",
  "shoreline",
  "top_10",
  "price_drops",
  "new_this_week",
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

// Per-block dev override. When set, forces a block on or off for the
// current user regardless of tier/flag rules. Persisted in
// localStorage by the dev tweaks panel (see tweaks-panel.jsx).
// Production traffic never sees overrides — they're a dev preview tool.
export type BlockOverride = "auto" | "force_show" | "force_hide";

export function readBlockOverrides(): Partial<Record<BlockId, BlockOverride>> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem("pulpo-block-overrides");
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return parsed as Partial<Record<BlockId, BlockOverride>>;
  } catch {
    return {};
  }
}

// Resolve the rendered block list for the current user.
//
// The flag map governs which filters apply. When `paid_home_variant_v1`
// is off, every tier sees every block (legacy behavior). When on, the
// VISIBILITY matrix governs. The other flags layer additional cuts:
//   * usp_popup_v1 → `usps` is excluded for every tier
//   * hero_v4      → `featured` is excluded (absorbed into hero)
// Per-block localStorage overrides win above everything (dev preview).
export function visibleBlocksFor(
  user: GatingUser,
  flags: RegistryFlags,
): readonly BlockId[] {
  const tier = tierFor(user);
  const overrides = readBlockOverrides();

  return BLOCK_ORDER.filter((blockId) => {
    const override = overrides[blockId];
    if (override === "force_show") return true;
    if (override === "force_hide") return false;

    // Tier visibility. When the paid-home flag is off, every block is
    // visible to every tier — matches pre-Wave-4 behavior.
    if (flags.paid_home_variant_v1) {
      if (!VISIBILITY[blockId][tier]) return false;
    }
    // Wave 5 flag-driven exclusions, applied after tier filtering.
    if (flags.usp_popup_v1 && blockId === "usps") return false;
    if (flags.hero_v4 && blockId === "featured") return false;
    return true;
  });
}
