// The Listing contract now lives in shared/listing.ts, alongside the
// filter/rank engine that operates on it — the API, the MCP tools and
// the bot all need the same shape, and a second definition would be
// the exact drift the shared core exists to prevent.
//
// Re-exported from the original path so every existing import in
// web/app keeps working unchanged.
export type {
  DiscoveryTag,
  Listing,
  Localized,
  MasterCategory,
  Subcategory,
} from "../../../shared/listing";
