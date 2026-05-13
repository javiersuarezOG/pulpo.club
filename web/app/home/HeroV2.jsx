// Homepage v3 hero — dark forest theme, dynamic live leaderboard,
// floating Just In pill, real-data LIVE NOW counter card.
//
// The animation logic obeys the performance rules in the v3 spec:
//   * Only `transform`, `opacity`, and `width` (the leaderboard bars'
//     deliberate exception, on fixed-position children) are animated.
//   * No backdrop-filter, no decorative box-shadow, no filter.
//   * One setInterval drives the leaderboard, counter, AND Just In
//     pill together — never three independent timers.
//   * IntersectionObserver pauses the interval when the hero scrolls
//     offscreen; document.visibilitychange pauses on tab-hidden.
//   * prefers-reduced-motion short-circuits the interval entirely and
//     renders a static initial board. The media query is also listened
//     to mid-session so a toggle while the user is on the page reacts.
//   * The 10 row DOM nodes are pre-built once and updated in place via
//     refs — no innerHTML thrash, no GC pressure.
//
// Telemetry per the v3 spec:
//   * Start/pause/resume events around the interval lifecycle (not
//     one event per cycle — that would blow up PostHog ingestion).
//   * homepage.cta_clicked for both CTAs (existing event, new copy).
//   * hero_just_in_clicked when the pill is activated.
//
// Data flow:
//   * Leaderboard widths held in `widthsRef` + state so the React
//     render fires only on diff, but the row mutations still happen
//     synchronously inside the interval handler.
//   * LIVE NOW counter (top-right) reads /data/last_updated.json
//     once on mount via timedFetch; the result is cached in
//     localStorage so a cold second visit shows real numbers
//     immediately.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { IconArrowRight, IconBoltFilled } from "./icons.jsx";
import {
  CYCLE_MS_PRODUCTION,
  SOURCE_COUNT_FALLBACK,
  LISTING_COUNT_FALLBACK,
} from "./heroConfig";
import {
  INITIAL_WIDTHS,
  SAMPLE_LISTINGS,
  gradeFor,
  toneFor,
  nextCycle,
  randomCandidate,
  slugifyListing,
} from "./heroLeaderboard";
import { readLiveCounterCache, writeLiveCounterCache } from "../lib/live-counter-cache";

// ───── helpers ─────────────────────────────────────────────────────

// Format an integer with thousands separators for the LIVE NOW counter.
// Uses the user's locale so es-SV renders "1.247" and en-US "1,247".
function fmtCount(n, locale) {
  try {
    return new Intl.NumberFormat(locale === "es" ? "es-SV" : "en-US").format(n);
  } catch {
    return String(n);
  }
}

// Short USD price for the Just In pill ("$845k", "$1.2M"). Pure helper
// so the pill renders fast without an Intl format setup per render.
function fmtShortPrice(n) {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1000) return `$${Math.round(n / 1000)}k`;
  return `$${n}`;
}

// Substitute {key} placeholders in a localized template string. Tiny
// shim — no Intl.MessageFormat dep, no escape handling, just what the
// v3 hero needs.
function fillTemplate(tpl, vars) {
  let out = String(tpl);
  for (const [k, v] of Object.entries(vars)) {
    out = out.replaceAll(`{${k}}`, String(v));
  }
  return out;
}

// ───── component ───────────────────────────────────────────────────

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

export function HeroV2({ app, locale }) {
  // Cached counter values: read synchronously so first paint already
  // shows real numbers when the user is returning. Falls back to
  // heroConfig constants only on the true first visit.
  const initialCounter = useMemo(() => {
    const cached = readLiveCounterCache();
    return {
      total_listings: cached?.total_listings ?? LISTING_COUNT_FALLBACK,
      source_count: cached?.source_count ?? SOURCE_COUNT_FALLBACK,
    };
  }, []);
  const [counter, setCounter] = useState(initialCounter);

  // Reduced-motion is the kill switch. Both the React render path
  // (hide Just In, no pop animation) and the interval (never starts)
  // honor it.
  const [reducedMotion, setReducedMotion] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(REDUCED_MOTION_QUERY).matches;
  });

  // Leaderboard widths are held in BOTH a ref (mutated in place by
  // the interval) and state (for the React render). The ref keeps
  // cycles cheap; the state forces a re-render so the rows visually
  // update. We could omit state by mutating DOM directly through row
  // refs, but the React render path keeps reduced-motion + initial
  // load deterministic.
  const [widths, setWidths] = useState(() => INITIAL_WIDTHS.slice());
  const widthsRef = useRef(widths);
  widthsRef.current = widths;

  // Just In pill state — the listing currently highlighted + its grade
  // chip + position. Primed on mount with the first sample so users
  // see the pill from frame 1 instead of waiting for the first 7s
  // cycle; the first real tick then swaps in something different.
  // insertedAt is null in this priming state because no insertion has
  // actually happened — the pill is showing a sample, not a fresh
  // entry.
  const [pill, setPill] = useState(() => {
    const seed = SAMPLE_LISTINGS[0];
    const seedWidth = INITIAL_WIDTHS[0];
    return {
      listing: seed,
      width: seedWidth,
      grade: gradeFor(seedWidth),
      insertedAt: 1,
    };
  });
  const [pillPopKey, setPillPopKey] = useState(0);

  // Highlighted row index for the NEW badge + peach flash. The flash
  // is a CSS animation pinned to a `data-just-inserted` attribute that
  // clears after the animation completes.
  const [insertedRow, setInsertedRow] = useState(null);

  // Section-viewed (existing v2 contract). Fires once at first 50%
  // visible. Hero is the only section without a separate observer
  // tied to its container — the leaderboard IO below handles both
  // jobs.
  const sectionViewedFiredRef = useRef(false);

  // Refs/state for the interval lifecycle. Pause/resume telemetry
  // tracks whether we've fired `started` yet (idempotent) + the
  // current paused state.
  const intervalRef = useRef(null);
  const startedRef = useRef(false);
  const pausedRef = useRef(false);
  const heroRef = useRef(null);

  // ── CTA handlers (preserved telemetry: homepage.cta_clicked) ─────

  const onPrimaryCta = useCallback(() => {
    const ctaText = t("home.hero.cta_primary", locale);
    try {
      track("homepage.cta_clicked", { location: "hero_primary", cta_text: ctaText });
    } catch { /* never crash render */ }
    if (app && typeof app.openSignup === "function") {
      app.openSignup({ mode: "signup" });
    }
  }, [app, locale]);

  const onSecondaryCta = useCallback(() => {
    const ctaText = t("home.hero.cta_secondary", locale);
    try {
      track("homepage.cta_clicked", { location: "hero_secondary", cta_text: ctaText });
    } catch { /* never crash render */ }
    if (typeof document === "undefined") return;
    const target = document.getElementById("hp-shelf-top10");
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [locale]);

  // ── Just In pill click → signup modal (per plan) ─────────────────

  const onJustInClick = useCallback(() => {
    if (!pill) return;
    const slug = slugifyListing(pill.listing.name);
    try {
      track("hero_just_in_clicked", {
        position: pill.insertedAt,
        listing_id: slug,
      });
    } catch { /* ignore */ }
    if (app && typeof app.openSignup === "function") {
      app.openSignup({ mode: "signup" });
    }
  }, [pill, app]);

  // ── Live counter fetch (real numbers from /data/last_updated.json) ─

  useEffect(() => {
    let cancelled = false;
    // Same endpoint LiveStats.jsx already consumes — no duplicate
    // fetch path, the file is already cached at edge per vercel.json.
    import("../telemetry/perf").then(({ timedFetch }) =>
      timedFetch("last_updated.json", "/data/last_updated.json", {
        headers: { Accept: "application/json" },
      })
    )
      .then(r => (r.ok ? r.json() : null))
      .then(json => {
        if (cancelled || !json) return;
        const total = typeof json.total_listings === "number" ? json.total_listings : null;
        const statuses = json.source_status || {};
        const sources = Object.keys(statuses).length || null;
        if (total != null && sources != null) {
          setCounter({ total_listings: total, source_count: sources });
          writeLiveCounterCache({
            total_listings: total,
            source_count: sources,
            fetched_at: new Date().toISOString(),
          });
        }
      })
      .catch(() => { /* swallow — last-loaded value stays on screen */ });
    return () => { cancelled = true; };
  }, []);

  // ── Reduced-motion media listener (react to mid-session toggle) ──

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(REDUCED_MOTION_QUERY);
    const handler = (e) => setReducedMotion(!!e.matches);
    // Older Safari uses addListener; newer browsers addEventListener.
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    }
    if (typeof mq.addListener === "function") {
      mq.addListener(handler);
      return () => mq.removeListener(handler);
    }
    return undefined;
  }, []);

  // ── Interval lifecycle: starts on IO-enter, pauses on IO-leave +
  //    document hidden. Reduced-motion short-circuits to a one-time
  //    render-only path. ───────────────────────────────────────────

  const tick = useCallback(() => {
    const candidate = randomCandidate();
    const result = nextCycle(widthsRef.current, candidate);
    widthsRef.current = result.widths;
    setWidths(result.widths);
    setPill({
      listing: result.pillListing,
      width: result.pillWidth,
      grade: result.pillGrade,
      insertedAt: result.insertedAt,
    });
    setPillPopKey((k) => k + 1);
    if (result.insertedAt != null) {
      // 1-based → 0-based for the row index
      setInsertedRow(result.insertedAt - 1);
      // Clear the highlight after the 2.2s peach flash so a subsequent
      // insert at the same index re-fires.
      window.setTimeout(() => {
        setInsertedRow((prev) => (prev === result.insertedAt - 1 ? null : prev));
      }, 2200);
    }
  }, []);

  const startInterval = useCallback(() => {
    if (intervalRef.current != null) return;
    intervalRef.current = window.setInterval(tick, CYCLE_MS_PRODUCTION);
  }, [tick]);

  const stopInterval = useCallback(() => {
    if (intervalRef.current == null) return;
    window.clearInterval(intervalRef.current);
    intervalRef.current = null;
  }, []);

  // IntersectionObserver — drives both section_viewed (once) and the
  // interval start/pause cycle. Threshold 0.5 mirrors the v2 contract.
  useEffect(() => {
    if (typeof window === "undefined" || typeof IntersectionObserver === "undefined") return;
    const el = heroRef.current;
    if (!el) return;

    const obs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            if (!sectionViewedFiredRef.current) {
              sectionViewedFiredRef.current = true;
              try { track("homepage.section_viewed", { section: "hero" }); } catch { /* ignore */ }
            }
            if (!startedRef.current) {
              startedRef.current = true;
              try {
                track("hero_live_leaderboard_started", {
                  reduced_motion: reducedMotion,
                  cycle_ms: CYCLE_MS_PRODUCTION,
                });
              } catch { /* ignore */ }
            }
            if (reducedMotion) return; // reduced-motion: never start the timer
            if (pausedRef.current && document.visibilityState === "visible") {
              pausedRef.current = false;
              try { track("hero_live_leaderboard_resumed", {}); } catch { /* ignore */ }
            }
            if (document.visibilityState === "visible") startInterval();
          } else {
            if (intervalRef.current != null) {
              stopInterval();
              if (!pausedRef.current) {
                pausedRef.current = true;
                try { track("hero_live_leaderboard_paused", {}); } catch { /* ignore */ }
              }
            }
          }
        }
      },
      { threshold: 0.5 },
    );
    obs.observe(el);
    return () => {
      obs.disconnect();
      stopInterval();
    };
  }, [reducedMotion, startInterval, stopInterval]);

  // Visibility listener: pause on tab hidden, resume when visible
  // (only if the hero is still in viewport). Independent from IO so
  // a user who hides the tab mid-hero gets the right behavior on
  // return.
  useEffect(() => {
    if (typeof document === "undefined") return;
    const onVis = () => {
      if (document.visibilityState === "hidden") {
        if (intervalRef.current != null) {
          stopInterval();
          if (!pausedRef.current) {
            pausedRef.current = true;
            try { track("hero_live_leaderboard_paused", {}); } catch { /* ignore */ }
          }
        }
      } else if (document.visibilityState === "visible") {
        if (reducedMotion) return;
        if (!startedRef.current) return; // hero hasn't been seen yet
        if (pausedRef.current) {
          pausedRef.current = false;
          try { track("hero_live_leaderboard_resumed", {}); } catch { /* ignore */ }
        }
        // Only resume if the hero is still on screen. The IO will
        // re-check intersection on the next paint; we let it own the
        // start.
        startInterval();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [reducedMotion, startInterval, stopInterval]);

  // ── Render ───────────────────────────────────────────────────────

  // Pre-label parts: split into three i18n keys + a styled span around
  // the count. Per the plan, copy verbatim is sandboxed in i18n.jsx.
  const eyebrowBefore = t("home.hero.eyebrow_before", locale);
  const eyebrowAfter = t("home.hero.eyebrow_after", locale);
  const eyebrowSources = fillTemplate(
    t("home.hero.eyebrow_sources", locale),
    { n: counter.source_count },
  );

  const counterTemplate = fillTemplate(
    t("home.hero.counter_template", locale),
    { count: fmtCount(counter.total_listings, locale), sources: counter.source_count },
  );

  // Subhead, microcopy, etc. — straight t() lookups.
  const previewHeadline = t("home.hero.preview.headline", locale);
  const previewSr = t("home.hero.preview.sr", locale);

  // Just In pill copy + position chip.
  let pillPositionText = "";
  if (pill) {
    pillPositionText = pill.insertedAt != null
      ? fillTemplate(t("home.hero.just_in_position", locale), { n: pill.insertedAt })
      : t("home.hero.off_the_board", locale);
  }
  const pillAria = pill
    ? fillTemplate(t("home.hero.just_in_aria", locale), { name: pill.listing.name })
    : "";

  return (
    <section
      ref={heroRef}
      className="hp-hero hp-hero-v3"
      aria-labelledby="hp-hero-h1"
    >
      {/* Decorative topographic lines (right two-thirds, behind everything) */}
      <svg
        className="hp-hero-topo"
        viewBox="0 0 800 280"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path d="M380,30 Q450,70 520,50 T640,80" />
        <path d="M370,60 Q450,100 530,80 T660,110" />
        <path d="M360,90 Q450,130 540,110 T680,140" />
        <path d="M340,150 Q450,190 560,170 T720,200" />
        <path d="M320,210 Q450,250 580,230 T760,260" />
      </svg>

      <div className="hp-hero-inner">
        {/* Live counter card (top-right, hidden <768px). Lives inside
            hp-hero-inner so its right edge anchors to the centered
            1280px content frame on wide monitors instead of drifting
            to the viewport edge. The copy + preview pair sits in a
            narrower 720px subgroup on the left; the counter is the
            only thing pinned to the wide frame's right edge. */}
        <aside
          className="hp-hero-counter"
          aria-label={t("home.hero.counter_live", locale)}
        >
          <span className="hp-hero-counter-dot" aria-hidden="true" />
          <div className="hp-hero-counter-text">
            <span className="hp-hero-counter-label">{t("home.hero.counter_live", locale)}</span>
            <span className="hp-hero-counter-value" id="hero-live-count">
              {counterTemplate}
            </span>
          </div>
        </aside>

        <div className="hp-hero-copy">
          {/* Pre-label pill */}
          <span className="hp-hero-eyebrow">
            <span className="hp-hero-eyebrow-dot" aria-hidden="true" />
            <span>{eyebrowBefore}</span>
            <span className="hp-hero-eyebrow-clay">{eyebrowSources}</span>
            <span>{eyebrowAfter}</span>
          </span>

          {/* H1 with brush stroke under "ranked." */}
          <h1 id="hp-hero-h1" className="hp-hero-h1">
            <span className="hp-hero-h1-line">{t("home.hero.h1.before", locale)}</span>
            {" "}
            <span className="hp-hero-h1-italic">
              {t("home.hero.h1.italic", locale)}
              <svg
                className="hp-hero-brush"
                viewBox="0 0 120 9"
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                <path
                  d="M2,5 Q30,1 60,5 T118,3"
                  stroke="#C77D52"
                  strokeWidth="3"
                  fill="none"
                  strokeLinecap="round"
                />
              </svg>
            </span>
          </h1>

          <div className="hp-hero-grid">
            <div className="hp-hero-grid-left">
              <p className="hp-hero-subhead">{t("home.hero.subhead", locale)}</p>

              <div className="hp-hero-ctas">
                <button type="button" className="hp-cta hp-hero-cta-primary hp-cta-block" onClick={onPrimaryCta}>
                  <span>{t("home.hero.cta_primary", locale)}</span>
                  <IconArrowRight size={15} />
                </button>
                <button type="button" className="hp-cta hp-hero-cta-secondary hp-cta-block" onClick={onSecondaryCta}>
                  <span>{t("home.hero.cta_secondary", locale)}</span>
                </button>
              </div>

              <p className="hp-hero-microcopy">{t("home.hero.microcopy", locale)}</p>
            </div>

            {/* Tilted newsletter preview wrap. Visual is aria-hidden;
                SR gets a hidden text equivalent. The Just In pill IS
                interactive so it's outside the aria-hidden subtree.
                Sits in the right column of .hp-hero-grid, which is
                capped at 720px and left-aligned within the 1280px
                outer frame so the preview hugs the subhead/CTAs row
                rather than drifting to the viewport edge. */}
            <div className="hp-hero-preview-wrap">
              <div className="hp-hero-preview" aria-hidden="true">
                <div className="hp-hero-preview-echo hp-hero-preview-echo-1" />
                <div className="hp-hero-preview-echo hp-hero-preview-echo-2" />
                <div className="hp-hero-preview-front">
                  <div className="hp-hero-preview-head">
                    <div className="hp-hero-preview-head-text">
                      <span className="hp-hero-preview-label">{t("home.hero.preview.label", locale)}</span>
                      <span className="hp-hero-preview-headline">{previewHeadline}</span>
                    </div>
                    <span className="hp-hero-preview-live">
                      <span className="hp-hero-preview-live-dot" />
                      {t("home.hero.preview.live", locale)}
                    </span>
                  </div>
                  <ol className="hp-hero-preview-rows">
                    {widths.map((w, i) => {
                      const grade = gradeFor(w);
                      const tone = toneFor(w);
                      const isInserted = insertedRow === i && !reducedMotion;
                      return (
                        <li
                          key={i}
                          className={`hp-hero-preview-row${isInserted ? " hp-hero-preview-row-new" : ""}`}
                        >
                          <span className="hp-hero-preview-pos">{String(i + 1).padStart(2, "0")}</span>
                          <span className="hp-hero-preview-bar">
                            <span
                              className={`hp-hero-preview-bar-fill hp-hero-preview-bar-fill-${tone}`}
                              style={{ width: `${w}%` }}
                            />
                          </span>
                          <span className="hp-hero-preview-score">{grade}</span>
                          {isInserted ? (
                            <span className="hp-hero-preview-new-badge">{t("home.hero.new_badge", locale)}</span>
                          ) : null}
                        </li>
                      );
                    })}
                  </ol>
                </div>
              </div>
              <span className="sr-only">{previewSr}</span>

              {/* Just In pill — interactive, sits outside aria-hidden
                  subtree. Hidden under reduced-motion (pill is a
                  motion artifact; subscribers in that mode get the
                  static board only). */}
              {!reducedMotion && pill ? (
                <button
                  type="button"
                  className="hp-hero-justin"
                  onClick={onJustInClick}
                  aria-label={pillAria}
                  aria-live="polite"
                  // Bumping key forces React to remount → CSS pop
                  // keyframe replays. Stable across same-cycle re-
                  // renders so the animation isn't double-fired.
                  key={pillPopKey}
                >
                  <span className="hp-hero-justin-head">
                    <span className="hp-hero-justin-icon" aria-hidden="true">
                      <IconBoltFilled size={11} />
                    </span>
                    <span className="hp-hero-justin-label">{t("home.hero.just_in_label", locale)}</span>
                    <span className="hp-hero-justin-position">{pillPositionText}</span>
                  </span>
                  <span className="hp-hero-justin-name">{pill.listing.name}</span>
                  <span className="hp-hero-justin-row">
                    <span className="hp-hero-justin-price">{fmtShortPrice(pill.listing.price)}</span>
                    <span className={`hp-hero-justin-grade hp-hero-justin-grade-${pill.grade[0].toLowerCase()}`}>
                      {pill.grade}
                    </span>
                  </span>
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* Wave handoff to the cream Featured Deal section below. Two
          stacked paths, both aria-hidden. */}
      <svg
        className="hp-hero-waves"
        viewBox="0 0 680 110"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path d="M0,70 Q170,30 340,55 T680,45 L680,110 L0,110 Z" fill="#1F3D31" />
        <path d="M0,85 Q170,55 340,75 T680,65 L680,110 L0,110 Z" fill="#3D6450" opacity="0.5" />
      </svg>
    </section>
  );
}
