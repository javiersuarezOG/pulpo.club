// Hero V5 (v6 redesign) — "Sunday morning, coffee, your top 10" hero.
//   * Left: H1 + lead + 3-point checklist + an inline free email capture.
//   * Right: the "Pulpo Free" card — your real Top 3 ranked picks shown,
//     with the 4–10 zone frosted behind a Pulpo Pro unlock. Built from
//     real ranked listings (useListings → top 7) so it never lies, and
//     uses local thumbnail_url only (never broker CDN photos).
//   * Below: the "Where to start" subsection (5 destination cards),
//     unchanged from the prior hero.
//
// Block visibility: when hero_v5 is on, blockRegistry suppresses the
// legacy `hero` slot AND `shoreline` (HeroV5 absorbs both).
//
// VERSION SOURCE OF TRUTH: this component's version lives in
// `web/app/home/versions.json` under `blocks.hero_v5`. Bump it there when
// the rendered output changes; the /api/home/version endpoint reads
// that file directly.

import React, { useCallback } from "react";
import { t, formatPriceI18n, formatSizeI18n } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { Icon, PulpoMark } from "../components.jsx";
import { useListings } from "../data/use-listings";
import versions from "./versions.json";

const HERO_V5_VERSION = versions.blocks.hero_v5 || "unknown";

// ── Pulpo mark (matches PulpoMark in components.jsx — spiral + gripper bulb).
function PulpoMarkInline({ size = 22 }) {
  return (
    <svg width={size} height={size} viewBox="-50 -50 100 100" fill="none" aria-hidden="true">
      <path
        d="M -38 0 C -38 -21, -21 -38, 0 -38 C 21 -38, 38 -21, 38 0 C 38 17, 24 30, 7 30 C -8 30, -18 18, -18 4 C -18 -8, -8 -18, 4 -18 C 12 -18, 18 -12, 18 -4"
        stroke="currentColor" strokeWidth="8.5" strokeLinecap="round" fill="none"
      />
      <circle cx="18" cy="-4" r="9.5" fill="currentColor" />
      <circle cx="18" cy="-4" r="5.5" fill="var(--gold)" />
    </svg>
  );
}

// ── 5 destination cards (unchanged). Slugs expand in pages.jsx#buildFiltersForCategory.
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
      track("hero_v5_destination_clicked", { destination: dest.slug || "all", version: HERO_V5_VERSION });
    } catch { /* never crash on telemetry */ }
    onNavigate(dest.slug);
  }, [dest.slug, onNavigate]);

  return (
    <button
      type="button"
      className={`hp-hero-v5-dest hp-hero-v5-dest-${dest.mod}${isAll ? " hp-hero-v5-dest-all" : ""}`}
      onClick={onClick}
    >
      <span className="hp-hero-v5-dest-mark" aria-hidden="true"><PulpoMarkInline size={22} /></span>
      <span className="hp-hero-v5-dest-copy">
        <span className="hp-hero-v5-dest-label">{t(dest.labelKey, locale)}</span>
        <span className="hp-hero-v5-dest-tag">{t(dest.tagKey, locale)}</span>
      </span>
    </button>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────
const NL_EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Top-N ranked, shelf-eligible listings (gate mirrors isShelfEligible:
// rank_score present + a real local thumbnail + card-eligible). Pure +
// null-safe so an empty/loading dataset never throws.
function pickTop(listings, n) {
  return (listings || [])
    .filter((l) => l && l.rank_score != null && l.thumbnail_url && l.card_eligible)
    .slice()
    .sort((a, b) => b.rank_score - a.rank_score)
    .slice(0, n);
}

// Value grade derived from the real composite rank_score (0–100).
function valueGrade(score) {
  if (score == null) return null;
  if (score >= 85) return "A+";
  if (score >= 78) return "A";
  if (score >= 70) return "A−";
  if (score >= 62) return "B+";
  return "B";
}

function ListingRow({ listing, rank, locale }) {
  const grade = valueGrade(listing.rank_score);
  const size = listing.size_m2 != null ? formatSizeI18n(listing.size_m2, locale) : null;
  return (
    <div className="hv6-r">
      <span className="hv6-rank">{rank}</span>
      <span className="hv6-thumb">
        <img src={listing.thumbnail_url} alt="" loading="lazy" decoding="async" />
      </span>
      <span className="hv6-meta">
        <span className="hv6-mt">{listing.zone_name}</span>
        {size && <span className="hv6-ms">{size}</span>}
        {grade && (
          <span className="hv6-grade">{grade} {t("home.hero.v5.grade_value", locale)}</span>
        )}
      </span>
      <span className="hv6-price">{formatPriceI18n(listing.price, locale)}</span>
    </div>
  );
}

function SkeletonRow({ rank }) {
  return (
    <div className="hv6-r hv6-r-skel" aria-hidden="true">
      <span className="hv6-rank">{rank}</span>
      <span className="hv6-thumb hv6-skel" />
      <span className="hv6-meta">
        <span className="hv6-skel-line" />
        <span className="hv6-skel-line hv6-skel-line-sm" />
      </span>
    </div>
  );
}

// ── Pulpo Free card: real Top 3 shown, 4–10 frosted behind a Pro unlock.
function FreeTopCard({ app, locale }) {
  const listings = useListings();
  const picks = pickTop(listings, 7);
  const top3 = picks.slice(0, 3);
  const locked = picks.slice(3, 7);
  const haveData = top3.length === 3;

  const onUnlock = useCallback(() => {
    try { track("hero_v6_pro_unlock_clicked", { version: HERO_V5_VERSION }); } catch { /* ignore */ }
    if (app && typeof app.openFreeMonthModal === "function") {
      app.openFreeMonthModal({ trigger: "hero_pro_lock" });
    }
  }, [app]);

  return (
    <div className="hv6-stage">
      <div className="hv6-glow" aria-hidden="true" />
      <div className="hv6-ghost" aria-hidden="true" />
      <div className="hv6-card">
        <div className="hv6-card-top">
          <span className="hv6-brand">
            <span className="hv6-brand-mark"><PulpoMarkInline size={22} /></span>
            <span className="hv6-brand-wm">pulpo</span>
            <span className="hv6-free-tag">{t("home.hero.v5.card_free_tag", locale)}</span>
          </span>
          <span className="hv6-live"><i aria-hidden="true" />{t("home.hero.v5.card_live", locale)}</span>
        </div>

        <div className="hv6-card-title">
          {t("home.hero.v5.card_title_a", locale)}{" "}
          <b>{t("home.hero.v5.card_title_b", locale)}</b>{" "}
          {t("home.hero.v5.card_title_c", locale)}
        </div>
        <p className="hv6-card-kick">{t("home.hero.v5.card_kick", locale)}</p>
        <div className="hv6-filters">
          <span className="hv6-filters-lead">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
              <path d="M4 6h16M7 12h10M10 18h4" />
            </svg>
            {t("home.hero.v5.card_filters_lead", locale)}
          </span>
          {["home.hero.v5.card_filter_1", "home.hero.v5.card_filter_2", "home.hero.v5.card_filter_3", "home.hero.v5.card_filter_4"].map((k) => (
            <span className="hv6-chip" key={k}>{t(k, locale)}</span>
          ))}
        </div>

        {haveData
          ? top3.map((l, i) => <ListingRow key={l.id} listing={l} rank={i + 1} locale={locale} />)
          : [1, 2, 3].map((n) => <SkeletonRow key={n} rank={n} />)}

        <div className="hv6-lock">
          <div className="hv6-lock-rows">
            {(locked.length ? locked : [0, 1, 2, 3]).map((l, i) =>
              l && l.id
                ? <ListingRow key={l.id} listing={l} rank={i + 4} locale={locale} />
                : <SkeletonRow key={`s${i}`} rank={i + 4} />
            )}
          </div>
          <div className="hv6-lock-over">
            <span className="hv6-lock-badge" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-button-text)" strokeWidth="2.2">
                <rect x="4" y="11" width="16" height="10" rx="2.5" />
                <path d="M8 11V8a4 4 0 0 1 8 0v3" />
              </svg>
            </span>
            <div className="hv6-lock-ttl">{t("home.hero.v5.lock_more", locale, { n: 7 })}</div>
            <div className="hv6-lock-sub">{t("home.hero.v5.lock_sub", locale)}</div>
            <button type="button" className="hv6-lock-cta" onClick={onUnlock}>
              {t("home.hero.v5.lock_cta", locale)} <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Inline free email capture → POST /api/newsletter (Resend, no account).
function EmailCapture({ locale }) {
  const [email, setEmail] = React.useState("");
  const [status, setStatus] = React.useState({ kind: "idle" }); // idle|loading|success|already|error|invalid

  const submit = useCallback(async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const value = email.trim();
    if (!NL_EMAIL_RE.test(value)) { setStatus({ kind: "invalid" }); return; }
    setStatus({ kind: "loading" });
    const domain = value.split("@")[1] || "";
    try {
      const r = await fetch("/api/newsletter", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: value, source: "homepage_hero", locale }),
      });
      const body = await r.json().catch(() => ({}));
      let result;
      if (r.ok) { setStatus({ kind: body.resubscribed ? "already" : "success" }); result = body.resubscribed ? "already_subscribed" : "success"; }
      else if (r.status === 429) { setStatus({ kind: "error" }); result = "rate_limited"; }
      else if (body && body.error === "invalid_email") { setStatus({ kind: "invalid" }); result = "validation_failed"; }
      else { setStatus({ kind: "error" }); result = "error"; }
      try { track("hero.email_submitted", { source: "homepage_hero", email_domain_only: domain, result }); } catch { /* ignore */ }
    } catch {
      setStatus({ kind: "error" });
      try { track("hero.email_submitted", { source: "homepage_hero", email_domain_only: domain, result: "error" }); } catch { /* ignore */ }
    }
  }, [email, locale]);

  if (status.kind === "success" || status.kind === "already") {
    return (
      <div className="hv6-done" role="status">
        <span className="hv6-done-mark"><PulpoMarkInline size={20} /></span>
        <div>
          <div className="hv6-done-ttl">{t("home.hero.v5.nl_success_title", locale)}</div>
          <div className="hv6-done-body">
            {t(status.kind === "already" ? "home.hero.v5.nl_already" : "home.hero.v5.nl_success", locale)}
          </div>
        </div>
      </div>
    );
  }

  return (
    <form className="hv6-signup" onSubmit={submit} noValidate>
      <input
        type="email"
        className="hv6-signup-input"
        placeholder={t("home.hero.v5.nl_placeholder", locale)}
        aria-label={t("home.hero.v5.nl_aria", locale)}
        value={email}
        onChange={(e) => { setEmail(e.target.value); if (status.kind !== "idle") setStatus({ kind: "idle" }); }}
        disabled={status.kind === "loading"}
      />
      <button type="submit" className="hv6-signup-btn" disabled={status.kind === "loading"}>
        {t(status.kind === "loading" ? "home.hero.v5.nl_cta_loading" : "home.hero.v5.email_cta", locale)}
      </button>
      {(status.kind === "invalid" || status.kind === "error") && (
        <p className="hv6-signup-err" role="alert">
          {t(status.kind === "invalid" ? "home.hero.v5.nl_invalid" : "home.hero.v5.nl_error", locale)}
        </p>
      )}
    </form>
  );
}

export function HeroV5({ app, locale }) {
  React.useEffect(() => {
    try {
      track("hero_v5_viewed", { version: HERO_V5_VERSION });
      track("homepage.section_viewed", { section: "hero_v5" });
    } catch { /* ignore */ }
  }, []);

  const onNavigate = useCallback(
    (slug) => {
      if (!app || typeof app.goBrowse !== "function") return;
      if (slug == null) { app.goBrowse({}); return; }
      app.goBrowse({ category: slug });
    },
    [app],
  );

  return (
    <section className="hp-hero-v5" aria-labelledby="hp-hero-v5-h1">
      <div className="hp-hero-v5-inner">

        {/* Top: copy on the left, Pulpo Free card on the right. */}
        <div className="hv6-top">
          <div className="hv6-copy">
            <h1 id="hp-hero-v5-h1" className="hv6-h1">
              {t("home.hero.v5.h1_a", locale)}
              <em className="hv6-h1-em">{t("home.hero.v5.h1_b", locale)}</em>
            </h1>
            <p className="hv6-lead">{t("home.hero.v5.lead", locale)}</p>
            <ul className="hv6-usp">
              <li>{t("home.hero.v5.usp_1", locale)}</li>
              <li>{t("home.hero.v5.usp_2", locale)}</li>
              <li>{t("home.hero.v5.usp_3", locale)}</li>
            </ul>
            <EmailCapture locale={locale} />
          </div>
          <div className="hv6-viz">
            <FreeTopCard app={app} locale={locale} />
          </div>
        </div>

        {/* Bottom: "Where to start" — 5 destination cards. */}
        <div className="hp-hero-v5-section">
          <div className="hp-hero-v5-section-head">
            <h2 className="hp-hero-v5-section-title">{t("home.hero.v5.section_title", locale)}</h2>
            <div className="hp-hero-v5-section-sub">{t("home.hero.v5.section_sub", locale)}</div>
          </div>
          <div className="hp-hero-v5-cards">
            {DESTINATIONS.map((dest) => (
              <DestinationCard key={dest.mod} dest={dest} locale={locale} onNavigate={onNavigate} />
            ))}
          </div>
        </div>

      </div>
    </section>
  );
}
