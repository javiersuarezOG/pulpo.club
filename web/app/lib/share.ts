// Source-opaque share tokens.
//
// A listing's internal id is `${source}__${source_id}` (e.g.
// `remax__001461165132`). Putting that in a public share URL leaks
// the broker — the user's hard rule is that the share surface never
// identifies the source. base64url-encoding the id produces an opaque
// token (`cmVtYXhfXzAwMTQ2MTE2NTEzMg`) that the SPA can decode
// client-side. It's deterministic so multiple shares of the same
// listing produce the same URL.
//
// This is NOT a privacy/security measure — anyone curious can
// base64-decode the token. It is brand protection: WhatsApp doesn't
// render the broker name in the link itself, and the share preview
// (PR #2) renders Pulpo branding only.
//
// The complementary slug-based scheme (`/l/lote-el-tunco-60k`) lands
// in PR #2 once we have `web/data/slug_lookup.json`. Tokens stay as
// the canonical machine-friendly form even after slugs exist — they
// keep working as a permanent fallback when a slug is missing.

const TOKEN_RE = /^[A-Za-z0-9_-]+$/;

function toBase64Url(s: string): string {
  // btoa handles latin1; listing ids are pure ASCII (alnum + underscores
  // + dots + dashes — see SAFE_LISTING_ID_RE in url-routing.ts) so we can
  // pass the string straight through.
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(token: string): string | null {
  if (!TOKEN_RE.test(token)) return null;
  try {
    const padded = token.replace(/-/g, "+").replace(/_/g, "/");
    return atob(padded);
  } catch {
    return null;
  }
}

export function encodeShareToken(id: string): string {
  return toBase64Url(id);
}

export function decodeShareToken(token: string): string | null {
  return fromBase64Url(token);
}

// Build the full https://pulpo.club/browse?pin=<token> share URL for a
// listing. This is the canonical share format per the share-pin PRD:
// recipients land on /browse with the listing pinned as the first card
// + (on desktop) the detail panel auto-opened, instead of dead-ending
// on /listing/<id>.
//
// Source-opacity (the hard rule from #457): the pin value is the
// base64url token, NOT the raw id — so the URL contains no broker name.
// Decoded client-side in BrowsePage via resolvePinFromParam.
//
// Backward compat: `/l/<token>` URLs already in the wild still work —
// parseLocation decodes the token, the app shell rewrites to
// /browse?pin=<token> at mount. resolvePinFromParam also accepts raw
// ids so hand-typed /browse?pin=remax__123 URLs degrade gracefully.
//
// Falls back to window.location.origin when window is defined (browser)
// so dev/preview environments produce links that point to themselves.
export function shareUrlFor(listingId: string): string {
  const token = encodeShareToken(listingId);
  const origin = typeof window !== "undefined" && window.location?.origin
    ? window.location.origin
    : "https://pulpo.club";
  return `${origin}/browse?pin=${token}`;
}

// Listing IDs in the catalog: alphanumerics, dashes, underscores, dots.
// Mirrors SAFE_LISTING_ID_RE in url-routing.ts. Reject anything that
// smells like a path traversal or has slashes before letting it become
// a key in BrowsePage / app shell state.
const SAFE_LISTING_ID_RE = /^[A-Za-z0-9._\-]+$/;

// Resolve a raw ?pin URL param into a listing id. Tries the
// base64url-token decode first (the canonical share format). Falls
// through to "raw id" interpretation so any URL of the form
// /browse?pin=<rawid> the user might paste in by hand still works.
// Returns null on garbage so the caller can silently no-op.
export function resolvePinFromParam(pinParam: string | null): string | null {
  if (!pinParam) return null;
  const decoded = decodeShareToken(pinParam);
  if (decoded && SAFE_LISTING_ID_RE.test(decoded)) return decoded;
  if (SAFE_LISTING_ID_RE.test(pinParam)) return pinParam;
  return null;
}
