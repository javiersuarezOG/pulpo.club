// Barrel export for the homepage v2 shell + sections.
//
// The homepage shell (NewHomePage) composes its sections in the order
// specified by the block registry: hero → featured → USP band → pick
// shoreline → six type-specific Top 10 shelves (Beach × Land/Condos/
// Homes, then Lake same). The header is now the shared SiteHeader
// (mounted at the app level), not a homepage-only component.
//
// Phase 3 (May 2026): the single Top 10 / Price Drops / New This Week
// trio was replaced by the six type-specific shelves. NEW + PRICE-DROP
// signals migrated to per-card chips (CardSignalChip, PR #421).
//
// Previous v1 components (Hero email form, ProofRow, CategoryGrid,
// DiscoveryPills, USPRow, ShelfRail) were retired in the v2 redesign.
// Their files have been removed; their event types remain in
// telemetry/events.ts for PostHog funnel-history continuity.
export { NewHomePage } from "./NewHomePage.jsx";
export { HeroV2 } from "./HeroV2.jsx";
export { FeaturedDeal } from "./FeaturedDeal.jsx";
export { USPBand } from "./USPBand.jsx";
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
