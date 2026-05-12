// Homepage v2 hero. Pre-label pill, H1 with serif-italic "ranked.",
// two-column layout (single column on mobile), primary + secondary
// CTAs, microcopy, and a CSS-only tilted newsletter preview on the
// right with 10 leaderboard rows.
//
// CTAs:
//   - "Start free month" → app.openSignup({ mode: "signup" })
//   - "See sample deals" → smooth-scrolls to the Top 10 shelf
//
// The preview card is decorative (aria-hidden); a visually-hidden
// text equivalent is provided for screen-reader users.
import React, { useCallback } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { IconArrowRight } from "./icons.jsx";

// Leaderboard rows — fill widths + tonal buckets are part of the
// design spec (verbatim percentages). They're CSS-only — no listing
// data is rendered here, just the editorial preview.
const ROWS = [
  { pos: "01", width: 96, tone: "deep", score: "A+" },
  { pos: "02", width: 89, tone: "deep", score: "A+" },
  { pos: "03", width: 82, tone: "deep", score: "A"  },
  { pos: "04", width: 77, tone: "deep", score: "A"  },
  { pos: "05", width: 71, tone: "mid",  score: "A-" },
  { pos: "06", width: 64, tone: "mid",  score: "B+" },
  { pos: "07", width: 58, tone: "mid",  score: "B"  },
  { pos: "08", width: 52, tone: "mid",  score: "B"  },
  { pos: "09", width: 47, tone: "soft", score: "B-" },
  { pos: "10", width: 41, tone: "soft", score: "B-" },
];

export function HeroV2({ app, locale }) {
  const onPrimaryCta = useCallback(() => {
    const label = t("home.hero.cta_primary", locale);
    try { track("homepage.cta_clicked", { location: "hero_primary", cta_text: label }); } catch { /* ignore */ }
    if (app && typeof app.openSignup === "function") {
      app.openSignup({ mode: "signup" });
    }
  }, [app, locale]);

  const onSecondaryCta = useCallback(() => {
    const label = t("home.hero.cta_secondary", locale);
    try { track("homepage.cta_clicked", { location: "hero_secondary", cta_text: label }); } catch { /* ignore */ }
    if (typeof document === "undefined") return;
    const target = document.getElementById("hp-shelf-top10");
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [locale]);

  return (
    <section className="hp-hero" aria-labelledby="hp-hero-h1">
      {/* Decorative coords label, hidden on mobile */}
      <span className="hp-hero-coords" aria-hidden="true">
        {t("home.hero.coords", locale)}
      </span>

      <div className="hp-hero-inner">
        <div className="hp-hero-copy">
          <span className="hp-hero-eyebrow">
            <span className="hp-hero-eyebrow-dot" aria-hidden="true" />
            {t("home.hero.eyebrow", locale)}
          </span>

          <h1 id="hp-hero-h1" className="hp-hero-h1">
            <span className="hp-hero-h1-line">
              {t("home.hero.h1.before", locale)}
            </span>
            {" "}
            <span className="hp-hero-h1-italic">{t("home.hero.h1.italic", locale)}</span>
          </h1>

          <div className="hp-hero-grid">
            <div className="hp-hero-grid-left">
              <p className="hp-hero-subhead">{t("home.hero.subhead", locale)}</p>

              <div className="hp-hero-ctas">
                <button type="button" className="hp-cta hp-cta-dark hp-cta-block" onClick={onPrimaryCta}>
                  <span>{t("home.hero.cta_primary", locale)}</span>
                  <IconArrowRight size={18} />
                </button>
                <button type="button" className="hp-cta hp-cta-outline hp-cta-block" onClick={onSecondaryCta}>
                  <span>{t("home.hero.cta_secondary", locale)}</span>
                </button>
              </div>

              <p className="hp-hero-microcopy">{t("home.hero.microcopy", locale)}</p>
            </div>

            <div className="hp-hero-preview-wrap" aria-hidden="true">
              <div className="hp-hero-preview">
                <div className="hp-hero-preview-echo hp-hero-preview-echo-1" />
                <div className="hp-hero-preview-echo hp-hero-preview-echo-2" />
                <div className="hp-hero-preview-front">
                  <div className="hp-hero-preview-head">
                    <div className="hp-hero-preview-head-text">
                      <span className="hp-hero-preview-label">{t("home.hero.preview.label", locale)}</span>
                      <span className="hp-hero-preview-headline">{t("home.hero.preview.headline", locale)}</span>
                    </div>
                    <span className="hp-hero-preview-live">{t("home.hero.preview.live", locale)}</span>
                  </div>
                  <ol className="hp-hero-preview-rows">
                    {ROWS.map((r) => (
                      <li key={r.pos} className="hp-hero-preview-row">
                        <span className="hp-hero-preview-pos">{r.pos}</span>
                        <span className="hp-hero-preview-bar">
                          <span
                            className={`hp-hero-preview-bar-fill hp-hero-preview-bar-fill-${r.tone}`}
                            style={{ width: `${r.width}%` }}
                          />
                        </span>
                        <span className="hp-hero-preview-score">{r.score}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
              <span className="sr-only">{t("home.hero.preview.sr", locale)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Editorial wave bands at the bottom */}
      <svg
        className="hp-hero-waves"
        viewBox="0 0 680 110"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path d="M0,70 Q170,30 340,55 T680,45 L680,110 L0,110 Z" fill="#DDE9DC" opacity="0.7" />
        <path d="M0,85 Q170,55 340,75 T680,65 L680,110 L0,110 Z" fill="#C9DBC7" opacity="0.6" />
        <path d="M0,100 Q170,80 340,92 T680,85 L680,110 L0,110 Z" fill="#1F3D31" opacity="0.08" />
      </svg>
    </section>
  );
}
