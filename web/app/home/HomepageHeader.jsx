// Homepage v2 header. Renders only on route === "home" (app.jsx hides
// the shared TopNav there). Wordmark + nav links + Sign in + Start
// free month CTA. Mobile: wordmark + CTA + hamburger; clicking the
// hamburger opens a full-width sheet from the top with the links
// stacked, 48px tap targets. Focus is trapped while the sheet is
// open; Escape closes.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { PulpoLogo } from "../components.jsx";
import { IconMenu2, IconX, IconArrowRight } from "./icons.jsx";

const CTA_LOCATION = "header";

function fireSignup(app, mode) {
  if (!app || typeof app.openSignup !== "function") return;
  app.openSignup({ mode });
}

export function HomepageHeader({ app, locale }) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const closeBtnRef = useRef(null);
  const openBtnRef = useRef(null);

  const closeSheet = useCallback(() => {
    setSheetOpen((wasOpen) => {
      if (wasOpen) {
        try { track("mobile_nav.closed", {}); } catch { /* never crash on telemetry */ }
      }
      return false;
    });
  }, []);

  const openSheet = useCallback(() => {
    setSheetOpen(true);
    try { track("mobile_nav.opened", {}); } catch { /* never crash on telemetry */ }
  }, []);

  // Trap focus + escape-to-close while the sheet is open. The close
  // button gets focus on open; tab-cycle is limited to elements
  // inside the sheet via two sentinel divs.
  useEffect(() => {
    if (!sheetOpen) return;
    const prevActive = typeof document !== "undefined" ? document.activeElement : null;
    closeBtnRef.current?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeSheet();
      }
    };
    document.addEventListener("keydown", onKey);
    // Lock body scroll behind the sheet on small screens
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      // Restore focus to the trigger after close, so keyboard users
      // don't get punted to the document root.
      if (prevActive && typeof prevActive.focus === "function") {
        try { prevActive.focus(); } catch { /* ignore */ }
      } else {
        openBtnRef.current?.focus();
      }
    };
  }, [sheetOpen, closeSheet]);

  const goLake = useCallback(() => {
    closeSheet();
    try { track("mobile_nav.link_clicked", { link: "lake" }); } catch { /* ignore */ }
    if (app && typeof app.goBrowse === "function") {
      app.goBrowse({ master_category: "lake" });
    }
  }, [app, closeSheet]);

  const goBeach = useCallback(() => {
    closeSheet();
    try { track("mobile_nav.link_clicked", { link: "beach" }); } catch { /* ignore */ }
    if (app && typeof app.goBrowse === "function") {
      app.goBrowse({ master_category: "beach" });
    }
  }, [app, closeSheet]);

  const goHow = useCallback(() => {
    closeSheet();
    try { track("mobile_nav.link_clicked", { link: "how_it_works" }); } catch { /* ignore */ }
    if (typeof document === "undefined") return;
    const target = document.getElementById("why-pulpo");
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [closeSheet]);

  const goPricing = useCallback(() => {
    closeSheet();
    try { track("mobile_nav.link_clicked", { link: "pricing" }); } catch { /* ignore */ }
    if (app && typeof app.go === "function") {
      app.go("plans");
    }
  }, [app, closeSheet]);

  const onSignIn = useCallback(() => {
    closeSheet();
    try { track("mobile_nav.link_clicked", { link: "sign_in" }); } catch { /* ignore */ }
    fireSignup(app, "login");
  }, [app, closeSheet]);

  const onPrimaryCta = useCallback(() => {
    const label = t("home.header.cta", locale);
    try {
      track("homepage.cta_clicked", { location: CTA_LOCATION, cta_text: label });
    } catch { /* ignore */ }
    fireSignup(app, "signup");
  }, [app, locale]);

  return (
    <header className="hp-header" data-testid="hp-header">
      <div className="hp-header-inner">
        <button
          type="button"
          className="hp-header-logo"
          onClick={() => { if (app && typeof app.go === "function") app.go("home"); }}
          aria-label="Pulpo" // i18n-allow: brand name, identical in EN and ES
        >
          <PulpoLogo size={18} />
        </button>

        <nav className="hp-header-nav" aria-label={t("home.header.nav_aria", locale)}>
          <button type="button" className="hp-header-link" onClick={goLake}>
            {t("home.header.nav.lake", locale)}
          </button>
          <button type="button" className="hp-header-link" onClick={goBeach}>
            {t("home.header.nav.beach", locale)}
          </button>
          <button type="button" className="hp-header-link" onClick={goHow}>
            {t("home.header.nav.how", locale)}
          </button>
          <button type="button" className="hp-header-link" onClick={goPricing}>
            {t("home.header.nav.pricing", locale)}
          </button>
        </nav>

        <div className="hp-header-actions">
          <button type="button" className="hp-header-signin" onClick={onSignIn}>
            {t("home.header.signin", locale)}
          </button>
          <button type="button" className="hp-cta hp-cta-dark" onClick={onPrimaryCta}>
            <span>{t("home.header.cta", locale)}</span>
          </button>
          <button
            ref={openBtnRef}
            type="button"
            className="hp-header-burger"
            onClick={openSheet}
            aria-label={t("home.header.open_menu", locale)}
            aria-expanded={sheetOpen}
            aria-controls="hp-mobile-sheet"
          >
            <IconMenu2 size={22} strokeWidth={1.8} />
          </button>
        </div>
      </div>

      {sheetOpen ? (
        <div
          id="hp-mobile-sheet"
          className="hp-mobile-sheet"
          role="dialog"
          aria-modal="true"
          aria-label={t("home.header.open_menu", locale)}
        >
          <div className="hp-mobile-sheet-head">
            <PulpoLogo size={18} />
            <button
              ref={closeBtnRef}
              type="button"
              className="hp-mobile-sheet-close"
              onClick={closeSheet}
              aria-label={t("home.header.close_menu", locale)}
            >
              <IconX size={22} strokeWidth={1.8} />
            </button>
          </div>
          <nav className="hp-mobile-sheet-nav" aria-label={t("home.header.mobile_nav_aria", locale)}>
            <button type="button" className="hp-mobile-link" onClick={goLake}>
              {t("home.header.nav.lake", locale)}
            </button>
            <button type="button" className="hp-mobile-link" onClick={goBeach}>
              {t("home.header.nav.beach", locale)}
            </button>
            <button type="button" className="hp-mobile-link" onClick={goHow}>
              {t("home.header.nav.how", locale)}
            </button>
            <button type="button" className="hp-mobile-link" onClick={goPricing}>
              {t("home.header.nav.pricing", locale)}
            </button>
            <button type="button" className="hp-mobile-link" onClick={onSignIn}>
              {t("home.header.signin", locale)}
            </button>
          </nav>
          <div className="hp-mobile-sheet-cta">
            <button type="button" className="hp-cta hp-cta-dark hp-cta-block" onClick={() => { closeSheet(); onPrimaryCta(); }}>
              <span>{t("home.header.cta", locale)}</span>
              <IconArrowRight size={18} />
            </button>
          </div>
        </div>
      ) : null}
    </header>
  );
}
