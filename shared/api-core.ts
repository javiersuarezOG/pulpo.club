// shared/api-core.ts — the single entry point the serverless functions
// consume the shared core through.
//
// WHY THIS BARREL EXISTS
// Vercel compiles TypeScript functions only for files INSIDE api/.
// Anything a .ts function imports from outside that tree is never
// compiled into the bundle, so the function dies at load with
// FUNCTION_INVOCATION_FAILED. That is what took /api/v1/* and /api/mcp
// down on 2026-08-25; it is a boundary rule, not a TypeScript or
// module-format problem (a CommonJS `require()` across the same
// boundary works fine — see the probe table in docs/api-v1.md).
//
// So the functions no longer import shared/ directly. Instead:
//
//   api/v1/*.ts  --import-->  api/_core.js   (inside api/, so compiled)
//   api/_core.js --require->  shared/dist/api-core.cjs
//   shared/dist/api-core.cjs  <-- esbuild bundle of THIS file
//
// This file is the bundle's entry: everything the API and the MCP tools
// need, and nothing else. The website continues to import the shared
// sources directly and is unaffected — the CJS bundle is a compilation
// artifact, not a second copy of the logic.
//
// Adding a capability the API needs? Export it here, or the function
// cannot reach it.

export { API_VERSION } from "./version";
export type { ApiListEnvelope, ApiError } from "./version";

export { buildListingId, parseListingId, isListingId, ID_SEPARATOR } from "./listing-id";
export type { ListingIdParts } from "./listing-id";

export { ZONE_NAMES, pretty, zoneName } from "./zones";
export { decodeHtmlEntities } from "./decode-html";

export { adaptListing, detectListingLang } from "./adapt/listing";
export type { CountryRef } from "./adapt/listing";

export {
  WEIGHT_DEFAULTS,
  makeDefaultFilters,
  recomputeComposite,
  buildTopRankMap,
  applyFilters,
  applyRankCap,
} from "./engine/filters";

export {
  readFilterFromURL,
  readSortFromURL,
  readViewFromURL,
  hasFilterParamsInURL,
  FILTER_URL_KEYS,
  PRICE_HISTO_MAX,
} from "./engine/params";
export type { FilterShape } from "./engine/params";

export {
  tokenize,
  matchesQuery,
  matchesQueryString,
  scoreListing,
  buildSuggestions,
} from "./engine/search";
export type { Suggestion } from "./engine/search";

export type {
  Listing,
  Localized,
  MasterCategory,
  Subcategory,
  DiscoveryTag,
} from "./listing";
