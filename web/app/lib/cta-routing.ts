// Wave-1 CTA routing — one place that decides what every revenue-blocking
// CTA does in each of the three user states. Built so that adding a
// fourth branch later (e.g. an enterprise tier) is one entry in the
// matrix below, not a refactor of seven files.
//
// Background:
//   * Pre-Wave-1 the homepage hero, Just In pill, FeaturedDeal,
//     HomepageHeader primary CTA, and NotifProUpsell all called
//     `app.openSignup({ mode: "signup" })` unconditionally — a paid
//     user clicking "Start free month" got a signup modal.
//   * Off-market detail pages overlaid a hard paywall covering the
//     entire body, blocking free users from seeing the soft-cap
//     teaser (USPs, distance pills, zone). Off-market should be LESS
//     scary to free users, not more — the more they see, the more they
//     want Pro.
//
// Two primitives:
//   * routeCtaForState(ctaId, user)  — pure decision; returns a Branch.
//   * dispatchCentralBranch(branch, app, locale, t) — fires the side
//     effect for the 4 branches that don't vary by CTA. Caller still
//     handles the "passthrough" branch (CTA-specific action) and
//     decides whether to call this at all.
//
// trackCtaRouted is the single funnel-debug event for the next year.
// Property shape is fixed once shipped — see events.ts.

import { tierFor, type GatingUser, type Tier } from "./gating";
import { track } from "../telemetry/hook";

// ── CTA call sites ────────────────────────────────────────────────────
//
// Every CTA that flows through the routing utility. Add a new entry
// here when wiring a new site; the matrix below requires a row for it.

export type CtaId =
  | "header_primary"        // HomepageHeader "Start free month" button
  | "hero_primary"          // HeroV2 primary CTA
  | "hero_just_in"          // HeroV2 Just In pill (rotating listing names)
  | "featured_deal"         // FeaturedDeal editorial card click
  | "newsletter_activation" // account.jsx NotifProUpsell upgrade button
  | "shelf_card"            // home shelf card click (passthrough always)
  | "broker_outbound"       // detail-page CTA bar broker link (passthrough for paid)
  | "favorites_action"      // heart icon on a card / "Save" button
  | "account_entry";        // nav avatar / "My account" entry point

// ── Branch enum ──────────────────────────────────────────────────────
//
// Six values. Original five locked at Wave-1; `free_month_modal` added
// post-Wave-5 when the anon-and-free conversion funnel consolidated on
// an in-page modal instead of a /start page redirect. Adding a seventh
// requires bumping the cta_routed event schema and updating any
// downstream PostHog insight that filters on this property.

export type Branch =
  | "stripe_checkout"  // Anon → /start (email + Stripe); free → startStripeCheckout()
  | "paywall"          // Free hitting a Pro-gated CTA → /plans (existing Pro pitch surface)
  | "free_signup"      // Anon hitting a save/share-style action → SignupModal mode=signup
  | "login_ui"         // Anon hitting Account area / authed-only feature → SignupModal mode=login
  | "free_month_modal" // Anon/free hitting a conversion CTA → FreeMonthModal (in-page Stripe upsell)
  | "passthrough";     // Caller handles (open listing, broker outbound, scroll, no-op)

// ── Routing matrix ───────────────────────────────────────────────────
//
// The spec. Rows = CTA, columns = tier. Reads top-to-bottom should
// match the Wave-1 plan table — keep them in sync.

// Post-Wave-5 update: anon + free rows for conversion-oriented CTAs
// (hero, header, just-in, featured, shelf cards, favorites) all route
// to `free_month_modal` instead of the previous page redirect (anon)
// or paywall / passthrough (free). Paid tier behavior is UNCHANGED.
// The new modal is the single conversion surface; the matrix is now
// the only place this fans out.
const MATRIX: Record<CtaId, Record<Tier, Branch>> = {
  header_primary: {
    anonymous: "free_month_modal",
    free:      "free_month_modal",
    pro:       "passthrough",
    agency:    "passthrough",
  },
  hero_primary: {
    anonymous: "free_month_modal",
    free:      "free_month_modal",
    pro:       "passthrough",
    agency:    "passthrough",
  },
  hero_just_in: {
    // Anon + free: opens the conversion modal. Paid users keep the
    // passthrough that opens the named listing (the pill names a real
    // listing — ignoring it for paid wastes the impression).
    anonymous: "free_month_modal",
    free:      "free_month_modal",
    pro:       "passthrough",
    agency:    "passthrough",
  },
  featured_deal: {
    // Anon + free: opens the conversion modal. Paid: passthrough →
    // caller opens the resolved listing (wave-5b).
    anonymous: "free_month_modal",
    free:      "free_month_modal",
    pro:       "passthrough",
    agency:    "passthrough",
  },
  newsletter_activation: {
    // The toggle only renders for paid users today (account.jsx gates
    // on isPaid). The "Upgrade" CTA shown to free/anon is the route here.
    // Anon: login_ui — the standard authed flow handles their post-login
    // landing. Free: paywall → /plans pitch. Paid: passthrough (UI never
    // surfaces this route for them, but the matrix is complete for
    // safety + analytics). NOT routed to free_month_modal — this CTA
    // is settings-page-only and the modal would be out of context.
    anonymous: "login_ui",
    free:      "paywall",
    pro:       "passthrough",
    agency:    "passthrough",
  },
  shelf_card: {
    // Anon + free: card click opens the conversion modal. Paid:
    // passthrough → caller opens the listing (or no-op for placeholder
    // editorial cards). The matrix's defensive paid passthrough is
    // unchanged from Wave-1.
    anonymous: "free_month_modal",
    free:      "free_month_modal",
    pro:       "passthrough",
    agency:    "passthrough",
  },
  broker_outbound: {
    // Paid-only outbound link. Free/anon never see this CTA — the
    // detail CTA bar shows the upgrade button instead. Matrix entries
    // for non-paid tiers are defensive; if a caller ever fires this
    // for a free user it'd be a paywall trigger. NOT routed to
    // free_month_modal — broker links are post-conversion behavior.
    anonymous: "paywall",
    free:      "paywall",
    pro:       "passthrough",
    agency:    "passthrough",
  },
  favorites_action: {
    // Anon + free save → conversion modal. Paid: toggle saves directly
    // (passthrough, existing behavior). Free users today have a free
    // saves quota; flipping to modal means clicking the heart kicks
    // them into upgrade rather than letting them save — intentional
    // funnel decision per the conversion plan.
    anonymous: "free_month_modal",
    free:      "free_month_modal",
    pro:       "passthrough",
    agency:    "passthrough",
  },
  account_entry: {
    // Anon clicking the profile nav → login modal. Signed-in users
    // navigate to /account (passthrough, existing route-gate). NOT
    // routed to free_month_modal — account navigation isn't a
    // conversion surface; sending an anon visitor to a paywall when
    // they tap "My account" would be hostile.
    anonymous: "login_ui",
    free:      "passthrough",
    pro:       "passthrough",
    agency:    "passthrough",
  },
};

// ── Pure decision function ────────────────────────────────────────────

export function routeCtaForState(ctaId: CtaId, user: GatingUser): Branch {
  return MATRIX[ctaId][tierFor(user)];
}

// ── Telemetry ─────────────────────────────────────────────────────────
//
// Fires cta_routed with the canonical property shape. Wraps the track()
// call in try/catch so a telemetry failure never blocks the dispatch.

export function trackCtaRouted(
  ctaId: CtaId,
  user: GatingUser,
  branch: Branch,
  flagEnabled: boolean,
): void {
  try {
    track("cta_routed", {
      cta_id: ctaId,
      user_state: tierFor(user),
      branch,
      flag_enabled: flagEnabled,
    });
  } catch {
    /* never crash a CTA on a telemetry failure */
  }
}

// ── Central dispatch ──────────────────────────────────────────────────
//
// Four of the five branches dispatch the same way regardless of which
// CTA fired (stripe_checkout / paywall / free_signup / login_ui).
// Passthrough is caller-specific; this returns false so the caller
// knows to handle it. Suppression-style no-ops are also passthrough —
// caller fires telemetry then returns.

export type FreeMonthModalTrigger =
  | "hero_cta"
  | "header_cta"
  | "usp_section"
  | "shelf_card"
  | "featured_deal"
  | "hero_just_in"
  | "favorites_action"
  | "browse_card";

export type AppLike = {
  user?: GatingUser;
  openSignup?: (cfg: { mode: "signup" | "login"; pendingAction?: string; pendingListing?: string }) => void;
  go?: (route: string) => void;
  showToast?: (msg: string) => void;
  // Conversion modal mount point. When `free_month_modal` is the routed
  // branch, dispatchCentralBranch calls this. Absent in unit tests that
  // exercise the matrix in isolation; the branch then silently no-ops
  // (caller-side test assertions inspect `branch` directly).
  openFreeMonthModal?: (cfg: { trigger: FreeMonthModalTrigger }) => void;
};

export type DispatchOptions = {
  // For stripe_checkout: optional onError forwarded to startStripeCheckout
  // when the user is signed-in (cookie-based path). Anon users redirect
  // to /start regardless.
  onCheckoutError?: (code: string) => void;
  // For free_signup: chain a post-signin action so the user lands on
  // the right destination (e.g. checkout for upsell CTAs).
  pendingAction?: string;
  pendingListing?: string;
  // For free_month_modal: identifies the call-site that fired the CTA.
  // Threaded into the modal's shown/dismissed/cta_clicked telemetry so
  // PostHog can slice conversion by entry point (hero vs USP vs shelf).
  trigger?: FreeMonthModalTrigger;
};

// Dispatch the central branches. Returns true if handled, false if the
// branch is "passthrough" (caller's responsibility). Imports are kept
// inline-async so this module is tree-shake-safe and dispatch can be
// called from non-React contexts without pulling React or the auth
// client into a unit test.
export async function dispatchCentralBranch(
  branch: Branch,
  app: AppLike,
  options: DispatchOptions = {},
): Promise<boolean> {
  switch (branch) {
    case "passthrough":
      return false;

    case "free_signup": {
      const cfg: { mode: "signup"; pendingAction?: string; pendingListing?: string } = { mode: "signup" };
      if (options.pendingAction) cfg.pendingAction = options.pendingAction;
      if (options.pendingListing) cfg.pendingListing = options.pendingListing;
      app.openSignup?.(cfg);
      return true;
    }

    case "free_month_modal": {
      // Post-Wave-5: the conversion modal replaces the page-redirect /
      // signup-modal anon paths. Trigger label is opt-in (defaults are
      // CTA-specific) so the modal's telemetry can attribute the source.
      const trigger: FreeMonthModalTrigger = options.trigger ?? "hero_cta";
      app.openFreeMonthModal?.({ trigger });
      return true;
    }

    case "login_ui":
      app.openSignup?.({ mode: "login" });
      return true;

    case "paywall":
      app.go?.("plans");
      return true;

    case "stripe_checkout": {
      const tier = tierFor(app.user);
      if (tier === "anonymous") {
        // Anonymous → /start, which collects email + handles Stripe
        // checkout in one flow. Forward the current URL's params so
        // UTMs and ?code= survive the redirect; /start's
        // useCampaignParams will pick them up and persist to
        // sessionStorage for the Stripe metadata.
        if (typeof window !== "undefined") {
          try {
            const params = new URLSearchParams(window.location.search);
            params.set("intent", "upgrade");
            window.location.assign(`/start?${params.toString()}`);
          } catch {
            window.location.assign("/start?intent=upgrade");
          }
        }
        return true;
      }
      // Signed-in (free) → existing helper. Dynamic import to keep
      // this module React-free and test-friendly.
      const { startStripeCheckout } = await import("../auth/stripe-checkout.js");
      await startStripeCheckout({
        onError: (code: string) => {
          if (options.onCheckoutError) {
            options.onCheckoutError(code);
            return;
          }
          // Default: bounce to /plans where the user can retry.
          app.go?.("plans");
        },
      });
      return true;
    }
  }
}
