// Pick your shoreline — two large editorial cards (Lake, Beach).
// Each card has a white head (label + arrow tile + subtitle) and a
// colored mockup tail with three nested listing-row previews. The
// preview rows are decorative (aria-hidden); the whole card is a
// single button that navigates to /browse with the master filter
// applied.
import React, { useCallback } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { IconRipple, IconBeach, IconArrowRight } from "./icons.jsx";

const LAKE_ROWS = [
  { price: "$324k", zone: "Lago de Coatepeque", body: "2bd cabin · -31%" },
  { price: "$198k", zone: "Lago de Suchitlán", body: "Buildable land · -26%" },
  { price: "$425k", zone: "Lago de Ilopango", body: "4bd · price drop" },
];
const BEACH_ROWS = [
  { price: "$615k", zone: "El Tunco", body: "3bd beach · -28%" },
  { price: "$845k", zone: "Las Flores", body: "Oceanfront · new today" },
  { price: "$720k", zone: "Costa del Sol", body: "3bd condo · price drop" },
];

function ShorelineCard({ shoreline, locale, app }) {
  const isLake = shoreline === "lake";
  const labelKey = isLake ? "home.shoreline.lake.label" : "home.shoreline.beach.label";
  const rows = isLake ? LAKE_ROWS : BEACH_ROWS;

  const onClick = useCallback(() => {
    try { track("shoreline_card_clicked", { shoreline }); } catch { /* ignore */ }
    if (app && typeof app.goBrowse === "function") {
      app.goBrowse({ master_category: shoreline });
    }
  }, [shoreline, app]);

  const ariaLabel = (() => {
    const tpl = t("home.shoreline.cta_aria", locale);
    return typeof tpl === "string" ? tpl.replace("{shoreline}", t(labelKey, locale)) : t(labelKey, locale);
  })();

  return (
    <button
      type="button"
      className={`hp-shoreline-card hp-shoreline-card-${shoreline}`}
      onClick={onClick}
      aria-label={ariaLabel}
    >
      <div className="hp-shoreline-head">
        <div className="hp-shoreline-head-left">
          <span className="hp-shoreline-icon" aria-hidden="true">
            {isLake ? <IconRipple size={16} strokeWidth={1.7} /> : <IconBeach size={16} strokeWidth={1.7} />}
          </span>
          <span className="hp-shoreline-label">{t(labelKey, locale)}</span>
        </div>
        <span className="hp-shoreline-arrow" aria-hidden="true">
          <IconArrowRight size={14} strokeWidth={1.8} />
        </span>
      </div>
      <p className="hp-shoreline-subtitle">{t("home.shoreline.subtitle", locale)}</p>
      <div className="hp-shoreline-tail" aria-hidden="true">
        {rows.map((r, i) => (
          <div className="hp-shoreline-row" key={i}>
            <span className="hp-shoreline-row-art" />
            <span className="hp-shoreline-row-text">
              <span className="hp-shoreline-row-line1">{r.price} · {r.zone}</span>
              <span className="hp-shoreline-row-line2">{r.body}</span>
            </span>
          </div>
        ))}
      </div>
    </button>
  );
}

export function PickShoreline({ app, locale }) {
  return (
    <section className="hp-shoreline" aria-labelledby="hp-shoreline-h2">
      <div className="hp-shoreline-inner">
        <h2 id="hp-shoreline-h2" className="hp-shoreline-h2">
          {t("home.shoreline.h2", locale)}
        </h2>
        <div className="hp-shoreline-grid">
          <ShorelineCard shoreline="lake" locale={locale} app={app} />
          <ShorelineCard shoreline="beach" locale={locale} app={app} />
        </div>
      </div>
    </section>
  );
}
