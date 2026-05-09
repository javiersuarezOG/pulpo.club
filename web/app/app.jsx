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
  ToastHost,
  ConsentBanner,
} from "./pages.jsx";
import { AccountPage } from "./account.jsx";
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
import { bootAssetTelemetry } from "./telemetry/asset-load";
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

  const [route, setRoute] = useState("home");
  const [routeParams, setRouteParams] = useState({});
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
  // Hot-line for triggering Clerk's hosted sign-in / sign-up modal
  // imperatively, without a click-time Suspense boundary that would
  // throw React #426. <ClerkActionsBinder> inside ClerkShell wires
  // this up once the SDK loads (flag-on only); SignupModal calls it.
  const [clerkActions, setClerkActions] = useState(null);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [toast, setToast] = useState(null);
  const [openListingId, setOpenListingId] = useState(null);
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
    bootWebVitals();
    bootAssetTelemetry();
  }, []);

  // Marquee the document.title so the tab text scrolls like a
  // marquesina. Pure-cosmetic — pauses entirely when the user has
  // `prefers-reduced-motion: reduce` set (accessibility — animated
  // tab titles can be disorienting). Resets to the original on
  // unmount so the tab doesn't keep a stale rotated state.
  useEffect(() => {
    if (typeof window === "undefined" || !document) return;
    const reduce = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;
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
    // 320ms per char ≈ Pulpo (5 letters + space) every ~2s. Faster
    // becomes flicker on macOS Safari; slower reads as broken.
    const id = setInterval(tick, 320);
    return () => {
      clearInterval(id);
      document.title = original;
    };
  }, []);

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

  const go = useCallback((r, params = {}) => {
    const from = route;
    setRoute(r); setRouteParams(params); setOpenListingId(null);
    window.scrollTo(0, 0);
    if (from !== r) _measure("perf.route_transition", { from, to: r });
  }, [route, _measure]);
  const goBrowse = useCallback((params = {}) => {
    const from = route;
    setRoute("browse"); setRouteParams(params); setOpenListingId(null);
    window.scrollTo(0, 0);
    if (from !== "browse") _measure("perf.route_transition", { from, to: "browse" });
  }, [route, _measure]);
  const openListing = useCallback((id) => {
    setOpenListingId(id);
    _measure("perf.detail_open", { listing_id: id });
  }, [_measure]);
  const closeListing = useCallback(() => setOpenListingId(null), []);

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

  const app = {
    route, routeParams, go, goBrowse,
    user, signin, signout, isSigningOut,
    savedIds, toggleSave,
    signupModal, openSignup, closeSignup,
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

  const openListingObj = openListingId ? listings.find(l => l.id === openListingId) : null;

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
        {route === "home" && <HomePage app={app} />}
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

      {openListingObj && (
        <div className="detail-overlay" onClick={() => closeListing()}>
          <div className="detail-panel" onClick={(e) => e.stopPropagation()}>
            <ListingDetail listing={openListingObj} app={app} asPanel={true} />
          </div>
        </div>
      )}

      <SignupModal app={app} />
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

ReactDOM.createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <ListingsProvider>
      <App />
    </ListingsProvider>
  </ErrorBoundary>
);
