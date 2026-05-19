// ContactPage — /contact route shell.
//
// This PR ships the route + visual scaffold ONLY. The actual form +
// `api/contact.js` submission land in a follow-up PR (legal-suite plan
// PR-F). Until then the page reads as a "Coming soon" placeholder with
// the topical inbox addresses surfaced so determined users can still
// reach us via direct email.
//
// Frontend non-negotiables:
//   - Responsive: same content column as LegalPage.
//   - i18n: every string via t().
//   - Telemetry: fires `legal.page_viewed` (slug=contact) on mount; the
//     real `contact.form_opened` / `contact.form_submitted` events land
//     with PR-F.
//   - Design tokens only.

import React, { useEffect } from "react";
import { useDocumentMeta } from "../../lib/use-document-meta";
import { t } from "../../i18n.jsx";
import { track } from "../../telemetry/client";

const PAGE_STYLES = `
.page-contact {
  max-width: 640px;
  margin: 0 auto;
  padding: 48px var(--section-pad, 24px) 96px;
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: var(--type-body-size);
  line-height: var(--type-body-line);
}
.page-contact__back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--type-card-meta-size);
  color: var(--ink-3);
  text-decoration: none;
  margin-bottom: 32px;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-family: inherit;
}
.page-contact__back:hover { color: var(--ink); }
.page-contact__title {
  font-family: var(--font-display);
  font-size: 36px;
  line-height: 44px;
  font-weight: 400;
  color: var(--ink);
  margin: 0 0 8px;
}
.page-contact__lede {
  font-size: var(--type-body-size);
  line-height: var(--type-body-line);
  color: var(--ink-2);
  margin: 0 0 32px;
}
.page-contact__placeholder {
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 24px;
  margin: 0 0 32px;
  font-size: var(--type-card-meta-size);
  color: var(--ink-2);
  line-height: 1.6;
}
.page-contact__inbox-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 12px;
}
.page-contact__inbox-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px;
  padding: 16px;
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.page-contact__inbox-label {
  font-size: var(--type-card-meta-size);
  font-weight: 600;
  color: var(--ink);
  margin: 0;
}
.page-contact__inbox-address {
  font-family: var(--font-mono);
  font-size: var(--type-card-meta-size);
  color: var(--ink-2);
  margin: 0;
}
@media (max-width: 599px) {
  .page-contact { padding: 24px 16px 80px; }
  .page-contact__title { font-size: 28px; line-height: 36px; }
}
`;

export function ContactPage({ app }) {
  const locale = app?.locale === "es" ? "es" : "en";

  useDocumentMeta({
    title: t("contact.page.title", locale),
    description: t("contact.page.description", locale),
  });

  useEffect(() => {
    track("legal.page_viewed", { page: "contact" });
  }, []);

  return (
    <div className="page page-contact" role="main">
      <style>{PAGE_STYLES}</style>
      <button
        type="button"
        className="page-contact__back"
        onClick={() => app.go("home")}
        aria-label={t("legal.back_to_home", locale)}
      >
        ← {t("legal.back_to_home", locale)}
      </button>

      <h1 className="page-contact__title">{t("contact.page.title", locale)}</h1>
      <p className="page-contact__lede">{t("contact.page.lede", locale)}</p>

      <div className="page-contact__placeholder" role="status">
        {t("contact.page.form_coming_soon", locale)}
      </div>

      <ul className="page-contact__inbox-list" aria-label={t("contact.page.inbox_list_label", locale)}>
        <li className="page-contact__inbox-row">
          <p className="page-contact__inbox-label">{t("contact.topic.general", locale)}</p>
          <p className="page-contact__inbox-address">contact@pulpo.club</p>
        </li>
        <li className="page-contact__inbox-row">
          <p className="page-contact__inbox-label">{t("contact.topic.privacy", locale)}</p>
          <p className="page-contact__inbox-address">privacy@pulpo.club</p>
        </li>
        <li className="page-contact__inbox-row">
          <p className="page-contact__inbox-label">{t("contact.topic.legal", locale)}</p>
          <p className="page-contact__inbox-address">legal@pulpo.club</p>
        </li>
      </ul>
    </div>
  );
}
