// Featured deal — single editorial card between hero and USPs.
// Mobile: stacked single column. ≥768px: 280px-narrative + 1fr-panel
// two-column. Clicking anywhere on the card fires
// homepage.featured_deal_clicked and opens signup (since the actual
// featured-deal route isn't wired yet — same behaviour as the
// primary CTA so the funnel reads cleanly).
import React, { useCallback } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { IconArrowRight } from "./icons.jsx";
import { getCategoryImage } from "../assets/categories/index.js";

export function FeaturedDeal({ app, locale }) {
  const onClick = useCallback(() => {
    try { track("homepage.featured_deal_clicked", {}); } catch { /* ignore */ }
    if (app && typeof app.openSignup === "function") {
      app.openSignup({ mode: "signup" });
    }
  }, [app]);

  return (
    <section className="hp-featured" aria-labelledby="hp-featured-title">
      <article className="hp-featured-card" onClick={onClick}>
        <div className="hp-featured-left">
          <span className="hp-featured-eyebrow">{t("home.featured.eyebrow", locale)}</span>
          <h2 id="hp-featured-title" className="hp-featured-title">
            {t("home.featured.title", locale)}
          </h2>
          <p className="hp-featured-body">{t("home.featured.body", locale)}</p>
          <button
            type="button"
            className="hp-featured-arrow"
            onClick={(e) => { e.stopPropagation(); onClick(); }}
            aria-label={t("home.featured.cta_aria", locale)}
          >
            <IconArrowRight size={16} />
          </button>
        </div>
        <div className="hp-featured-right">
          <div className="hp-featured-panel">
            <div className="hp-featured-panel-head">
              <span className="hp-featured-zone">{t("home.featured.zone", locale)}</span>
              <span className="hp-featured-tag">{t("home.featured.tag", locale)}</span>
            </div>
            <div className="hp-featured-art">
              <img
                src={getCategoryImage("water_features")}
                alt=""
                className="hp-featured-art-img"
                loading="eager"
                decoding="async"
              />
              <span className="hp-featured-discount">{t("home.featured.discount", locale)}</span>
            </div>
            <dl className="hp-featured-stats">
              <div className="hp-featured-stat">
                <dt>{t("home.featured.stat_asking", locale)}</dt>
                <dd>$487,000</dd>
              </div>
              <div className="hp-featured-stat">
                <dt>{t("home.featured.stat_value", locale)}</dt>
                <dd className="hp-featured-stat-value">$632,000</dd>
              </div>
              <div className="hp-featured-stat">
                <dt>{t("home.featured.stat_days", locale)}</dt>
                <dd>2</dd>
              </div>
            </dl>
          </div>
        </div>
      </article>
    </section>
  );
}
