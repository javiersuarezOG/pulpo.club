// USP row — the 3-column "Why Pulpo" strip below the category grid.
//
// Pure presentation, no data dependencies. Bilingual strings live in
// i18n.jsx; this component is locale-agnostic.
//
// Mobile-first: columns stack vertically below 768px, switch to 3-up
// at desktop. No telemetry — informational content per the rewrite
// plan §10b.
import React from "react";
import { t } from "../i18n.jsx";

const COLUMNS = [
  { title: "usp.col_1_title", body: "usp.col_1_body" },
  { title: "usp.col_2_title", body: "usp.col_2_body" },
  { title: "usp.col_3_title", body: "usp.col_3_body" },
];

/**
 * @param {object} props
 * @param {string} props.locale  — "en" | "es"
 */
export function USPRow({ locale }) {
  return (
    <section className="usp-row" aria-labelledby="usp-row-heading">
      <h2 id="usp-row-heading" className="sr-only">
        {t("usp.row_heading", locale)}
      </h2>
      <div className="usp-row-inner">
        {COLUMNS.map((col) => (
          <div className="usp-col" key={col.title}>
            <h3 className="usp-col-title">{t(col.title, locale)}</h3>
            <p className="usp-col-body">{t(col.body, locale)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
