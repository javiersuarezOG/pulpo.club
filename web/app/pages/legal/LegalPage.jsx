// LegalPage — shared renderer for /terms, /privacy, /cookies, /subscription, /imprint.
//
// Reads its body from `web/app/config/legal-content.ts` (typed
// LegalDocument), so adding/removing a section means editing prose, not
// JSX. The same component renders all five public legal pages —
// parameterised only by `slug`.
//
// Frontend non-negotiables checklist (per the audit plan):
//   - Responsive: single content column, max-width capped, padding via
//     design tokens. No horizontal scroll at 320px.
//   - i18n: locale-aware. Each LegalDocument carries `body.en` + `body.es`;
//     the component picks based on `app.locale`. ES copy currently shows
//     the "draft pending counsel review" placeholder text.
//   - Telemetry: fires `legal.page_viewed` on mount with the page slug.
//   - Design tokens: every spacing/color value reads from tokens.css.

import React, { useEffect } from "react";
import { findDocument } from "../../config/legal-content";
import { ENTITY } from "../../config/legal-entity";
import { useDocumentMeta } from "../../lib/use-document-meta";
import { t } from "../../i18n.jsx";
import { track } from "../../telemetry/client";

const PAGE_STYLES = `
.page-legal {
  max-width: 760px;
  margin: 0 auto;
  padding: 48px var(--section-pad, 24px) 96px;
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: var(--type-body-size);
  line-height: var(--type-body-line);
}
.page-legal__back {
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
.page-legal__back:hover { color: var(--ink); }
.page-legal__title {
  font-family: var(--font-display);
  font-size: 36px;
  line-height: 44px;
  font-weight: 400;
  color: var(--ink);
  margin: 0 0 8px;
}
.page-legal__updated {
  font-size: var(--type-card-meta-size);
  color: var(--ink-3);
  margin: 0 0 32px;
}
.page-legal__draft-banner {
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-left: 4px solid var(--accent);
  border-radius: 8px;
  padding: 16px 20px;
  margin: 0 0 32px;
  font-size: var(--type-card-meta-size);
  line-height: 1.6;
  color: var(--ink-2);
}
.page-legal__incorporation-banner {
  background: var(--paper-2);
  border: 1px solid var(--line-2);
  border-radius: 8px;
  padding: 16px 20px;
  margin: 0 0 24px;
  font-size: var(--type-card-meta-size);
  line-height: 1.6;
  color: var(--ink-2);
}
.page-legal__section { margin: 0 0 32px; }
.page-legal__section-heading {
  font-family: var(--font-sans);
  font-size: 18px;
  line-height: 24px;
  font-weight: 600;
  color: var(--ink);
  margin: 0 0 12px;
}
.page-legal__section-body {
  white-space: pre-wrap;
  color: var(--ink-2);
  margin: 0;
}
@media (max-width: 599px) {
  .page-legal { padding: 24px 16px 80px; }
  .page-legal__title { font-size: 28px; line-height: 36px; }
}
`;

export function LegalPage({ app, slug }) {
  const locale = app?.locale === "es" ? "es" : "en";
  const doc = findDocument(slug);

  // Set <title> + <meta>. Done at the top level so SSR-equivalent crawlers
  // see them as soon as the route mounts.
  useDocumentMeta({
    title: doc ? doc.title[locale] : "Pulpo",
    description: doc ? doc.description[locale] : "",
  });

  useEffect(() => {
    if (slug) {
      track("legal.page_viewed", { page: slug });
    }
  }, [slug]);

  if (!doc) {
    // Should be unreachable — every legal route maps to a known slug.
    // Render a sane fallback rather than blanking the page.
    return (
      <div className="page page-legal" role="main">
        <style>{PAGE_STYLES}</style>
        <h1 className="page-legal__title">Page not found</h1>
        <p>The page you requested doesn't exist.</p>
      </div>
    );
  }

  return (
    <div className="page page-legal" role="main">
      <style>{PAGE_STYLES}</style>
      <button
        type="button"
        className="page-legal__back"
        onClick={() => app.go("home")}
        aria-label={t("legal.back_to_home", locale)}
      >
        ← {t("legal.back_to_home", locale)}
      </button>
      <h1 className="page-legal__title">{doc.title[locale]}</h1>
      <p className="page-legal__updated">
        {t("legal.last_updated", locale)}: {doc.last_updated}
      </p>

      {!doc.review_complete && (
        <div className="page-legal__draft-banner" role="status">
          {t("legal.draft_banner", locale)}
        </div>
      )}

      {!ENTITY.incorporated && (
        <div className="page-legal__incorporation-banner" role="status">
          {t("legal.incorporation_banner", locale)}
        </div>
      )}

      {doc.sections
        .filter((section) => (section.if ? section.if() : true))
        .map((section) => (
          <section key={section.id} className="page-legal__section" id={section.id}>
            <h2 className="page-legal__section-heading">{section.heading[locale]}</h2>
            <p className="page-legal__section-body">{section.body[locale]}</p>
          </section>
        ))}
    </div>
  );
}
