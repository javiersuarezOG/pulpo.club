// Hero photo pool for /start (and any future marketing surface that
// wants a "landscape-friendly Pulpo brand photo" without picking a
// specific listing).
//
// Reuses the existing curated category-image set under
// `web/app/assets/categories/` — these are the same WebP images the
// home page's "Find Your Style" carousel uses, already bundled by Vite
// at build time. No new asset commits needed.
//
// Subset: not every category image is landscape-friendly as a hero
// (some are tightly-cropped tile compositions). The HERO_POOL below is
// the hand-picked subset that works at the hero's 16:10 / 4:3 aspect
// ratios across viewports.

import { CATEGORY_IMAGES } from "../assets/categories";

// Order matters only for the deterministic rotation fallback below.
const HERO_KEYS = [
  "beachfront",
  "ocean_view",
  "mountain_view",
  "water_features",
  "flat_buildable",
  "build_ready",
  "agricultural",
] as const;

type HeroKey = (typeof HERO_KEYS)[number];

// Pick a hero photo. Default mode is `random`: a different image on
// each page mount, matching Pulpo's "fresh every visit" tone.
// `daily` rotates deterministically by day-of-year — useful if we ever
// want share-link previews to stay consistent within a 24h window.
export function pickHeroPhoto(
  mode: "random" | "daily" = "random"
): { url: string; key: HeroKey } {
  const available = HERO_KEYS.filter((k) => CATEGORY_IMAGES[k]);
  if (available.length === 0) {
    // Safety net — should never fire (build would have failed if the
    // imports broke). Falls through to the first key in the pool with
    // an undefined URL; the consumer's CSS gradient backdrop handles
    // the visual fallback.
    return { url: "", key: HERO_KEYS[0] };
  }
  let idx = 0;
  if (mode === "daily") {
    // Days since Jan 1, 2026 — deterministic per UTC day.
    const epoch = Date.UTC(2026, 0, 1);
    const days = Math.floor((Date.now() - epoch) / 86_400_000);
    idx = ((days % available.length) + available.length) % available.length;
  } else {
    idx = Math.floor(Math.random() * available.length);
  }
  const key = available[idx];
  return { url: CATEGORY_IMAGES[key], key };
}
