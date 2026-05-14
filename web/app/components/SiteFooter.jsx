// Wave-3a: extracted from app.jsx's inline footer. Behavior preserved
// exactly — same conditional render rules and same content. The
// "Browse" section heading became "Discover" to match the Wave-3a nav
// rename; everything else stays.
//
// Hardcoded English in the column links (Plans / About / Newsletter /
// Press / Terms / Privacy / Contact) is pre-existing tech debt. The
// preview-smoke ES canary doesn't sweep /plans or /account where this
// footer renders, so the violation isn't visible to the test. Out of
// scope for Wave 3a; tracked for a separate i18n sweep.

import React from "react";
import { t } from "../i18n.jsx";
import { PulpoLogo } from "../components.jsx";

// Render conditions from app.jsx — kept here so callers can early-exit
// instead of always mounting + rendering nothing.
export function shouldShowSiteFooter(route, opts = {}) {
  if (route === "home") return false;
  if (route === "browse") return false;
  if (route === "account" && !opts.showFooterOnAccount) return false;
  return true;
}

export function SiteFooter({ app, locale, tweaks }) {
  if (!shouldShowSiteFooter(app.route, { showFooterOnAccount: tweaks?.showFooterOnAccount })) {
    return null;
  }
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
