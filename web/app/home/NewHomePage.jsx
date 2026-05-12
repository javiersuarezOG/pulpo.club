// Rewritten homepage shell — composes the five Phase 4B components
// in the section order specified by the rewrite brief:
//
//   1. Hero            — copy-led + email form
//   2. ProofRow        — "This week's top 3 deals"
//   3. CategoryGrid    — Beach × {homes,condos,land} + Lake × same
//   4. DiscoveryPills  — All / ★ Top rated / Under $250K / Gated / Waterfront
//   5. USPRow          — 3-column "Why Pulpo"
//
// Rendered by app.jsx when VITE_NEW_HOMEPAGE=1 (see the flag check
// there); otherwise the legacy HomePage in pages.jsx renders. The
// shell itself owns NO state — every component reads from useListings()
// / loadFeaturedJson() / app context independently. This keeps the
// shell trivial to swap during the rollout.
//
// The full Discover-shelves stack is intentionally NOT rendered here.
// Per the rewrite plan Q6, shelves moved to the BrowsePage (Phase 5).
// Keeping the homepage tight: hero + proof + category + pills + USPs
// is enough surface for cold-visitor conversion; warm visitors who
// want shelves click through to /browse.
import React from "react";
import { Hero, ProofRow, CategoryGrid, DiscoveryPills, USPRow } from "./index.js";
import { ShelfRail } from "./ShelfRail.jsx";

/**
 * @param {object} props
 * @param {object} props.app  — App state with goBrowse(...) + openListing(...)
 */
export function NewHomePage({ app }) {
  const locale = app.locale;
  return (
    <div className="new-homepage">
      <Hero locale={locale} />
      <ProofRow app={app} locale={locale} />
      <CategoryGrid app={app} locale={locale} />
      <DiscoveryPills app={app} locale={locale} sourcePage="homepage" />
      <USPRow locale={locale} />
      {/* Activity shelves — 2 in the reduced config: new_this_week +
          price_drops. ShelfRail self-hides empty shelves + the whole
          rail when nothing qualifies, so a thin catalog won't render
          a broken section. */}
      <ShelfRail app={app} locale={locale} />
    </div>
  );
}
