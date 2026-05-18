// Wave-3a: extracted from app.jsx's inline footer.
//
// Post-Wave-5 split into two variants:
//   * Trimmed (home + browse): one row — country badge · © · Terms · Privacy.
//     Marketing-surface footer. Aria-light, no column links.
//   * Full (saved + plans + account-when-enabled): the original 4-column
//     layout with Discover / Pulpo / Legal columns + tagline. Utility
//     pages where deeper navigation is appropriate.
//
// Hardcoded EN column labels in the full variant are pre-existing tech
// debt (called out in the file's prior header comment). The ES canary
// in preview-smoke.spec.ts only sweeps `/`, which now renders the
// trimmed variant — so the canary stays green without touching the
// full variant's debt. A separate i18n sweep is the right follow-up
// when those utility pages get a copy review.

import React from "react";
import { t } from "../i18n.jsx";
import { PulpoLogo } from "../components.jsx";

// Render conditions. Account opts in via a tweak; everything else
// (home / browse / saved / plans) renders by default now.
export function shouldShowSiteFooter(route, opts = {}) {
  if (route === "account" && !opts.showFooterOnAccount) return false;
  return true;
}

// Variant resolution. Marketing landing surfaces get the trimmed
// footer; utility pages get the full layout. Editing this is a
// one-line change.
export function siteFooterVariant(route) {
  if (route === "home" || route === "browse") return "trimmed";
  return "full";
}

function SiteFooterTrimmed({ locale }) {
  const year = new Date().getFullYear();
  return (
    <footer className="site-footer site-footer-trimmed">
      <div className="footer-trim-inner">
        <span className="footer-trim-badge">🇸🇻 {t("footer.country_badge", locale)}</span>
        <span className="footer-trim-sep" aria-hidden="true">·</span>
        <span className="footer-trim-copy">{t("footer.fine_print", locale, { year })}</span>
        <span className="footer-trim-sep" aria-hidden="true">·</span>
        <span className="footer-trim-link">{t("footer.link.terms", locale)}</span>
        <span className="footer-trim-sep" aria-hidden="true">·</span>
        <span className="footer-trim-link">{t("footer.link.privacy", locale)}</span>
      </div>
    </footer>
  );
}

function SiteFooterFull({ app, locale }) {
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
            <h5>Discover</h5>
            <button className="link-btn" onClick={() => app.goBrowse({ category: "beachfront" })}>Beachfront</button>
            <button className="link-btn" onClick={() => app.goBrowse({ category: "build_ready" })}>Build-ready</button>
            <button className="link-btn" onClick={() => app.goBrowse({ category: "off_market" })}>Off-market</button>
            <button className="link-btn" onClick={() => app.goBrowse({ category: "agricultural" })}>Agricultural</button>
          </div>
          <div>
            <h5>Pulpo</h5>
            <button className="link-btn" onClick={() => app.go("plans")}>Plans</button>
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
  );
}

export function SiteFooter({ app, locale, tweaks }) {
  if (!shouldShowSiteFooter(app.route, { showFooterOnAccount: tweaks?.showFooterOnAccount })) {
    return null;
  }
  const variant = siteFooterVariant(app.route);
  return variant === "trimmed"
    ? <SiteFooterTrimmed locale={locale} />
    : <SiteFooterFull app={app} locale={locale} />;
}
