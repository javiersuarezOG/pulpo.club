// shared/zones.ts — zone slug → human-readable name.
//
// Slugs come from `pulpo/normalize.py:ZONE_PATTERNS`. They are stable
// identifiers ("el-tunco"), not display strings, and every surface that
// shows one to a user needs the same mapping: the website's listing
// cards, `/api/v1/meta` (so a chat channel can label a zone button),
// and the MCP tools (so an LLM grounds on "El Tunco", not "el-tunco").
//
// This lives in shared/ rather than in the web adapter because a bot
// hardcoding its own copy of this table is precisely the drift the API
// layer exists to prevent.
//
// Note these names are intentionally NOT localized: they are proper
// place names ("Playa El Cuco", "Lago de Coatepeque") that read the same
// in EN and ES copy, which is why they never went through `t()` on the
// website either.

export const ZONE_NAMES: Record<string, string> = {
  "el-cuco": "Playa El Cuco",
  "las-flores": "Las Flores",
  "punta-mango": "Punta Mango",
  "el-espino": "El Espino",
  "el-tunco": "El Tunco",
  "el-sunzal": "El Sunzal",
  "el-zonte": "El Zonte",
  "san-diego": "San Diego (K59)",
  "mizata": "Mizata",
  "conchagua": "Conchagua",
  "jiquilisco": "Jiquilisco",
  "puerto-la-libertad": "Puerto La Libertad",
  "la-libertad": "La Libertad",
  "la-union": "La Unión",
  "lago-coatepeque": "Lago de Coatepeque",
  "lago-ilopango": "Lago de Ilopango",
  "costa-del-sol": "Costa del Sol",
};

/**
 * Look a slug up in `lookup`, falling back to a Title-Cased version of
 * the slug itself.
 *
 * The fallback matters: the pipeline mints zone slugs from broker text,
 * so the catalog always contains slugs this table has never seen. They
 * should render as "Playa Las Tunas", not as a raw slug and not as a
 * blank — the em dash is reserved for genuinely absent values.
 */
export function pretty(
  slug: string | null | undefined,
  lookup: Record<string, string>,
): string {
  if (!slug) return "—";
  if (lookup[slug]) return lookup[slug];
  return slug
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Display name for a zone slug. */
export function zoneName(slug: string | null | undefined): string {
  return pretty(slug, ZONE_NAMES);
}
