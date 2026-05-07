// Pulpo — main app shell, router, auth state.
// Visual design baked in: palette=pulpo (white & deep green),
// hero=magazine, density=comfortable, corners=default,
// base-size=15px, font-theme=editorial.
// Production flows preserved: auth (signup/login/logout), saved listings,
// detail-view paywall (soft prompt @5, hard gate @8), locale, toasts.
// QA helpers exposed via ?debug=1 URL flag (no UI in production).
import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import ReactDOM from "react-dom/client";
import { t, useLocale } from "./i18n.jsx";
import { LISTINGS } from "./data.jsx";
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
import { track } from "./telemetry/hook";
import { bootWebVitals } from "./telemetry/web-vitals";
import "./styles/index.css";

function App() {
  // Tweakable defaults — host rewrites this block when the user changes a tweak,
  // so values persist across reloads.
  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "authState": "signed_out",
    "density": "comfortable",
    "showStyleCarousel": true,
    "showFooterOnAccount": false
  }/*EDITMODE-END*/;
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);

  const [route, setRoute] = useState("home");
  const [routeParams, setRouteParams] = useState({});
  const [locale, setLocale] = useLocale();
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("pulpo-user")) || null; } catch { return null; }
  });

  // Auth-state tweak — overrides persisted user when set to a non-default value.
  // Lets the user preview the full app from any auth perspective without
  // having to manually log in/out.
  useEffect(() => {
    if (tweaks.authState === "signed_out") {
      setUser(null);
    } else if (tweaks.authState === "signed_in_free") {
      setUser({ email: "you@pulpo.club", name: "Demo User", plan: "free", joined: Date.now() });
    } else if (tweaks.authState === "signed_in_pro") {
      setUser({ email: "you@pulpo.club", name: "Demo User", plan: "pro", joined: Date.now() });
    }
  }, [tweaks.authState]);
  const [savedIds, setSavedIds] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem("pulpo-saved")) || []); } catch { return new Set(); }
  });
  const [signupModal, setSignupModal] = useState(null);
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

  const go = useCallback((r, params = {}) => {
    setRoute(r); setRouteParams(params); setOpenListingId(null);
    window.scrollTo(0, 0);
  }, []);
  const goBrowse = useCallback((params = {}) => {
    setRoute("browse"); setRouteParams(params); setOpenListingId(null);
    window.scrollTo(0, 0);
  }, []);
  const openListing = useCallback((id) => setOpenListingId(id), []);
  const closeListing = useCallback(() => setOpenListingId(null), []);

  const toggleSave = useCallback((id) => {
    setSavedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) { next.delete(id); showToast(t("toast.removed", locale)); }
      else { next.add(id); showToast(t("toast.saved", locale)); }
      return next;
    });
  }, [showToast]);

  const openSignup = useCallback((cfg = {}) => setSignupModal(cfg), []);
  const closeSignup = useCallback(() => setSignupModal(null), []);

  const signin = useCallback(({ email, provider }) => {
    setUser({ email, provider: provider || "email", joined: Date.now() });
    const pendingSave = signupModal?.pendingSave;
    const pendingListing = signupModal?.pendingListing;
    setSignupModal(null);
    if (pendingSave) setSavedIds(prev => new Set([...prev, pendingSave]));
    showToast(t("toast.welcome", locale));
    if (pendingListing) setTimeout(() => setOpenListingId(pendingListing), 400);
  }, [signupModal, showToast]);

  const signout = useCallback(() => {
    setUser(null); setDetailViewCount(0);
    showToast(t("toast.logged_out", locale));
  }, [showToast, locale]);

  const recordDetailView = useCallback(() => setDetailViewCount(c => c + 1), []);

  const app = {
    route, routeParams, go, goBrowse,
    user, signin, signout,
    savedIds, toggleSave,
    signupModal, openSignup, closeSignup,
    openListing, closeListing, openListingId,
    detailViewCount, recordDetailView,
    showToast, toast,
    locale, setLocale,
    showShelfBlur: true,
    tweaks,
  };

  const openListingObj = openListingId ? LISTINGS.find(l => l.id === openListingId) : null;

  return (
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

      {__PULPO_DEV_PANEL__ && showDevPanel && (
      <TweaksPanel>
        <TweakSection label="Auth state" />
        <TweakRadio
          label="Signed in as"
          value={tweaks.authState}
          options={[
            { value: "signed_out",     label: "Out" },
            { value: "signed_in_free", label: "Free" },
            { value: "signed_in_pro",  label: "Pro" },
          ]}
          onChange={(v) => setTweak("authState", v)}
        />

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
    <App />
  </ErrorBoundary>
);
