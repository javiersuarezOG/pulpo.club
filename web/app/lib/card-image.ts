// Single frontend source of truth for the display-gate contract (plan
// 003, owner rule 2026-06-12): an image that's just text — a flyer,
// logo, or render — must NEVER be shown on ANY surface. Inventory
// surfaces (Browse/Discover grid, Saved, map cards) keep the listing
// findable but swap a non-eligible image for the bundled category
// fallback illustration; curated surfaces (home shelves, featured
// pools, newsletter picks) drop the listing entirely.
//
// This predicate mirrors the Python `pulpo/display_gates.py`
// `is_card_displayable` consumer used by the newsletter + featured
// pools, and the same `listing.card_eligible === true &&
// listing.has_text_overlay !== true` check `listingForSuggestionThumb`
// applies to autocomplete thumbs in pages.jsx.
//
// `card_eligible` is the photo phase's verdict (≥800×600 AND not a
// logo/placeholder); `has_text_overlay` is the positive OCR flag for
// branded/flyer images. A null/missing `card_eligible` means the photo
// phase never approved a card image — treated as NOT displayable by
// design (that IS the hard rule).

export function isCardImageDisplayable(listing: {
  card_eligible?: boolean | null;
  has_text_overlay?: boolean | null;
} | null | undefined): boolean {
  if (!listing) return false;
  return listing.card_eligible === true && listing.has_text_overlay !== true;
}
