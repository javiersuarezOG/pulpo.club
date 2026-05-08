// Typed event catalog. Adding an event = adding a row here. Components
// import from './hook' and call `track(name, payload)` — TypeScript
// rejects unknown event names + wrong payload shapes.
//
// Auto-segmented by PostHog (no code needed): country (IP), city,
// device_type, browser, os, referrer, utm_*. Read on the dashboard side
// in PostHog — don't duplicate them here.

export type AuthState = "anonymous" | "free" | "pro";

export type EventMap = {
  // ───── Acquisition ─────
  "landing.viewed": {
    route: string;
  };
  "consent.granted": { region?: string };
  "consent.declined": { region?: string };

  // ───── Discover ─────
  "hero.cta_clicked": { destination: "browse" | "see_listing" };
  "shelf.scrolled": { shelf_key: string; scroll_pct: number; items_visible: number };
  "shelf.see_all_clicked": { shelf_key: string };
  "style_carousel.tile_clicked": { style_key: string };

  // ───── Browse ─────
  "card.clicked": {
    listing_id: string;
    source_view: "discover" | "browse" | "saved";
    source_shelf?: string;
  };
  "browse.filter_changed": { filter_key: string; value: string | number | boolean | null; active_count: number };
  "browse.sort_changed": { sort: string };
  "browse.view_toggled": { view: "cards" | "table" };
  "browse.empty_results": { filters: Record<string, unknown> };
  // PR-4f — interactive PriceHistogram instrumentation
  "browse.price_histogram.dragged": {
    from_min: number;
    from_max: number | null;
    to_min: number;
    to_max: number | null;
  };
  "browse.price_histogram.bar_clicked": { bucket_min: number; bucket_max: number };
  "browse.price_histogram.reset": Record<string, never>;

  // ───── Detail / Saves / Auth ─────
  "detail.opened": { listing_id: string; auth_state: AuthState; plan?: "free" | "pro" };
  "detail.photo_lightbox_opened": { listing_id: string };
  "save.toggled": {
    listing_id: string;
    auth_state: AuthState;
    action: "add" | "remove";
  };
  "signup_modal.shown": {
    trigger: "heart" | "detail_view_count" | "manual" | "paywall";
  };
  "signup.completed": { provider: "email" | "google" | "apple" | "magic_link" };
  "paywall.shown": { kind: "detail_view" | "off_market" | "save_cap" };
  "paywall.bypassed": { kind: "detail_view" | "off_market" | "save_cap"; action: "upgrade" | "dismiss" };
  "plans.viewed": { source: "topnav" | "footer" | "paywall" | "manual" };
  "view_original.clicked": { listing_id: string; source_label: string };

  // ───── Upgrade flow (Stripe Checkout) ─────
  // Fires when the upgrade button is clicked and we kick off
  // /api/stripe/create-checkout-session. Pairs with the return-URL
  // event below to compute checkout completion rate.
  "upgrade.checkout_started": Record<string, never>;
  // Fires when the user lands back at /preview/?upgrade=success or
  // ?upgrade=cancelled after Stripe Checkout. The webhook (server-side)
  // is the source of truth for the actual plan flip; this event is
  // user-experience-only.
  "upgrade.checkout_returned": { result: "success" | "cancelled" };

  // ───── Manage subscription (Stripe Customer Portal) ─────
  // Fires when the Pro user clicks "Manage plan" on the Account page,
  // before we POST /api/stripe/billing-portal. Pairs with `portal.error`
  // to surface auth / config bugs that block the portal redirect.
  "portal.opened": Record<string, never>;
  "portal.error": { reason: string };

  // ───── Locale ─────
  "locale.changed": { from: string; to: string };

  // ───── System ─────
  "data.fetch.failed": { stage: string; error_class: string };
  "client.error": { message: string; stack?: string };

  // ───── Web Vitals ─────
  "web_vitals.lcp": { value: number; rating: "good" | "needs-improvement" | "poor"; route: string };
  "web_vitals.inp": { value: number; rating: "good" | "needs-improvement" | "poor"; route: string };
  "web_vitals.cls": { value: number; rating: "good" | "needs-improvement" | "poor"; route: string };
  "web_vitals.ttfb": { value: number; rating: "good" | "needs-improvement" | "poor"; route: string };

  // ───── Performance — app-specific (PR-photo-nav-perf) ─────
  // Broad UX perf signals beyond the standard Web Vitals. Each event
  // carries a `ms` field; PostHog dashboards aggregate by route +
  // device_type to surface the actual user perception bottlenecks.
  /** Click→render latency on the listing-card photo carousel arrows. */
  "card.photo_nav_latency": {
    listing_id: string;
    from_idx: number;
    to_idx: number;
    ms: number;
  };
  /** Wall-clock time to fetch + parse a JSON data file. Network-bound;
   *  high values flag CDN cache misses or large payloads. */
  "perf.data_fetch": {
    file: "ranked.json" | "last_updated.json" | "featured.json";
    ms: number;
    bytes: number | null;
    cache: "hit" | "miss" | "unknown";
  };
  /** Wall-clock time for filter recompute on Browse. High values =
   *  the filter pipeline got expensive (Sets/Arrays growing, debounce
   *  not landing). */
  "perf.filter_recompute": {
    ms: number;
    result_count: number;
    active_filters: number;
  };
  /** Card click → detail-panel rendered. */
  "perf.detail_open": { listing_id: string; ms: number };
  /** Lightbox open: gallery click → lightbox visible (image not yet loaded). */
  "perf.lightbox_open": { listing_id: string; ms: number };
  /** Route transition (Discover ↔ Browse ↔ Saved ↔ Plans ↔ Account). */
  "perf.route_transition": { from: string; to: string; ms: number };
};

export type EventName = keyof EventMap;
