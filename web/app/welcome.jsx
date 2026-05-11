// /welcome — post-payment landing for the anonymous /start flow.
//
// The user has just completed Stripe Checkout. The webhook is creating
// (or has just created) a Clerk invitation to the email they submitted;
// Clerk's hosted email sends them a link to set their password. This
// page is the "we sent it, check your inbox" reassurance + a fallback
// CTA to head to the main app.
//
// No app shell — same mount-time branch in app.jsx that handles /start.
import React, { useEffect } from "react";
import { t, useLocale } from "./i18n.jsx";
import { PulpoLogo } from "./components.jsx";
import { track } from "./telemetry/hook";
import "./styles/welcome.css";

export default function WelcomePage() {
  const [locale] = useLocale();

  useEffect(() => {
    track("welcome.viewed", {});
  }, []);

  return (
    <div className="welcome-page">
      <header className="welcome-nav">
        <a href="/" className="welcome-logo" aria-label="Pulpo home">
          <PulpoLogo size={28} />
        </a>
      </header>
      <main className="welcome-main">
        <div className="welcome-card">
          <div className="welcome-icon" aria-hidden="true">📬</div>
          <h1 className="welcome-headline">{t("welcome.headline", locale)}</h1>
          <p className="welcome-body">{t("welcome.body", locale)}</p>
          <a className="welcome-cta" href="/">
            {t("welcome.cta", locale)}
          </a>
          <a className="welcome-resend" href="mailto:hello@pulpo.club">
            {t("welcome.resend_link", locale)}
          </a>
        </div>
      </main>
    </div>
  );
}
