// Hero V5 — editorial "Sunday morning, coffee, your top 10" hero.
// Replaces HeroV4 AND PickShoreline when the `hero_v5` flag is on:
//   * Top half: H1 + warm sub on the left, newsletter postcard preview
//     on the right (mirrors what users get in the Sunday edition).
//   * Bottom half: a "Where to start" subsection with 5 destination
//     cards — All listings + the four covered regions
//     (Surf City I, Surf City II, Lago Coatepeque, Lago Ilopango).
//
// The postcard preview is intentionally static — sourced from the same
// editorial format as the real newsletter ("MARKET CONTEXT / What's
// moving this week" + 3 numbered insights). No live feed; the content
// is hand-curated and updated alongside the newsletter cadence.
//
// Block visibility: when hero_v5 is on, blockRegistry suppresses the
// legacy `hero` slot AND `shoreline` (HeroV5 absorbs both).
//
// VERSION SOURCE OF TRUTH: this component's version lives in
// `web/app/home/versions.json` under `blocks.hero`. Bump it there when
// the rendered output changes; the /api/home/version endpoint reads
// that file directly.

import React, { useCallback } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import versions from "./versions.json";

// Compile-time import of the version registry — Vite inlines this so
// there's no runtime fetch. Carried as a property on every HeroV5
// telemetry event so PostHog cohorts can split funnels by visual
// revision (v5 vs v5.1 vs future) without changing event names.
const HERO_V5_VERSION = versions.blocks.hero_v5 || "unknown";

// ── Pulpo mark (matches PulpoMark in components.jsx — spiral + gripper bulb).
// Inlined here to keep HeroV5 self-contained and avoid a circular import
// from components.jsx → HeroV5 → components.jsx during fast refresh.
function PulpoMarkInline({ size = 22 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="-50 -50 100 100"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M -38 0 C -38 -21, -21 -38, 0 -38 C 21 -38, 38 -21, 38 0 C 38 17, 24 30, 7 30 C -8 30, -18 18, -18 4 C -18 -8, -8 -18, 4 -18 C 12 -18, 18 -12, 18 -4"
        stroke="currentColor"
        strokeWidth="8.5"
        strokeLinecap="round"
        fill="none"
      />
      <circle cx="18" cy="-4" r="9.5" fill="currentColor" />
      <circle cx="18" cy="-4" r="5.5" fill="var(--gold)" />
    </svg>
  );
}

// ── 5 destination cards. The card slug is passed to `app.goBrowse`,
// which then runs through `buildFiltersForCategory` in pages.jsx. All
// five slugs are recognized there (see pages.jsx ~line 985).
const DESTINATIONS = [
  { slug: null,           mod: "all", labelKey: "home.hero.v5.dest.all.label", tagKey: "home.hero.v5.dest.all.tag" },
  { slug: "surf_city_1",  mod: "s1",  labelKey: "home.hero.v5.dest.s1.label",  tagKey: "home.hero.v5.dest.s1.tag" },
  { slug: "surf_city_2",  mod: "s2",  labelKey: "home.hero.v5.dest.s2.label",  tagKey: "home.hero.v5.dest.s2.tag" },
  { slug: "coatepeque",   mod: "cp",  labelKey: "home.hero.v5.dest.cp.label",  tagKey: "home.hero.v5.dest.cp.tag" },
  { slug: "ilopango",     mod: "il",  labelKey: "home.hero.v5.dest.il.label",  tagKey: "home.hero.v5.dest.il.tag" },
];

function DestinationCard({ dest, locale, onNavigate }) {
  const isAll = dest.mod === "all";
  const onClick = useCallback(() => {
    try {
      track("hero_v5_destination_clicked", {
        destination: dest.slug || "all",
        version: HERO_V5_VERSION,
      });
    } catch { /* never crash on telemetry */ }
    onNavigate(dest.slug);
  }, [dest.slug, onNavigate]);

  return (
    <button
      type="button"
      className={`hp-hero-v5-dest hp-hero-v5-dest-${dest.mod}${isAll ? " hp-hero-v5-dest-all" : ""}`}
      onClick={onClick}
    >
      <span className="hp-hero-v5-dest-mark" aria-hidden="true">
        <PulpoMarkInline size={22} />
      </span>
      <span className="hp-hero-v5-dest-copy">
        <span className="hp-hero-v5-dest-label">{t(dest.labelKey, locale)}</span>
        <span className="hp-hero-v5-dest-tag">{t(dest.tagKey, locale)}</span>
      </span>
    </button>
  );
}

// ── Newsletter postcard preview. Hardcoded editorial content modeled on
// the real Sunday newsletter "MARKET CONTEXT / What's moving this week"
// section. Refreshed manually alongside the newsletter cadence.
function NewsletterPostcard({ locale }) {
  // Three numbered insights — keys live in i18n.jsx under home.hero.v5.pc.*
  const insights = [0, 1, 2].map((i) => ({
    lead: t(`home.hero.v5.pc.insight_${i}_lead`, locale),
    body: t(`home.hero.v5.pc.insight_${i}_body`, locale),
  }));

  return (
    <div className="hp-hero-v5-postcard-wrap" aria-hidden="true">
      <div className="hp-hero-v5-postcard">
        <div className="hp-hero-v5-pc-head">
          <div className="hp-hero-v5-pc-brand">
            <span className="hp-hero-v5-pc-mark"><PulpoMarkInline size={22} /></span>
            <span className="hp-hero-v5-pc-wm">{t("home.hero.v5.pc.brand", locale)}</span>
            <span className="hp-hero-v5-pc-pro">Pro</span>
          </div>
          <div className="hp-hero-v5-pc-issue">{t("home.hero.v5.pc.issue", locale)}</div>
        </div>
        <div className="hp-hero-v5-pc-date">{t("home.hero.v5.pc.date", locale)}</div>

        <div className="hp-hero-v5-pc-eyebrow">{t("home.hero.v5.pc.market_eyebrow", locale)}</div>
        <h3 className="hp-hero-v5-pc-title">
          {t("home.hero.v5.pc.market_title_a", locale)}
          <em>{t("home.hero.v5.pc.market_title_b", locale)}</em>
        </h3>

        <ol className="hp-hero-v5-pc-insights">
          {insights.map((ins, i) => (
            <li className="hp-hero-v5-pc-insight" key={i}>
              <span className="hp-hero-v5-pc-num">{String(i + 1).padStart(2, "0")}</span>
              <div className="hp-hero-v5-pc-body">
                <span className="hp-hero-v5-pc-lead">{ins.lead}</span>{" "}
                <span dangerouslySetInnerHTML={{ __html: ins.body }} />
              </div>
            </li>
          ))}
        </ol>

        <div className="hp-hero-v5-pc-more">{t("home.hero.v5.pc.more", locale)}</div>
        <div className="hp-hero-v5-pc-foot">
          <span>{t("home.hero.v5.pc.foot_left", locale)}</span>
          <span>{t("home.hero.v5.pc.foot_right", locale)}</span>
        </div>
      </div>
    </div>
  );
}

export function HeroV5({ app, locale }) {
  // Mount telemetry — fire once per page load so dashboards can split
  // hero_v5 sessions from legacy hero_v4 sessions.
  React.useEffect(() => {
    try { track("hero_v5_viewed", { version: HERO_V5_VERSION }); } catch { /* ignore */ }
  }, []);

  const onNavigate = useCallback(
    (slug) => {
      if (!app || typeof app.goBrowse !== "function") return;
      // null slug = "All listings". goBrowse({}) lands on /browse with
      // every filter cleared, same as a fresh nav click.
      if (slug == null) {
        app.goBrowse({});
        return;
      }
      // Named region — pages.jsx#buildFiltersForCategory expands the
      // slug into a master_category + zones bundle. See that function
      // for the surf_city_1 / surf_city_2 / coatepeque / ilopango cases.
      app.goBrowse({ category: slug });
    },
    [app],
  );

  return (
    <section className="hp-hero-v5" aria-labelledby="hp-hero-v5-h1">
      <div className="hp-hero-v5-inner">

        {/* Top: copy on left, newsletter postcard preview on right. */}
        <div className="hp-hero-v5-top">
          <div className="hp-hero-v5-copy">
            <h1 id="hp-hero-v5-h1" className="hp-hero-v5-h1">
              <span className="hp-hero-v5-h1-line">{t("home.hero.v5.h1_a", locale)}</span>{" "}
              <em className="hp-hero-v5-h1-italic">{t("home.hero.v5.h1_b", locale)}</em>
            </h1>
            <p className="hp-hero-v5-sub">{t("home.hero.v5.sub", locale)}</p>
          </div>
          <NewsletterPostcard locale={locale} />
        </div>

        {/* Bottom: "Where to start" subsection — 5 destination cards. */}
        <div className="hp-hero-v5-section">
          <div className="hp-hero-v5-section-head">
            <h2 className="hp-hero-v5-section-title">{t("home.hero.v5.section_title", locale)}</h2>
            <div className="hp-hero-v5-section-sub">{t("home.hero.v5.section_sub", locale)}</div>
          </div>
          <div className="hp-hero-v5-cards">
            {DESTINATIONS.map((dest) => (
              <DestinationCard
                key={dest.mod}
                dest={dest}
                locale={locale}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        </div>

      </div>
    </section>
  );
}
