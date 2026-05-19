// Per-path auth/paid gating. Layered on top of `gating.ts` (the canonical
// "what tier is this user" hub) so the URL layer maps *paths* to
// *minimum tiers* without re-deriving tier rules.
//
// Adding a new route: add an entry below + the path constant in
// url-routing.ts. Don't sprinkle `if (!user)` checks in components — the
// router enforces gates uniformly on mount + every popstate.

import { tierFor, type GatingUser, type Tier } from "./gating";
import type { Route } from "./url-routing";

export type GateOutcome =
  | { kind: "allow" }
  // Render the section path normally, open SignupModal as an overlay.
  // The URL stays put so post-signin the content slot is already
  // correct (no redirect chain).
  | { kind: "modal"; minTier: Tier; postLoginRoute: Route };

type RouteGate = {
  minTier: Tier;
  // Currently the only mode in use; `redirect` and `inline_paywall`
  // are reserved for future routes if we need them.
  onDenied: "modal";
};

const ROUTE_GATES: Record<Route, RouteGate> = {
  // Public surfaces — anyone can render them.
  home:    { minTier: "anonymous", onDenied: "modal" },
  browse:  { minTier: "anonymous", onDenied: "modal" },
  plans:   { minTier: "anonymous", onDenied: "modal" },
  // Listing detail (overlay or future full page) is public for the
  // teaser; deeper paywalls (off-market price, full gallery, source
  // link) gate inside the render via `gating.ts` helpers — never per
  // URL, because the URL doesn't know which listings are off-market.
  // No entry needed — listing detail isn't a Route, it's an overlay.

  // Auth-required surfaces. `free` tier passes; `anonymous` triggers
  // the sign-in modal.
  saved:   { minTier: "free", onDenied: "modal" },
  account: { minTier: "free", onDenied: "modal" },
};

const TIER_RANK: Record<Tier, number> = {
  anonymous: 0,
  free:      1,
  pro:       2,
  agency:    2,
};

function meetsTier(user: GatingUser, minTier: Tier): boolean {
  return TIER_RANK[tierFor(user)] >= TIER_RANK[minTier];
}

// Evaluate a route against the current user. Returns `allow` when the
// user has sufficient tier, otherwise the gate's denial mode + the
// route to land on after the gate is satisfied.
//
// `searchParams` allows per-route bypasses. Currently used by /account
// — when `?welcome=1` is on the URL the user has just completed Stripe
// Checkout but doesn't have a Clerk session yet. We let them render the
// page in a "logged-out preview" state with the <WelcomeModal> overlay,
// instead of bouncing them to the SignupModal which would hide the
// fact they just paid.
export function evaluateGate(
  route: Route,
  user: GatingUser,
  searchParams?: URLSearchParams,
): GateOutcome {
  const gate = ROUTE_GATES[route];
  if (meetsTier(user, gate.minTier)) {
    return { kind: "allow" };
  }
  // Welcome bypass — only for /account, only when the post-Stripe
  // (or post-Clerk-magic-link) `?welcome=1` flag is present. The page
  // renders in logged-out-preview mode; the WelcomeModal handles the
  // sign-in nudge. This is the ONLY route that opts into this bypass.
  //
  // Defense in depth: the load-bearing bypass is now a
  // `welcomeModalState` short-circuit in app.jsx's gate effect — the
  // searchParams check here would otherwise lose the race against the
  // welcome-effect URL strip (the gate effect runs after the strip
  // in the same render-commit pass). Keeping this check covers the
  // legacy CI path where Clerk is off and the same-tick effect
  // ordering still applies, plus any future caller that doesn't go
  // through app.jsx.
  if (route === "account" && searchParams && searchParams.get("welcome") === "1") {
    return { kind: "allow" };
  }
  return { kind: "modal", minTier: gate.minTier, postLoginRoute: route };
}
