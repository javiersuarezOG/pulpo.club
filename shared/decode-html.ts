// Tiny HTML-entity decoder. The scrape pipeline preserves the raw
// description verbatim, which means HTML entities like &amp;aacute;
// (a doubly-encoded "á") survive into ranked.json. The detail panel
// reads `description` as plain text, so we decode + strip tags here.
//
// We don't pull in a full DOMParser — the entity set we encounter is
// small and well-known. Add to ENTITIES as new ones surface in
// production data.

const ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  aacute: "á",
  Aacute: "Á",
  eacute: "é",
  Eacute: "É",
  iacute: "í",
  Iacute: "Í",
  oacute: "ó",
  Oacute: "Ó",
  uacute: "ú",
  Uacute: "Ú",
  ntilde: "ñ",
  Ntilde: "Ñ",
  uuml: "ü",
  Uuml: "Ü",
  iexcl: "¡",
  iquest: "¿",
  ordm: "º",
  ordf: "ª",
  middot: "·",
  hellip: "…",
  ndash: "–",
  mdash: "—",
  lsquo: "'",
  rsquo: "'",
  ldquo: "“",
  rdquo: "”",
};

const TAG_RE = /<\/?[a-z][^>]*>/gi;
const ENTITY_RE = /&([a-zA-Z]+|#\d+);/g;

export function decodeHtmlEntities(input: string): string {
  if (!input) return "";
  // Decode entities (one pass; the scrape data is doubly-encoded so a
  // second pass mops up the stragglers).
  let s = input.replace(ENTITY_RE, (match, body) => {
    if (body.startsWith("#")) {
      const code = parseInt(body.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    return ENTITIES[body] ?? match;
  });
  s = s.replace(ENTITY_RE, (match, body) => {
    if (body.startsWith("#")) {
      const code = parseInt(body.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    return ENTITIES[body] ?? match;
  });
  // Strip raw HTML tags. Anything substantive in the description is
  // surfaced via title/usps/canonical-description anyway.
  s = s.replace(TAG_RE, " ");
  return s.replace(/\s+/g, " ").trim();
}
