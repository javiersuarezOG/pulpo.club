// Wave-3a: extracted from app.jsx's inline footer.
//
// Post-Wave-5 split into two variants:
//   * Trimmed (home + browse + all legal-suite pages):
//     one row — country badge · © · legal links · cookie preferences.
//   * Full (saved + plans + account-when-enabled): the 4-column layout
//     with Discover / Pulpo / Legal columns + tagline.
//
// Legal-suite (feat/footer-legal-links):
//   * Trimmed + full footer now link to real /terms /privacy /cookies
//     /subscription /imprint /contact routes — the previous spans + dead
//     anchors were the audit's P0-2 finding.
//   * A "Cookie Preferences" button in both variants calls
//     `openConsentPreferences()` which clears the persisted consent
//     decision and re-shows the ConsentBanner. GDPR Art. 7(3) requires
//     withdrawal to be as easy as giving consent.
//   * All footer-link clicks fire `footer.link_clicked` with the link
//     key + surface variant.

import React from "react";
import { t } from "../i18n.jsx";
import { PulpoLogo } from "../components.jsx";
import { track } from "../telemetry/client";
import { openConsentPreferences } from "../lib/consent";

// Render conditions. Account opts in via a tweak; everything else
// (home / browse / saved / plans / legal-suite pages) renders by
// default.
export function shouldShowSiteFooter(route, opts = {}) {
  if (route === "account" && !opts.showFooterOnAccount) return false;
  return true;
}

// Variant resolution. Marketing landing surfaces + the legal-suite
// pages get the trimmed footer. Utility pages (saved/plans) get the
// full layout.
export function siteFooterVariant(route) {
  if (route === "home" || route === "browse") return "trimmed";
  // Legal pages are content-dense in their own right — trimmed footer
  // keeps the chrome minimal so the reading column stays the focus.
  if (
    route === "terms" ||
    route === "privacy" ||
    route === "cookies" ||
    route === "subscription" ||
    route === "imprint" ||
    route === "contact"
  ) {
    return "trimmed";
  }
  return "full";
}

// Shared link-click helper. Fires `footer.link_clicked` then navigates.
// `linkKey` is the stable analytics identifier (NOT the user-visible
// label, which is locale-dependent).
function navigateAndTrack(app, surface, linkKey, target) {
  track("footer.link_clicked", { link: linkKey, surface });
  if (typeof target === "function") {
    target();
  } else if (target) {
    app.go(target);
  }
}

function CookiePreferencesButton({ surface, className, locale }) {
  return (
    <button
      type="button"
      className={className}
      onClick={() => {
        track("footer.link_clicked", { link: "cookie_preferences", surface });
        track("consent.preferences_opened", { source: "footer" });
        openConsentPreferences();
      }}
    >
      {t("footer.link.cookie_preferences", locale)}
    </button>
  );
}

function SiteFooterTrimmed({ app, locale }) {
  const year = new Date().getFullYear();
  return (
    <footer className="site-footer site-footer-trimmed">
      <div className="footer-trim-inner">
        <span className="footer-trim-badge">🇸🇻 {t("footer.country_badge", locale)}</span>
        <span className="footer-trim-sep" aria-hidden="true">·</span>
        <span className="footer-trim-copy">{t("footer.fine_print", locale, { year })}</span>
        <span className="footer-trim-sep" aria-hidden="true">·</span>
        <button
          type="button"
          className="footer-trim-link link-btn"
          onClick={() => navigateAndTrack(app, "trimmed", "terms", "terms")}
        >
          {t("footer.link.terms", locale)}
        </button>
        <span className="footer-trim-sep" aria-hidden="true">·</span>
        <button
          type="button"
          className="footer-trim-link link-btn"
          onClick={() => navigateAndTrack(app, "trimmed", "privacy", "privacy")}
        >
          {t("footer.link.privacy", locale)}
        </button>
        <span className="footer-trim-sep" aria-hidden="true">·</span>
        <button
          type="button"
          className="footer-trim-link link-btn"
          onClick={() => navigateAndTrack(app, "trimmed", "cookies", "cookies")}
        >
          {t("footer.link.cookies", locale)}
        </button>
        <span className="footer-trim-sep" aria-hidden="true">·</span>
        <button
          type="button"
          className="footer-trim-link link-btn"
          onClick={() => navigateAndTrack(app, "trimmed", "contact", "contact")}
        >
          {t("footer.link.contact", locale)}
        </button>
        <span className="footer-trim-sep" aria-hidden="true">·</span>
        <CookiePreferencesButton
          surface="trimmed"
          className="footer-trim-link link-btn"
          locale={locale}
        />
      </div>
    </footer>
  );
}

function SiteFooterFull({ app, locale }) {
  const year = new Date().getFullYear();
  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <div className="footer-brand">
          <PulpoLogo size={20}/>
          <p>{t("footer.tagline", locale)}</p>
          <div className="footer-country">🇸🇻 {t("footer.country_badge", locale)}</div>
        </div>
        <div className="footer-cols">
          <div>
            <h5>{t("footer.col.discover.heading", locale)}</h5>
            <button
              className="link-btn"
              onClick={() => {
                track("footer.link_clicked", { link: "discover.beachfront", surface: "full" });
                app.goBrowse({ category: "beachfront" });
              }}
            >
              {t("footer.col.discover.beachfront", locale)}
            </button>
            <button
              className="link-btn"
              onClick={() => {
                track("footer.link_clicked", { link: "discover.build_ready", surface: "full" });
                app.goBrowse({ category: "build_ready" });
              }}
            >
              {t("footer.col.discover.build_ready", locale)}
            </button>
            <button
              className="link-btn"
              onClick={() => {
                track("footer.link_clicked", { link: "discover.off_market", surface: "full" });
                app.goBrowse({ category: "off_market" });
              }}
            >
              {t("footer.col.discover.off_market", locale)}
            </button>
            <button
              className="link-btn"
              onClick={() => {
                track("footer.link_clicked", { link: "discover.agricultural", surface: "full" });
                app.goBrowse({ category: "agricultural" });
              }}
            >
              {t("footer.col.discover.agricultural", locale)}
            </button>
          </div>
          <div>
            <h5>{t("footer.col.pulpo.heading", locale)}</h5>
            <button
              className="link-btn"
              onClick={() => navigateAndTrack(app, "full", "plans", "plans")}
            >
              {t("footer.col.pulpo.plans", locale)}
            </button>
            <button
              className="link-btn"
              onClick={() => navigateAndTrack(app, "full", "subscription", "subscription")}
            >
              {t("footer.link.subscription", locale)}
            </button>
            <button
              className="link-btn"
              onClick={() => navigateAndTrack(app, "full", "contact", "contact")}
            >
              {t("footer.link.contact", locale)}
            </button>
          </div>
          <div>
            <h5>{t("footer.col.legal.heading", locale)}</h5>
            <button
              className="link-btn"
              onClick={() => navigateAndTrack(app, "full", "terms", "terms")}
            >
              {t("footer.link.terms", locale)}
            </button>
            <button
              className="link-btn"
              onClick={() => navigateAndTrack(app, "full", "privacy", "privacy")}
            >
              {t("footer.link.privacy", locale)}
            </button>
            <button
              className="link-btn"
              onClick={() => navigateAndTrack(app, "full", "cookies", "cookies")}
            >
              {t("footer.link.cookies", locale)}
            </button>
            <button
              className="link-btn"
              onClick={() => navigateAndTrack(app, "full", "imprint", "imprint")}
            >
              {t("footer.link.imprint", locale)}
            </button>
            <CookiePreferencesButton
              surface="full"
              className="link-btn"
              locale={locale}
            />
          </div>
        </div>
      </div>
      <div className="footer-fine">{t("footer.fine_print_full", locale, { year })}</div>
    </footer>
  );
}

export function SiteFooter({ app, locale, tweaks }) {
  if (!shouldShowSiteFooter(app.route, { showFooterOnAccount: tweaks?.showFooterOnAccount })) {
    return null;
  }
  const variant = siteFooterVariant(app.route);
  return variant === "trimmed"
    ? <SiteFooterTrimmed app={app} locale={locale} />
    : <SiteFooterFull app={app} locale={locale} />;
}
