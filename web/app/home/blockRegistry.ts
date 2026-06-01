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
  // Wave-6: editorial "Sunday morning, coffee, your top 10 properties"
  // hero. Absorbs both the legacy `hero` block AND the `shoreline`
  // block (its 5 destination cards include All listings + 4 regions),
  // so when hero_v5 is on the registry suppresses those two slots.
  | "hero_v5"
  | "featured"
  // `usps` (the in-page USPBand "For subscribers only" 3-card band)
  // was eliminated in Wave-6 — content moved to the standalone
  // UspPopup modal. Do NOT re-add here without restoring USPBand.jsx.
  | "shoreline"
  // Phase 3 — six type-specific Top 10 shelves replacing the single
  // top_10 / price_drops / new_this_week trio. NEW + PRICE-DROP signals
  // now ride on per-card chips (PR #421). Beach-first, by type
  // ascending (terrenos → condos → homes).
  | "top_beach_terrenos"
  | "top_beach_condos"
  | "top_beach_homes"
  | "top_lake_terrenos"
  | "top_lake_condos"
  | "top_lake_homes";

// ╭───────────────────────────────────────────────────────────────────╮
// │ HOME PAGE BLOCK VISIBILITY MATRIX                                  │
// │                                                                    │
// │ Edit a cell to change who sees what. No other code needs to        │
// │ change. Each row = a block. Each column = a user tier.             │
// │                                                                    │
// │ Authoring order = render order — drag a row to reorder visually.   │
// ╰───────────────────────────────────────────────────────────────────╯
const VISIBILITY: Record<BlockId, Record<Tier, boolean>> = {
  // block               anon    free    pro     agency
  hero:               { anonymous: true,  free: true,  pro: true,  agency: true  }, // CTA gated in component for paid
  hero_v5:            { anonymous: true,  free: true,  pro: true,  agency: true  }, // Wave-6: replaces hero + shoreline when flag on
  featured:           { anonymous: true,  free: true,  pro: false, agency: false },
  shoreline:          { anonymous: true,  free: true,  pro: false, agency: false }, // post-Wave-5: upsell surface, hidden from paid
  // Phase 3: each shelf renders only when ≥5 listings qualify (the
  // hero_v4 hideShelf gate inside HomeShelf). Visible to every tier.
  top_beach_terrenos: { anonymous: true,  free: true,  pro: true,  agency: true  },
  top_beach_condos:   { anonymous: true,  free: true,  pro: true,  agency: true  },
  top_beach_homes:    { anonymous: true,  free: true,  pro: true,  agency: true  },
  top_lake_terrenos:  { anonymous: true,  free: true,  pro: true,  agency: true  },
  top_lake_condos:    { anonymous: true,  free: true,  pro: true,  agency: true  },
  top_lake_homes:     { anonymous: true,  free: true,  pro: true,  agency: true  },
};

// Render order — authoring order in the matrix is the rendered order.
// Keep this in sync with VISIBILITY's key order. Phase 3 puts the
// Beach × types first (Beach is the volume category — terrenos/condos/
// homes ascending by entry price), then Lake.
// Exported so the versions ↔ registry sync test can iterate it; also
// useful for any future tooling that needs the canonical block list.
export const BLOCK_ORDER: readonly BlockId[] = [
  "hero",
  "hero_v5",
  "featured",
  "shoreline",
  "top_beach_terrenos",
  "top_beach_condos",
  "top_beach_homes",
  "top_lake_terrenos",
  "top_lake_condos",
  "top_lake_homes",
];

// Flag map controlling the registry's filter behavior. Each wave adds
// its own flag here so the consumer can read both without breaking
// older call sites.
export type RegistryFlags = {
  // Wave 4: filter by tier (paid users skip upsell blocks).
  paid_home_variant_v1: boolean;
  // Wave 5#8 → Wave 6: the in-page USPBand was eliminated; this flag
  // now only controls whether the standalone UspPopup modal arms its
  // scroll / exit-intent triggers. Kept on RegistryFlags for shape
  // stability; the registry no longer filters on it.
  usp_popup_v1: boolean;
  // Wave 5#7+#9: white photo-led hero. The new hero "owns" the
  // featured listing visually, so the standalone `featured` block is
  // suppressed when the flag is on.
  hero_v4: boolean;
  // Wave 6: editorial "Sunday morning, coffee, your top 10 properties"
  // hero with a postcard preview + 5 destination cards. When on, this
  // suppresses BOTH the legacy `hero` block AND `shoreline` (the
  // destination cards include All listings + the 4 regions that
  // PickShoreline used to surface).
  hero_v5: boolean;
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
    if (flags.hero_v4 && blockId === "featured") return false;
    // Wave 6: hero_v5 replaces both the legacy hero AND shoreline.
    // When the flag is on:
    //   * hero_v5 is the rendered hero
    //   * hero is suppressed (legacy v2/v4 hero would double up)
    //   * shoreline is suppressed (the 5 destination cards absorb it)
    // When the flag is off, hero_v5 itself is suppressed.
    // `usps` was eliminated entirely in Wave 6 (USPBand.jsx deleted);
    // no filtering needed — there's no block to filter.
    if (flags.hero_v5) {
      if (blockId === "hero") return false;
      if (blockId === "shoreline") return false;
    } else {
      if (blockId === "hero_v5") return false;
    }
    return true;
  });
}
