// Wave-3a: single site header used on every route. Replaces the
// bespoke HomepageHeader (home-only) and the inline TopNav that lived
// in pages.jsx. The TopNav-style design is what wins on every non-home
// page today; the homepage now uses the same chrome and lets the hero
// own its CTAs.
//
// Active-state highlighting tracks `app.route`. Section nav reads:
//   Home / Discover / Favorites
// URL paths still say /, /browse, /saved — the URL rename is Wave 3b
// (gated on a PostHog dashboard audit).
//
// Telemetry: nav clicks pass through `app.go(...)` and indirectly fire
// `route.changed`. No header-specific click events are added in
// Wave 3a — the engagement plan reserves a new `chrome_nav_clicked`
// event for Wave 3b's broader chrome instrumentation.

import React from "react";
import { t, LOCALES } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { Icon, PulpoLogo } from "../components.jsx";
import { LiveStats } from "./LiveStats.jsx";

// Compact EN/ES toggle. Only used by SiteHeader so it lives here.
function LocaleToggle({ app }) {
  return (
    <div className="locale-toggle" role="group" aria-label={t("locale.toggle_aria", app.locale)}>
      {LOCALES.map(lc => (
        <button
          key={lc}
          className={app.locale === lc ? "active" : ""}
          onClick={() => {
            const prev = app.locale;
            if (prev !== lc) {
              track("locale.changed", { from: prev, to: lc });
            }
            app.setLocale(lc);
          }}
        >
          {lc.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export function SiteHeader({ app }) {
  const lc = app.locale;
  return (
    <header className="topnav" data-testid="site-header">
      <div className="topnav-inner">
        <button className="logo-btn" onClick={() => app.go("home")} aria-label={t("nav.home", lc)}>
          <PulpoLogo />
        </button>
        <nav className="topnav-links" aria-label={t("nav.home", lc)}>
          <button
            className={app.route === "home" ? "active" : ""}
            onClick={() => app.go("home")}
          >
            {t("nav.home", lc)}
          </button>
          <button
            className={app.route === "browse" ? "active" : ""}
            onClick={() => app.go("browse")}
          >
            {t("nav.discover", lc)}
          </button>
          <button
            className={app.route === "saved" ? "active" : ""}
            onClick={() => app.go("saved")}
          >
            {t("nav.favorites", lc)}
            {app.savedIds.size > 0 && (
              <span className="count-badge">{app.savedIds.size}</span>
            )}
          </button>
        </nav>
        <div className="topnav-right">
          <LiveStats locale={lc} />
          <LocaleToggle app={app} />
          {app.user ? (
            <div className="profile-chip">
              <button
                className="avatar avatar-btn"
                onClick={() => app.go("account")}
                title={t("nav.account", lc)}
                aria-label={t("nav.account", lc)}
              >{app.user.email[0].toUpperCase()}</button>
              <button
                className="link-btn"
                onClick={() => app.signout()}
                disabled={app.isSigningOut}
                aria-busy={app.isSigningOut || undefined}
              >{t("nav.logout", lc)}</button>
            </div>
          ) : (
            <button
              className="topnav-auth-icon"
              onClick={() => app.openSignup({ mode: "login" })}
              aria-label={t("nav.account_or_sign_in", lc)}
              title={t("nav.account_or_sign_in", lc)}
            >
              <Icon name="user" size={20}/>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
