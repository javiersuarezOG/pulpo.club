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
};

export type EventName = keyof EventMap;
