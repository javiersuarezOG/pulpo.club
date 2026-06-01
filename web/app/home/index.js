// Barrel export for the homepage v2 shell + sections.
//
// The homepage shell (NewHomePage) composes its sections in the order
// specified by the block registry. As of Wave-6 (default-on hero_v5):
//   hero_v5 (absorbs hero + shoreline) → six type-specific Top 10
//   shelves (Beach × Land/Condos/Homes, then Lake same).
//
// Kill-switch (hero_v5 off): hero → featured (when hero_v4 off) →
// shoreline → same six shelves.
//
// The header is the shared SiteHeader mounted at the app level, not a
// homepage-only component.
//
// Phase 3 (May 2026): the single Top 10 / Price Drops / New This Week
// trio was replaced by the six type-specific shelves. NEW + PRICE-DROP
// signals migrated to per-card chips (CardSignalChip, PR #421).
//
// Wave-6 (June 2026): USPBand ("For subscribers only" 3-card band)
// eliminated. Its content lives on in the standalone UspPopup modal.
//
// Previous v1 components (Hero email form, ProofRow, CategoryGrid,
// DiscoveryPills, USPRow, ShelfRail) were retired in the v2 redesign.
// Their files have been removed; their event types remain in
// telemetry/events.ts for PostHog funnel-history continuity.
export { NewHomePage } from "./NewHomePage.jsx";
export { HeroV2 } from "./HeroV2.jsx";
export { HeroV4 } from "./HeroV4.jsx";
export { HeroV5 } from "./HeroV5.jsx";
export { FeaturedDeal } from "./FeaturedDeal.jsx";
export { PickShoreline } from "./PickShoreline.jsx";
export {
  TopBeachTerrenosShelf,
  TopBeachCondosShelf,
  TopBeachHomesShelf,
  TopLakeTerrenosShelf,
  TopLakeCondosShelf,
  TopLakeHomesShelf,
  HomeShelf,
} from "./HomeShelf.jsx";
