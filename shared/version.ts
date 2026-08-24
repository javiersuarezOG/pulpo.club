// shared/version.ts — the v1 contract's identity and envelope.
//
// `shared/` is the channel-agnostic capability core. Everything in here
// must stay platform-neutral: no `fs`, no `process`, no `window`, no
// React. The website imports it in-process (Vite compiles it like any
// other module); the `/api/v1/*` serverless functions import the same
// files; future channel adapters (MCP, Telegram) do too. One source of
// logic, three consumers — that is the whole point of the layer.
//
// Node-only concerns (reading the catalog off disk) live on the API
// side and are typechecked by `tsconfig.api.json`, which is the only
// project that pulls in @types/node.

/**
 * Path segment AND payload marker for the current contract.
 *
 * Version policy: `v1` is frozen and additive-only. New fields and new
 * optional params are fine; renames, removals, and changes to the
 * meaning of an existing field are not — those get a `/api/v2`.
 */
export const API_VERSION = "v1";

/**
 * The envelope every v1 list endpoint returns.
 *
 * `generated_at` is the catalog's own timestamp (when the nightly
 * pipeline produced the data), not the time of this request — channels
 * show it as a freshness stamp, and it is `null` when the pipeline did
 * not stamp one rather than being faked with `now`.
 */
export interface ApiListEnvelope<T> {
  data: T[];
  total: number;
  limit: number;
  offset: number;
  generated_at: string | null;
  country: string;
}

/** Error body shape. Matches the repo-wide `{ error: "snake_case" }` convention. */
export interface ApiError {
  error: string;
}
