// Pulpo — main app shell, router, auth state.
// Visual design baked in: palette=pulpo (white & deep green),
// hero=magazine, density=comfortable, corners=default,
// base-size=15px, font-theme=editorial.
// Production flows preserved: auth (signup/login/logout), saved listings,
// detail-view paywall (soft prompt @5, hard gate @8), locale, toasts.
// QA helpers exposed via ?debug=1 URL flag (no UI in production).
import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import ReactDOM from "react-dom/client";
import { t, useLocale, useUnits } from "./i18n.jsx";
import { ListingsProvider, useListings, useListingsState } from "./data/use-listings.tsx";
import { PulpoLogo } from "./components.jsx";
import {
  TopNav,
  BottomNav,
  HomePage,
  BrowsePage,
  SavedPage,
  PlansPage,
  ListingDetail,
  SignupModal,
  WelcomeModal,
  ProUpsellModal,
  ToastHost,
  ConsentBanner,
} from "./pages.jsx";
import { NewHomePage } from "./home";
import { AccountPage } from "./account.jsx";

// Feature flag for the rewritten homepage (rewrite plan Phase 4C).
// Set VITE_NEW_HOMEPAGE=1 in the deploy env to opt this preview in
// globally. Per-session override via `?new=1` query param — useful
// for staged QA on production (test the new homepage on the live
// deploy before flipping the env var) AND for Playwright specs
// targeting the new surfaces.
//
// Read once at module load — flipping mid-session won't take effect
// until reload, matching every other VITE_* env-driven flag (Clerk,
// PostHog, etc.).
const USE_NEW_HOMEPAGE = (() => {
  if (import.meta.env.VITE_NEW_HOMEPAGE === "1") return true;
  try {
    if (typeof window === "undefined") return false;
    const params = new URLSearchParams(window.location.search);
    return params.has("new");
  } catch {
    return false;
  }
})();
import {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRadio,
  TweakToggle,
  TweakButton,
} from "./tweaks-panel.jsx";
import { ErrorBoundary } from "./error-boundary.jsx";
import { ClerkShell, clerkEnabled } from "./auth/clerk-shell.jsx";
import { fetchSaves, postSaveAction } from "./auth/saves-client.js";
import { track } from "./telemetry/hook";
import { bootWebVitals } from "./telemetry/web-vitals";
import {
  parseLocation,
  pathForRoute,
  pathForListing,
  urlFor,
  isSameLocation,
} from "./lib/url-routing";
import { evaluateGate } from "./lib/route-gates";
import { useDocumentMeta } from "./lib/use-document-meta";
import { bootAssetTelemetry } from "./telemetry/asset-load";
import { bootGlobalErrorHandlers } from "./telemetry/errors";
import "./styles/index.css";

function App() {
  // Tweakable defaults — host rewrites this block when the user changes a tweak,
  // so values persist across reloads.
  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "density": "comfortable",
    "showStyleCarousel": true,
    "showFooterOnAccount": false
  }/*EDITMODE-END*/;
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // Mount-time route seed — read pathname so cold-loading /browse,
  // /saved, /plans, /account, or /listing/:id renders the right section
  // immediately. The `parsed.isListingPath` flag tells `closeListing`
  // whether the user entered on the detail (in which case "back" must
  // not exit the site — replaceState to "/" instead).
  const _initialParsed = useMemo(() => {
    if (typeof window === "undefined") return { route: "home", openListingId: null, isListingPath: false };
    return parseLocation(window.location.pathname);
  }, []);
  const [route, setRoute] = useState(_initialParsed.route);
  const [routeParams, setRouteParams] = useState({});
  // Tracks whether the current detail view was entered cold (no source
  // section underneath). Reset to false whenever the user navigates to a
  // section in-app; set true on cold-load entry.
  const coldEnteredDetailRef = useRef(_initialParsed.isListingPath);
  const [locale, setLocale] = useLocale();
  const [units, setUnits] = useUnits();
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("pulpo-user")) || null; } catch { return null; }
  });

  // PR-9d removed the dev-panel auth-state mock. Clerk drives `setUser`
  // via ClerkUserSync when enabled (the production default). For the
  // legacy auth path (e.g. local dev or CI without a Clerk publishable
  // key) the localStorage seed in `useState` above is the source of
  // truth — seed `pulpo-user` directly to fake an auth state in tests.
  const [savedIds, setSavedIds] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem("pulpo-saved")) || []); } catch { return new Set(); }
  });
  const [signupModal, setSignupModal] = useState(null);
  // Seed openListingId from the URL on mount so cold-loading
  // /listing/:id opens the detail panel without a flicker. Listings
  // load async via useListings(); the detail panel renders its own
  // pending skeleton while the id hasn't resolved yet.
  // Hot-line for triggering Clerk's hosted sign-in / sign-up modal
  // imperatively, without a click-time Suspense boundary that would
  // throw React #426. <ClerkActionsBinder> inside ClerkShell wires
  // this up once the SDK loads (flag-on only); SignupModal calls it.
  const [clerkActions, setClerkActions] = useState(null);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [toast, setToast] = useState(null);
  const [openListingId, setOpenListingId] = useState(_initialParsed.openListingId);
  // Guard against re-entry on rapid backdrop taps / Esc-then-click.
  // history.back() is async — popstate fires next tick — so a second
  // call mid-flight would close more than one history entry.
  const closingRef = useRef(false);
  const [detailViewCount, setDetailViewCount] = useState(() => {
    return +localStorage.getItem("pulpo-detail-views") || 0;
  });

  // Dev panel gate: visible only when (a) the build is non-production AND
  // (b) the URL carries ?dev=1 or ?debug=1, OR we're in `vite dev`. In
  // production builds `__PULPO_DEV_PANEL__` is the literal `false`, so
  // both panels (TweaksPanel and DebugPanel) get dead-code-eliminated by
  // tree-shaking. See vite.config.js.
  const showDevPanel = useMemo(() => {
    if (!__PULPO_DEV_PANEL__) return false;
    try {
      const params = new URLSearchParams(window.location.search);
      return import.meta.env.DEV || params.has("dev") || params.has("debug");
    } catch {
      return import.meta.env.DEV;
    }
  }, []);
  // Legacy ?debug=1 flag — still wires the lower-right DebugPanel
  // specifically (separate from the full TweaksPanel above).
  const debug = useMemo(() => {
    if (!__PULPO_DEV_PANEL__) return false;
    try { return new URLSearchParams(window.location.search).has("debug"); }
    catch { return false; }
  }, []);

  // Telemetry boot — fires `landing.viewed` once per app mount and
  // wires Web Vitals (LCP/INP/CLS/TTFB) → PostHog. PostHog itself is
  // lazy-loaded inside requestIdleCallback, so this runs cheaply.
  useEffect(() => {
    track("landing.viewed", { route: window.location.pathname || "/" });
    track("route.changed", {
      from_path: null,
      to_path: window.location.pathname + window.location.search,
      trigger: "cold_load",
    });
    // Cutover marker — fires ONCE per browser when the user first
    // encounters the post-rewrite shelf config (15 → 2 per Q6).
    // localStorage gate persists the "fired" state so PostHog gets
    // exactly one marker per visitor; subsequent sessions don't
    // re-emit. Dashboards key off this event's existence to split
    // sessions into pre-rewrite vs post-rewrite buckets cleanly.
    try {
      const SHELF_MARKER_KEY = "pulpo-shelf-cutover-fired";
      if (!localStorage.getItem(SHELF_MARKER_KEY)) {
        // Lazy-import the config so this code path doesn't pull the
        // shelves config (and its filter predicates) into the boot
        // bundle. Module is small but the principle stands.
        import("./config/shelves.ts").then(({ activeShelves, RETIRED_SHELF_KEYS }) => {
          track("shelf.config_changed", {
            old_keys: [...RETIRED_SHELF_KEYS],
            new_keys: activeShelves().map((s) => s.key),
          });
          try { localStorage.setItem(SHELF_MARKER_KEY, "1"); } catch { /* ignore */ }
        }).catch(() => { /* ignore — boot must never fail on this */ });
      }
    } catch { /* localStorage disabled → skip the marker, no harm */ }
    bootWebVitals();
    bootAssetTelemetry();
    bootGlobalErrorHandlers();
  }, []);

  // 404 fallback — Vercel rewrites every unknown path to the SPA, so a
  // typo like `/test` boots <App /> with the URL still showing `/test`.
  // parseLocation then defaults to route="home" but the URL doesn't
  // clean up, which (a) confuses users who shared the bad URL, (b)
  // pollutes PostHog's $pageview path breakdown. Detect "unknown path
  // that fell through to home" on mount and replaceState to `/` so the
  // URL matches what the user actually sees. Listing paths
  // (`/listing/...`) are real even when the id doesn't resolve, so they
  // keep their URL — the detail panel's missing-state covers UX there.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const path = window.location.pathname;
    if (path === "/") return;
    // Known section + listing paths produce a non-home route OR
    // isListingPath=true. Anything else is a 404 fall-through.
    if (_initialParsed.route !== "home" || _initialParsed.isListingPath) return;
    track("route.fallback_redirected", { from_path: path });
    window.history.replaceState({}, "", "/" + window.location.search + window.location.hash);
    // Intentional one-shot, not reactive — runs at mount with the
    // resolved _initialParsed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Browser-default scrollRestoration is "auto" — it tries to restore a
  // scroll position that no longer exists once section content has
  // changed under it, which produces flickers and "back-button leaves
  // me at the top of a different page" weirdness. Take it manual; our
  // `go()` callbacks scrollTo(0,0) explicitly.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const prev = window.history.scrollRestoration;
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
    return () => {
      if ("scrollRestoration" in window.history && prev) {
        window.history.scrollRestoration = prev;
      }
    };
  }, []);

  // popstate — back/forward navigation. Reseeds route + openListingId
  // from the URL, scrolls to top, and fires telemetry. Browse filter
  // params are reseeded inside BrowsePage's own popstate listener so the
  // chips visually re-sync.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onPop = (event) => {
      const fromPath = ""; // popstate doesn't tell us where we came from.
      const parsed = parseLocation(window.location.pathname);
      // Detect direction from the event state shape. Without explicit
      // state we treat a popstate as "back"; forward is also a popstate
      // but the only practical difference for us is the trigger label.
      const trigger = event && event.state && event.state.forward ? "forward" : "back";
      setOpenListingId(parsed.openListingId);
      setRoute(parsed.route);
      // popstate landing on /listing/:id with no app-pushed state means
      // the user navigated forward from history into a detail entry.
      // It's not a cold-load (the SPA is already mounted), but the
      // "back from here exits" semantic doesn't apply either — the
      // popstate listener correctly handles the back chain.
      coldEnteredDetailRef.current = false;
      track("route.changed", {
        from_path: fromPath || null,
        to_path: window.location.pathname + window.location.search,
        trigger,
      });
      window.scrollTo(0, 0);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Marquee the document.title so the tab text scrolls like a
  // marquesina. Pure-cosmetic — pauses entirely when the user has
  // `prefers-reduced-motion: reduce` set (accessibility — animated
  // tab titles can be disorienting).
  //
  // Only runs on the home route. On other sections (/browse, /listing/:id,
  // …) the title is informational ("Listing X in Zone Y — Pulpo") and
  // benefits from being readable, not scrolling. useDocumentMeta sets
  // the route-specific title; this effect re-runs on every route change
  // and either kicks the marquee off home or stays out of the way
  // elsewhere.
  useEffect(() => {
    if (typeof window === "undefined" || !document) return;
    if (route !== "home" || openListingId) return;
    const reduce = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;
    // Snapshot the current title — useDocumentMeta wrote it before this
    // effect ran (effect ordering: useDocumentMeta is mounted higher).
    // If the title changes mid-marquee (e.g. locale flip while on home)
    // the dep array re-runs this effect and the snapshot refreshes.
    const original = document.title;
    // The separator gives the eye a clear loop point + makes a one-
    // word title readable as it scrolls back around. Three spaces
    // either side of the bullet keep the words from running into
    // each other on browsers that condense whitespace in the tab.
    const text = original + "   •   ";
    let offset = 0;
    const tick = () => {
      offset = (offset + 1) % text.length;
      document.title = text.slice(offset) + text.slice(0, offset);
    };
    const id = setInterval(tick, 320);
    return () => {
      clearInterval(id);
      document.title = original;
    };
  }, [route, openListingId, locale]);

  // Handle the Stripe Checkout return URL. The server's create-checkout-
  // session sends success → /preview/?upgrade=success&session_id=...
  // and cancel → /preview/?upgrade=cancelled. Without this, the user
  // lands back here after paying and nothing visible happens (the
  // webhook flips the Clerk plan async, but that lands silently). Fires
  // once per app mount, then strips the query so a refresh doesn't
  // re-toast. Captures `locale` at mount time which is always the user's
  // first-paint locale — accurate for the moment they're returning.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const status = params.get("upgrade");
    if (!status) return;
    if (status === "success") {
      track("upgrade.checkout_returned", { result: "success" });
      setToast({ id: Date.now(), message: t("upgrade.success_toast", locale) });
    } else if (status === "cancelled") {
      track("upgrade.checkout_returned", { result: "cancelled" });
      setToast({ id: Date.now(), message: t("upgrade.cancelled_toast", locale) });
    }
    params.delete("upgrade");
    params.delete("session_id");
    const newSearch = params.toString();
    const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : "") + window.location.hash;
    window.history.replaceState({}, "", newUrl);
    // Intentionally only on mount — re-running on locale change would
    // re-toast a stripped URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Handle `?welcome=1` — set by Stripe `success_url` after a /start
  // checkout AND by Clerk's invitation `redirectUrl` after a magic-link
  // accept. Both moments converge on the same surface; the
  // <WelcomeModal> picks its variant from `user` state (anon vs
  // signed-in). Fires once on mount, then strips the param so a
  // refresh doesn't re-open the modal.
  const [welcomeModalState, setWelcomeModalState] = useState(null);
  const welcomeParamHandledRef = useRef(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (welcomeParamHandledRef.current) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("welcome") !== "1") return;
    welcomeParamHandledRef.current = true;
    const sessionId = params.get("session_id") || null;
    params.delete("welcome");
    params.delete("session_id");
    const newSearch = params.toString();
    const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : "") + window.location.hash;
    window.history.replaceState({}, "", newUrl);
    setWelcomeModalState({ sessionId });
    // Telemetry fires from inside the WelcomeModal component on mount
    // (so the `variant` field reflects the auth state at render time,
    // not the moment of the URL detection).
  }, []);
  const closeWelcomeModal = useCallback(() => setWelcomeModalState(null), []);

  // Handle `?login=1` — set by /start's "Log in" link so anonymous
  // visitors who already have an account land on `/` and immediately
  // see the Clerk hosted sign-in modal. Fires once clerkActions is
  // wired (Suspense boundary inside ClerkShell resolves it lazily).
  // When Clerk isn't enabled, fall back to the legacy SignupModal in
  // login mode so the link still does something useful in CI / dev.
  // Strips `?login=1` after firing so a refresh doesn't loop.
  const loginParamHandledRef = useRef(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (loginParamHandledRef.current) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("login") !== "1") return;

    // Strip the param synchronously so a re-render doesn't re-enter.
    params.delete("login");
    const newSearch = params.toString();
    const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : "") + window.location.hash;
    window.history.replaceState({}, "", newUrl);
    loginParamHandledRef.current = true;

    // Clerk path — wait for clerkActions to bind, then open the hosted
    // sign-in modal. ClerkShell mounts lazily so clerkActions may be
    // null on the first render; the effect re-runs when it lands.
    if (clerkActions && typeof clerkActions.openSignIn === "function") {
      clerkActions.openSignIn();
      return;
    }
    // Legacy path — open the in-app SignupModal in login mode. This
    // also serves as the fallback when Clerk isn't enabled in CI / dev.
    setSignupModal({ mode: "login", source: "start_login_link" });
  }, [clerkActions]);

  useEffect(() => {
    if (user) localStorage.setItem("pulpo-user", JSON.stringify(user));
    else localStorage.removeItem("pulpo-user");
  }, [user]);
  useEffect(() => {
    localStorage.setItem("pulpo-saved", JSON.stringify([...savedIds]));
  }, [savedIds]);
  useEffect(() => {
    localStorage.setItem("pulpo-detail-views", String(detailViewCount));
  }, [detailViewCount]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  const showToast = useCallback((message) => setToast({ id: Date.now(), message }), []);

  // Single post-signin effect: when user transitions to signed-in,
  // close the SignupModal AND fire any pending action carried on the
  // modal config. Covers both the legacy signin() callback and
  // Clerk's hosted modal flow (ClerkUserSync sets user async after
  // the hosted modal self-closes). Before this lived here, only the
  // legacy path fired pending actions — Clerk users dropped them on
  // the floor (e.g. clicked Heart-while-anonymous → signed in via
  // Clerk → save was lost, since signin() never ran).
  //
  // Supported pending actions on signupModal:
  //   pendingSave    — listing_id to add to saved set
  //   pendingListing — listing_id to open the detail panel for
  //   pendingAction  — "checkout" → kick off Stripe Checkout redirect
  useEffect(() => {
    if (!user || !signupModal) return;
    const cfg = signupModal;
    setSignupModal(null);
    // signup.completed fires when the modal was a "signup" flow at the
    // moment of transition. signin.completed (in the auth-telemetry
    // effect below) fires for every transition — both surface in
    // PostHog. Distinguishing the two lets the dashboard build a true
    // acquisition-funnel completion metric.
    if (cfg.mode === "signup") {
      track("signup.completed", {
        provider: (user.provider) || "legacy",
      });
    }
    if (cfg.pendingSave) {
      setSavedIds(prev => prev.has(cfg.pendingSave) ? prev : new Set([...prev, cfg.pendingSave]));
    }
    if (cfg.pendingListing) {
      setTimeout(() => setOpenListingId(cfg.pendingListing), 400);
    }
    // postLoginRoute set by the route-gate effect (see below) when an
    // anonymous user lands cold on /saved or /account. After sign-in
    // the user is on the right path already (URL stays put while the
    // modal is open) — but we re-confirm `route` matches in case the
    // user navigated elsewhere with the modal open.
    if (cfg.postLoginRoute && route !== cfg.postLoginRoute) {
      setRoute(cfg.postLoginRoute);
    }
    if (cfg.pendingAction === "checkout") {
      // Lazy-load the helper so the Stripe-checkout chunk only fires
      // for users who actually intended to upgrade.
      import("./auth/stripe-checkout.js").then(({ startStripeCheckout }) => {
        startStripeCheckout({
          onError: (code) => {
            // sign_in_required shouldn't happen here (we just signed
            // in), but if it does, swallow rather than re-prompting.
            if (code !== "sign_in_required") {
              showToast(t("plans.checkout_error_toast", locale));
            }
          },
        });
      });
    }
    // route is intentionally NOT in deps — the post-signin chain reads
    // route once at the moment the user transitions, not later.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, signupModal, locale, showToast]);

  // Auth telemetry. Fires once per transition for both Clerk-on
  // (ClerkUserSync drives setUser) and legacy (signin/signout
  // callbacks). Identity-keyed on user.email so tab visibility
  // re-renders don't double-fire.
  const prevAuthEmailRef = useRef(user ? user.email : null);
  useEffect(() => {
    const prev = prevAuthEmailRef.current;
    const next = user ? user.email : null;
    if (prev === next) return;
    prevAuthEmailRef.current = next;
    if (next && !prev) {
      track("signin.completed", {
        provider: (user && user.provider) || "legacy",
        plan:     (user && user.plan)     || "free",
      });
    } else if (!next && prev) {
      track("signout.completed", {});
    }
  }, [user]);

  // PR-9c — Clerk-on path takes the saves list from the server.
  // Hydrates on user transition; clears on sign-out so we don't
  // display the previous user's set briefly. Also reconciles any
  // anonymous Heart click captured in pulpo-pending-save before
  // sign-in (the flow: anon clicks Heart → save intent stashed →
  // SignupModal → Clerk sign-in completes → ClerkUserSync sets
  // user → this effect fires the pending POST + hydrates).
  const clerkUserId = user && user.clerkId;
  useEffect(() => {
    if (!clerkEnabled()) return;
    if (!clerkUserId) {
      setSavedIds(new Set());
      return;
    }
    let cancelled = false;
    (async () => {
      let pending = null;
      try { pending = localStorage.getItem("pulpo-pending-save"); } catch {}
      if (pending) {
        const r = await postSaveAction(pending, "add");
        try { localStorage.removeItem("pulpo-pending-save"); } catch {}
        if (!cancelled && r.ok) {
          setSavedIds(new Set(r.saves));
          showToast(t("toast.saved", locale));
          return;
        }
      }
      const r = await fetchSaves();
      if (!cancelled && r.ok) setSavedIds(new Set(r.saves));
    })();
    return () => { cancelled = true; };
  }, [clerkUserId, locale, showToast]);

  // PR-photo-nav-perf — instrument route transitions + detail open
  // for compelling perf telemetry. Uses requestAnimationFrame so the
  // measurement spans through React's commit phase (the actual user-
  // visible "next page" / "panel rendered" moment).
  const _measure = useCallback((eventName, payload) => {
    const t0 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const t1 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
      track(eventName, { ...payload, ms: Math.round(t1 - t0) });
    }));
  }, []);

  // Push a new history entry for a section navigation. `goBrowse` is a
  // thin wrapper that also handles the category routeParam; we serialize
  // the category into the URL via filter-url.ts inside BrowsePage's
  // existing writer effect, so here we just pushState the path.
  const go = useCallback((r, params = {}) => {
    const from = route;
    const fromPath = typeof window !== "undefined"
      ? window.location.pathname + window.location.search
      : "";
    const target = urlFor({ route: r }, "");
    // Same-route, same-URL → no-op so the back button doesn't accumulate
    // duplicate entries.
    const same = typeof window !== "undefined"
      && isSameLocation({ route: r }, window.location.pathname, "");
    setRoute(r);
    setRouteParams(params);
    setOpenListingId(null);
    coldEnteredDetailRef.current = false;
    if (typeof window !== "undefined" && !same) {
      window.history.pushState({ pulpo: true }, "", target);
      track("route.changed", { from_path: fromPath, to_path: target, trigger: "click" });
    }
    if (typeof window !== "undefined") window.scrollTo(0, 0);
    if (from !== r) _measure("perf.route_transition", { from, to: r });
  }, [route, _measure]);

  const goBrowse = useCallback((params = {}) => {
    const from = route;
    const fromPath = typeof window !== "undefined"
      ? window.location.pathname + window.location.search
      : "";
    setRoute("browse");
    setRouteParams(params);
    setOpenListingId(null);
    coldEnteredDetailRef.current = false;
    // BrowsePage's mount-time effect re-reads the URL and applies the
    // category. We push the bare /browse path here; filter-url.ts's
    // `writeFilterToURL` writes the cat= param via replaceState as
    // soon as filters settle.
    if (typeof window !== "undefined") {
      const target = urlFor({ route: "browse" }, "");
      const onBrowseAlready = window.location.pathname === "/browse";
      if (onBrowseAlready) {
        // Already on /browse — don't add a history entry; the filter
        // effect inside BrowsePage will replaceState the category.
      } else {
        window.history.pushState({ pulpo: true }, "", target);
        track("route.changed", { from_path: fromPath, to_path: target, trigger: "click" });
      }
      window.scrollTo(0, 0);
    }
    if (from !== "browse") _measure("perf.route_transition", { from, to: "browse" });
  }, [route, _measure]);

  const openListing = useCallback((id) => {
    if (!id) return;
    const fromPath = typeof window !== "undefined"
      ? window.location.pathname + window.location.search
      : "";
    setOpenListingId(id);
    if (typeof window !== "undefined") {
      const target = pathForListing(id);
      // Don't push duplicate if already on /listing/<id>.
      if (window.location.pathname !== target) {
        window.history.pushState({ pulpo: true, listing: id }, "", target);
        track("route.changed", { from_path: fromPath, to_path: target, trigger: "click" });
      }
    }
    _measure("perf.detail_open", { listing_id: id });
  }, [_measure]);

  const closeListing = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    // Reset the guard on next tick — popstate fires asynchronously.
    setTimeout(() => { closingRef.current = false; }, 200);

    if (typeof window === "undefined") {
      setOpenListingId(null);
      return;
    }
    if (coldEnteredDetailRef.current) {
      // User landed cold on /listing/:id — there's no source section
      // underneath. history.back() would exit the site. Instead replace
      // the current entry with /, so Browser Back exits cleanly with no
      // surprise loop.
      const fromPath = window.location.pathname + window.location.search;
      window.history.replaceState({ pulpo: true }, "", "/");
      coldEnteredDetailRef.current = false;
      setOpenListingId(null);
      setRoute("home");
      track("route.changed", { from_path: fromPath, to_path: "/", trigger: "click" });
    } else {
      // In-app open → history.back() pops the listing entry. The
      // popstate listener below mutates state (setOpenListingId(null) +
      // restores route from URL).
      window.history.back();
    }
  }, []);

  const toggleSave = useCallback((id) => {
    const authState = !user ? "anonymous" : (user.plan === "pro" ? "pro" : "free");

    // Anon click while flag-on → stash intent, open SignupModal. The
    // hydration effect picks up `pulpo-pending-save` after Clerk
    // sign-in completes and posts it server-side.
    if (clerkEnabled() && !clerkUserId) {
      try { localStorage.setItem("pulpo-pending-save", id); } catch {}
      setSignupModal({ mode: "signup", pendingSave: id });
      track("save.toggled", { listing_id: id, action: "add", auth_state: authState, gated: true });
      return;
    }

    // Optimistic local toggle. `wasSaved` is set inside the updater
    // so we know which way to roll back if the server call fails.
    let wasSaved = false;
    setSavedIds(prev => {
      wasSaved = prev.has(id);
      const next = new Set(prev);
      if (wasSaved) next.delete(id);
      else next.add(id);
      return next;
    });
    showToast(t(wasSaved ? "toast.removed" : "toast.saved", locale));
    track("save.toggled", {
      listing_id: id,
      action:     wasSaved ? "remove" : "add",
      auth_state: authState,
    });

    // Flag-off keeps localStorage-only behaviour (legacy). Flag-on
    // syncs to /api/saves and rolls back the optimistic update on
    // any non-2xx (cap-reached, network, 500).
    if (!clerkEnabled() || !clerkUserId) return;
    const action = wasSaved ? "remove" : "add";
    postSaveAction(id, action).then((r) => {
      if (r.ok) {
        // Server-authoritative state — handles dupes, partial fails.
        setSavedIds(new Set(r.saves));
        return;
      }
      setSavedIds(prev => {
        const next = new Set(prev);
        if (wasSaved) next.add(id);
        else next.delete(id);
        return next;
      });
      if (r.error === "save_cap_reached") {
        // Telemetry — save-cap is a paywall surface even though it
        // presents as a toast today (BACKLOG: convert to inline upgrade
        // card on Saved page).
        track("paywall.shown", { kind: "save_cap", listing_id: id });
        showToast("Free plan caps at 10 saves — upgrade to keep adding.");
      } else if (r.status === 401) {
        showToast("Sign in to save listings.");
      } else {
        showToast("Couldn't save — try again.");
      }
    });
  }, [clerkUserId, showToast, locale]);

  const openSignup = useCallback((cfg = {}) => {
    // Telemetry — fire `signup_modal.shown` once per open. Trigger is
    // derived from the cfg we received (so callers don't have to pass
    // it explicitly): pendingSave → heart, pendingAction:checkout →
    // checkout, pendingListing → pendingListing, otherwise manual /
    // paywall by inspection.
    let trigger = "manual";
    if (cfg.pendingSave) trigger = "heart";
    else if (cfg.pendingAction === "checkout") trigger = "checkout";
    else if (cfg.pendingListing) trigger = "pendingListing";
    track("signup_modal.shown", {
      trigger,
      mode: cfg.mode === "login" ? "login" : "signup",
    });
    setSignupModal(cfg);
  }, []);
  const closeSignup = useCallback(() => setSignupModal(null), []);

  const signin = useCallback(({ email, provider }) => {
    // Just flip user state. The post-signin effect above closes the
    // modal AND chains any pending action — keeping the wiring in one
    // place so Clerk and legacy paths behave identically.
    setUser({ email, provider: provider || "email", joined: Date.now() });
    showToast(t("toast.welcome", locale));
  }, [showToast, locale]);

  const signout = useCallback(() => {
    if (isSigningOut) return; // re-entry guard for double-clicks
    setIsSigningOut(true);
    track("auth.signout_started", { had_clerk_actions: !!clerkActions });

    // Clerk path: clear the Clerk session FIRST. Without this,
    // ClerkUserSync would re-hydrate the user from Clerk's persisted
    // cookie on the next render — local setUser(null) gets undone
    // immediately and the user appears to never log out. clerkActions
    // becomes truthy when ClerkActionsBinder has wired up; if it
    // isn't yet (very early click) we fall through and at least clear
    // local state.
    const finish = () => {
      setUser(null);
      setDetailViewCount(0);
      showToast(t("toast.logged_out", locale));
      setIsSigningOut(false);
    };

    if (clerkActions && typeof clerkActions.signOut === "function") {
      // Hard ceiling: 3s. If Clerk's signOut hangs (network blip,
      // SDK error code we didn't catch) we still clear local state so
      // the user isn't stuck staring at a disabled button.
      let done = false;
      const safeFinish = () => { if (!done) { done = true; finish(); } };
      const timeout = setTimeout(safeFinish, 3000);
      Promise.resolve()
        .then(() => clerkActions.signOut())
        .catch((err) => {
          if (typeof console !== "undefined" && console.warn) {
            console.warn("[pulpo] clerk.signOut failed:", err);
          }
        })
        .finally(() => { clearTimeout(timeout); safeFinish(); });
      return;
    }
    finish();
  }, [clerkActions, isSigningOut, showToast, locale]);

  const recordDetailView = useCallback(() => setDetailViewCount(c => c + 1), []);

  // Live listings — fetched once on mount, drives every page below.
  const listings = useListings();
  const listingsState = useListingsState();

  // Resolve the open listing once (used both by route-meta below and
  // the detail overlay further down). null while listings.json is still
  // loading OR if the id doesn't resolve (deleted/sold).
  const _openListingObj = openListingId
    ? listings.find(l => l.id === openListingId)
    : null;

  // Per-route document title + OG meta + canonical + hreflang.
  // Listing detail uses the resolved listing; sections fall back to the
  // section-specific copy in metaForSection.
  const _routeSearch = typeof window !== "undefined" ? window.location.search : "";
  useDocumentMeta({
    route,
    locale,
    listing: _openListingObj || null,
    search: _routeSearch,
  });

  // Route gate enforcement — runs whenever the route or user changes.
  // /saved and /account require >= free; anonymous users get the
  // sign-in modal as an overlay (URL stays put so post-signin the
  // content slot is already correct, no second redirect).
  //
  // The gate doesn't render anything itself — this effect just opens
  // the modal. The page components show a placeholder behind it.
  useEffect(() => {
    // Pass current URL search params so route-gates.ts can honour the
    // `?welcome=1` bypass for /account (post-Stripe / post-magic-link
    // landing where the user has paid but doesn't have a Clerk session
    // yet — PR-B.4b).
    const searchParams = typeof window !== "undefined"
      ? new URLSearchParams(window.location.search)
      : undefined;
    const outcome = evaluateGate(route, user, searchParams);
    if (outcome.kind === "modal") {
      // Already in a signup/login flow? Don't re-fire.
      if (signupModal && (signupModal.mode === "login" || signupModal.mode === "signup")) {
        return;
      }
      // Open login modal with the current route as the post-login
      // destination so the post-signin chain effect lands them right
      // back here.
      setSignupModal({
        mode: "login",
        postLoginRoute: outcome.postLoginRoute,
        gateReason: "auth_required",
      });
      track("signup_modal.shown", { trigger: "manual", mode: "login" });
    }
    // Intentionally not depending on signupModal — that would re-fire
    // every time the modal closes. We only care about route + user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, user]);

  // PR-B.5 — home-page Pulpo Pro upsell modal. Triggered by HomePage's
  // mount-time effect when the URL carries a campaign signal (see
  // lib/upsell-config.ts). State is { trigger, urlCode, utms } or null
  // when not open. App owns it (rather than HomePage) so the modal can
  // outlive a route change if needed.
  const [proUpsellModal, setProUpsellModal] = useState(null);
  const openProUpsellModal = useCallback((cfg) => setProUpsellModal(cfg), []);
  const closeProUpsellModal = useCallback(() => setProUpsellModal(null), []);

  const app = {
    route, routeParams, go, goBrowse,
    user, signin, signout, isSigningOut,
    savedIds, toggleSave,
    signupModal, openSignup, closeSignup,
    proUpsellModal, openProUpsellModal, closeProUpsellModal,
    openListing, closeListing, openListingId,
    detailViewCount, recordDetailView,
    showToast, toast,
    locale, setLocale,
    units, setUnits,
    showShelfBlur: true,
    tweaks,
    listings,
    listingsState,
    clerkActions,
  };

  const openListingObj = _openListingObj;
  // Detail panel pending state: URL says /listing/:id but listings.json
  // hasn't resolved yet, OR the id doesn't match a known listing.
  const listingPending = openListingId && !openListingObj && listingsState.status === "loading";
  const listingMissing = openListingId && !openListingObj && listingsState.status !== "loading";

  return (
    // <ClerkShell> mounts <ClerkProvider> only when VITE_USE_CLERK=1.
    // Flag off → returns children unchanged. Flag on → also mounts a
    // ClerkUserSync inside the provider that maps Clerk's user to
    // App's `setUser` so every downstream `app.user` reader works
    // unchanged. Lives inside App so `setUser` is in scope.
    <ClerkShell setUser={setUser} onClerkActions={setClerkActions}>
    <div className={`app density-${tweaks.density}`}>
      <TopNav app={app} />
      <main className="main">
        {route === "home" && (USE_NEW_HOMEPAGE ? <NewHomePage app={app} /> : <HomePage app={app} />)}
        {route === "browse" && <BrowsePage app={app} />}
        {route === "saved" && <SavedPage app={app} />}
        {route === "plans" && <PlansPage app={app} />}
        {route === "account" && <AccountPage app={app} />}
      </main>

      {route !== "browse" && (route !== "account" || tweaks.showFooterOnAccount) && (
        <footer className="site-footer">
          <div className="footer-inner">
            <div className="footer-brand">
              <PulpoLogo size={20}/>
              <p>{t("footer.tagline", locale)}</p>
              <div className="footer-country">🇸🇻 {t("footer.country_badge", locale)}</div>
            </div>
            <div className="footer-cols">
              <div>
                <h5>Browse</h5>
                <button className="link-btn" onClick={() => goBrowse({ category: "beachfront" })}>Beachfront</button>
                <button className="link-btn" onClick={() => goBrowse({ category: "build_ready" })}>Build-ready</button>
                <button className="link-btn" onClick={() => goBrowse({ category: "off_market" })}>Off-market</button>
                <button className="link-btn" onClick={() => goBrowse({ category: "agricultural" })}>Agricultural</button>
              </div>
              <div>
                <h5>Pulpo</h5>
                <button className="link-btn" onClick={() => go("plans")}>Plans</button>
                <a className="link-btn">About</a>
                <a className="link-btn">Newsletter</a>
                <a className="link-btn">Press</a>
              </div>
              <div>
                <h5>Legal</h5>
                <a className="link-btn">Terms</a>
                <a className="link-btn">Privacy</a>
                <a className="link-btn">Contact</a>
              </div>
            </div>
          </div>
          <div className="footer-fine">© 2026 Pulpo · A discovery-first land investment marketplace</div>
        </footer>
      )}

      <BottomNav app={app} />

      {(openListingObj || listingPending || listingMissing) && (
        <div className="detail-overlay" onClick={() => closeListing()}>
          <div className="detail-panel" onClick={(e) => e.stopPropagation()}>
            {openListingObj ? (
              <ListingDetail listing={openListingObj} app={app} asPanel={true} />
            ) : listingPending ? (
              <div className="detail-panel-pending" aria-busy="true" aria-live="polite">
                <div className="detail-panel-pending-photo" />
                <div className="detail-panel-pending-block" />
                <div className="detail-panel-pending-block" style={{ width: "60%" }} />
                <div className="detail-panel-pending-block" style={{ width: "80%" }} />
              </div>
            ) : (
              <div className="detail-panel-empty">
                <p>{locale === "es"
                  ? "Este anuncio ya no está disponible."
                  : "This listing is no longer available."}</p>
                <button className="link-btn" onClick={() => closeListing()}>
                  {locale === "es" ? "Volver a Descubrir" : "Back to Discover"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      <SignupModal app={app} />
      {welcomeModalState && (
        <WelcomeModal
          app={app}
          state={welcomeModalState}
          onClose={closeWelcomeModal}
        />
      )}
      {proUpsellModal && (
        <ProUpsellModal
          app={app}
          trigger={proUpsellModal.trigger}
          urlCode={proUpsellModal.urlCode}
          utms={proUpsellModal.utms}
          onClose={closeProUpsellModal}
        />
      )}
      <ToastHost app={app} />
      <ConsentBanner locale={locale} />

      {__PULPO_DEV_PANEL__ && showDevPanel && (
      <TweaksPanel>
        <TweakSection label="Layout" />
        <TweakRadio
          label="Density"
          value={tweaks.density}
          options={["comfortable", "compact"]}
          onChange={(v) => setTweak("density", v)}
        />
        <TweakToggle
          label="Show 'Find Your Style' carousel"
          value={tweaks.showStyleCarousel}
          onChange={(v) => setTweak("showStyleCarousel", v)}
        />
        <TweakToggle
          label="Show footer on Account page"
          value={tweaks.showFooterOnAccount}
          onChange={(v) => setTweak("showFooterOnAccount", v)}
        />

        <TweakSection label="Locale" />
        <TweakRadio
          label="Language"
          value={locale}
          options={[
            { value: "en", label: "EN" },
            { value: "es", label: "ES" },
          ]}
          onChange={(v) => setLocale(v)}
        />

        <TweakSection label="Quick nav" />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "0 12px 12px" }}>
          <TweakButton onClick={() => go("home")}>Discover</TweakButton>
          <TweakButton onClick={() => goBrowse({})}>Browse</TweakButton>
          <TweakButton onClick={() => go("saved")}>Saved</TweakButton>
          <TweakButton onClick={() => go("plans")}>Plans</TweakButton>
          <TweakButton onClick={() => go("account", { section: "profile" })}>Account · Profile</TweakButton>
          <TweakButton onClick={() => go("account", { section: "notifications" })}>· Notifs</TweakButton>
          <TweakButton onClick={() => go("account", { section: "subscription" })}>· Subscription</TweakButton>
          <TweakButton onClick={() => go("account", { section: "security" })}>· Security</TweakButton>
        </div>
      </TweaksPanel>
      )}

      {__PULPO_DEV_PANEL__ && debug && <DebugPanel app={app} />}
    </div>
    </ClerkShell>
  );
}

// QA-only debug panel — visible when URL has ?debug=1.
function DebugPanel({ app }) {
  const [open, setOpen] = useState(true);
  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        style={{ position: "fixed", bottom: 16, right: 16, zIndex: 999,
          padding: "8px 12px", borderRadius: 999,
          background: "#111", color: "#fff", fontSize: 12, fontFamily: "monospace" }}
      >debug</button>
    );
  }
  const row = { display: "flex", gap: 6, flexWrap: "wrap" };
  const btn = { padding: "6px 10px", borderRadius: 6, fontSize: 12,
    background: "#222", color: "#fff", fontFamily: "monospace" };
  return (
    <div style={{ position: "fixed", bottom: 16, right: 16, zIndex: 999,
      width: 260, padding: 12, borderRadius: 10,
      background: "rgba(20,20,20,0.96)", color: "#fff",
      fontFamily: "monospace", fontSize: 12,
      display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong>Debug · QA only</strong>
        <button onClick={() => setOpen(false)} style={{ color: "#aaa" }}>×</button>
      </div>
      <div>auth: {app.user ? app.user.email : "logged out"}</div>
      <div>detail views: {app.detailViewCount}</div>
      <div style={row}>
        <button style={btn} onClick={() => app.user ? app.signout() : app.signin({ email: "demo@pulpo.club" })}>
          {app.user ? "log out" : "log in"}
        </button>
      </div>
      <div style={row}>
        <button style={btn} onClick={() => { localStorage.setItem("pulpo-detail-views", "0"); window.location.reload(); }}>views=0</button>
        <button style={btn} onClick={() => { localStorage.setItem("pulpo-detail-views", "5"); window.location.reload(); }}>views=5</button>
        <button style={btn} onClick={() => { localStorage.setItem("pulpo-detail-views", "8"); window.location.reload(); }}>views=8</button>
      </div>
    </div>
  );
}

// Mount-time route branch. /start is a public marketing surface that
// renders without the app shell (no TopNav, no BottomNav, no
// ListingsProvider). It's a hard navigation away from the SPA — not
// state-routed — so we dispatch on the pathname before <App /> runs.
// The chunk is dynamically imported so it only loads when the user
// is actually on /start; the SPA bundle stays clean for everyone else.
//
// /welcome was previously a sibling here; PR-B.4b replaced it with a
// modal on /account?welcome=1, so the page is gone.
(() => {
  const path = typeof window !== "undefined" ? window.location.pathname : "/";
  const root = ReactDOM.createRoot(document.getElementById("root"));
  if (path === "/start" || path === "/start/") {
    import("./start.jsx").then((mod) => {
      const StartPage = mod.default;
      root.render(
        <ErrorBoundary>
          <StartPage />
        </ErrorBoundary>
      );
    });
    return;
  }
  root.render(
    <ErrorBoundary>
      <ListingsProvider>
        <App />
      </ListingsProvider>
    </ErrorBoundary>
  );
})();
