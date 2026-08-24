// The matcher moved to shared/engine/search.ts so /api/v1, the MCP
// tools and the Telegram bot resolve a query exactly the way /browse
// does. Re-exported from the original path so every call site and the
// existing test suite keep their imports.
export {
  buildSuggestions,
  matchesQuery,
  matchesQueryString,
  scoreListing,
  tokenize,
} from "../../../shared/engine/search";
export type { Suggestion } from "../../../shared/engine/search";
