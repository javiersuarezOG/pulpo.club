// Section-path ↔ React-state mapping. Single source of truth so app.jsx,
// the popstate listener, and the gate-evaluator all read the URL the same
// way. Listing detail is rendered as an overlay on top of a section, so
// `/listing/:id` parses to `{ route: <last section>, openListingId: <id> }`.

export type Route = "home" | "browse" | "saved" | "plans" | "account";

// /account has nested sub-section paths (`/account/profile`, etc.). The
// allow-list below is the only place the section keys live; AccountPage
// reads `routeParams.section` and the default tab when section is omitted
// is the FIRST entry.
export const ACCOUNT_SECTION_KEYS = [
  "profile",
  "notifications",
  "subscription",
  "security",
] as const;
export type AccountSection = typeof ACCOUNT_SECTION_KEYS[number];
const ACCOUNT_SECTION_SET = new Set<string>(ACCOUNT_SECTION_KEYS);

export type ParsedLocation = {
  route: Route;
  openListingId: string | null;
  // True when the pathname is `/listing/...` — the caller distinguishes
  // a cold-entry-on-detail (browser back must replaceState to "/", not
  // exit the site) from an in-app card click.
  isListingPath: boolean;
  // Sub-section for /account/<section>. `null` for /account (no segment)
  // OR an unknown section that failed the allow-list — both degrade to
  // the default tab downstream (first ACCOUNT_SECTION_KEYS entry).
  section: AccountSection | null;
};

const SECTION_PATHS: Record<string, Route> = {
  "/":         "home",
  "/browse":   "browse",
  "/saved":    "saved",
  "/plans":    "plans",
  "/account":  "account",
};

const LISTING_PREFIX = "/listing/";
const ACCOUNT_PREFIX = "/account/";

// Listing IDs in the catalog look like `idealista-12345` — alphanumerics,
// dashes, underscores, dots. Reject anything that smells like a path
// traversal or a slash-bearing ID so a malformed URL never reaches React
// state.
const SAFE_LISTING_ID_RE = /^[A-Za-z0-9._\-]+$/;

export function parseLocation(pathname: string, fallbackRoute: Route = "home"): ParsedLocation {
  // Trailing-slash tolerance for sections; "/browse/" → "/browse".
  const normalized = pathname.length > 1 && pathname.endsWith("/")
    ? pathname.slice(0, -1)
    : pathname;

  if (normalized in SECTION_PATHS) {
    return { route: SECTION_PATHS[normalized], openListingId: null, isListingPath: false, section: null };
  }

  // `/account/<section>` — single-segment sub-paths only. Unknown sections
  // silently degrade to /account (route=account, section=null). We don't
  // 404 here because the catch-all Vercel rewrite already lands SPA, and
  // a hand-typed `/account/foo` should land somewhere usable.
  if (normalized.startsWith(ACCOUNT_PREFIX)) {
    const rest = normalized.slice(ACCOUNT_PREFIX.length);
    // Reject nested paths (`/account/foo/bar`) — only single-segment sub-
    // sections are valid. The router doesn't model anything deeper.
    if (rest && !rest.includes("/")) {
      const section = ACCOUNT_SECTION_SET.has(rest) ? (rest as AccountSection) : null;
      return { route: "account", openListingId: null, isListingPath: false, section };
    }
    return { route: "account", openListingId: null, isListingPath: false, section: null };
  }

  if (normalized.startsWith(LISTING_PREFIX)) {
    const raw = normalized.slice(LISTING_PREFIX.length);
    let id: string | null = null;
    try {
      const decoded = decodeURIComponent(raw);
      if (SAFE_LISTING_ID_RE.test(decoded)) id = decoded;
    } catch {
      // Malformed encoding — treat as no listing.
    }
    return { route: fallbackRoute, openListingId: id, isListingPath: true, section: null };
  }

  // Unknown path — Vercel rewrites everything to the SPA, so we just
  // fall back to home. (This also covers `/preview` once the rewrites
  // are dropped — Vercel's 404 fires before the SPA boots.)
  return { route: "home", openListingId: null, isListingPath: false, section: null };
}

export function pathForRoute(route: Route, section?: AccountSection | null): string {
  switch (route) {
    case "home":    return "/";
    case "browse":  return "/browse";
    case "saved":   return "/saved";
    case "plans":   return "/plans";
    case "account": return section ? `/account/${section}` : "/account";
  }
}

export function pathForListing(listingId: string): string {
  const encoded = encodeURIComponent(listingId);
  if (encoded.includes("/")) {
    // Should never happen — encodeURIComponent escapes `/` to `%2F`. If
    // a listing id slips through containing a literal `/` somehow, we'd
    // break the Vercel `/listing/:id` single-segment rewrite. Fall back
    // to the home path so we never produce a broken URL.
    return "/";
  }
  return `${LISTING_PREFIX}${encoded}`;
}

// Build the full URL string for `pushState` — preserves the query string
// from the current location for sections that use one (Browse), and
// drops it for sections that don't.
export function urlFor(
  args: { route?: Route; listingId?: string | null; section?: AccountSection | null },
  currentSearch: string = ""
): string {
  if (args.listingId) {
    return `${pathForListing(args.listingId)}${currentSearch}`;
  }
  const route = args.route ?? "home";
  const path = pathForRoute(route, route === "account" ? (args.section ?? null) : null);
  // Browse keeps its filter query string. Other sections clear it so we
  // don't accumulate stale `?cat=…` on `/saved` etc.
  const search = route === "browse" ? currentSearch : "";
  return `${path}${search}`;
}

// True when going to (route, listingId) wouldn't change the URL — used by
// `go()` to skip duplicate history entries.
export function isSameLocation(
  args: { route?: Route; listingId?: string | null; section?: AccountSection | null },
  currentPath: string,
  currentSearch: string = ""
): boolean {
  const target = urlFor(args, currentSearch);
  return target === `${currentPath}${currentSearch}`;
}
