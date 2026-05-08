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
