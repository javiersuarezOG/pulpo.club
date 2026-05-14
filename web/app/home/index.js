// Barrel export for the homepage v2 shell + sections.
//
// The homepage v2 shell (NewHomePage) composes the sections in the
// order specified by the design spec: hero → featured → USP band →
// pick shoreline → top 10 → price drops → new this week. The header
// is now the shared SiteHeader (mounted at the app level), not a
// homepage-only component.
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
export { TopTenShelf, PriceDropsShelf, NewThisWeekShelf, HomeShelf } from "./HomeShelf.jsx";
