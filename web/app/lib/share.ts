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

// Build the full https://pulpo.club/l/<token> URL for a listing.
// Falls back to window.location.origin when window is defined (browser)
// so dev/preview environments produce links that point to themselves.
export function shareUrlFor(listingId: string): string {
  const token = encodeShareToken(listingId);
  const origin = typeof window !== "undefined" && window.location?.origin
    ? window.location.origin
    : "https://pulpo.club";
  return `${origin}/l/${token}`;
}
