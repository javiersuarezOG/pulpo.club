// Static category imagery, keyed by SHELVES/PILLS `key`. Use `getCategoryImage(key)`
// for a curated tile photo; falls back to null when no curated asset exists.
// Source masters live in `/category_imgs/` at the repo root (gitignored — not
// committed). To re-export after editing a master, run from the repo root:
//
//   for f in category_imgs/*.png; do \
//     magick "$f" -resize '1200x>' -strip -quality 72 -define webp:method=6 \
//       "web/app/assets/categories/$(basename "${f%.png}").webp"; \
//   done
import agricultural from "./agricultural.webp";
import beachfront from "./beachfront.webp";
import best_documented from "./best_documented.webp";
import build_ready from "./build_ready.webp";
import commercial from "./commercial.webp";
import flat_buildable from "./flat_buildable.webp";
import motivated_sellers from "./motivated_sellers.webp";
import mountain_view from "./mountain_view.webp";
import new_this_week from "./new_this_week.webp";
import ocean_view from "./ocean_view.webp";
import off_market from "./off_market.webp";
import price_drops from "./price_drops.webp";
import under_100k from "./under_100k.webp";
import under_50k from "./under_50k.webp";
import water_features from "./water_features.webp";

export const CATEGORY_IMAGES = {
  agricultural,
  beachfront,
  best_documented,
  build_ready,
  commercial,
  flat_buildable,
  motivated_sellers,
  mountain_view,
  new_this_week,
  ocean_view,
  off_market,
  price_drops,
  under_100k,
  under_50k,
  water_features,
};

export function getCategoryImage(key) {
  return CATEGORY_IMAGES[key] || null;
}

// Deterministic visual fallback for a listing that has no usable photo
// (no URL, or onerror). Picks from the bundled category WebPs so the
// surface never renders a text-only placeholder. Priority chain:
//   master_category → land_type → beachfront_tier → has_*_view flags →
//   final fallback to `flat_buildable` (a neutral, photo-friendly land
//   shot).
export function categoryImageForListing(listing) {
  if (!listing) return CATEGORY_IMAGES.flat_buildable;
  if (listing.master_category === "beach") return CATEGORY_IMAGES.beachfront;
  if (listing.master_category === "lake")  return CATEGORY_IMAGES.water_features;
  if (listing.land_type === "agricultural") return CATEGORY_IMAGES.agricultural;
  if (listing.land_type === "commercial")   return CATEGORY_IMAGES.commercial;
  if (listing.beachfront_tier) return CATEGORY_IMAGES.beachfront;
  if (listing.has_ocean_view)  return CATEGORY_IMAGES.ocean_view;
  if (listing.has_mountain_view) return CATEGORY_IMAGES.mountain_view;
  if (listing.has_water_body)  return CATEGORY_IMAGES.water_features;
  return CATEGORY_IMAGES.flat_buildable;
}
