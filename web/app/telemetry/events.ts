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
  // hero.cta_clicked: legacy Hero CTA — now fires from NewHomePage's
  // Hero email form via the "newsletter_signup" destination value.
  // The original "browse" / "see_listing" destinations are retained
  // in the union for backward compatibility with any in-flight
  // PostHog funnels that filter on them; new code uses the email
  // path.
  "hero.cta_clicked": { destination: "browse" | "see_listing" | "newsletter_signup" };
  "shelf.see_all_clicked": { shelf_key: string };
  // Phase 9 cutover: shelf.scrolled (defined but never fired since
  // the catalog landed), style_carousel.tile_clicked (UI deleted with
  // the legacy HomePage), and newsletter.cta_clicked (replaced by
  // hero.email_submitted in #223) have been removed from the type
  // catalog. PostHog historical data is unaffected — it still
  // accepts ANY event name; the type removal just prevents new code
  // from referencing the retired events.

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
  // Pagination control on Browse — fires when the user clicks
  // "Load N more". `from`/`to` are the visibleCount before/after the
  // click; `total` is the total filtered result count so we can tell
  // a page-2 load apart from page-N.
  "browse.load_more_clicked": { from: number; to: number; total: number };

  // ───── New homepage (rewrite Phase 4) ─────
  // Email form on the rewritten hero. Phase 6 wires the actual
  // /api/newsletter endpoint; the event fires regardless so we can
  // see submit-rate trends before the backend lands. PII rule (per
  // the rewrite plan §10e): NEVER send the raw email — only the
  // domain after @. result ∈ submit-outcomes; validation_failed
  // fires on client-side regex failure before any network call.
  "hero.email_submitted": {
    source: "homepage_hero";
    email_domain_only: string;
    result: "success" | "error" | "validation_failed" | "already_subscribed" | "rate_limited";
  };
  // Proof-row card surfaces. Impression fires when a card enters the
  // viewport (IntersectionObserver, debounced 500ms, once per page-view).
  // Click fires on tap. Payloads share shape so PostHog can join them
  // with a `card.clicked` group for the funnel.
  "proof_row.card_impression": {
    listing_id: string;
    rank: number;
    star_rating: number;
    position: 1 | 2 | 3;
    master_category: "beach" | "lake" | null;
    subcategory: "homes" | "condos" | "land" | null;
    proof_row_tier: "override" | "strict" | "relaxed_rank" | "relaxed_eligibility" | "shortfall" | null;
  };
  "proof_row.card_clicked": {
    listing_id: string;
    rank: number;
    star_rating: number;
    position: 1 | 2 | 3;
    master_category: "beach" | "lake" | null;
    subcategory: "homes" | "condos" | "land" | null;
    proof_row_tier: "override" | "strict" | "relaxed_rank" | "relaxed_eligibility" | "shortfall" | null;
  };
  // Category grid — 6 tiles for the beach × {homes,condos,land} +
  // lake × same matrix. Listing counts at click time so a sparsely
  // populated bucket shows up in the funnel even if conversion is
  // identical to a dense one.
  "category_grid.tile_clicked": {
    master_category: "beach" | "lake";
    subcategory: "homes" | "condos" | "land";
    listing_count_at_click: number;
  };
  "category_grid.browse_all_clicked": {
    master_category: "beach" | "lake";
    listing_count_at_click: number;
  };
  // Discovery pill row — All / ★ Top rated / Under $250K / Gated /
  // Waterfront. source_page lets us tell the homepage row apart from
  // the same pills surfaced on /browse.
  "discovery_pill.clicked": {
    filter: "all" | "top_rated" | "under_250k" | "gated" | "waterfront";
    source_page: "homepage" | "browse";
  };
  // Top nav — link clicks routed through this single event so the
  // funnel doesn't have to enumerate every destination. link_destination
  // is the path the user lands on; link_label is the visible text in
  // the locale at click time (NOT i18n key — actual rendered label).
  "nav.link_clicked": {
    link_label: string;
    link_destination: string;
  };

  // ── Homepage v2 (redesign) ────────────────────────────────────────
  // The redesigned homepage (NewHomePage rewrite #2) replaces the
  // Hero email form + ProofRow + CategoryGrid + DiscoveryPills with
  // a CTA-led hero + Featured deal + USP band + Pick Shoreline + 3
  // editorial shelves. Old event names (hero.email_submitted,
  // proof_row.*, category_grid.*, discovery_pill.*) stay in this
  // catalog for funnel-history continuity but no longer fire from
  // the homepage. New events below.
  "homepage.cta_clicked": {
    location: "header" | "hero_primary" | "hero_secondary";
    cta_text: string;
  };
  "homepage.featured_deal_clicked": Record<string, never>;
  "homepage.section_viewed": {
    section: "hero" | "featured" | "usps" | "shoreline" | "top_10" | "price_drops" | "new_this_week";
  };
  "homepage.shelf_view_all_clicked": {
    shelf: "top_10" | "price_drops" | "new_this_week";
  };
  "homepage.shelf_card_clicked": {
    shelf: "top_10" | "price_drops" | "new_this_week";
    position: number;
    listing_id: string;
  };
  "homepage.shelf_scrolled": {
    shelf: "top_10" | "price_drops" | "new_this_week";
    max_position_reached: number;
  };
  "shoreline_card_clicked": {
    shoreline: "beach" | "lake";
  };
  "mobile_nav.opened": Record<string, never>;
  "mobile_nav.closed": Record<string, never>;
  "mobile_nav.link_clicked": {
    link: "lake" | "beach" | "how_it_works" | "pricing" | "sign_in";
  };

  // ── Homepage v3 hero (dynamic live leaderboard) ──────────────────
  // The hero's animated leaderboard is the centerpiece of the v3
  // redesign. We do NOT fire an event per cycle (hundreds per session
  // would blow up the analytics bill); instead we fire start/pause/
  // resume so dashboards can answer "did the user see it run, and
  // for how long". reduced_motion=true means the user's OS prefers
  // reduced motion AND we short-circuited the interval — the event
  // still fires so we can size the audience receiving the static
  // fallback. cycle_ms echoes the production interval the page is
  // running at (so an experiment that shortens it shows up clearly).
  "hero_live_leaderboard_started": {
    reduced_motion: boolean;
    cycle_ms: number;
  };
  // Pause/resume cycle. Fires on IntersectionObserver-leave (hero
  // scrolled offscreen) and on document.visibilitychange (tab hidden).
  "hero_live_leaderboard_paused": Record<string, never>;
  "hero_live_leaderboard_resumed": Record<string, never>;
  // Just In pill click. Pill is a button — clicking it opens the
  // signup modal (same destination as the primary CTA) so the
  // existing signup_modal.shown funnel picks up the conversion.
  // listing_id is a slug of the sample listing name until backend
  // listings replace the fixture.
  "hero_just_in_clicked": {
    position: number | null; // 1-10 if the entry made the board, null = off
    listing_id: string;
  };

  // ── Cutover marker (rewrite Phase 7) ─────────────────────────────
  // One-time event fired per browser when the user first encounters
  // the new homepage shelf config (reduced from 15 → 2 per Q6 of the
  // rewrite plan). PostHog dashboards key off this to split sessions
  // into pre-rewrite vs post-rewrite buckets cleanly. The localStorage
  // gate that backs "one-time per browser" lives in app.jsx.
  "shelf.config_changed": {
    old_keys: string[];   // RETIRED_SHELF_KEYS from web/app/config/shelves.ts
    new_keys: string[];   // active shelf keys at fire time
  };

  // ───── Detail / Saves / Auth ─────
  "detail.opened": { listing_id: string; auth_state: AuthState; plan?: "free" | "pro" };
  "detail.photo_lightbox_opened": { listing_id: string };
  // Post-#305 the detail panel surfaces four in-panel upgrade CTAs.
  // This event fires the moment any of them is clicked (before
  // cta_routed / free_month_modal.shown) so dashboards can slice the
  // detail-panel conversion funnel by which sub-CTA actually pulled
  // the user into the modal. `listing_state` distinguishes off-market
  // gated paths from active-listing gallery/USP unlocks.
  "detail.upgrade_cta_clicked": {
    cta_location:
      | "broker_outbound"
      | "locked_thumb"
      | "locked_usp"
      | "more_photos_overlay";
    listing_id: string;
    listing_state: "active" | "off_market";
  };
  "save.toggled": {
    listing_id: string;
    auth_state: AuthState;
    action: "add" | "remove";
    // Set true when the click was intercepted by the anonymous-user
    // gate (SignupModal opens, intent stashed for post-signin replay).
    // Lets us tell anon-blocked clicks apart from real toggles in the
    // funnel — different conversion semantics.
    gated?: boolean;
  };
  "signup_modal.shown": {
    trigger: "heart" | "detail_view_count" | "manual" | "paywall" | "checkout" | "pendingListing";
    mode: "signup" | "login";
  };
  "signup.completed": { provider: "email" | "google" | "apple" | "magic_link" | "clerk" | "legacy" };
  // signin.completed fires on every signed-in transition (including
  // first-ever signups). signup.completed fires only when the SignupModal
  // was open with mode==="signup" at the moment of transition. Either or
  // both may fire for a given event in PostHog.
  "signin.completed": {
    provider: "clerk" | "legacy" | "email" | "google" | "apple" | "magic_link";
    plan: "free" | "pro";
  };
  "signout.completed": Record<string, never>;
  // Fires the moment the user clicks logout — before we touch local
  // state or call clerkActions.signOut. Pairs with signout.completed
  // (which fires when the user transition lands) so a missing
  // signout.completed after signout.started tells you the Clerk
  // signOut call hung or the user re-hydrated from a stale cookie.
  "auth.signout_started": { had_clerk_actions: boolean };

  // Generic API-error telemetry. Wired by the client-side fetch
  // helpers so non-2xx responses show up in PostHog with enough
  // detail to triage from the dashboard. `reason` mirrors the
  // server's response.error code; `detail` carries err.message
  // when the server included it.
  "api.error": {
    endpoint: string;
    status: number;
    reason?: string;
    detail?: string;
  };
  "paywall.shown": { kind: "detail_view" | "off_market" | "save_cap"; listing_id?: string };
  "paywall.bypassed": { kind: "detail_view" | "off_market" | "save_cap"; action: "upgrade" | "dismiss" | "have_account"; listing_id?: string };
  "plans.viewed": { source: "topnav" | "footer" | "paywall" | "manual" };
  "view_original.clicked": { listing_id: string; source_label: string };

  // Wave-1 CTA routing — fires once per click on any CTA that flows
  // through lib/cta-routing.ts. Property shape is locked at ship; the
  // branch enum mirrors the Branch type in cta-routing.ts. flag_enabled
  // tells us which path executed (new routing on / rollback on) so we
  // can compare conversion across a kill-switch flip.
  // user_state matches gating.ts's Tier ("agency" is paid-tier-equivalent
  // to "pro"; preserved separately for analytics segmentation).
  "cta_routed": {
    cta_id:
      | "header_primary"
      | "hero_primary"
      | "hero_just_in"
      | "featured_deal"
      | "newsletter_activation"
      | "shelf_card"
      | "broker_outbound"
      | "favorites_action"
      | "account_entry"
      // PR #305 made shelf/browse cards passthrough → open ListingDetail;
      // in-panel upgrade CTAs (broker outbound, locked thumb, locked USP,
      // more-photos overlay) now route through this id so the conversion
      // funnel reads a uniform cta_routed step regardless of entry surface.
      | "detail_upgrade";
    user_state: "anonymous" | "free" | "pro" | "agency";
    branch: "stripe_checkout" | "paywall" | "free_signup" | "login_ui" | "passthrough" | "free_month_modal";
    flag_enabled: boolean;
  };

  // ───── Upgrade flow (Stripe Checkout) ─────
  // Fires when the upgrade button is clicked and we kick off
  // /api/stripe/create-checkout-session. Pairs with the return-URL
  // event below to compute checkout completion rate.
  // Wave-2: `has_promo` reports whether the click carried a promo code
  // (from URL or sessionStorage) when fired. Splits the funnel by
  // promo-vs-no-promo conversion. Optional for backward-compat with
  // any in-flight session that emitted the event before the prop landed.
  "upgrade.checkout_started": { has_promo?: boolean };
  // Wave-2: fires server-side from /api/stripe/create-checkout-session
  // and /api/stripe/start-checkout whenever a promo code is attempted.
  // `succeeded` reflects whether Stripe's promotion-code lookup matched
  // an active code. `source` distinguishes the two endpoints so
  // dashboards can split the funnel.
  "promo_code_applied": {
    code: string;
    succeeded: boolean;
    source: "start_checkout" | "create_checkout_session";
  };

  // Wave-4: fires once per homepage mount with the resolved block list
  // from home/blockRegistry.ts. Tells us in production whether the
  // paid-home filter is engaging — when `flag_enabled: false` everyone
  // gets the same 7-block list (today's behavior); when true, paid
  // users get the filtered 4-block list. The string[] values are
  // BlockId values, in render order.
  "paid_home_rendered": {
    user_state: "anonymous" | "free" | "pro" | "agency";
    blocks_visible: string[];
    flag_enabled: boolean;
  };

  // Wave-5 USP popup. Replaces the inline USPBand surface with a
  // triggered modal. `trigger` distinguishes the four arming paths so
  // dashboards can see which funnels conversion best. shown/dismissed/
  // cta_clicked share the trigger label for cross-event joins.
  "usp_popup.shown": {
    trigger: "url_param" | "scroll" | "timer" | "exit_intent";
    user_state: string;  // tierFor() result; left open-string to
                         // avoid event-type churn if a new tier lands.
  };
  "usp_popup.dismissed": {
    trigger: "url_param" | "scroll" | "timer" | "exit_intent";
    action: "escape" | "backdrop" | "close_button" | "maybe_later";
  };
  "usp_popup.cta_clicked": {
    trigger: "url_param" | "scroll" | "timer" | "exit_intent";
  };

  // Wave-5b: fires when FeaturedDeal resolves a real listing from
  // featured.json + the local cache. Absent → the card fell back to
  // the hardcoded placeholder (flag off, fetch failed, or the pool's
  // listing id didn't match the local catalogue). Dashboards can
  // compare engagement on real vs hardcoded by joining on whether
  // this event fired for the session.
  "featured_deal_resolved": {
    listing_id: string;
    user_state: string;
  };

  // Wave 5#7+#9 (hero_v4 flag) — fires once per homepage mount when
  // the new white photo-led hero renders. Joining this event against
  // homepage.cta_clicked + cta_routed tells us whether the visual
  // refresh moves conversion. Empty payload — flag/user_state already
  // captured by paid_home_rendered and cta_routed.
  "hero_v4_viewed": Record<string, never>;
  // Fires when the user lands back at /preview/?upgrade=success or
  // ?upgrade=cancelled after Stripe Checkout. The webhook (server-side)
  // is the source of truth for the actual plan flip; this event is
  // user-experience-only.
  "upgrade.checkout_returned": { result: "success" | "cancelled" };
  // Stripe → Pulpo landing anchor. Fires the moment the post-Stripe URL
  // is detected (`?welcome=1` on /account or `?upgrade=success|cancelled`
  // on /preview/), BEFORE Clerk hydration. Pair with welcome_modal.shown
  // to distinguish "returned from Stripe" (this event) from "welcome
  // modal mounted after Clerk hydration" (welcome_modal.shown variant=
  // anon, can be delayed up to 5s). Post-Stripe activation funnels anchor
  // on this rather than welcome_modal.shown.
  "stripe.return_landed": {
    surface:
      | "account_welcome"
      | "preview_upgrade_success"
      | "preview_upgrade_cancelled";
    result: "success" | "cancelled";
  };

  // ───── /start landing (acquisition funnel) ─────
  // Standalone marketing page that funnels visitors into Stripe Checkout
  // without a Clerk sign-up wall. UTMs are auto-attached by PostHog at
  // the event-meta layer; do NOT duplicate them in payloads here. The
  // funnel reads cleanly as:
  //   $pageview (auto) → start.viewed
  //                    → start.cta_clicked
  //                    → start.checkout_redirected
  //                    → upgrade.checkout_returned (result=success)
  // and then later, post-invitation-accept, the existing signin.completed
  // closes the loop with the (now-identified) PostHog person.
  /** Cold-load of /start. `has_code` mirrors whether the URL carried
   *  `?code=…`; everything else (utm_*, country, device_type) is auto-
   *  attached by PostHog. */
  "start.viewed": { has_code: boolean };
  /** User clicks "Get access". /start is a single-button page — no
   *  email or code inputs (Stripe collects both). `has_code` echoes
   *  whether a `?code=…` URL param was attached so PostHog funnels
   *  can break down marketing-link conversion vs organic. */
  "start.cta_clicked": { has_code: boolean };
  /** Fires immediately before window.location.assign(stripeUrl). Pairs
   *  with the existing upgrade.checkout_returned event so the same funnel
   *  logic computes completion rate for /start as it does for /plans. */
  "start.checkout_redirected": { had_promo_code: boolean };
  /** URL-supplied promo code didn't resolve (typo, exhausted, test-vs-
   *  live mismatch). The frontend soft-fails: retries the API call
   *  without the code, sends the user to Stripe at full price. This
   *  event fires so we can surface broken campaign URLs in PostHog. */
  "start.code_error_shown": { reason: "invalid_promo_code" | "exhausted" };
  /** /account?welcome=1 modal mounted (PR-B.4b). Fires AFTER Clerk
   *  hydration resolves (or after the 5s `auth_load_timeout`
   *  fallback). `variant=anon` means a paid user whose Clerk
   *  invitation hasn't been accepted yet; `signed_in` means the
   *  post-invitation round trip completed and the session is live.
   *  Before the hydration gate (pre-2026-05-19), this event
   *  briefly mis-attributed signed-in users as anon during the
   *  Clerk SDK boot race — that flash is fixed by the gate.
   *  `surface` is "account" today but reserved so the same modal
   *  can surface elsewhere later without renaming the event. */
  "welcome_modal.shown": {
    variant: "anon" | "signed_in";
    surface: "account";
  };
  /** Modal dismissed — `action` distinguishes user-initiated dismissals
   *  (close button, ESC, backdrop, primary CTA) from the auto-dismiss
   *  on the signed-in variant after the brief acknowledgement. */
  "welcome_modal.dismissed": {
    variant: "anon" | "signed_in";
    action: "close" | "esc" | "backdrop" | "explore" | "auto";
  };
  /** Anonymous-variant CTA → opens Gmail in a new tab. */
  "welcome_modal.cta_inbox_clicked": Record<string, never>;
  /** Anonymous-variant secondary CTA → POSTs /api/clerk/resend-invitation. */
  "welcome_modal.cta_resend_clicked": Record<string, never>;
  /** Modal mount gated on Clerk hydration but the 5s timeout fired
   *  first — either Clerk SDK boot failed or hydration is unusually
   *  slow. `resolved_user` lets us split true SDK failures (false)
   *  from late-hydration cases where the user did eventually
   *  populate after the timer fired (true). Non-zero rate is a
   *  paging signal — Clerk auth is broken for some fraction of
   *  paid users. */
  "welcome_modal.auth_load_timeout": {
    resolved_user: boolean;
  };
  /** Anonymous-variant resend hit Clerk's "user already exists"
   *  branch in /api/clerk/resend-invitation. We show the
   *  "refresh this page" copy instead of the "check your inbox"
   *  copy. Counting these tells us how often the secondary loop
   *  reported on 2026-05-19 actually happens. */
  "welcome_modal.resend_user_exists": Record<string, never>;
  /** Anonymous-variant resend completed normally — Clerk re-fired
   *  the invitation email. Splits the cta_resend_clicked funnel
   *  into success / user_exists / failed so we can compute a real
   *  success rate. */
  "welcome_modal.resend_done": Record<string, never>;
  /** Anonymous-variant resend returned a non-2xx or threw. Pairs
   *  with the user-visible "Couldn't resend" copy and feeds the
   *  support-volume signal. */
  "welcome_modal.resend_failed": Record<string, never>;
  /** WelcomeModal anon variant fetched /api/clerk/invitation-status
   *  on mount and got a discriminated response. `status` matches the
   *  endpoint's return shape — invitation_pending is the happy path;
   *  user_exists / no_email / webhook_pending are the previously-
   *  silent failure modes the modal now surfaces to the user.
   *  Slicing webhook.checkout_completed.invitation_sent against this
   *  event tells us "what fraction of paying users see each variant"
   *  end-to-end. */
  "welcome_modal.invitation_status_resolved": {
    status: "invitation_pending" | "user_exists" | "no_email"
          | "webhook_pending" | "session_not_found" | "session_not_complete"
          | "fetch_failed";
  };
  /** User_exists variant CTA → opens Clerk's hosted sign-in via
   *  app.clerkActions.openSignIn (or falls back to legacy SignupModal
   *  when Clerk is off). Captures the "I already have an account"
   *  recovery path that pre-PR was completely silent — users sat on
   *  the lying "check your inbox" copy forever. */
  "welcome_modal.signin_existing_clicked": Record<string, never>;

  /** / home-page Pro upsell modal mounted (PR-B.5). `trigger` reflects
   *  which URL signal opened the modal — utm_* params, a ?code=… link,
   *  an explicit ?upsell=1, or (when the direct-traffic flag is on)
   *  direct. PostHog funnels can break down conversion by trigger to
   *  see which channel converts best. */
  "pro_upsell.shown": {
    trigger: "utm" | "code" | "explicit" | "direct";
    has_code: boolean;
  };
  /** Modal dismissed without converting. `action` distinguishes the
   *  paths so we can compare "users who close vs ESC vs Maybe later". */
  "pro_upsell.dismissed": {
    trigger: "utm" | "code" | "explicit" | "direct";
    action: "close" | "esc" | "backdrop" | "maybe_later";
  };
  /** Primary CTA clicked → frontend POSTs /api/stripe/start-checkout
   *  (same backend as /start). `had_promo_code` mirrors whether a
   *  URL `?code=…` got pre-applied. */
  "pro_upsell.cta_clicked": {
    trigger: "utm" | "code" | "explicit" | "direct";
    had_promo_code: boolean;
  };
  /** Fires immediately before window.location.assign(stripeUrl). Pairs
   *  with the existing upgrade.checkout_returned event for end-to-end
   *  funnel completion. */
  "pro_upsell.checkout_redirected": {
    trigger: "utm" | "code" | "explicit" | "direct";
    had_promo_code: boolean;
  };
  /** User clicks the /start "Log in" link. Funnel-side measure of
   *  returning-customer traffic vs new acquisition. */
  "start.login_link_clicked": Record<string, never>;

  // ───── Free-month conversion modal (in-page Stripe upsell) ─────
  // Replaces the previous "redirect to /start?intent=upgrade" page jump
  // for anon AND free users on hero, USP section, listing-card, and
  // featured-deal click paths. Paid users never see this modal.
  // Properties match the pro_upsell.* shape so PostHog funnels can join
  // the two modal surfaces, but `trigger` enumerates the click sources
  // (not URL signals).
  /** Mounted. Fires once per modal appearance. */
  "free_month_modal.shown": {
    trigger:
      | "hero_cta"
      | "header_cta"
      | "usp_section"
      | "shelf_card"
      | "featured_deal"
      | "hero_just_in"
      | "favorites_action"
      | "browse_card"
      | "detail_upgrade";
    user_state: "anonymous" | "free";
    flag_enabled: boolean;
    has_code: boolean;
    geo_currency: "usd" | "eur";
    price_amount: number;
  };
  /** Dismissed without converting. */
  "free_month_modal.dismissed": {
    trigger:
      | "hero_cta"
      | "header_cta"
      | "usp_section"
      | "shelf_card"
      | "featured_deal"
      | "hero_just_in"
      | "favorites_action"
      | "browse_card"
      | "detail_upgrade";
    action: "escape" | "backdrop" | "close_button" | "maybe_later";
  };
  /** Primary CTA clicked → POST /api/stripe/start-checkout. */
  "free_month_modal.cta_clicked": {
    trigger:
      | "hero_cta"
      | "header_cta"
      | "usp_section"
      | "shelf_card"
      | "featured_deal"
      | "hero_just_in"
      | "favorites_action"
      | "browse_card"
      | "detail_upgrade";
    has_code: boolean;
  };
  /** Fires immediately before window.location.assign(stripeUrl). */
  "free_month_modal.checkout_redirected": {
    trigger:
      | "hero_cta"
      | "header_cta"
      | "usp_section"
      | "shelf_card"
      | "featured_deal"
      | "hero_just_in"
      | "favorites_action"
      | "browse_card"
      | "detail_upgrade";
    has_code: boolean;
  };
  /** Surface-side error. `reason` mirrors pro_upsell.* for parity. */
  "free_month_modal.error": {
    trigger:
      | "hero_cta"
      | "header_cta"
      | "usp_section"
      | "shelf_card"
      | "featured_deal"
      | "hero_just_in"
      | "favorites_action"
      | "browse_card"
      | "detail_upgrade";
    reason: string;
  };
  /** Fires when an unrecognized URL (e.g. /test) gets cleanly
   *  replaceState'd to /. Surfaces broken inbound links in PostHog. */
  "route.fallback_redirected": { from_path: string };

  // ───── Account sub-section deep-links (PR account-section-urls) ─────
  /** Fires once per resolved /account/<section> tab — cold-load (URL
   *  hit), in-app nav click, and browser back/forward all emit. Lets
   *  PostHog answer "did anyone actually deep-link a sub-section?",
   *  which is the justification for these dedicated URLs. `entry`
   *  distinguishes inbound traffic vs intra-page navigation so the
   *  dashboards don't conflate the two. */
  "account.section_viewed": {
    section: "profile" | "notifications" | "subscription" | "security";
    entry: "url" | "nav_click" | "popstate";
  };

  // ───── Preferred category chip selector (PR preferred-categories) ─────
  /** Fires every time a chip is toggled inside the /account/notifications
   *  preference selector. `selected_categories_after` is the resulting
   *  array (post-change), so dashboards can compute the most-common
   *  picks without joining sequential events. Categories are the same
   *  vocabulary that powers Discover shelves + Browse pills (see
   *  web/app/lib/categories.ts) — same field will drive newsletter
   *  filtering and future personalization. */
  "account.preferred_categories_toggled": {
    category: string;
    action: "select" | "deselect";
    selected_count_after: number;
    selected_categories_after: string[];
  };
  /** Fires when the user tries to select a 5th chip while already at
   *  PREFERENCE_CATEGORIES_MAX (today: 4). Instructive signal for
   *  whether the cap should rise. */
  "account.preferred_categories_limit_hit": {
    attempted_category: string;
    current_selection: string[];
  };
  /** Fires when a profile update (e.g. preferred categories) wrote
   *  successfully to local state but failed to persist to Clerk —
   *  network blip, expired session, server-side write error. Pairs
   *  with the rollback in `app.updateUserProfile`; the UI reverts
   *  to the prior state and surfaces a toast. Non-zero rate here
   *  is the leading indicator that cross-device sync is broken. */
  "account.profile_sync_failed": {
    keys: string;
    reason: string;
    status: number;
  };

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
  /** Card image load duration: from React render → onLoad fired.
   *  Only emitted for `eager` images (the above-the-fold cards on
   *  Browse/Discover/Saved). Lazy images defer their fetch until
   *  intersection so a "duration" wouldn't be meaningful — they get
   *  measured separately if we ever wire an IntersectionObserver
   *  start-stamp. `idx` is the photo carousel index, `source` is the
   *  surface so PostHog can compare browse vs discover vs saved. */
  "perf.card_image_load": {
    listing_id: string;
    idx: number;
    ms: number;
    source: "browse" | "discover" | "saved";
  };
  /** Lazy-loaded card image — viewport-entry → onLoad latency. Stamps
   *  start time when an IntersectionObserver fires for the card's
   *  Photo wrapper, ends when `<img onLoad>` fires. ms can be 0 when
   *  native lazy-loading prefetched the bytes before the card became
   *  visible (the optimal case). source matches perf.card_image_load
   *  so PostHog can split browse vs discover vs saved. */
  "perf.card_image_lazy_load": {
    listing_id: string;
    idx: number;
    ms: number;
    source: "browse" | "discover" | "saved";
  };
  /** Static asset (JS bundle / CSS / WebP image) load timing, observed
   *  via PerformanceObserver(type="resource"). Lets us see whether the
   *  Vite-built /preview/assets/* chain is hitting browser cache on
   *  return visits. `kind` is derived from filename:
   *    entry  — /preview/assets/index.js (or hashed equivalent)
   *    chunk  — /preview/assets/<other>.js
   *    css    — /preview/assets/*.css
   *    webp   — /preview/assets/*.webp (category tile images)
   *  cache:
   *    hit       — served from browser cache (transferSize === 0 with
   *                non-zero encodedBodySize, or deliveryType==="cache")
   *    miss      — bytes were transferred over the wire
   *    unknown   — neither signal available (older browsers) */
  "perf.asset_load": {
    kind: "entry" | "chunk" | "css" | "webp";
    url: string;
    ms: number;
    bytes: number;
    cache: "hit" | "miss" | "unknown";
  };
  /** Web Vitals LCP attribution. Tells us *what* the LCP element
   *  actually is — `<img class="hero-bg">` vs a card photo vs the
   *  hero text. When `url` is set, the LCP is an image and the URL
   *  identifies which one. Pairs with web_vitals.lcp for diagnosis. */
  "web_vitals.lcp.attribution": {
    element_tag: string;
    element_class?: string;
    url?: string;
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

  // ───── Image lifecycle ─────
  /** Browser's <img onerror> fired — real load failure (404, decode
   *  error, DNS, CORS, etc.). The Photo component falls back to the
   *  zoned placeholder; this event is what surfaces the failure in
   *  PostHog (image errors don't bubble as JS exceptions, so they
   *  bypass $exception capture). Group by `source` + `is_local` to
   *  triage: is_local=true → local /photos/* file broken (regression
   *  in nightly download or rewrite); is_local=false → third-party
   *  CDN failure (expected baseline). */
  "image.error": {
    url: string;
    listing_id: string;
    idx: number;
    source: "discover" | "browse" | "saved" | "detail" | "unknown";
    is_local: boolean;
  };
  /** Fires when an image neither loaded nor errored within 8 s of the
   *  URL change. Catches the React+browser-cache opacity-stuck class
   *  (onLoad doesn't fire for cache hits if React attached the listener
   *  after the synchronous load completed) AND slow CDNs that never
   *  resolve. Post-fix this should baseline near zero; a non-zero rate
   *  is a regression signal. `was_cached_likely`=true when the <img>
   *  element's `.complete` flag was true at the 8 s mark but `loaded`
   *  state was still false — i.e., the opacity-stuck signature. */
  "image.stuck": {
    url: string;
    listing_id: string;
    idx: number;
    source: "discover" | "browse" | "saved" | "detail" | "unknown";
    is_local: boolean;
    was_cached_likely: boolean;
  };

  // ───── Section-URL routing (PR section-urls) ─────
  /** Fires on every route change (pushState, popstate, or cold-load).
   *  PostHog reconstructs the session graph from these. `trigger` lets
   *  the analyst tell genuine user navigation apart from history-API
   *  side-effects. `to_path` is the full pathname (including
   *  `/listing/<id>`); `from_path` is null on cold-load. */
  "route.changed": {
    from_path: string | null;
    to_path: string;
    trigger: "click" | "back" | "forward" | "cold_load";
  };

  // ───── Legal-suite pages (PR legal-routes-shells) ─────
  /** Fires on mount of any public legal route (/terms, /privacy, /cookies,
   *  /subscription, /imprint, /contact). Lets us see drop-off + ToS-link
   *  click-through from Stripe Checkout. `page=imprint` covers both the
   *  /imprint and /impressum URLs (same route, two paths). */
  "legal.page_viewed": {
    page: "terms" | "privacy" | "cookies" | "subscription" | "imprint" | "contact";
  };
};

export type EventName = keyof EventMap;
