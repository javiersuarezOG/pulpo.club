// Pulpo pages: Home (discovery), Browse, Detail, Saved, Plans, Modals
import React, {
  useState as pUseState,
  useEffect as pUseEffect,
  useRef as pUseRef,
  useMemo as pUseMemo,
  useCallback as pUseCallback,
} from "react";
import { t, tr, LOCALES } from "./i18n.jsx";
import { clerkEnabled } from "./auth/clerk-shell.jsx";
// Static-only imports from the prototype data file (shelves, pills, zones).
// The LISTINGS array is now live data, accessed per-component via
// useListings() / useListingsState().
import { SHELVES, PILLS, PILL_GROUPS, ZONES } from "./data.jsx";
import { getCategoryImage } from "./assets/categories/index.js";
import { useListings, useListingsState } from "./data/use-listings.tsx";
import {
  readFilterFromURL,
  readSortFromURL,
  writeFilterToURL,
} from "./data/filter-url.ts";
import { track, optIn, optOut } from "./telemetry/hook";
import { readConsent, writeConsent, CONSENT_POLICY_VERSION } from "./lib/consent";
import { useDebouncedValue } from "./lib/use-debounced-value.ts";
import { priceForCountry, fetchPriceForCurrentGeo } from "./lib/pricing";
import { markUpsellDismissed, decideShouldShowUpsell } from "./lib/upsell-config";
import { captureCampaignParams } from "./lib/campaign";
import { startCheckoutFromModal } from "./lib/stripe-modal-checkout";
import {
  Icon,
  PulpoLogo,
  Badge,
  Photo,
  HeartButton,
  ListingCard,
  SkeletonCard,
  Toast,
  formatPrice,
  formatSize,
  formatDaysListed,
  formatPpm,
  ppmSuffix,
  daysListedTone,
  landTypeLabel,
  formatDistanceKm,
  currentLocale,
  currentUnits,
} from "./components.jsx";
import { LiveStats } from "./components/LiveStats.jsx";
import { useUnits } from "./i18n.jsx";
import { startStripeCheckout } from "./auth/stripe-checkout.js";
import {
  uspsVisibleFor,
  galleryThumbsUnlockedFor,
  isPaid as gateIsPaid,
} from "./lib/gating.ts";
import { trackCtaRouted, routeCtaForState, dispatchCentralBranch } from "./lib/cta-routing";

// Hide the Agency plan tier until we're ready to ship it. Flip to true to
// re-enable. Kept as a module constant so a single edit (no tweak panel,
// no env var) restores the third card.
const SHOW_AGENCY_PLAN = false;

// Source-of-truth price for Pulpo Pro. Mirrors automation/stripe_setup.mjs
// (PRICE_AMOUNT = 1000 cents = €10/mo). The Stripe Price is denominated
// in EUR. When the Stripe price changes, update both. The annual toggle
// was removed because there is no annual price in Stripe today —
// re-introduce both when a yearly price ships.
const PRO_PRICE_EUR_PER_MONTH = 10;

// TopNav, BottomNav, and LocaleToggle were extracted in Wave-3a:
//   web/app/components/SiteHeader.jsx  — replaces TopNav + LocaleToggle
//   web/app/components/BottomNav.jsx   — same logic, own file
// app.jsx imports them directly now; the re-exports below kept the
// pages.jsx surface stable during the rewrite phase and are no longer
// needed.

// ====== Pill rail ======
// Three labeled groups (WHERE / RANKING / FILTERS), each chip toggles a
// specific URL param so chips compose instead of swap:
//   WHERE   — master = beach | lake | (null = All)         single-select
//   RANKING — rmax=10  OR  status=price_drop  OR  status=new   single-select
//   FILTERS — tag=waterfront (toggle) + pmax=100000|250000 (mutex pair)
//
// Click logic reads the current URL, computes the next URL, and navigates
// to /browse. When the user is already on /browse, app.goBrowse keeps the
// same route but updates routeParams; the BrowsePage mount-time effect
// re-reads the URL and applies the new filter set.
function readPillState() {
  if (typeof window === "undefined") return new URLSearchParams();
  return new URLSearchParams(window.location.search);
}

function isPillActive(pill, params) {
  if (pill.param === "master") {
    const cur = params.get("master") || null;
    return cur === pill.value;
  }
  if (pill.param === "rmax") {
    return params.get("rmax") === pill.value;
  }
  if (pill.param === "status") {
    const cur = (params.get("status") || "").split(",").filter(Boolean);
    return cur.includes(pill.value);
  }
  if (pill.param === "tag") {
    const cur = (params.get("tag") || "").split(",").filter(Boolean);
    return cur.includes(pill.value);
  }
  if (pill.param === "pmax") {
    return params.get("pmax") === pill.value;
  }
  return false;
}

// Compute the next URLSearchParams after clicking `pill` within `group`.
// Single-select groups: clicking active = clear; clicking inactive = set
// (and clear sibling selections in the same group). Toggle: add/remove
// from the tag set. price_mutex: set pmax to this value (overrides the
// sibling chip in the same group).
function nextParamsForPill(group, pill, params) {
  const next = new URLSearchParams(params);
  const isActive = isPillActive(pill, params);

  if (group === "where") {
    // master is mutex; clicking active value clears it; clicking "All"
    // (value === null) always clears.
    if (pill.value == null || isActive) next.delete("master");
    else next.set("master", pill.value);
    return next;
  }

  if (group === "ranking") {
    // RANKING is mutex across three different URL params. Clear all three
    // first, then set the clicked one (unless it was already active → clear-only).
    next.delete("rmax");
    next.delete("status");
    if (!isActive) {
      if (pill.param === "rmax") next.set("rmax", pill.value);
      else if (pill.param === "status") next.set("status", pill.value);
    }
    return next;
  }

  // FILTERS group: mixed behavior
  if (pill.behavior === "toggle") {
    // tag set: add/remove pill.value
    const cur = new Set((next.get("tag") || "").split(",").filter(Boolean));
    if (isActive) cur.delete(pill.value);
    else cur.add(pill.value);
    if (cur.size === 0) next.delete("tag");
    else next.set("tag", [...cur].join(","));
    return next;
  }
  if (pill.behavior === "price_mutex") {
    if (isActive) next.delete("pmax");
    else next.set("pmax", pill.value);
    return next;
  }
  return next;
}

function PillRail({ app }) {
  // Re-read URL on every render so the rail reflects external filter changes
  // (FilterPanel toggles, back-button, deep links). Keyed by app.routeParams
  // so clicks trigger a re-render even when the URL string itself is mutated
  // via replaceState by writeFilterToURL.
  const params = readPillState();
  const lc = app.locale;

  const handleClick = (groupKey, pill) => {
    const next = nextParamsForPill(groupKey, pill, params);
    // Preserve dev/debug/utm params that aren't filter-related.
    // (They're already in `params` by virtue of starting from window.search.)
    const qs = next.toString();
    if (typeof window !== "undefined") {
      const url = `/browse${qs ? `?${qs}` : ""}`;
      // Push to history so back-button works for chip navigation.
      window.history.pushState({}, "", url);
    }
    // Route to /browse without a `category` slug — the filter state is
    // already encoded in the URL params we just wrote.
    app.goBrowse({ category: null });
  };

  return (
    <div className="pill-rail-wrap" role="region" aria-label={t("pill.rail.aria", lc)}>
      {Object.entries(PILL_GROUPS).map(([groupKey, group]) => (
        <div key={groupKey} className={`pill-tier pill-tier-${groupKey}`}>
          <span className="pill-tier-label">{t(group.headerKey, lc)}</span>
          <div className="pill-rail">
            {group.pills.map(p => {
              const active = isPillActive(p, params);
              return (
                <button
                  key={p.key}
                  className={`pill-chip ${active ? "is-active" : ""}`}
                  onClick={() => handleClick(groupKey, p)}
                  aria-pressed={active}
                >
                  <span className="pill-icon" aria-hidden="true">
                    <Icon name={p.icon} size={15} strokeWidth={1.6}/>
                  </span>
                  {tr(p.label, lc)}
                </button>
              );
            })}
          </div>
          <div className="pill-rail-fade" />
        </div>
      ))}
    </div>
  );
}

// ====== Browse — filter sidebar ======
function FilterPanel({ filters, setFilters, count, onClose, app }) {
  // Helper to count active filters from a CANDIDATE filter shape — used
  // by the telemetry below to compute active_count POST-toggle without
  // double-rendering. Mirrors the logic of `activeCount` below.
  const countActive = (f) =>
    (f.zones?.size || 0)
    + (f.land_types?.size || 0) + (f.features?.size || 0)
    + (f.infra?.size || 0) + (f.status?.size || 0)
    + (f.price_max != null || f.price_min > 0 ? 1 : 0)
    + (f.master_category ? 1 : 0)
    + (f.subcategory ? 1 : 0)
    + (f.discovery_tags?.size || 0)
    + (f.include_incomplete ? 1 : 0);

  // Telemetry — fire browse.filter_changed once per logical filter
  // change. The event type has existed in events.ts since the
  // catalog landed (#212-era) but had no consumer; Phase 7 wires it.
  // Payload normalizes Set values to a count (PostHog can't serialize
  // Sets), keeps scalars, and reports active_count POST-update so
  // the funnel can join with the post-state.
  //
  // Suppressed keys (tuning sliders, not discrete filters): the
  // V/L/M weight sliders fire `update({weights})` on every tick
  // during a drag — emitting telemetry per tick would flood the
  // funnel with no signal value. `score_min` is the same pattern.
  // Both are excluded.
  const FILTER_CHANGE_SUPPRESSED = new Set(["weights", "score_min"]);
  const emitFilterChange = (key, value, candidate) => {
    if (FILTER_CHANGE_SUPPRESSED.has(key)) return;
    let normalizedValue;
    if (value instanceof Set) {
      // Set values are multi-select state — emit the set's size as
      // a useful scalar; the actual contents are visible elsewhere
      // (filter chips, URL).
      normalizedValue = value.size;
    } else if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      normalizedValue = value;
    } else {
      normalizedValue = null;
    }
    track("browse.filter_changed", {
      filter_key: key,
      value: normalizedValue,
      active_count: countActive(candidate),
    });
  };

  const update = (patch) => {
    const next = { ...filters, ...patch };
    for (const [key, value] of Object.entries(patch)) {
      emitFilterChange(key, value, next);
    }
    setFilters(next);
  };
  const toggleSet = (key, val) => {
    const s = new Set(filters[key]);
    if (s.has(val)) s.delete(val); else s.add(val);
    update({ [key]: s });
  };
  // Rewrite Phase 5B — single-select toggle for master/subcategory.
  // Click an active chip again → clears (null). Click another → swaps.
  const toggleSingle = (key, val) => {
    update({ [key]: filters[key] === val ? null : val });
  };
  const zoneList = ZONES.map(z => z.name);
  const activeCount = countActive(filters);
  const lc = app?.locale || currentLocale();

  return (
    <aside className="filter-panel">
      <div className="filter-head">
        <h3>{t("filter.title", lc)}</h3>
        {activeCount > 0 && <button className="link-btn" onClick={() => setFilters(makeDefaultFilters())}>{t("filter.clear", lc)}</button>}
        {onClose && <button className="icon-btn" onClick={onClose} aria-label={t("common.close", lc)}><Icon name="close" size={18}/></button>}
      </div>

      {/* PR-4c — area-unit preference. Persists in localStorage via useUnits()
          in app.jsx; flips formatSize / formatPpm everywhere. */}
      {app?.setUnits && (
        <div className="units-toggle-row">
          <span className="units-toggle-label">{t("units.label", lc)}</span>
          <div className="units-toggle" role="group" aria-label={t("units.aria", lc)}>
            <button
              type="button"
              className={app.units !== "vrs2" ? "is-active" : ""}
              onClick={() => app.setUnits("m2")}
              aria-pressed={app.units !== "vrs2"}
            >{t("units.m2", lc)}</button>
            <button
              type="button"
              className={app.units === "vrs2" ? "is-active" : ""}
              onClick={() => app.setUnits("vrs2")}
              aria-pressed={app.units === "vrs2"}
            >{t("units.vrs2", lc)}</button>
          </div>
        </div>
      )}

      {/* ── Rewrite Phase 5B — new IA axes (master/sub/tags) ────── */}
      <FilterGroup title={t("filter.master_category", lc)}>
        <div className="chip-grid">
          {["beach", "lake"].map((m) => (
            <button
              key={m}
              className={`chip ${filters.master_category === m ? "is-active" : ""}`}
              onClick={() => toggleSingle("master_category", m)}
            >
              {t(`filter.master.${m}`, lc)}
            </button>
          ))}
        </div>
      </FilterGroup>

      <FilterGroup title={t("filter.subcategory", lc)}>
        <div className="chip-grid">
          {["homes", "condos", "land"].map((s) => (
            <button
              key={s}
              className={`chip ${filters.subcategory === s ? "is-active" : ""}`}
              onClick={() => toggleSingle("subcategory", s)}
            >
              {t(`filter.sub.${s}`, lc)}
            </button>
          ))}
        </div>
      </FilterGroup>

      <FilterGroup title={t("filter.discovery_tags", lc)}>
        <div className="chip-grid">
          {["top_rated", "under_250k", "gated", "waterfront"].map((tag) => (
            <button
              key={tag}
              className={`chip ${filters.discovery_tags?.has(tag) ? "is-active" : ""}`}
              onClick={() => toggleSet("discovery_tags", tag)}
            >
              {t(`filter.tag.${tag}`, lc)}
            </button>
          ))}
          {/* Inverse-semantic chip — opt-in to see listings where the
              broker hasn't shared price or size. They sort below all
              complete listings. */}
          <button
            className={`chip ${filters.include_incomplete ? "is-active" : ""}`}
            onClick={() => update({ include_incomplete: !filters.include_incomplete })}
          >
            {t("filter.show_incomplete", lc)}
          </button>
        </div>
      </FilterGroup>

      <FilterGroup title={t("filter.zone", lc)}>
        <div className="chip-grid">
          {zoneList.map(z => (
            <button key={z}
              className={`chip ${filters.zones.has(z) ? "is-active" : ""}`}
              onClick={() => toggleSet("zones", z)}>{z}</button>
          ))}
        </div>
      </FilterGroup>

      <FilterGroup title={t("filter.price", lc)}>
        <PriceHistogram filters={filters} setFilters={update} />
      </FilterGroup>

      <FilterGroup title={t("filter.land_type", lc)}>
        <div className="chip-grid">
          {["residential","agricultural","commercial","tourist","mixed","raw"].map(typeKey => (
            <button key={typeKey}
              className={`chip ${filters.land_types.has(typeKey) ? "is-active" : ""}`}
              onClick={() => toggleSet("land_types", typeKey)}>{landTypeLabel(typeKey)}</button>
          ))}
        </div>
      </FilterGroup>

      <FilterGroup title={t("filter.size", lc)}>
        <div className="range-row">
          <label>{t("filter.size_min", lc, { n: (filters.size_min/10000).toFixed(1) })}</label>
          <input type="range" min="0" max="200000" step="500"
            value={filters.size_min} onChange={(e) => update({ size_min: +e.target.value })}/>
        </div>
      </FilterGroup>

      <FilterGroup title={t("filter.features", lc)}>
        <div className="chip-grid">
          {["beachfront","ocean_view","mountain_view","flat","water_body"].map(k => (
            <button key={k}
              className={`chip ${filters.features.has(k) ? "is-active" : ""}`}
              onClick={() => toggleSet("features", k)}>{t(`filter.feature.${k}`, lc)}</button>
          ))}
        </div>
      </FilterGroup>

      <FilterGroup title={t("filter.infrastructure", lc)}>
        <div className="chip-grid">
          {["water","power","paved","sewage"].map(k => (
            <button key={k}
              className={`chip ${filters.infra.has(k) ? "is-active" : ""}`}
              onClick={() => toggleSet("infra", k)}>{t(`filter.infra.${k}`, lc)}</button>
          ))}
        </div>
      </FilterGroup>

      <FilterGroup title={t("filter.status", lc)}>
        <div className="chip-grid">
          {["new","price_drop","off_market","motivated"].map(k => (
            <button key={k}
              className={`chip ${filters.status.has(k) ? "is-active" : ""}`}
              onClick={() => toggleSet("status", k)}>{t(`filter.status.${k}`, lc)}</button>
          ))}
        </div>
      </FilterGroup>

      <FilterGroup title={t("filter.readiness", lc)}>
        <div className="range-row">
          <label>{t(`filter.readiness.${filters.readiness ?? 0}`, lc)}</label>
          <input type="range" min="0" max="4" step="1"
            value={filters.readiness} onChange={(e) => update({ readiness: +e.target.value })}/>
        </div>
      </FilterGroup>

      {/* PR-4b — photos chip (legacy parity). */}
      <FilterGroup title={t("filter.photos", lc)}>
        <div className="chip-grid">
          {["all","with","none"].map(k => (
            <button key={k}
              className={`chip ${filters.photos === k ? "is-active" : ""}`}
              onClick={() => update({ photos: k })}>{t(`filter.photos_${k}`, lc)}</button>
          ))}
        </div>
      </FilterGroup>

      {/* PR-4b — advanced ranking (legacy parity). Collapsed by default;
          power-user surface for the score-floor + V/L/M weight tuning. */}
      <AdvancedRanking filters={filters} update={update} />

      {onClose && (
        <div className="filter-apply">
          <button className="btn-primary block" onClick={onClose}>{t("filter.show_count", lc, { n: count })}</button>
        </div>
      )}
    </aside>
  );
}

// ====== Advanced ranking — score floor + V/L/M weight sliders ======
// Mirrors the legacy "Adjust the ranking" panel. Weights auto-rebalance:
// when one slider moves, the other two scale to keep the sum at 100.
// Methodology link opens the "How we rank" modal.
function AdvancedRanking({ filters, update }) {
  const [open, setOpen] = pUseState(false);
  const [methOpen, setMethOpen] = pUseState(false);
  const lc = currentLocale();

  const setWeight = (key, value) => {
    const w = filters.weights || { ...WEIGHT_DEFAULTS };
    const next = { ...w, [key]: value };
    // Rebalance the other two so the sum stays at 100. Mirrors legacy
    // _wireWeightSliders.
    const others = ["value", "location", "momentum"].filter(k => k !== key);
    const remainder = 100 - value;
    const sumOthers = w[others[0]] + w[others[1]];
    if (sumOthers > 0) {
      next[others[0]] = Math.max(0, Math.round((w[others[0]] / sumOthers) * remainder));
      next[others[1]] = Math.max(0, 100 - value - next[others[0]]);
    } else {
      next[others[0]] = Math.round(remainder / 2);
      next[others[1]] = remainder - next[others[0]];
    }
    update({ weights: next });
  };

  const reset = () => update({ score_min: 0, weights: { ...WEIGHT_DEFAULTS } });
  const w = filters.weights || WEIGHT_DEFAULTS;

  return (
    <div className="filter-group filter-group-advanced">
      <button
        className="filter-group-title filter-group-toggle"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span>{lc === "es" ? "Ajusta el ranking" : "Tune the ranking"}</span>
        <Icon name={open ? "chevron_up" : "chevron_down"} size={14} />
      </button>
      {open && (
        <div className="advanced-ranking">
          <div className="advanced-ranking-help">
            <button className="link-btn" onClick={() => setMethOpen(true)}>
              {lc === "es" ? "¿Cómo calculamos esto?" : "How we rank"}
            </button>
          </div>
          <div className="range-row">
            <label>
              {lc === "es" ? "Puntaje mínimo" : "Investment score"}: <strong>{filters.score_min ?? 0}</strong>
            </label>
            <input type="range" min="0" max="100" step="5"
              value={filters.score_min ?? 0}
              onChange={(e) => update({ score_min: +e.target.value })}/>
          </div>
          <div className="range-row">
            <label>{lc === "es" ? "Precio vs. comparables" : "Price vs. comps"}: <strong>{w.value}%</strong></label>
            <input type="range" min="0" max="100" step="5"
              value={w.value}
              onChange={(e) => setWeight("value", +e.target.value)}/>
          </div>
          <div className="range-row">
            <label>{lc === "es" ? "Ubicación" : "Location"}: <strong>{w.location}%</strong></label>
            <input type="range" min="0" max="100" step="5"
              value={w.location}
              onChange={(e) => setWeight("location", +e.target.value)}/>
          </div>
          <div className="range-row">
            <label>{lc === "es" ? "Momentum del área" : "Area momentum"}: <strong>{w.momentum}%</strong></label>
            <input type="range" min="0" max="100" step="5"
              value={w.momentum}
              onChange={(e) => setWeight("momentum", +e.target.value)}/>
          </div>
          <button className="link-btn" onClick={reset}>
            {lc === "es" ? "Restablecer" : "Reset to defaults"}
          </button>
          <p className="advanced-ranking-hint">
            {lc === "es"
              ? `Elige "Mejor coincidencia (tus pesos)" en el orden para usar tus pesos.`
              : `Pick "Best match (your weights)" in the sort dropdown to use your weights.`}
          </p>
        </div>
      )}
      <MethodologyModal open={methOpen} onClose={() => setMethOpen(false)} />
    </div>
  );
}

// ====== "How we rank" methodology modal (legacy parity, restyled) ======
function MethodologyModal({ open, onClose }) {
  const lc = currentLocale();
  pUseEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-methodology" onClick={(e) => e.stopPropagation()} role="dialog" aria-labelledby="meth-title">
        <button className="modal-close" onClick={onClose} aria-label={t("common.close", lc)}>
          <Icon name="close" size={18} />
        </button>
        <h2 id="meth-title">{lc === "es" ? "Cómo clasificamos" : "How we rank"}</h2>
        <p className="meth-tagline">
          {lc === "es"
            ? "Cada propiedad recibe un puntaje compuesto de 0–100 basado en tres dimensiones simples."
            : "Every listing gets a 0–100 composite score from three plain-English dimensions."}
        </p>
        <h3>{lc === "es" ? "Precio vs. comparables" : "Price vs. comparable lots"}</h3>
        <p>
          {lc === "es"
            ? "Qué tan barato es por m² comparado con lotes similares en la misma zona. 100 = el más barato; 0 = el más caro."
            : "How cheap this listing is per square meter compared to similar lots in the same area. 100 = cheapest comparable; 0 = most expensive."}
        </p>
        <h3>{lc === "es" ? "Ubicación y accesibilidad" : "Location & accessibility"}</h3>
        <p>
          {lc === "es"
            ? "Posición y acceso del lote — beneficio de zona, frente al mar, acceso pavimentado, agua y luz, cercanía al aeropuerto."
            : "Zone tier, beachfront, paved access, water/power on the lot, and proximity to the nearest international airport."}
        </p>
        <h3>{lc === "es" ? "Momentum del área" : "Area momentum"}</h3>
        <p>
          {lc === "es"
            ? "Qué tan caliente está la zona — re-precios indican vendedores motivados; nuevo inventario indica demanda creciente."
            : "How often listings get repriced down (motivated sellers) and how quickly new inventory appears in each zone."}
        </p>
        <h3>{lc === "es" ? "El compuesto" : "The composite"}</h3>
        <div className="meth-formula">
          {lc === "es"
            ? "compuesto = 0.40 × Precio + 0.35 × Ubicación + 0.25 × Momentum"
            : "composite = 0.40 × Price vs Comps + 0.35 × Location + 0.25 × Momentum"}
        </div>
        <p>
          {lc === "es"
            ? "Mueve los pesos en \"Ajusta el ranking\" para ver tu propio compuesto."
            : `Move the weights under "Tune the ranking" to see your own composite.`}
        </p>
      </div>
    </div>
  );
}

function FilterGroup({ title, children }) {
  return (
    <div className="filter-group">
      <div className="filter-group-title">{title}</div>
      {children}
    </div>
  );
}

// PR-4f — Interactive price histogram (range-slider-over-histogram).
// Industry-canonical pattern (Airbnb / Zillow / Redfin / Booking):
//   - Two draggable thumbs sit ABOVE the bars (min on left, max on right).
//   - Histogram bars are visual context; each bar is also a click target.
//   - A semi-transparent --accent-soft overlay between thumbs shows the
//     active range at a glance.
//   - Click a bar → filter to that single bucket.
//   - Drag across bars (D3-brush) → set range from start bucket to end.
//   - Drag a thumb → set that side of the range.
//   - Reset link / Escape → clear range.
//   - Min/max number inputs stay below — keyboard a11y + power users.
const HISTO_BUCKETS = 24;
const HISTO_VISUAL_MAX = 1_000_000;            // visual scale of the bars
const HISTO_BAR_WIDTH_USD = HISTO_VISUAL_MAX / HISTO_BUCKETS;  // ~$41,667

function bucketToPrice(bucket) {
  return Math.round(bucket * HISTO_BAR_WIDTH_USD);
}

function priceToBucket(price) {
  if (price == null || price <= 0) return 0;
  return Math.min(HISTO_BUCKETS, Math.max(0, Math.round(price / HISTO_BAR_WIDTH_USD)));
}

function PriceHistogram({ filters, setFilters }) {
  const LISTINGS = useListings();
  const lc = currentLocale();
  const trackRef = pUseRef(null);
  // dragging: null | "min" | "max" | "brush"
  // brushFrom / brushTo: bucket indices during a brush gesture (live)
  const [dragging, setDragging] = pUseState(null);
  const [brushFrom, setBrushFrom] = pUseState(null);
  const [brushTo, setBrushTo] = pUseState(null);
  // While dragging a thumb, hold a live override so the visual updates
  // smoothly without committing to filters on every pointermove.
  const [liveMin, setLiveMin] = pUseState(null);
  const [liveMax, setLiveMax] = pUseState(null);

  const counts = pUseMemo(() => {
    const arr = new Array(HISTO_BUCKETS).fill(0);
    LISTINGS.forEach(l => {
      if (typeof l.price !== "number" || l.price <= 0) return;
      const b = Math.min(HISTO_BUCKETS - 1, Math.floor(l.price / HISTO_VISUAL_MAX * HISTO_BUCKETS));
      arr[b] += 1;
    });
    return arr;
  }, [LISTINGS]);
  const peak = Math.max(...counts, 1);

  // Visual position math — committed filter values, overridden by live
  // drag values when the user is mid-gesture.
  const visualMinPrice = liveMin != null ? liveMin : filters.price_min;
  const visualMaxPrice =
    liveMax != null ? liveMax :
    (filters.price_max != null ? filters.price_max : HISTO_VISUAL_MAX);
  const minPct = Math.min(100, Math.max(0, (visualMinPrice / HISTO_VISUAL_MAX) * 100));
  const maxPct = Math.min(100, Math.max(0, (visualMaxPrice / HISTO_VISUAL_MAX) * 100));

  // Brush overlay (during a brush drag, before commit).
  const brushActive = dragging === "brush" && brushFrom != null && brushTo != null;
  const brushLow = brushActive ? Math.min(brushFrom, brushTo) : null;
  const brushHigh = brushActive ? Math.max(brushFrom, brushTo) + 1 : null;

  // Convert pointer X to bucket index (0..HISTO_BUCKETS-1, clamped).
  const pointerToBucket = (clientX) => {
    const el = trackRef.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    if (r.width <= 0) return 0;
    const x = clientX - r.left;
    return Math.min(HISTO_BUCKETS - 1, Math.max(0, Math.floor(x / r.width * HISTO_BUCKETS)));
  };

  const hasRange = filters.price_min > 0 || filters.price_max != null;

  // ── Thumb drag ────────────────────────────────────────────────
  const startThumbDrag = (which, e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(which);
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onThumbMove = (e) => {
    if (dragging !== "min" && dragging !== "max") return;
    const bucket = pointerToBucket(e.clientX);
    const price = bucketToPrice(bucket);
    if (dragging === "min") {
      // Don't let min cross max.
      const cap = filters.price_max != null ? filters.price_max : HISTO_VISUAL_MAX;
      setLiveMin(Math.min(price, cap));
    } else {
      const floor = filters.price_min;
      setLiveMax(Math.max(price, floor));
    }
  };
  const onThumbUp = () => {
    if (dragging !== "min" && dragging !== "max") return;
    if (dragging === "min" && liveMin != null) {
      setFilters({ price_min: liveMin });
      track("browse.price_histogram.dragged", {
        from_min: filters.price_min, from_max: filters.price_max,
        to_min: liveMin, to_max: filters.price_max,
      });
    } else if (dragging === "max" && liveMax != null) {
      const newMax = liveMax >= HISTO_VISUAL_MAX ? null : liveMax;
      setFilters({ price_max: newMax });
      track("browse.price_histogram.dragged", {
        from_min: filters.price_min, from_max: filters.price_max,
        to_min: filters.price_min, to_max: newMax,
      });
    }
    setDragging(null);
    setLiveMin(null);
    setLiveMax(null);
  };

  // ── Bar click + brush ─────────────────────────────────────────
  // Pointer-down on the track (not on a thumb) starts a brush.
  // We track from the bucket under the pointer, and on pointer-up
  // either commit (single-bar click → that bucket; brush → range).
  const onTrackPointerDown = (e) => {
    // Ignore clicks that originated on a thumb (they handle their own).
    if (e.target.closest && e.target.closest(".histo-thumb")) return;
    if (e.button !== undefined && e.button !== 0) return; // left-click only on mouse
    e.preventDefault();
    const bucket = pointerToBucket(e.clientX);
    setDragging("brush");
    setBrushFrom(bucket);
    setBrushTo(bucket);
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onTrackPointerMove = (e) => {
    if (dragging !== "brush") return;
    setBrushTo(pointerToBucket(e.clientX));
  };
  const onTrackPointerUp = (_e) => {
    if (dragging !== "brush") return;
    if (brushFrom == null || brushTo == null) {
      setDragging(null);
      return;
    }
    const lo = Math.min(brushFrom, brushTo);
    const hi = Math.max(brushFrom, brushTo);
    const isSingleClick = lo === hi;
    const newMin = bucketToPrice(lo);
    // Inclusive of the last bucket: max = right edge of bucket hi.
    // If hi is the rightmost bucket, treat as "no upper cap" (keeps
    // listings >$1M in scope).
    const hiPrice = bucketToPrice(hi + 1);
    const newMax = hi === HISTO_BUCKETS - 1 ? null : hiPrice;
    setFilters({ price_min: newMin, price_max: newMax });
    if (isSingleClick) {
      track("browse.price_histogram.bar_clicked", {
        bucket_min: newMin, bucket_max: hiPrice,
      });
    } else {
      track("browse.price_histogram.dragged", {
        from_min: filters.price_min, from_max: filters.price_max,
        to_min: newMin, to_max: newMax,
      });
    }
    setDragging(null);
    setBrushFrom(null);
    setBrushTo(null);
  };

  // ── Reset ─────────────────────────────────────────────────────
  const onReset = () => {
    setFilters({ price_min: 0, price_max: null });
    track("browse.price_histogram.reset", {});
  };
  const onKeyDown = (e) => {
    if (e.key === "Escape" && hasRange) {
      e.preventDefault();
      onReset();
    }
  };

  // ── Keyboard on thumbs ────────────────────────────────────────
  const onMinKey = (e) => {
    let delta = 0;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") delta = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") delta = 1;
    if (e.shiftKey) delta *= 5;
    if (delta === 0) return;
    e.preventDefault();
    const cur = priceToBucket(filters.price_min);
    const cap = priceToBucket(filters.price_max != null ? filters.price_max : HISTO_VISUAL_MAX);
    const next = Math.min(cap, Math.max(0, cur + delta));
    setFilters({ price_min: bucketToPrice(next) });
  };
  const onMaxKey = (e) => {
    let delta = 0;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") delta = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") delta = 1;
    if (e.shiftKey) delta *= 5;
    if (delta === 0) return;
    e.preventDefault();
    const curIdx = filters.price_max != null ? priceToBucket(filters.price_max) : HISTO_BUCKETS;
    const floor = priceToBucket(filters.price_min);
    const nextIdx = Math.min(HISTO_BUCKETS, Math.max(floor, curIdx + delta));
    const newPrice = nextIdx >= HISTO_BUCKETS ? null : bucketToPrice(nextIdx);
    setFilters({ price_max: newPrice });
  };

  return (
    <div className="histo" onKeyDown={onKeyDown}>
      <div
        className={`histo-track ${dragging ? "is-dragging" : ""}`}
        ref={trackRef}
        onPointerDown={onTrackPointerDown}
        onPointerMove={onTrackPointerMove}
        onPointerUp={onTrackPointerUp}
        onPointerCancel={onTrackPointerUp}
      >
        <div className="histo-bars" aria-hidden="true">
          {counts.map((c, i) => {
            const left = i * (100 / HISTO_BUCKETS);
            const right = (i + 1) * (100 / HISTO_BUCKETS);
            const inRange = left >= minPct && right <= maxPct + 0.01;
            const inBrush = brushActive && i >= brushLow && i < brushHigh;
            return (
              <div
                key={i}
                className={`histo-bar ${inRange ? "active" : ""} ${inBrush ? "is-brushed" : ""}`}
                style={{ height: `${(c/peak)*100}%` }}
              />
            );
          })}
        </div>
        {/* Range overlay — shaded band between thumbs */}
        <div
          className="histo-range-overlay"
          style={{ left: `${minPct}%`, width: `${Math.max(0, maxPct - minPct)}%` }}
          aria-hidden="true"
        />
        {/* Brush overlay (while dragging across bars, before commit) */}
        {brushActive && (
          <div
            className="histo-brush-overlay"
            style={{
              left: `${brushLow * (100 / HISTO_BUCKETS)}%`,
              width: `${(brushHigh - brushLow) * (100 / HISTO_BUCKETS)}%`,
            }}
            aria-hidden="true"
          />
        )}
        <button
          type="button"
          role="slider"
          className={`histo-thumb histo-thumb-min ${dragging === "min" ? "is-dragging" : ""}`}
          style={{ left: `${minPct}%` }}
          aria-label={lc === "es" ? "Precio mínimo" : "Minimum price"}
          aria-valuemin={0}
          aria-valuemax={HISTO_VISUAL_MAX}
          aria-valuenow={visualMinPrice}
          aria-valuetext={formatPrice(visualMinPrice)}
          onPointerDown={(e) => startThumbDrag("min", e)}
          onPointerMove={onThumbMove}
          onPointerUp={onThumbUp}
          onPointerCancel={onThumbUp}
          onKeyDown={onMinKey}
        >
          {dragging === "min" && (
            <span className="histo-thumb-label" aria-hidden="true">{formatPrice(visualMinPrice)}</span>
          )}
        </button>
        <button
          type="button"
          role="slider"
          className={`histo-thumb histo-thumb-max ${dragging === "max" ? "is-dragging" : ""}`}
          style={{ left: `${maxPct}%` }}
          aria-label={lc === "es" ? "Precio máximo" : "Maximum price"}
          aria-valuemin={0}
          aria-valuemax={HISTO_VISUAL_MAX}
          aria-valuenow={visualMaxPrice}
          aria-valuetext={liveMax != null ? formatPrice(liveMax) : (filters.price_max != null ? formatPrice(filters.price_max) : (lc === "es" ? "sin tope" : "no max"))}
          onPointerDown={(e) => startThumbDrag("max", e)}
          onPointerMove={onThumbMove}
          onPointerUp={onThumbUp}
          onPointerCancel={onThumbUp}
          onKeyDown={onMaxKey}
        >
          {dragging === "max" && (
            <span className="histo-thumb-label" aria-hidden="true">
              {liveMax != null && liveMax >= HISTO_VISUAL_MAX
                ? (lc === "es" ? "sin tope" : "no max")
                : formatPrice(visualMaxPrice)}
            </span>
          )}
        </button>
      </div>
      {hasRange && (
        <div className="histo-meta" aria-live="polite">
          <span className="histo-current-range">
            {formatPrice(filters.price_min)}–{filters.price_max != null ? formatPrice(filters.price_max) : (lc === "es" ? "sin tope" : "no max")}
          </span>
          <button type="button" className="link-btn histo-reset" onClick={onReset}>
            {lc === "es" ? "Restablecer" : "Reset"}
          </button>
        </div>
      )}
      <div className="price-inputs">
        <div className="price-input">
          <label>{lc === "es" ? "Mín" : "Min"}</label>
          <input type="number" value={filters.price_min} onChange={(e) => setFilters({ price_min: +e.target.value })} />
        </div>
        <div className="price-input">
          <label>{lc === "es" ? "Máx" : "Max"}</label>
          <input
            type="number"
            value={filters.price_max ?? ""}
            placeholder={filters.price_max == null ? (lc === "es" ? "sin tope" : "any") : ""}
            onChange={(e) => {
              const v = e.target.value;
              setFilters({ price_max: v === "" ? null : +v });
            }}
          />
        </div>
      </div>
    </div>
  );
}

// Default ranking weights — match legacy index.js (PR-4b restore).
const WEIGHT_DEFAULTS = { value: 40, location: 35, momentum: 25 };

function makeDefaultFilters() {
  return {
    zones: new Set(),
    land_types: new Set(),
    features: new Set(),
    infra: new Set(),
    status: new Set(),
    price_min: 0,
    // null = no upper cap. The previous default of 1,000,000 silently
    // hid every listing above $1M (~20% of the catalog) — Browse
    // counted ~700 while LiveStats correctly reported 873. Bug fix.
    price_max: null,
    size_min: 0,
    readiness: 0,
    // PR-4b — feature parity with legacy:
    score_min: 0,                             // 0–100 score floor
    weights: { ...WEIGHT_DEFAULTS },          // V/L/M weights, sum = 100
    photos: "all",                            // "all" | "with" | "none"
    // Rewrite Phase 5B — new IA filter axes (Beach/Lake × Homes/
    // Condos/Land + 4 discovery tags). The homepage CategoryGrid /
    // DiscoveryPills navigate here with these pre-set via
    // buildFiltersForCategory.
    master_category: null,                    // "beach" | "lake" | null
    subcategory: null,                        // "homes" | "condos" | "land" | null
    discovery_tags: new Set(),                // subset of {top_rated, under_250k, gated, waterfront}
    rank_max: null,                           // position-rank cap; e.g. 10 for "Top 10" chip
    // Inverse-semantic toggle. Defaults to false → listings where the
    // broker hasn't shared price or size are hidden. Toggling on
    // surfaces them at the bottom of the result set (ranker already
    // hard-floored them, so the order is correct without extra work).
    include_incomplete: false,
  };
}

// Recompute composite score from V/L/M components and user-overridden
// weights. Mirrors legacy index.js:recomputeComposite. Returns the
// listing's static rank_score when weights match defaults.
function recomputeComposite(l, w) {
  if (!w) return l.rank_score ?? 0;
  if (w.value === WEIGHT_DEFAULTS.value && w.location === WEIGHT_DEFAULTS.location && w.momentum === WEIGHT_DEFAULTS.momentum) {
    return l.rank_score ?? 0;
  }
  const v = l.value_score ?? 0;
  const ll = l.location_score ?? 0;
  const m = l.momentum_score ?? 0;
  const total = w.value + w.location + w.momentum;
  if (total <= 0) return 0;
  return (v * w.value + ll * w.location + m * w.momentum) / total;
}

// "Top 10" rank map: listing id → 1..10 based on global rank_score desc.
// Filters out sold + missing-rank listings before slicing, so the chip
// represents the 10 best *available* listings rather than the 10
// highest scores including sold/null entries. Same map is consumed by
// BrowsePage and SavedPage so the chip means the same thing on both
// surfaces — and stays attached to the listing regardless of filter
// or sort.
function buildTopRankMap(listings, n = 10) {
  const out = new Map();
  const ranked = [...listings]
    .filter((l) => !l.is_sold && l.rank_score != null)
    .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0))
    .slice(0, n);
  ranked.forEach((l, i) => out.set(l.id, i + 1));
  return out;
}

function applyFilters(listings, f) {
  return listings.filter(l => {
    if (l.is_sold) return false;
    // Quality gate — incomplete listings are hidden by default.
    // The Browse FilterPanel chip flips `include_incomplete` to opt in.
    if (l.is_incomplete && !f.include_incomplete) return false;
    if (f.zones.size && !f.zones.has(l.zone_name)) return false;
    if (f.land_types.size && !f.land_types.has(l.land_type)) return false;
    if (l.price < f.price_min) return false;
    if (f.price_max != null && l.price > f.price_max) return false;
    if (l.size_m2 < f.size_min) return false;
    if (f.features.has("beachfront") && !l.beachfront_tier) return false;
    if (f.features.has("ocean_view") && !l.has_ocean_view) return false;
    if (f.features.has("mountain_view") && !l.has_mountain_view) return false;
    if (f.features.has("flat") && !l.is_flat) return false;
    if (f.features.has("water_body") && !l.has_water_body) return false;
    if (f.infra.has("water") && !l.has_water) return false;
    if (f.infra.has("power") && !l.has_power) return false;
    if (f.infra.has("paved") && l.road_access_type !== "paved") return false;
    if (f.infra.has("sewage") && !l.has_sewage) return false;
    if (f.status.has("new") && l.first_seen_date > 7) return false;
    if (f.status.has("price_drop") && !l.is_repriced) return false;
    if (f.status.has("off_market") && l.source_type !== "off_market") return false;
    if (f.status.has("motivated") && (typeof l.days_listed !== "number" || l.days_listed < 90)) return false;
    if (l.readiness_score < f.readiness) return false;
    if ((f.score_min ?? 0) > 0 && (l.rank_score ?? 0) < f.score_min) return false;
    if (f.photos === "with" && (l.photos_count ?? 0) === 0) return false;
    if (f.photos === "none" && (l.photos_count ?? 0) > 0) return false;
    // Rewrite Phase 5B — new IA filters. master/sub are single-select;
    // discovery_tags is multi-select (every selected tag must apply).
    if (f.master_category && l.master_category !== f.master_category) return false;
    if (f.subcategory && l.subcategory !== f.subcategory) return false;
    if (f.discovery_tags && f.discovery_tags.size > 0) {
      const tags = Array.isArray(l.discovery_tags) ? l.discovery_tags : [];
      for (const required of f.discovery_tags) {
        if (!tags.includes(required)) return false;
      }
    }
    if (f.rank_max != null && f.rank_max > 0) {
      if (typeof l.rank !== "number" || l.rank > f.rank_max) return false;
    }
    return true;
  });
}

// ====== Browse Page ======
// Map a category key → which filters it pre-applies. Pulled out of the
// component so it can run from both useState's initializer and useEffect's
// resync (so clicking "All" actually clears prior category's filters).
function buildFiltersForCategory(category) {
  const f = makeDefaultFilters();
  if (!category) return f;
  const map = {
    beachfront: () => f.features.add("beachfront"),
    ocean_view: () => f.features.add("ocean_view"),
    mountain_view: () => f.features.add("mountain_view"),
    flat_buildable: () => f.features.add("flat"),
    water_features: () => f.features.add("water_body"),
    new_this_week: () => f.status.add("new"),
    price_drops: () => f.status.add("price_drop"),
    off_market: () => f.status.add("off_market"),
    motivated_sellers: () => f.status.add("motivated"),
    commercial: () => f.land_types.add("commercial"),
    agricultural: () => f.land_types.add("agricultural"),
    under_100k: () => { f.price_max = 100000; },
    under_50k: () => { f.price_max = 50000; },
    build_ready: () => { f.readiness = 3; },
    // Rewrite Phase 5B — new IA category slugs. Homepage CategoryGrid
    // emits `${master}_${sub}` ("beach_homes") + master-only ("beach"
    // for "Browse all"); DiscoveryPills emits the tag name directly.
    beach:        () => { f.master_category = "beach"; },
    lake:         () => { f.master_category = "lake"; },
    beach_homes:  () => { f.master_category = "beach"; f.subcategory = "homes"; },
    beach_condos: () => { f.master_category = "beach"; f.subcategory = "condos"; },
    beach_land:   () => { f.master_category = "beach"; f.subcategory = "land"; },
    lake_homes:   () => { f.master_category = "lake";  f.subcategory = "homes"; },
    lake_condos:  () => { f.master_category = "lake";  f.subcategory = "condos"; },
    lake_land:    () => { f.master_category = "lake";  f.subcategory = "land"; },
    top_rated:    () => { f.discovery_tags.add("top_rated"); },
    under_250k:   () => { f.discovery_tags.add("under_250k"); },
    gated:        () => { f.discovery_tags.add("gated"); },
    waterfront:   () => { f.discovery_tags.add("waterfront"); },
    top_10:       () => { f.rank_max = 10; },
  };
  map[category]?.();
  return f;
}

function BrowsePage({ app }) {
  const LISTINGS = useListings();
  const listingsState = useListingsState();
  // Initial filter state — seed from URL on first render so a refresh
  // of /browse?features=beachfront&pmax=100000 reproduces the view.
  const [filters, setFilters] = pUseState(() => {
    const seeded = buildFiltersForCategory(app.routeParams.category);
    if (typeof window !== "undefined") {
      return readFilterFromURL(window.location.search, seeded);
    }
    return seeded;
  });
  const [view, setView] = pUseState(() => localStorage.getItem("pulpo-view") || "cards");
  const [sort, setSort] = pUseState(() =>
    typeof window !== "undefined"
      ? readSortFromURL(window.location.search, "recent")
      : "recent"
  );
  const [filterDrawerOpen, setFilterDrawerOpen] = pUseState(false);

  // popstate filter resync — BrowsePage stays mounted when the user
  // goes Browse → Discover → back, or Browse → Listing → close → back.
  // Mount-time filter seed only runs once, so without this effect the
  // chips would render their last in-memory state, not what the URL
  // says. Resync on every history-API event so the chips visually
  // match the URL.
  pUseEffect(() => {
    if (typeof window === "undefined") return;
    const onPop = () => {
      const seeded = buildFiltersForCategory(
        new URLSearchParams(window.location.search).get("cat")
      );
      setFilters(readFilterFromURL(window.location.search, seeded));
      setSort(readSortFromURL(window.location.search, "recent"));
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Pagination — render in 60-card pages. Filters/sort/category changes
  // reset back to one page. Avoids dumping ~870 cards into the DOM at once.
  const PAGE_SIZE = 60;
  // Cards above this index get loading="eager" + fetchpriority="high".
  // The rest fall back to native loading="lazy" and only fetch when
  // they near the viewport, so a 60-card filter result doesn't slam
  // the priority lane.
  const ABOVE_FOLD_COUNT = 6;
  const [visibleCount, setVisibleCount] = pUseState(PAGE_SIZE);

  // When the category in the URL changes (incl. "All" which is null), resync
  // filters to match. Without this, useState's lazy initializer only runs once
  // and stale filters carry over — clicking "All" leaves the previous category's
  // chips still applied. We layer URL params on top so a cold-load with
  // ?inc=1 / ?pmin=... survives the first render — without this overlay,
  // the effect's mount-time fire reset URL-only flags to defaults.
  pUseEffect(() => {
    const f = buildFiltersForCategory(app.routeParams.category);
    if (Array.isArray(app.routeParams.zones) && app.routeParams.zones.length > 0) {
      f.zones = new Set(app.routeParams.zones);
    }
    if (typeof window !== "undefined") {
      setFilters(readFilterFromURL(window.location.search, f));
    } else {
      setFilters(f);
    }
  }, [app.routeParams.category, app.routeParams.zones]);

  // Persist filter + sort + category to URLSearchParams (replaceState
  // — no new history entries on every chip toggle).
  pUseEffect(() => {
    writeFilterToURL(filters, app.routeParams.category ?? null, sort);
  }, [filters, sort, app.routeParams.category]);

  pUseEffect(() => { localStorage.setItem("pulpo-view", view); }, [view]);

  // Reset pagination back to page 1 whenever the result set could change.
  // Without this, a filter that drops the count below visibleCount leaves
  // a stale "Load more (-N remaining)" button visible.
  pUseEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [filters, sort, app.routeParams.category]);

  // Debounce the slider-driven filter values 300ms so a single drag
  // doesn't fire dozens of applyFilters() passes. Chip toggles still
  // feel instant — the debounced snapshot tracks the live value.
  const debouncedFilters = useDebouncedValue(filters, 300);

  const topRankMap = pUseMemo(() => buildTopRankMap(LISTINGS), [LISTINGS]);

  const results = pUseMemo(() => {
    // PR-photo-nav-perf — filter+sort cost is the most expensive
    // recurring computation on Browse (873 listings × 15 predicates).
    // Telemetry surfaces P95 in PostHog so a regression is visible.
    const _perf_t0 = (typeof performance !== "undefined" && performance.now) ? performance.now() : 0;
    const r = applyFilters(LISTINGS, debouncedFilters);
    const sorters = {
      recent: (a, b) => a.first_seen_date - b.first_seen_date,
      price_asc: (a, b) => (a.price ?? Infinity) - (b.price ?? Infinity),
      price_desc: (a, b) => (b.price ?? -1) - (a.price ?? -1),
      size_desc: (a, b) => (b.size_m2 ?? 0) - (a.size_m2 ?? 0),
      ppm_asc: (a, b) => (a.price_per_m2 ?? Infinity) - (b.price_per_m2 ?? Infinity),
      // Push null days_listed to the end of asc order (unknown age
       // shouldn't masquerade as freshest).
      days_asc: (a, b) => {
        const av = typeof a.days_listed === "number" ? a.days_listed : Number.POSITIVE_INFINITY;
        const bv = typeof b.days_listed === "number" ? b.days_listed : Number.POSITIVE_INFINITY;
        return av - bv;
      },
      ready_desc: (a, b) => b.readiness_score - a.readiness_score,
      stars_desc: (a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0),
      // Composite using user-overridden weights (PR-4b — feature parity).
      composite_desc: (a, b) =>
        recomputeComposite(b, debouncedFilters.weights) -
        recomputeComposite(a, debouncedFilters.weights),
    };
    const sorted = [...r].sort(sorters[sort] || sorters.recent);
    // Emit perf telemetry for the full filter+sort cycle.
    if (_perf_t0 > 0 && typeof performance !== "undefined" && performance.now) {
      const ms = Math.round(performance.now() - _perf_t0);
      const _activeFilterCount =
        debouncedFilters.zones.size + debouncedFilters.land_types.size +
        debouncedFilters.features.size + debouncedFilters.infra.size +
        debouncedFilters.status.size +
        (debouncedFilters.price_max != null || debouncedFilters.price_min > 0 ? 1 : 0) +
        (debouncedFilters.readiness > 0 ? 1 : 0);
      track("perf.filter_recompute", {
        ms,
        result_count: sorted.length,
        active_filters: _activeFilterCount,
      });
    }
    return sorted;
  }, [debouncedFilters, sort, LISTINGS]);

  const activeFilterCount = filters.zones.size + filters.land_types.size + filters.features.size + filters.infra.size + filters.status.size + (filters.price_max != null || filters.price_min > 0 ? 1 : 0) + (filters.readiness > 0 ? 1 : 0);

  // Telemetry: report empty-result state once per filter change so the
  // funnel can flag filter combinations that nuke the results.
  pUseEffect(() => {
    if (results.length === 0 && activeFilterCount > 0) {
      track("browse.empty_results", {
        filters: {
          zones: [...filters.zones].length,
          land_types: [...filters.land_types].length,
          features: [...filters.features].length,
          infra: [...filters.infra].length,
          status: [...filters.status].length,
          price_min: filters.price_min,
          price_max: filters.price_max,
          readiness: filters.readiness,
        },
      });
    }
  }, [results.length, activeFilterCount]);

  // Wrap setSort / setView to fire telemetry on user-driven changes.
  // setFilters intentionally untracked — chip handlers wrap it themselves
  // when needed.
  const setSortTelemeter = pUseCallback((next) => {
    setSort(next);
    track("browse.sort_changed", { sort: next });
  }, []);
  const setViewTelemeter = pUseCallback((next) => {
    setView(next);
    track("browse.view_toggled", { view: next });
  }, []);

  // === Hooks done — branch on load state. ===
  if (listingsState.state.status === "loading") return <BrowseSkeleton />;
  if (listingsState.state.status === "error") {
    return <DataFetchFailed onRetry={listingsState.reload} />;
  }

  return (
    <div className="page page-browse">
      <PillRail app={app} />
      <div className="browse-layout">
        <div className="filter-desktop">
          <FilterPanel filters={filters} setFilters={setFilters} count={results.length} app={app} />
        </div>
        <div className="results-col">
          <div className="results-header">
            <div className="results-count">
              {filters.rank_max === 10 ? (
                // Top 10 chip is active. The Top 10 list is GLOBAL — chips
                // like Beach / Waterfront slice it, they don't re-rank it.
                // The "N of 10" meta makes the slice transparent: if Beach
                // is also active and 6 of the global Top 10 are beach
                // listings, the user sees "6 of 10" and understands they're
                // looking at the intersection, not a re-ranked "Top 10 in
                // beach."
                <>
                  <span className="results-cat-title">{t("browse.top10.title", app.locale)}</span>
                  <span className="results-cat-meta">
                    <span className="num">{results.length}</span> {t("browse.top10.of_ten", app.locale)}
                    <button
                      className="cat-clear"
                      onClick={() => {
                        // Clear rmax from URL so the user drops back to the
                        // full ranked list. Other chips (master, tag, pmax)
                        // stay applied — they're independent dimensions.
                        if (typeof window !== "undefined") {
                          const next = new URLSearchParams(window.location.search);
                          next.delete("rmax");
                          const qs = next.toString();
                          window.history.pushState({}, "", `/browse${qs ? `?${qs}` : ""}`);
                        }
                        app.goBrowse({ category: null });
                      }}
                      aria-label={t("browse.top10.clear", app.locale)}
                      title={t("browse.top10.clear", app.locale)}
                    >
                      <Icon name="close" size={14} strokeWidth={2}/>
                    </button>
                  </span>
                </>
              ) : app.routeParams.category ? (() => {
                const cat = PILLS.find(p => p.key === app.routeParams.category)
                          || SHELVES.find(s => s.key === app.routeParams.category);
                const label = cat ? tr(cat.label, app.locale) : app.routeParams.category;
                return (
                  <>
                    <span className="results-cat-title">{label}</span>
                    <span className="results-cat-meta">
                      <span className="num">{results.length}</span> {t("browse.in_country", app.locale)}
                      <button
                        className="cat-clear"
                        onClick={() => app.goBrowse({ category: null })}
                        aria-label={t("browse.clear_category", app.locale)}
                        title={t("browse.clear_category", app.locale)}
                      >
                        <Icon name="close" size={14} strokeWidth={2}/>
                      </button>
                    </span>
                  </>
                );
              })() : (
                <>
                  <span className="num">{results.length}</span> {t("card.listings_count", app.locale)}
                </>
              )}
            </div>
            <div className="results-controls">
              <button className="filter-mobile-btn" onClick={() => setFilterDrawerOpen(true)}>
                <Icon name="sliders" size={16} /> {t("view.filters", app.locale)} {activeFilterCount > 0 && <span className="count-badge">{activeFilterCount}</span>}
              </button>
              {/* Rewrite Phase 5B — top 4 options now lead the dropdown
                  with the brief's canonical labels (Highest value /
                  Lowest price / Newest / Largest plot). The underlying
                  sort KEYS are unchanged so saved URLs (?sort=stars_desc
                  etc.) keep working; only the visible labels move. The
                  legacy options stay below for power-user access. */}
              <select className="sort-select" value={sort} onChange={(e) => setSortTelemeter(e.target.value)}>
                <option value="stars_desc">{t("sort.highest_value", app.locale)}</option>
                <option value="price_asc">{t("sort.lowest_price", app.locale)}</option>
                <option value="days_asc">{t("sort.newest", app.locale)}</option>
                <option value="size_desc">{t("sort.largest_plot", app.locale)}</option>
                <option value="recent">{t("sort.recent", app.locale)}</option>
                <option value="price_desc">{t("sort.price_desc", app.locale)}</option>
                <option value="ppm_asc">{t("sort.ppm_asc_suffix", app.locale, { suffix: `$${ppmSuffix()}` })}</option>
                <option value="ready_desc">{t("sort.ready_desc", app.locale)}</option>
                <option value="composite_desc">{t("sort.composite_desc", app.locale)}</option>
              </select>
              <div className="view-toggle">
                <button className={view === "table" ? "active" : ""} onClick={() => setViewTelemeter("table")} aria-label={t("view.table", app.locale)}>
                  <Icon name="list" size={16}/>
                </button>
                <button className={view === "cards" ? "active" : ""} onClick={() => setViewTelemeter("cards")} aria-label={t("view.cards", app.locale)}>
                  <Icon name="grid" size={16}/>
                </button>
                {/* Map view placeholder per rewrite plan step 6. Disabled
                    until the map prototype lands; the tooltip explains
                    that to users who try clicking. */}
                <button
                  disabled
                  className="map-view-placeholder"
                  aria-label={t("view.map_coming_soon", app.locale)}
                  title={t("view.map_coming_soon", app.locale)}
                >
                  <Icon name="map_pin" size={16}/>
                </button>
              </div>
            </div>
          </div>

          {/* Active filter chips row */}
          {activeFilterCount > 0 && (
            <div className="active-filter-row">
              {[...filters.zones].map(z => <span key={z} className="active-chip" onClick={() => { const s = new Set(filters.zones); s.delete(z); setFilters({...filters, zones: s});}}>{z} <Icon name="close" size={12}/></span>)}
              {[...filters.land_types].map(t => <span key={t} className="active-chip" onClick={() => { const s = new Set(filters.land_types); s.delete(t); setFilters({...filters, land_types: s});}}>{landTypeLabel(t)} <Icon name="close" size={12}/></span>)}
              {[...filters.features].map(f => <span key={f} className="active-chip" onClick={() => { const s = new Set(filters.features); s.delete(f); setFilters({...filters, features: s});}}>{f.replace("_", " ")} <Icon name="close" size={12}/></span>)}
              {[...filters.infra].map(f => <span key={f} className="active-chip" onClick={() => { const s = new Set(filters.infra); s.delete(f); setFilters({...filters, infra: s});}}>{f} <Icon name="close" size={12}/></span>)}
              {[...filters.status].map(f => <span key={f} className="active-chip" onClick={() => { const s = new Set(filters.status); s.delete(f); setFilters({...filters, status: s});}}>{f.replace("_", " ")} <Icon name="close" size={12}/></span>)}
              {(filters.price_min > 0 || filters.price_max != null) && <span className="active-chip" onClick={() => setFilters({...filters, price_min: 0, price_max: null})}>{formatPrice(filters.price_min)}–{filters.price_max != null ? formatPrice(filters.price_max) : (app.locale === "es" ? "sin tope" : "no max")} <Icon name="close" size={12}/></span>}
            </div>
          )}

          {results.length === 0 ? (
            <EmptyResults
              onClear={() => setFilters(makeDefaultFilters())}
              filters={filters}
              listings={LISTINGS}
              setFilters={setFilters}
            />
          ) : view === "cards" ? (
            <>
              <div className="card-grid">
                {/* `priority={i < ABOVE_FOLD_COUNT}` is the actual fix for
                    Browse-after-filter slowness. Marking every card eager
                    storms the high-priority lane the moment 60 cards
                    mount, and above-fold cards stall behind off-screen
                    fetches. 6 covers ~2 rows on a desktop auto-fill grid
                    and ~3 rows on a typical mobile portrait — anything
                    below that falls through to native loading="lazy". */}
                {results.slice(0, visibleCount).map((l, i) => (
                  <ListingCard
                    key={l.id}
                    listing={l}
                    app={app}
                    priority={i < ABOVE_FOLD_COUNT}
                    source="browse"
                    topRank={topRankMap.get(l.id)}
                    onOpen={() => {
                      track("card.clicked", { listing_id: l.id, source_view: "browse" });
                      // Route through the matrix so anon + free hit the
                      // FreeMonthModal (paid users open the listing).
                      const branch = routeCtaForState("shelf_card", app?.user);
                      trackCtaRouted("shelf_card", app?.user, branch, true);
                      if (branch === "passthrough") {
                        app.openListing(l.id);
                        return;
                      }
                      void dispatchCentralBranch(branch, app, {
                        trigger: "browse_card",
                        pendingListing: l.id,
                      });
                    }}
                  />
                ))}
              </div>
              {visibleCount < results.length && (
                <div className="browse-load-more">
                  <button
                    className="btn-ghost lg"
                    onClick={() => {
                      const next = visibleCount + PAGE_SIZE;
                      track("browse.load_more_clicked", {
                        from: visibleCount,
                        to: Math.min(next, results.length),
                        total: results.length,
                      });
                      setVisibleCount(next);
                    }}
                  >
                    {t("browse.load_more", app.locale, { n: results.length - visibleCount })}
                  </button>
                </div>
              )}
            </>
          ) : (
            <ResultsTable results={results} app={app} sort={sort} setSort={setSortTelemeter} topRankMap={topRankMap} />
          )}
        </div>
      </div>

      {filterDrawerOpen && (
        <div className="filter-drawer-backdrop" onClick={() => setFilterDrawerOpen(false)}>
          <div className="filter-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-handle" />
            <FilterPanel filters={filters} setFilters={setFilters} count={results.length} onClose={() => setFilterDrawerOpen(false)} app={app} />
          </div>
        </div>
      )}
    </div>
  );
}

// ====== Results table ======
function ResultsTable({ results, app, sort, setSort, topRankMap }) {
  const headerSortable = (key, label) => {
    const map = { price: "price_asc", days: "days_asc", size: "size_desc", ppm: "ppm_asc" };
    const active = sort === map[key];
    return (
      <th onClick={() => setSort(map[key])} className={active ? "sorted" : ""}>
        {label} {active && <Icon name="chevron_down" size={12}/>}
      </th>
    );
  };
  return (
    <div className="results-table-wrap">
      <table className="results-table">
        <thead>
          <tr>
            <th></th>
            <th>Listing</th>
            <th>Zone</th>
            <th>Type</th>
            {headerSortable("size", "Size")}
            {headerSortable("price", "Price")}
            {headerSortable("ppm", `$${ppmSuffix()}`)}
            {headerSortable("days", "Days")}
            <th>Signal</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {results.map(l => (
            <tr key={l.id} onClick={() => app.openListing(l.id)}>
              <td className="thumb-cell">
                {(l.thumbnail_url ?? l.photos[0]) ? (
                  <img src={l.thumbnail_url ?? l.photos[0]} alt=""/>
                ) : (
                  <div className="thumb-placeholder"/>
                )}
              </td>
              <td className="title-cell">
                {topRankMap && topRankMap.get(l.id) != null && (
                  <span className="pulpo-rank pulpo-rank-inline" aria-label={`Pulpo ranked ${topRankMap.get(l.id)}`}>
                    <span className="pulpo-rank-star" aria-hidden="true">★</span>
                    <span className="pulpo-rank-num">{topRankMap.get(l.id)}</span>
                  </span>
                )}
                {tr(l.title, app.locale)}
              </td>
              <td>{l.zone_name}</td>
              <td><span className={`type-pill type-${l.land_type}`}>{landTypeLabel(l.land_type)}</span></td>
              <td className="num">{formatSize(l.size_m2)}</td>
              <td className="num bold">{formatPrice(l.price)}</td>
              <td className="num muted">{formatPpm(l.price_per_m2)}</td>
              <td className={`num tone-${daysListedTone(l.days_listed)}`}>{typeof l.days_listed === "number" ? `${l.days_listed}d` : "—"}</td>
              <td><Badge listing={l}/></td>
              <td onClick={(e) => e.stopPropagation()}><HeartButton listingId={l.id} app={app} variant="inline" size={16}/></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ====== Listing Detail ======
// schema.org RealEstateListing JSON-LD for /listing/:id. Embedded as a
// <script type="application/ld+json"> so Google + Bing get rich-result
// metadata (price, area, geo, photos, datePosted). Crawlers that
// execute JS see this; static social previews don't (the static-stub
// follow-up will fix that).
function ListingJsonLd({ listing, locale }) {
  const json = pUseMemo(() => {
    const lc = locale === "es" ? "es" : "en";
    const title = listing.title?.[lc] ?? listing.title?.en ?? "";
    const description = listing.description?.[lc] ?? listing.description?.en ?? "";
    const url = typeof window !== "undefined"
      ? new URL(`/listing/${encodeURIComponent(listing.id)}`, window.location.origin).toString()
      : `https://pulpo.club/listing/${encodeURIComponent(listing.id)}`;
    const photos = Array.isArray(listing.photos)
      ? listing.photos.slice(0, 8).map((src) => {
          try {
            return typeof window !== "undefined" ? new URL(src, window.location.origin).toString() : src;
          } catch { return src; }
        })
      : [];
    const data = {
      "@context": "https://schema.org",
      "@type": "RealEstateListing",
      "@id": url,
      url,
      name: title || "Pulpo listing",
      description: description || undefined,
      image: photos.length ? photos : undefined,
      address: {
        "@type": "PostalAddress",
        addressCountry: "SV",
        addressRegion: listing.region || undefined,
        addressLocality: listing.zone_name || undefined,
      },
      offers: listing.price && !listing.is_sold && listing.source_type !== "off_market"
        ? {
            "@type": "Offer",
            price: listing.price,
            priceCurrency: "USD",
            availability: "https://schema.org/InStock",
          }
        : undefined,
      floorSize: listing.size_m2
        ? { "@type": "QuantitativeValue", value: listing.size_m2, unitCode: "MTK" }
        : undefined,
    };
    // Strip undefined keys so the resulting JSON is clean.
    const stripped = JSON.parse(JSON.stringify(data));
    // Escape `<` so a description containing `</script>` (from a scrape
    // or LLM enrichment) can't break out of the JSON-LD island and run
    // as HTML. JSON.stringify doesn't escape `<` by default.
    return JSON.stringify(stripped).replace(/</g, "\\u003c");
  }, [listing.id, listing.title, listing.description, listing.photos, listing.price, listing.size_m2, listing.is_sold, listing.source_type, listing.region, listing.zone_name, locale]);
  return (
    <script
      type="application/ld+json"
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: json }}
    />
  );
}

function ListingDetail({ listing, app, asPanel = true }) {
  const [galleryIdx, setGalleryIdx] = pUseState(0);
  const [lightbox, setLightbox] = pUseState(false);
  const isSold = listing.is_sold;
  const isOffMarket = listing.source_type === "off_market";
  // Single source of truth for paywall rules — see web/app/lib/gating.ts.
  // Off-market is paid-only; anonymous + free hit the soft paywall.
  const isPaid = gateIsPaid(app.user);
  const offMarketLocked = isOffMarket && !isPaid;
  // Free signup unlocks: source URL, full gallery, all USPs, precise location.
  const needsSignup = !app.user;
  const uspCap = uspsVisibleFor(app.user);
  const thumbCap = galleryThumbsUnlockedFor(app.user);

  // PR-5 — detail telemetry. Fire `detail.opened` once per listing
  // (re-fires when user navigates to a different listing). Auth state
  // is anonymous in this PR; PR-9 wires the real free/pro distinction.
  pUseEffect(() => {
    const authState = !app.user ? "anonymous" : (isPaid ? "pro" : "free");
    track("detail.opened", {
      listing_id: listing.id,
      auth_state: authState,
      ...(app.user ? { plan: isPaid ? "pro" : "free" } : {}),
    });
    if (app.user && !isSold) app.recordDetailView();
  }, [listing.id]);

  // Paywall telemetry. Fires once per listing+lock transition when the
  // off-market hard paywall renders. Bypass events fire on the buttons
  // inside the overlay below, so the funnel
  // shown → bypassed.action=upgrade → plans.viewed → checkout closes.
  pUseEffect(() => {
    if (!offMarketLocked) return;
    track("paywall.shown", { kind: "off_market", listing_id: listing.id });
  }, [listing.id, offMarketLocked]);

  // PR-5 — lightbox a11y. ESC closes, ←/→ navigate, Tab is trapped
  // inside the lightbox. Focus moves to the close button on open and
  // returns to the trigger on close.
  const lightboxRef = pUseRef(null);
  const lightboxCloseRef = pUseRef(null);
  const lastFocusRef = pUseRef(null);
  pUseEffect(() => {
    if (!lightbox) return;
    lastFocusRef.current = document.activeElement;
    setTimeout(() => lightboxCloseRef.current?.focus(), 0);
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); setLightbox(false); }
      else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setGalleryIdx(i => (i - 1 + listing.photos.length) % listing.photos.length);
      }
      else if (e.key === "ArrowRight") {
        e.preventDefault();
        setGalleryIdx(i => (i + 1) % listing.photos.length);
      }
      else if (e.key === "Tab") {
        const root = lightboxRef.current;
        if (!root) return;
        const focusable = root.querySelectorAll(
          'button, [href], [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault(); first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      if (lastFocusRef.current && typeof lastFocusRef.current.focus === "function") {
        lastFocusRef.current.focus();
      }
    };
  }, [lightbox, listing.photos.length]);

  const openLightbox = (idx) => {
    const t0 = (typeof performance !== "undefined" && performance.now) ? performance.now() : 0;
    setGalleryIdx(idx);
    setLightbox(true);
    track("detail.photo_lightbox_opened", { listing_id: listing.id });
    // PR-photo-nav-perf — lightbox open latency = state-set → next paint.
    if (t0 > 0) {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const ms = Math.round(performance.now() - t0);
        track("perf.lightbox_open", { listing_id: listing.id, ms });
      }));
    }
  };

  const lc = app.locale;
  // Only push facts that have real data — skipping the "—" placeholders
  // we used to render. Facts with null / false / "unknown" values
  // disappear, and the parent section is hidden when fewer than 2
  // remain (rendering one orphan fact reads as a render-time bug, not
  // a feature). `road_access_type` ships "unknown" as a literal
  // enum value rather than null when the source data didn't disclose
  // it, so we filter that out explicitly alongside null/falsy checks.
  const isKnown = (v) =>
    v != null && v !== "" && v !== "unknown" && v !== "Unknown";
  // Closed-set guard for enum→i18n lookups. If the pipeline ever ships
  // a new enum value we haven't translated, capitalize() keeps it from
  // showing the raw i18n key — but the en-only fallback IS a smell to
  // catch in code review (add a new translation row when this trips).
  const ROAD_ENUMS = new Set(["paved", "gravel", "dirt"]);
  const BEACHFRONT_ENUMS = new Set(["on_beach", "walk_to_beach", "near_beach"]);

  const facts = [];
  if (isKnown(listing.road_access_type)) {
    const v = listing.road_access_type;
    const roadValue = ROAD_ENUMS.has(v)
      ? t(`detail.fact.road.${v}`, lc)
      : capitalize(v);
    facts.push({ icon: "road", label: t("detail.fact.road", lc), value: roadValue });
  }
  if (listing.has_water) {
    facts.push({ icon: "droplet", label: t("detail.fact.water", lc), value: t("detail.fact.water_on", lc) });
  }
  if (listing.has_power) {
    facts.push({ icon: "bolt", label: t("detail.fact.electricity", lc), value: t("detail.fact.power_at", lc) });
  }
  // Topography is always known (boolean), so it always shows.
  facts.push({ icon: "leaf", label: t("detail.fact.topography", lc), value: listing.is_flat ? t("detail.fact.flat_yes", lc) : t("detail.fact.flat_no", lc) });
  if (isKnown(listing.beachfront_tier)) {
    const v = listing.beachfront_tier;
    const beachValue = BEACHFRONT_ENUMS.has(v)
      ? t(`detail.fact.beachfront_tier.${v}`, lc)
      : capitalize(v.replace("_", " "));
    facts.push({ icon: "wave", label: t("detail.fact.beachfront_tier", lc), value: beachValue });
  }
  if (listing.has_ocean_view) {
    facts.push({ icon: "sun", label: t("detail.fact.ocean_view", lc), value: t("detail.fact.yes", lc) });
  }
  if (isKnown(listing.zoning_use)) {
    // TODO(i18n): zoning_use is `string | null` in the type — no closed
    // enum to translate yet, and the field is currently always null in
    // ranked.json. If/when the pipeline starts populating this we'll
    // need a `detail.fact.zoning.<value>` table along the lines of
    // road / beachfront above. capitalize() until then.
    facts.push({ icon: "zone", label: t("detail.fact.zoning", lc), value: capitalize(listing.zoning_use) });
  }
  if (listing.photos_count > 0) {
    facts.push({ icon: "camera", label: t("detail.fact.photos", lc), value: `${listing.photos_count}` });
  }
  const showKeyFacts = facts.length >= 2;

  return (
    <div className={`detail ${asPanel ? "as-panel" : "as-page"}`}>
      <ListingJsonLd listing={listing} locale={app.locale} />
      <div className="detail-head">
        <button className="link-btn" onClick={() => app.closeListing()}>
          <Icon name="arrow_left" size={16} strokeWidth={2}/> {t("detail.back", lc)}
        </button>
        <div className="detail-head-right">
          <HeartButton listingId={listing.id} app={app} variant="inline" size={20}/>
        </div>
      </div>

      {isSold && (
        <div className="sold-banner">
          <strong>{t("detail.sold_banner.title", lc)}</strong>
          {typeof listing.days_listed === "number" && (
            <span>{t("detail.sold_banner.days", lc, { n: listing.days_listed })}</span>
          )}
          <button className="link-btn" onClick={() => app.goBrowse({ category: null, zones: [listing.zone_name] })}>{t("detail.sold_banner.cta", lc, { zone: listing.zone_name })}</button>
        </div>
      )}

      <div className="detail-gallery">
        <div className="gallery-mosaic">
          <button
            className="gallery-main"
            onClick={() => listing.photos.length && !needsSignup && openLightbox(0)}
            aria-label={listing.photos.length ? t("detail.gallery.open", lc) : undefined}
          >
            {listing.photos[0] ? (
              <img src={listing.photos[0]} alt={tr(listing.title, app.locale)}/>
            ) : (
              <div className="gallery-placeholder">
                <Icon name="mountain" size={48} />
                <span>{listing.zone_name}</span>
              </div>
            )}
          </button>
          <div className="gallery-side">
            {[1,2,3,4].map(i => listing.photos[i] && (() => {
              // Index `i` is locked when it sits at or past the user's
              // tier-specific unlock cap (see lib/gating.ts).
              const locked = i >= thumbCap;
              return (
              <button
                key={i}
                className={`gallery-thumb ${locked ? "locked" : ""}`}
                aria-label={locked ? t("detail.gallery.locked_aria", lc) : t("detail.gallery.open_n", lc, { n: i + 1 })}
                onClick={() => {
                  if (locked) {
                    track("paywall.bypassed", {
                      kind: "detail_view", action: "upgrade", listing_id: listing.id,
                    });
                    track("detail.upgrade_cta_clicked", {
                      cta_location: i === 4 ? "more_photos_overlay" : "locked_thumb",
                      listing_id: listing.id,
                      listing_state: isOffMarket ? "off_market" : "active",
                    });
                    const branch = routeCtaForState("detail_upgrade", app?.user);
                    trackCtaRouted("detail_upgrade", app?.user, branch, true);
                    dispatchCentralBranch(branch, app, { trigger: "detail_upgrade" });
                  } else {
                    openLightbox(i);
                  }
                }}
              >
                <img src={listing.photos[i]} alt=""/>
                {locked && (
                  <div className="thumb-lock"><Icon name="lock" size={16}/></div>
                )}
                {!locked && i === 4 && listing.photos.length > 5 && (
                  <div className="more-photos">{t("detail.more_photos", lc, { n: listing.photos.length - 5 })}</div>
                )}
                {locked && i === 4 && (
                  <div className="more-photos">{t("detail.unlock_pro_free_month", lc)}</div>
                )}
              </button>
              );
            })())}
          </div>
        </div>
      </div>

      <div className="detail-body">
        <div className="detail-titlebar">
          <div className="detail-meta-top">
            <span>{listing.zone_name}</span><span className="dot">·</span>
            <span>{listing.province_state}</span><span className="dot">·</span>
            <span>{landTypeLabel(listing.land_type)}</span>
          </div>
          <h1 className="detail-title">{tr(listing.title, app.locale)}</h1>
          <div className="detail-badges">
            <Badge listing={listing}/>
            {listing.readiness_score >= 3 && !listing.is_repriced && <span className="pulpo-badge soft">{t("badge.build_ready", lc)}</span>}
            {listing.has_ocean_view && <span className="pulpo-badge soft">{t("badge.ocean_view", lc)}</span>}
            {listing.is_flat && <span className="pulpo-badge soft">{t("badge.flat", lc)}</span>}
          </div>
        </div>

        {listing.is_incomplete && (
          <div
            className="detail-broker-note"
            role="note"
            title={t("value.notshared.tooltip", lc)}
          >
            {t("detail.broker_note", lc)}
          </div>
        )}

        <div className="detail-keystats">
          <div className="kstat">
            <div className="kstat-label">{t("detail.price", lc)}</div>
            <div
              className={listing.price == null ? "kstat-value muted" : "kstat-value"}
              title={listing.price == null ? t("value.notshared.tooltip", lc) : undefined}
            >{formatPrice(listing.price)}</div>
            {listing.previous_price && <div className="kstat-sub strike">{formatPrice(listing.previous_price)}</div>}
          </div>
          <div className="kstat">
            <div className="kstat-label">{t("detail.size", lc)}</div>
            <div
              className={listing.size_m2 == null ? "kstat-value muted" : "kstat-value"}
              title={listing.size_m2 == null ? t("value.notshared.tooltip", lc) : undefined}
            >{formatSize(listing.size_m2)}</div>
          </div>
          {/* PPM derives from price + size; suppress the tile when
              either is null so users see "Not shared" once on the
              source field rather than twice on a derived stat. */}
          {listing.price != null && listing.size_m2 != null && (
            <div className="kstat">
              <div className="kstat-label">{`$${ppmSuffix()}`}</div>
              <div className="kstat-value">{formatPpm(listing.price_per_m2)}</div>
            </div>
          )}
          <div className="kstat">
            <div className="kstat-label">{t("detail.days_listed", lc)}</div>
            <div className={`kstat-value tone-${daysListedTone(listing.days_listed)}`}>{typeof listing.days_listed === "number" ? listing.days_listed : "—"}</div>
          </div>
        </div>

        <div className="detail-section">
          <p className="detail-description">{tr(listing.description, app.locale)}</p>
        </div>

        <div className="detail-section">
          <h3 className="section-title">{t("detail.reasons", app.locale)}</h3>
          <ul className="usp-list">
            {listing.usps.slice(0, uspCap).map((u, i) => (
              <li key={i}><Icon name="check" size={16} strokeWidth={2.4}/> {tr(u, app.locale)}</li>
            ))}
            {/* Anon + free hit the same in-panel conversion CTA: opens
                FreeMonthModal with `detail_upgrade` trigger, which
                pre-applies PULPOFREEMONTH at /api/stripe/start-checkout.
                Paid users see every USP and skip this row. */}
            {!isPaid && listing.usps.length > uspCap && (
              <li className="usp-locked">
                <Icon name="lock" size={14} strokeWidth={2}/>
                <button
                  className="link-btn"
                  onClick={() => {
                    track("paywall.bypassed", {
                      kind: "detail_view", action: "upgrade", listing_id: listing.id,
                    });
                    track("detail.upgrade_cta_clicked", {
                      cta_location: "locked_usp",
                      listing_id: listing.id,
                      listing_state: isOffMarket ? "off_market" : "active",
                    });
                    const branch = routeCtaForState("detail_upgrade", app?.user);
                    trackCtaRouted("detail_upgrade", app?.user, branch, true);
                    dispatchCentralBranch(branch, app, { trigger: "detail_upgrade" });
                  }}
                >
                  {t("detail.unlock_pro_free_month", lc)}
                </button>
              </li>
            )}
          </ul>
        </div>

        {showKeyFacts && (
          <div className="detail-section">
            <h3 className="section-title">{t("detail.key_facts", lc)}</h3>
            <div className="facts-grid">
              {facts.map(f => (
                <div className="fact-tile" key={f.label}>
                  <div className="fact-icon"><Icon name={f.icon} size={18}/></div>
                  <div className="fact-text">
                    <div className="fact-label">{f.label}</div>
                    <div className="fact-value">{f.value}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="detail-section">
          <h3 className="section-title">{t("detail.location", lc)}</h3>
          <div className="location-block">
            <div className="map-chip">
              <Icon name="map_pin" size={16}/>
              <span><strong>{listing.zone_name}</strong>, {listing.province_state}</span>
            </div>
            <div className="distance-pills">
              {/* Each pill renders only when its value is non-null. The
                  formatDistanceKm helper rounds to 5/10km steps and flags
                  the result as approximate when the listing's lat/lng is
                  fuzzy (medium/low DeepSeek confidence) or when the
                  distance came from the zone-table fallback (no lat/lng
                  at all, e.g. dist_airport_km derived from the per-zone
                  airports table). The "_approx" i18n keys prefix "ca."
                  so users see the precision difference. */}
              {(() => {
                const beach = formatDistanceKm(listing.dist_beach_km, listing);
                if (!beach) return null;
                if (listing.dist_beach_km < 1) {
                  return <span className="dpill"><Icon name="cat_beachfront" size={13} strokeWidth={1.6}/> {t("detail.on_beach", lc)}</span>;
                }
                const key = beach.approx ? "detail.km_to_beach_approx" : "detail.km_to_beach";
                return <span className="dpill"><Icon name="cat_beachfront" size={13} strokeWidth={1.6}/> {t(key, lc, { n: beach.n })}</span>;
              })()}
              {(() => {
                const airport = formatDistanceKm(listing.dist_airport_km, listing);
                if (!airport) return null;
                const key = airport.approx ? "detail.km_to_airport_approx" : "detail.km_to_airport";
                return <span className="dpill"><Icon name="plane" size={13} strokeWidth={1.6}/> {t(key, lc, { n: airport.n })}</span>;
              })()}
              {(() => {
                const town = formatDistanceKm(listing.dist_nearest_town_km, listing);
                if (!town) return null;
                const key = town.approx ? "detail.km_to_town_approx" : "detail.km_to_town";
                return <span className="dpill"><Icon name="cat_commercial" size={13} strokeWidth={1.6}/> {t(key, lc, { n: town.n })}</span>;
              })()}
            </div>
            {/* Real interactive map deferred — see plan followup. We
                used to render a CSS .static-map illustration here, but
                a fake map mislead users (no real coords behind it).
                The zone label + distance pills above carry their own
                weight; the section stays useful without the chrome. */}
          </div>
        </div>

        {/* Wave-1: the off-market full-page overlay used to live here
            and blocked anon + free users from seeing the detail body
            entirely. Removed because off-market should be LESS scary
            to non-paid users, not more — the more they see, the more
            they want Pro. The CTA bar below now handles the gate at
            the broker-outbound link (free/anon see an upgrade button,
            paid see the outbound). USP + gallery soft caps inside the
            body still apply via gating.ts. */}
      </div>

      {/* Sticky bottom CTA. Source-listing link is Pro-only — the
          vendor-URL outbound is a paid feature. Anon + free both land
          on FreeMonthModal (single conversion surface, pre-applies
          PULPOFREEMONTH on /api/stripe/start-checkout). Renders for
          both on-market and off-market listings; sold listings opt out
          (no point upselling on a finished sale). */}
      {!isSold && (
        <div className="detail-cta-bar">
          {!isPaid ? (
            <button
              className="btn-primary lg block"
              onClick={() => {
                track("paywall.bypassed", {
                  kind: "detail_view", action: "upgrade", listing_id: listing.id,
                });
                track("detail.upgrade_cta_clicked", {
                  cta_location: "broker_outbound",
                  listing_id: listing.id,
                  listing_state: isOffMarket ? "off_market" : "active",
                });
                // Uniform routing dispatch — the in-panel upgrade CTA is
                // the per-CTA paywall here. detail_upgrade matrix row
                // resolves to free_month_modal for anon/free.
                const branch = routeCtaForState("detail_upgrade", app.user);
                trackCtaRouted("detail_upgrade", app.user, branch, true);
                dispatchCentralBranch(branch, app, { trigger: "detail_upgrade" });
              }}
            >
              <Icon name="lock" size={16}/> {t("detail.unlock_pro_free_month", lc)}
            </button>
          ) : listing.original_url ? (
            <a
              className="btn-primary lg block"
              href={listing.original_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => {
                track("view_original.clicked", {
                  listing_id: listing.id,
                  source_label: listing.source_label,
                });
                trackCtaRouted("broker_outbound", app.user, "passthrough", true);
              }}
            >
              {t("detail.view_on", lc, { source: listing.source_label })} <Icon name="arrow_up_right" size={16} strokeWidth={2}/>
            </a>
          ) : (
            <button className="btn-primary lg block" disabled>
              {t("detail.off_market_inquire", lc)}
            </button>
          )}
          <button className="btn-ghost lg" onClick={(e) => { e.stopPropagation(); app.toggleSave(listing.id); }}>
            <Icon name="heart" size={16}/> {app.savedIds.has(listing.id) ? t("detail.saved", lc) : t("detail.save", lc)}
          </button>
        </div>
      )}

      {lightbox && (
        <div
          className="lightbox"
          onClick={() => setLightbox(false)}
          ref={lightboxRef}
          role="dialog"
          aria-modal="true"
          aria-label={t("lightbox.aria_label", lc, { n: galleryIdx + 1, total: listing.photos.length })}
        >
          <button
            className="lightbox-close"
            ref={lightboxCloseRef}
            onClick={(e) => { e.stopPropagation(); setLightbox(false); }}
            aria-label={t("lightbox.close", lc)}
          >
            <Icon name="close" size={22}/>
          </button>
          <img src={listing.photos[galleryIdx]} alt={`${tr(listing.title, app.locale)} — ${t("detail.fact.photos", lc)} ${galleryIdx + 1}`}/>
          <div className="lightbox-controls" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => setGalleryIdx((galleryIdx - 1 + listing.photos.length) % listing.photos.length)}
              aria-label={t("lightbox.prev", lc)}
            >
              <Icon name="chevron_left" size={24}/>
            </button>
            <span aria-live="polite">{galleryIdx + 1} / {listing.photos.length}</span>
            <button
              onClick={() => setGalleryIdx((galleryIdx + 1) % listing.photos.length)}
              aria-label={t("lightbox.next", lc)}
            >
              <Icon name="chevron_right" size={24}/>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
function capitalize(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }

// ====== Saved page ======
function SavedPage({ app }) {
  const LISTINGS = useListings();
  const items = LISTINGS.filter(l => app.savedIds.has(l.id));
  const [view, setView] = pUseState(() => localStorage.getItem("pulpo-saved-view") || "cards");
  const [sort, setSort] = pUseState("recent");
  pUseEffect(() => { localStorage.setItem("pulpo-saved-view", view); }, [view]);

  const topRankMap = pUseMemo(() => buildTopRankMap(LISTINGS), [LISTINGS]);

  const sorted = pUseMemo(() => {
    const arr = [...items];
    switch (sort) {
      case "price_asc": arr.sort((a,b) => a.price - b.price); break;
      case "price_desc": arr.sort((a,b) => b.price - a.price); break;
      case "size_desc": arr.sort((a,b) => b.size_m2 - a.size_m2); break;
      case "ppm_asc": arr.sort((a,b) => a.price_per_m2 - b.price_per_m2); break;
      case "days_asc": arr.sort((a,b) => {
        const av = typeof a.days_listed === "number" ? a.days_listed : Number.POSITIVE_INFINITY;
        const bv = typeof b.days_listed === "number" ? b.days_listed : Number.POSITIVE_INFINITY;
        return av - bv;
      }); break;
      default: arr.sort((a,b) => b.first_seen_date - a.first_seen_date);
    }
    return arr;
  }, [items, sort]);

  if (items.length === 0) {
    return (
      <div className="page page-saved">
        <div className="empty-state lg">
          <div className="empty-illus">
            <svg width="120" height="120" viewBox="0 0 120 120" fill="none">
              <path d="M20 80c0-25 20-45 45-45s45 20 45 45" stroke="var(--ink-3)" strokeWidth="2" fill="none"/>
              <path d="M60 50l3 6 6 1-4.5 4 1 6-5.5-3-5.5 3 1-6-4.5-4 6-1z" fill="var(--accent-2)"/>
            </svg>
          </div>
          <h2>{t("saved.empty.title", app.locale)}</h2>
          <p>{t("saved.empty.body", app.locale)}</p>
          <button className="btn-primary" onClick={() => app.go("browse")}>{t("saved.browse_cta", app.locale)}</button>
        </div>
      </div>
    );
  }
  return (
    <div className="page page-saved">
      <div className="page-header saved-header">
        <div>
          <h1>{t("saved.title", app.locale)}</h1>
          <p>{items.length} {t("card.listings_count", app.locale)}</p>
        </div>
        <div className="results-controls">
          <select className="sort-select" value={sort} onChange={e => setSort(e.target.value)}>
            <option value="recent">{t("sort.recently_saved", app.locale)}</option>
            <option value="price_asc">{t("sort.price_asc", app.locale)}</option>
            <option value="price_desc">{t("sort.price_desc", app.locale)}</option>
            <option value="size_desc">{t("sort.size_desc", app.locale)}</option>
            <option value="ppm_asc">{t("sort.ppm_asc_suffix", app.locale, { suffix: `$${ppmSuffix()}` })}</option>
            <option value="days_asc">{t("sort.days_asc", app.locale)}</option>
          </select>
          <div className="view-toggle">
            <button className={view === "table" ? "active" : ""} onClick={() => setView("table")} aria-label={t("view.table", app.locale)}>
              <Icon name="list" size={16}/>
            </button>
            <button className={view === "cards" ? "active" : ""} onClick={() => setView("cards")} aria-label={t("view.cards", app.locale)}>
              <Icon name="grid" size={16}/>
            </button>
          </div>
        </div>
      </div>
      {view === "cards" ? (
        <div className="card-grid">
          {sorted.map((l, i) => (
            <ListingCard
              key={l.id}
              listing={l}
              app={app}
              priority={i < 6}
              source="saved"
              topRank={topRankMap.get(l.id)}
              onOpen={() => {
                track("card.clicked", { listing_id: l.id, source_view: "saved" });
                app.openListing(l.id);
              }}
            />
          ))}
        </div>
      ) : (
        <ResultsTable results={sorted} app={app} sort={sort} setSort={setSort} topRankMap={topRankMap} />
      )}
    </div>
  );
}

// ====== Plans page ======
function PlansPage({ app }) {
  const lc = app.locale;
  // Telemetry — plans.viewed fires once per PlansPage mount. The event
  // type has existed in events.ts since the catalog landed but had no
  // consumer; Phase 7 wires it. `source` differentiates entry points
  // (topnav / footer / paywall / manual). The routeParams.plansSource
  // hint is set by callers that know the entry context (topnav click,
  // paywall upgrade button, etc.); cold loads + arrows-back land here
  // without that hint so we fall through to "manual".
  pUseEffect(() => {
    const source = app.routeParams && app.routeParams.plansSource;
    const validSources = ["topnav", "footer", "paywall", "manual"];
    track("plans.viewed", {
      source: validSources.includes(source) ? source : "manual",
    });
    // Mount-only effect — re-mounting on app.routeParams change is
    // not desirable (would double-fire on a routeParam tweak).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Pro upgrade — fires the Stripe Managed Payments redirect via the same
  // helper Account uses (account.jsx:344). On `sign_in_required` we open
  // the signup modal so anonymous visitors can complete the flow without
  // bouncing to a separate page; other errors surface a toast.
  const onUpgrade = () => {
    startStripeCheckout({
      onError: (code) => {
        if (code === "sign_in_required") {
          if (app.user) {
            // Server says we're not authenticated but the client has a
            // user — Clerk cookie / session mismatch (dev keys, dev-vs-
            // prod cookie domain, etc). Don't reopen the modal — that
            // would loop indefinitely AND, with Clerk enabled, throw
            // cannot_render_single_session_enabled. Surface a real
            // toast and let the user retry.
            app.showToast(t("plans.checkout_auth_mismatch", lc));
          } else {
            // Genuinely anonymous — open the signup modal and chain
            // the Stripe redirect after auth via pendingAction.
            app.openSignup({ mode: "signup", pendingAction: "checkout" });
          }
        } else {
          app.showToast(t("plans.checkout_error_toast", lc));
        }
      },
    });
  };
  // Feature line helper — keeps the JSX readable when every line is t()'d.
  const feat = (key) => (
    <li><Icon name="check" size={14} strokeWidth={2.4}/> {t(key, lc)}</li>
  );
  const featMuted = (key) => (
    <li className="muted">— {t(key, lc)}</li>
  );
  return (
    <div className="page page-plans">
      <div className="plans-head">
        <h1>{t("plans.head.title", lc)}</h1>
        <p>{t("plans.head.subtitle", lc)}</p>
      </div>
      <div className="plans-grid">
        <div className="plan-card">
          <div className="plan-name">{t("plans.free.name", lc)}</div>
          <div className="plan-price"><span>$0</span></div>
          <div className="plan-tag">{t("plans.free.tag", lc)}</div>
          <ul className="plan-features">
            {feat("plans.free.feat.browsing")}
            {feat("plans.free.feat.detail_views")}
            {feat("plans.free.feat.saves_cap")}
            {/* The three "this is what Pro adds" mirrors, muted on Free. */}
            {featMuted("pro.usp.alerts.short")}
            {featMuted("pro.usp.browse.short")}
            {featMuted("pro.usp.links.short")}
          </ul>
          <button className="btn-ghost block" disabled={!app.user}>
            {app.user ? t("plans.free.cta_current", lc) : t("plans.free.cta_signup", lc)}
          </button>
        </div>
        <div className="plan-card featured">
          <div className="plan-ribbon">{t("plans.pro.ribbon", lc)}</div>
          <div className="plan-name">{t("plans.pro.name", lc)}</div>
          <div className="plan-price">
            <span>€{PRO_PRICE_EUR_PER_MONTH}</span><span className="per">{t("plans.pro.per_month", lc)}</span>
          </div>
          <div className="plan-tag">{t("plans.pro.tag", lc)}</div>
          <ul className="plan-features">
            {feat("pro.usp.alerts.headline")}
            {feat("pro.usp.browse.headline")}
            {feat("pro.usp.links.headline")}
            {feat("plans.pro.feat.everything_in_free")}
          </ul>
          <button className="btn-primary block lg" onClick={onUpgrade}>
            {t("plans.upgrade_pro_cta", lc, { price: PRO_PRICE_EUR_PER_MONTH })}
          </button>
          <p className="plan-currency-note">{t("plans.pro.currency_note", lc)}</p>
        </div>
        {SHOW_AGENCY_PLAN && (
          <div className="plan-card">
            <div className="plan-name">{t("plans.agency.name", lc)}</div>
            <div className="plan-price">
              <span>€79</span><span className="per">{t("plans.pro.per_month", lc)}</span>
            </div>
            <div className="plan-tag">{t("plans.agency.tag", lc)}</div>
            <ul className="plan-features">
              {feat("plans.agency.feat.everything_in_pro")}
              {feat("plans.agency.feat.team_seats")}
              {feat("plans.agency.feat.shared_lists")}
              {feat("plans.agency.feat.csv_export")}
              {feat("plans.agency.feat.priority_off_market")}
            </ul>
            <button className="btn-ghost block">{t("plans.agency.cta_contact", lc)}</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ====== Sign-up modal ======
function SignupModal({ app }) {
  const m = app.signupModal;

  // Flag-on hand-off to Clerk. Trigger the hosted modal imperatively
  // via app.clerkActions (wired by ClerkActionsBinder once the SDK
  // chunk has loaded) — no click-time Suspense, so React #426 doesn't
  // fire. If clerkActions isn't ready yet (cold first paint), we wait;
  // the effect re-runs when it lands.
  //
  // Hook is at the top so order is stable across renders, regardless
  // of whether `m` or `clerkEnabled()` flip the early returns below.
  pUseEffect(() => {
    if (!m) return;
    if (!clerkEnabled()) return;
    if (!app.clerkActions) return;
    // Defensive: Clerk's hosted SignIn/SignUp throws
    // `cannot_render_single_session_enabled` when the user is already
    // signed in — and we have a race where consumers (e.g. the topnav
    // sign-in icon mid-Clerk-boot, or AccountPage redirects) can call
    // openSignup before ClerkUserSync has committed user state. Both
    // checks below are needed: `app.user` covers the legacy auth path
    // and the post-sync window; `clerkActions.isSignedIn()` covers the
    // boot-race window where Clerk's session is hydrated from cookies
    // but app.user hasn't synced yet. In either case, close the modal
    // silently and let app.jsx's post-signin effect process any
    // pendingAction once ClerkUserSync catches up.
    const clerkSays = typeof app.clerkActions.isSignedIn === "function"
      && app.clerkActions.isSignedIn();
    if (app.user || clerkSays) {
      app.closeSignup();
      return;
    }
    const target = m.mode === "login" ? "openSignIn" : "openSignUp";
    try {
      app.clerkActions[target]();
    } catch (err) {
      // Belt-and-braces: if Clerk still throws (e.g. its error code
      // changes between versions), don't blank the page via the
      // ErrorBoundary — silently close the modal. The user can retry
      // on the next render once state catches up.
      if (typeof console !== "undefined" && console.warn) {
        console.warn("[pulpo] clerk." + target + " failed:", err);
      }
    }
    app.closeSignup();
  }, [m, app.clerkActions, app.user]);

  if (!m) return null;
  if (clerkEnabled()) return null;
  return <LegacySignupModal app={app} m={m} />;
}

// Legacy email/password sign-in form. Only renders when VITE_USE_CLERK
// is off — extracted so its useState hooks don't clash with the parent
// component's lone useEffect on flag-on renders.
function LegacySignupModal({ app, m }) {
  const [mode, setMode] = pUseState(m.mode || "signup");
  const [email, setEmail] = pUseState(m.email || "");
  const [password, setPassword] = pUseState("");
  const [error, setError] = pUseState("");

  const submit = (e) => {
    e.preventDefault();
    if (!email || !email.includes("@")) { setError("Please enter a valid email."); return; }
    if (password.length < 6) { setError("Password must be at least 6 characters."); return; }
    app.signin({ email });
  };

  const oauth = (provider) => {
    app.signin({ email: `you@${provider}.com`, provider });
  };

  return (
    <div className="modal-backdrop" onClick={() => app.closeSignup()}>
      <div className="modal modal-signup" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={() => app.closeSignup()} aria-label={t("common.close", app.locale)}>
          <Icon name="close" size={18}/>
        </button>
        <div className="modal-head">
          <PulpoLogo />
          <h2>{mode === "signup" ? "Discover properties before they go public." : "Welcome back."}</h2>
          <p>{mode === "signup" ? "Free account. No credit card. Cancel anytime." : "Log in to access your saved listings."}</p>
        </div>
        <button className="oauth-btn google" onClick={() => oauth("google")}>
          <GoogleG/> Continue with Google
        </button>
        <button className="oauth-btn apple" onClick={() => oauth("apple")}>
          <AppleMark/> Continue with Apple
        </button>
        <div className="divider"><span>or</span></div>
        <form onSubmit={submit} className="modal-form">
          <label>Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@email.com"
              autoComplete="username"
              autoFocus
            />
          </label>
          <label>Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"  /* i18n-allow: LegacySignupModal only renders when Clerk is OFF (no VITE_CLERK_PUBLISHABLE_KEY) — tracked for full i18n in legacy-cleanup PR */
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
            />
          </label>
          {error && <div className="form-error">{error}</div>}
          <button type="submit" className="btn-primary block lg">
            {mode === "signup" ? "Create account →" : "Log in →"}
          </button>
        </form>
        <div className="modal-foot">
          {mode === "signup" ? (
            <>Already have an account? <button className="link-btn" onClick={() => setMode("login")}>Log in</button></>
          ) : (
            <>New here? <button className="link-btn" onClick={() => setMode("signup")}>Create account</button></>
          )}
        </div>
        <div className="modal-fine">By signing up you agree to the <a>Terms of Service</a>. You'll get weekly deal alerts — unsubscribe anytime.</div>
      </div>
    </div>
  );
}

const GoogleG = () => (
  <svg width="18" height="18" viewBox="0 0 18 18">
    <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.17-1.84H9v3.48h4.84c-.21 1.13-.84 2.08-1.79 2.72v2.26h2.9c1.7-1.56 2.69-3.86 2.69-6.62z"/>
    <path fill="#34A853" d="M9 18c2.43 0 4.47-.81 5.96-2.18l-2.9-2.26c-.81.54-1.84.86-3.06.86-2.35 0-4.34-1.59-5.05-3.72H.96v2.33C2.44 15.98 5.48 18 9 18z"/>
    <path fill="#FBBC05" d="M3.95 10.7c-.18-.54-.28-1.12-.28-1.7s.1-1.16.28-1.7V4.97H.96C.35 6.18 0 7.55 0 9s.35 2.82.96 4.03l2.99-2.33z"/>
    <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.46 3.45 1.34l2.58-2.58C13.46.89 11.43 0 9 0 5.48 0 2.44 2.02.96 4.97l2.99 2.33C4.66 5.17 6.65 3.58 9 3.58z"/>
  </svg>
);
const AppleMark = () => (
  <svg width="16" height="18" viewBox="0 0 16 18" fill="currentColor">
    <path d="M11.6 9.6c0-2 1.6-2.9 1.7-3-1-1.4-2.4-1.6-2.9-1.6-1.2-.1-2.4.7-3 .7-.6 0-1.6-.7-2.7-.7-1.4 0-2.7.8-3.4 2.1-1.5 2.5-.4 6.3 1 8.3.7 1 1.5 2.1 2.6 2 1-.1 1.4-.7 2.6-.7s1.5.7 2.6.6c1.1 0 1.8-1 2.5-2 .8-1.1 1.1-2.2 1.1-2.3-.1 0-2.1-.8-2.1-3.4zM10.1 3.6c.5-.7.9-1.6.8-2.6-.8 0-1.7.5-2.3 1.2-.5.6-.9 1.6-.8 2.5.9.1 1.8-.4 2.3-1.1z"/>
  </svg>
);

// ====== Toast helper ======
function ToastHost({ app }) {
  if (!app.toast) return null;
  return (
    <div className="toast">
      <Icon name="check" size={16} strokeWidth={2.4}/>
      <span>{app.toast.message}</span>
    </div>
  );
}

// ====== Empty results ======
// PR-4 — empty-state cross-suggest. Walks through active filters and
// proposes dropping the single most-restrictive one (the one whose
// removal would unlock the most results). Per the plan: "No
// beachfront listings under $50K. Try **Ocean View** under $50K?".
function EmptyResults({ onClear, filters, listings, setFilters }) {
  const lc = currentLocale();
  // Try removing each filter group one at a time; pick the one that
  // unlocks the most listings.
  const suggestion = pUseMemo(() => {
    if (!Array.isArray(listings) || !filters) return null;
    const candidates = [];
    const tryWithout = (label_en, label_es, mutator) => {
      const next = {
        zones: new Set(filters.zones),
        land_types: new Set(filters.land_types),
        features: new Set(filters.features),
        infra: new Set(filters.infra),
        status: new Set(filters.status),
        price_min: filters.price_min,
        price_max: filters.price_max,
        size_min: filters.size_min,
        readiness: filters.readiness,
      };
      mutator(next);
      const count = applyFilters(listings, next).length;
      if (count > 0) candidates.push({ count, next, label_en, label_es });
    };
    if (filters.features.has("beachfront")) {
      tryWithout("ocean view", "vista al mar", (n) => {
        n.features.delete("beachfront");
        n.features.add("ocean_view");
      });
    }
    if (filters.zones.size > 0) {
      tryWithout("any zone", "cualquier zona", (n) => n.zones = new Set());
    }
    if (filters.price_max != null) {
      tryWithout("any budget", "cualquier presupuesto", (n) => {
        n.price_min = 0;
        n.price_max = null;
      });
    }
    if (filters.features.size > 0) {
      tryWithout("any features", "cualquier característica", (n) => n.features = new Set());
    }
    if (filters.readiness > 0) {
      tryWithout("any readiness", "cualquier nivel de preparación", (n) => (n.readiness = 0));
    }
    candidates.sort((a, b) => b.count - a.count);
    return candidates[0] || null;
  }, [filters, listings]);

  return (
    <div className="empty-state">
      <div className="empty-illus" aria-hidden="true">
        <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
          <circle cx="35" cy="35" r="20" stroke="var(--ink-3)" strokeWidth="2"/>
          <line x1="50" y1="50" x2="65" y2="65" stroke="var(--ink-3)" strokeWidth="2" strokeLinecap="round"/>
        </svg>
      </div>
      <h3>
        {lc === "es"
          ? "Ninguna propiedad coincide con tus filtros."
          : "No listings match your filters."}
      </h3>
      {suggestion ? (
        <>
          <p>
            {lc === "es"
              ? `¿Quieres ver con `
              : `Want to try with `}
            <strong>{lc === "es" ? suggestion.label_es : suggestion.label_en}</strong>?{" "}
            {lc === "es" ? `Tendrías ${suggestion.count} resultados.` : `${suggestion.count} listings would match.`}
          </p>
          <div className="empty-actions">
            <button
              className="btn-primary"
              onClick={() => setFilters && setFilters(suggestion.next)}
            >
              {lc === "es" ? `Ver ${suggestion.count} ahora` : `See ${suggestion.count} now`}
            </button>
            <button className="btn-ghost" onClick={onClear}>
              {lc === "es" ? "Limpiar filtros" : "Clear filters"}
            </button>
          </div>
        </>
      ) : (
        <>
          <p>
            {lc === "es"
              ? "Quita algún filtro o explora otra zona."
              : "Try removing a filter, or explore a different zone."}
          </p>
          <button className="btn-primary" onClick={onClear}>
            {lc === "es" ? "Limpiar filtros" : "Clear filters"}
          </button>
        </>
      )}
    </div>
  );
}

// ====== Loading skeletons ======
function DiscoverSkeleton() {
  return (
    <div className="page page-home discover-magazine">
      <section className="hero" aria-busy="true">
        <div className="hero-bg" style={{ background: "var(--paper-3)" }} />
        <div className="hero-overlay" />
        <div className="hero-content">
          <div className="skel-line w-50" style={{ height: 14, marginBottom: 12 }} />
          <div className="skel-line w-80" style={{ height: 36, marginBottom: 14 }} />
          <div className="skel-line w-60" style={{ height: 16 }} />
        </div>
      </section>
      <div className="shelves" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <section className="shelf" key={i}>
            <div className="shelf-head">
              <div className="shelf-head-text">
                <div className="skel-line w-50" style={{ height: 24, marginBottom: 8 }} />
                <div className="skel-line w-80" style={{ height: 14 }} />
              </div>
            </div>
            <div className="shelf-rail">
              {[0, 1, 2, 3].map((j) => (
                <div className="shelf-item" key={j}>
                  <SkeletonCard />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function BrowseSkeleton() {
  return (
    <div className="page page-browse" aria-busy="true">
      <div className="card-grid">
        {Array.from({ length: 12 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    </div>
  );
}

// ====== Hard-error UI for permanent fetch failure (production) ======
// Locale comes from <html lang> via currentLocale() — DataFetchFailed
// renders before app context is established so we can't lean on a
// prop-threaded locale. The lang attribute is set by useLocale very
// early in app boot, so by the time this can render the value is
// already correct.
function DataFetchFailed({ onRetry }) {
  const lc = currentLocale();
  return (
    <div className="empty-state lg" role="alert">
      <h2>{t("data_fetch_failed.title", lc)}</h2>
      <p>{t("data_fetch_failed.body", lc)}</p>
      <button className="btn-primary" onClick={onRetry}>{t("common.retry", lc)}</button>
    </div>
  );
}

// ====== Cookie-consent banner shim ======
// ConsentBanner — 9-point ConsentBanner technical contract from
// legal_documents/03-cookie-policy.md (mirrors PDF §3.2). See
// web/app/lib/consent.ts for the storage + migration helpers.
//
// Behaviour:
//   - Shows on every visit until the user makes an affirmative choice.
//     The pre-v1 "auto-grant outside the EU" behaviour is gone —
//     ePrivacy + LGPD + UK PECR all require opt-in regardless, and
//     the friction of one tap is worth the legal posture.
//   - Two views: collapsed "summary" (Accept All / Decline All /
//     Manage preferences) and expanded "preferences" (granular
//     toggles per optional category + Save preferences).
//   - Accept All + Decline All buttons have equal visual weight per
//     PDF §3.2 #3. No dark patterns.
//   - The Cookie Preferences footer button (#322) re-opens the banner
//     by clearing the persisted record + dispatching the
//     `pulpo:open-consent-preferences` event.
//
// Telemetry:
//   - `consent.banner_shown { version }` on first render
//   - `consent.granted` / `consent.declined` on each save with the
//     accepted categories list
//   - `consent.category_toggled` for each preferences-pane interaction
//
// PostHog opt-in / opt-out: optIn() only fires when the user accepts
// the `analytics` category. telemetry/client.ts's `scheduleInit()`
// is the load-bearing gate (no analytics script loads until
// `hasConsented("analytics")`).

function ConsentBanner({ locale = "en" }) {
  const [record, setRecord] = pUseState(readConsent);
  const [view, setView] = pUseState("summary"); // "summary" | "preferences"
  const [acceptAnalytics, setAcceptAnalytics] = pUseState(true);
  const [acceptFunctional, setAcceptFunctional] = pUseState(true);
  const [forcedOpen, setForcedOpen] = pUseState(false);
  const shownFired = pUseRef(false);

  const isOpen = record === null || forcedOpen;

  // Fire `consent.banner_shown` once per render-into-view (one
  // banner_shown per user-session "open"). The ref prevents double
  // fire during StrictMode double-effect.
  pUseEffect(() => {
    if (!isOpen) return;
    if (shownFired.current) return;
    shownFired.current = true;
    track("consent.banner_shown", { version: CONSENT_POLICY_VERSION });
  }, [isOpen]);

  // Re-open signal from the footer's Cookie Preferences button.
  pUseEffect(() => {
    if (typeof window === "undefined") return;
    const handler = () => {
      setRecord(null);
      setForcedOpen(true);
      setView("summary");
      setAcceptAnalytics(true);
      setAcceptFunctional(true);
      shownFired.current = false;
    };
    window.addEventListener("pulpo:open-consent-preferences", handler);
    return () => window.removeEventListener("pulpo:open-consent-preferences", handler);
  }, []);

  if (!isOpen) return null;

  function commit(accepted) {
    const r = writeConsent(accepted);
    setRecord(r);
    setForcedOpen(false);
    setView("summary");

    const acceptedAnalytics = accepted.includes("analytics");
    const acceptedFunctional = accepted.includes("functional");
    if (acceptedAnalytics) optIn(); else optOut();

    if (acceptedAnalytics || acceptedFunctional) {
      track("consent.granted", {
        categories_accepted: r.accepted,
        version: r.v,
      });
    } else {
      track("consent.declined", {
        categories_accepted: r.accepted,
        version: r.v,
      });
    }
  }

  const acceptAll  = () => commit(["analytics", "functional"]);
  const declineAll = () => commit([]); // strictly_necessary only (implicit)
  const saveCurrent = () => {
    const accepted = [];
    if (acceptAnalytics)  accepted.push("analytics");
    if (acceptFunctional) accepted.push("functional");
    commit(accepted);
  };

  const onToggle = (category, next) => {
    track("consent.category_toggled", { category, accepted: next });
    if (category === "analytics")  setAcceptAnalytics(next);
    if (category === "functional") setAcceptFunctional(next);
  };

  return (
    <div
      className={`consent-banner consent-banner--${view}`}
      role="dialog"
      aria-modal="false"
      aria-label={t("consent.aria", locale)}
    >
      <style>{CONSENT_BANNER_STYLES}</style>
      {view === "summary" ? (
        <>
          <div className="consent-text">
            {t("consent.body", locale)}
          </div>
          <div className="consent-actions">
            <button
              className="consent-btn consent-btn--manage"
              onClick={() => {
                track("consent.preferences_opened", { source: "banner" });
                setView("preferences");
              }}
            >
              {t("consent.manage", locale)}
            </button>
            <button
              className="consent-btn consent-btn--decline"
              onClick={declineAll}
            >
              {t("consent.decline_all", locale)}
            </button>
            <button
              className="consent-btn consent-btn--accept"
              onClick={acceptAll}
            >
              {t("consent.accept_all", locale)}
            </button>
          </div>
        </>
      ) : (
        <div className="consent-prefs">
          <h2 className="consent-prefs__title">{t("consent.prefs.title", locale)}</h2>
          <p className="consent-prefs__lede">{t("consent.prefs.lede", locale)}</p>

          <div className="consent-prefs__category">
            <div className="consent-prefs__category-head">
              <label className="consent-prefs__category-label">
                {t("consent.category.strictly_necessary.label", locale)}
              </label>
              <span className="consent-prefs__category-always">
                {t("consent.category.always_active", locale)}
              </span>
            </div>
            <p className="consent-prefs__category-desc">
              {t("consent.category.strictly_necessary.desc", locale)}
            </p>
          </div>

          <div className="consent-prefs__category">
            <div className="consent-prefs__category-head">
              <label className="consent-prefs__category-label" htmlFor="consent-toggle-analytics">
                {t("consent.category.analytics.label", locale)}
              </label>
              <input
                id="consent-toggle-analytics"
                type="checkbox"
                className="consent-prefs__toggle"
                checked={acceptAnalytics}
                onChange={(e) => onToggle("analytics", e.target.checked)}
              />
            </div>
            <p className="consent-prefs__category-desc">
              {t("consent.category.analytics.desc", locale)}
            </p>
          </div>

          <div className="consent-prefs__category">
            <div className="consent-prefs__category-head">
              <label className="consent-prefs__category-label" htmlFor="consent-toggle-functional">
                {t("consent.category.functional.label", locale)}
              </label>
              <input
                id="consent-toggle-functional"
                type="checkbox"
                className="consent-prefs__toggle"
                checked={acceptFunctional}
                onChange={(e) => onToggle("functional", e.target.checked)}
              />
            </div>
            <p className="consent-prefs__category-desc">
              {t("consent.category.functional.desc", locale)}
            </p>
          </div>

          <div className="consent-actions consent-actions--prefs">
            <button
              className="consent-btn consent-btn--decline"
              onClick={declineAll}
            >
              {t("consent.decline_all", locale)}
            </button>
            <button
              className="consent-btn consent-btn--accept"
              onClick={acceptAll}
            >
              {t("consent.accept_all", locale)}
            </button>
            <button
              className="consent-btn consent-btn--save"
              onClick={saveCurrent}
            >
              {t("consent.save", locale)}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Inline styles for the expanded preferences view. The base
// `.consent-banner` rules live in styles/index.css.
const CONSENT_BANNER_STYLES = `
.consent-banner--preferences {
  max-width: 560px;
  align-items: stretch;
  flex-direction: column;
  padding: 24px;
  gap: 16px;
  max-height: calc(100vh - 32px);
  overflow-y: auto;
}
.consent-prefs__title {
  font-family: var(--font-display);
  font-size: 22px;
  line-height: 28px;
  margin: 0 0 4px;
  color: var(--paper);
  font-weight: 400;
}
.consent-prefs__lede {
  font-size: 13px;
  line-height: 1.5;
  color: var(--paper);
  opacity: 0.85;
  margin: 0 0 8px;
}
.consent-prefs__category {
  padding: 12px 0;
  border-top: 1px solid color-mix(in oklch, var(--paper) 20%, var(--ink));
}
.consent-prefs__category-head {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: space-between;
}
.consent-prefs__category-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--paper);
}
.consent-prefs__category-always {
  font-size: 12px;
  color: var(--paper);
  opacity: 0.7;
}
.consent-prefs__category-desc {
  font-size: 12px;
  line-height: 1.5;
  color: var(--paper);
  opacity: 0.8;
  margin: 6px 0 0;
}
.consent-prefs__toggle {
  width: 20px;
  height: 20px;
  accent-color: var(--paper);
  cursor: pointer;
}
.consent-actions--prefs {
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-top: 8px;
}
.consent-btn {
  padding: 8px 14px;
  border-radius: var(--radius);
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-sans);
  cursor: pointer;
  border: 1px solid transparent;
}
.consent-btn--manage {
  color: var(--paper);
  background: transparent;
  border-color: color-mix(in oklch, var(--paper) 40%, transparent);
}
.consent-btn--decline {
  color: var(--paper);
  background: transparent;
  border-color: var(--paper);
}
.consent-btn--accept {
  color: var(--ink);
  background: var(--paper);
}
.consent-btn--save {
  color: var(--ink);
  background: var(--paper);
}
.consent-btn:hover:not(:disabled) {
  opacity: 0.9;
}
@media (max-width: 600px) {
  .consent-banner--preferences { padding: 20px 16px; }
  .consent-actions--prefs { justify-content: stretch; }
  .consent-actions--prefs .consent-btn { flex: 1 1 auto; }
}
`;

// ────────────────────────────────────────────────────────────────────
// WelcomeModal — post-payment / post-Clerk-invitation landing overlay.
//
// Mounted by app.jsx when ?welcome=1 is detected in the URL. Two
// variants based on `app.user` state:
//   - anon: user just completed Stripe Checkout but hasn't accepted
//           the Clerk invitation yet. Modal says "check your inbox"
//           with a primary CTA to open Gmail and a secondary "resend
//           my invitation" button that hits /api/clerk/resend-invitation.
//   - signed_in: user accepted the invitation, set a password, and
//           is now signed in. Modal says "you're all set" with a
//           single "start exploring" CTA that auto-dismisses after ~3s.
//
// Hydration gate (2026-05-19): the same URL handles both moments,
// and Clerk hydration is async. To prevent the anon-variant copy
// from flashing during the post-invitation round trip while Clerk
// is still booting, the modal returns null until `app.authLoaded`
// flips true. A 5s safety-net timer renders the modal even if Clerk
// never hydrates (SDK boot failure, ad-blocker, CSP regression) so
// the modal can't hang forever — `welcome_modal.auth_load_timeout`
// telemetry fires in that case so we can spot it in PostHog.
//
// Tokens-only CSS in web/app/styles/index.css's .welcome-modal block.
// Mobile-first; ESC + backdrop click dismiss.
function WelcomeModal({ app, state, onClose }) {
  const lc = app.locale;
  // Gate rendering on Clerk hydration. If authLoaded is true (Clerk
  // off OR Clerk on and isLoaded resolved) we can trust `app.user`.
  // While false, render nothing — but only up to AUTH_LOAD_TIMEOUT_MS.
  const AUTH_LOAD_TIMEOUT_MS = 5000;
  const [authTimedOut, setAuthTimedOut] = pUseState(false);
  const authLoaded = app.authLoaded !== false; // treat undefined as ready
  const renderReady = authLoaded || authTimedOut;
  const isSignedIn = !!app.user;
  const variant = isSignedIn ? "signed_in" : "anon";
  const [resending, setResending] = pUseState(false);
  const [resendResult, setResendResult] = pUseState(null);
  // Discriminated status from /api/clerk/invitation-status — fetched
  // once on anon-variant mount (signed_in skips it; nothing to verify).
  // Drives which copy the anon branch renders. Null = still fetching;
  // see the four `welcome_modal.anon.status.*` i18n keys for the
  // resolved-status copy. Pre-PR the anon body lied uniformly
  // ("we just sent an invitation") regardless of which Path-B webhook
  // outcome the user actually hit — see the postmortem in
  // ~/.claude/plans/bug-report-post-stripe-bright-flurry.md.
  const [statusInfo, setStatusInfo] = pUseState(null);
  const dialogRef = React.useRef(null);

  // Safety-net timeout: if Clerk never finishes hydrating we still
  // surface the modal (in whatever auth state we have) so the user
  // isn't stuck on a blank backdrop. Telemetry tags whether `user`
  // had populated by the time the timer fired — true = late
  // hydration, false = SDK boot likely failed.
  React.useEffect(() => {
    if (authLoaded) return undefined;
    const id = setTimeout(() => {
      setAuthTimedOut(true);
      track("welcome_modal.auth_load_timeout", { resolved_user: !!app.user });
    }, AUTH_LOAD_TIMEOUT_MS);
    return () => clearTimeout(id);
  }, [authLoaded, app.user]);

  // Fire `welcome_modal.shown` once the variant is resolvable (auth
  // gate cleared). Re-fires if the variant flips after the gate
  // (e.g. late-hydration moves user from null → signed-in object
  // while the modal is mounted). The hydration gate above ensures
  // we don't double-fire as anon→signed_in during the normal boot
  // race; this guard handles the post-timeout late-hydration case.
  React.useEffect(() => {
    if (!renderReady) return undefined;
    track("welcome_modal.shown", { variant, surface: "account" });
    // Auto-dismiss the signed-in variant after a brief acknowledgement
    // so the user lands on the real signed-in /account page.
    if (variant === "signed_in") {
      const id = setTimeout(() => {
        track("welcome_modal.dismissed", { variant, action: "auto" });
        onClose();
      }, 3200);
      return () => clearTimeout(id);
    }
    return undefined;
  }, [renderReady, variant, onClose]);

  // Invitation-status fetch — only meaningful for the anon variant.
  // Mounts once when the modal is render-ready AND the user isn't
  // signed in yet AND we have a session_id to verify against. The
  // endpoint is read-only + idempotent so polling is safe; we poll
  // ONCE on mount and re-poll after a 5s delay if the first response
  // was `webhook_pending` (the only transient state — others are
  // terminal). Pre-PR this whole flow was missing — the modal had no
  // idea whether an invitation was actually created.
  React.useEffect(() => {
    if (!renderReady || isSignedIn) return undefined;
    if (!state || !state.sessionId) return undefined;
    let cancelled = false;
    let retryTimer = null;
    const fetchStatus = async () => {
      try {
        const res = await fetch(
          `/api/clerk/invitation-status?session_id=${encodeURIComponent(state.sessionId)}`,
          { headers: { "Accept": "application/json" } },
        );
        if (cancelled) return;
        if (!res.ok) {
          setStatusInfo({ status: "fetch_failed" });
          track("welcome_modal.invitation_status_resolved", { status: "fetch_failed" });
          return;
        }
        const data = await res.json().catch(() => ({}));
        const status = (data && data.status) || "fetch_failed";
        setStatusInfo({
          status,
          emailDomain: (data && data.email_domain) || "",
        });
        track("welcome_modal.invitation_status_resolved", { status });
        // webhook_pending is transient — Stripe hasn't fired the
        // webhook yet OR it's still inflight. Retry once after 5s
        // to see if the server caught up. If still pending after
        // the retry we leave the user on the pending copy with a
        // "if it doesn't show up in 5 minutes, email us" escalation.
        if (status === "webhook_pending") {
          retryTimer = setTimeout(fetchStatus, 5000);
        }
      } catch {
        if (cancelled) return;
        setStatusInfo({ status: "fetch_failed" });
        track("welcome_modal.invitation_status_resolved", { status: "fetch_failed" });
      }
    };
    fetchStatus();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [renderReady, isSignedIn, state]);

  // ESC dismiss + focus trap entry — modeled on the SignupModal pattern.
  React.useEffect(() => {
    if (!renderReady) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") {
        track("welcome_modal.dismissed", { variant, action: "esc" });
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    if (dialogRef.current) dialogRef.current.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [renderReady, variant, onClose]);

  // While Clerk is mid-hydration and the safety-net hasn't fired,
  // render nothing — no backdrop, no flash of stale anon copy.
  if (!renderReady) return null;

  const onBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      track("welcome_modal.dismissed", { variant, action: "backdrop" });
      onClose();
    }
  };

  const onResend = async () => {
    if (resending || !state || !state.sessionId) {
      track("welcome_modal.resend_failed", {});
      setResendResult({ ok: false, msg: t("welcome_modal.anon.resend_failed", lc) });
      return;
    }
    setResending(true);
    setResendResult(null);
    track("welcome_modal.cta_resend_clicked", {});
    try {
      const res = await fetch("/api/clerk/resend-invitation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sessionId }),
      });
      if (!res.ok) {
        track("welcome_modal.resend_failed", {});
        setResendResult({ ok: false, msg: t("welcome_modal.anon.resend_failed", lc) });
      } else {
        const data = await res.json().catch(() => ({}));
        if (data && data.status === "user_exists") {
          // Clerk already has a user for this email — there's no new
          // invitation to re-send. Tell the user to refresh instead
          // of lying with "check your inbox".
          track("welcome_modal.resend_user_exists", {});
          setResendResult({ ok: false, msg: t("welcome_modal.anon.resend_user_exists", lc) });
        } else {
          track("welcome_modal.resend_done", {});
          setResendResult({ ok: true, msg: t("welcome_modal.anon.resend_done", lc) });
        }
      }
    } catch {
      track("welcome_modal.resend_failed", {});
      setResendResult({ ok: false, msg: t("welcome_modal.anon.resend_failed", lc) });
    }
    setResending(false);
  };

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onClick={onBackdropClick}
    >
      <div
        ref={dialogRef}
        className="modal welcome-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t("welcome_modal.aria.dialog", lc)}
        tabIndex={-1}
      >
        <button
          type="button"
          className="modal-close"
          aria-label={t("welcome_modal.aria.close", lc)}
          onClick={() => {
            track("welcome_modal.dismissed", { variant, action: "close" });
            onClose();
          }}
        >
          ×
        </button>
        <div className="welcome-modal-eyebrow">{t("welcome_modal.eyebrow", lc)}</div>
        {variant === "anon" ? (
          (() => {
            // Status-branched anon rendering — see the
            // welcome_modal.anon.status.* i18n keys + the comment on
            // statusInfo above. The default (statusInfo still null
            // OR status === "invitation_pending") is the canonical
            // "check inbox" copy. The three other branches surface
            // outcomes the modal pre-PR rendered identically + wrong.
            const status = statusInfo && statusInfo.status;
            if (status === "user_exists") {
              return (
                <>
                  <h2 className="welcome-modal-headline">{t("welcome_modal.anon.status.user_exists.headline", lc)}</h2>
                  <p className="welcome-modal-body">
                    {t("welcome_modal.anon.status.user_exists.body", lc, {
                      email_domain: (statusInfo && statusInfo.emailDomain) || "your email",
                    })}
                  </p>
                  <button
                    type="button"
                    className="welcome-modal-cta-primary"
                    onClick={() => {
                      track("welcome_modal.signin_existing_clicked", {});
                      if (app.clerkActions && typeof app.clerkActions.openSignIn === "function") {
                        app.clerkActions.openSignIn();
                      } else if (typeof app.openSignup === "function") {
                        app.openSignup({ mode: "login" });
                      }
                    }}
                  >
                    {t("welcome_modal.anon.status.user_exists.cta", lc)}
                  </button>
                </>
              );
            }
            if (status === "no_email") {
              return (
                <>
                  <h2 className="welcome-modal-headline">{t("welcome_modal.anon.status.no_email.headline", lc)}</h2>
                  <p className="welcome-modal-body">{t("welcome_modal.anon.status.no_email.body", lc)}</p>
                  <a
                    className="welcome-modal-cta-primary"
                    href="mailto:hello@pulpo.club?subject=Pulpo%20Pro%20activation%20help"
                    onClick={() => track("welcome_modal.cta_inbox_clicked", {})}
                  >
                    {t("welcome_modal.anon.status.no_email.cta", lc)}
                  </a>
                </>
              );
            }
            // Default branch — covers invitation_pending (happy path,
            // expected case), webhook_pending (still polling),
            // session_not_found, session_not_complete, fetch_failed,
            // AND the null-status pre-resolution window. Body switches
            // to the webhook_pending wording when that's the resolved
            // status so we don't lie about "we sent an invitation"
            // while we're waiting for Stripe to actually fire the
            // webhook. Resend CTA is always available — it's the
            // user-facing escape hatch for any of the failure modes.
            const isWebhookPending = status === "webhook_pending";
            return (
              <>
                <h2 className="welcome-modal-headline">{t("welcome_modal.anon.headline", lc)}</h2>
                <p className="welcome-modal-body">
                  {isWebhookPending
                    ? t("welcome_modal.anon.status.webhook_pending.body", lc)
                    : t("welcome_modal.anon.body", lc)}
                </p>
                <a
                  className="welcome-modal-cta-primary"
                  href="https://mail.google.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => track("welcome_modal.cta_inbox_clicked", {})}
                >
                  {t("welcome_modal.anon.cta_inbox", lc)}
                </a>
                <button
                  type="button"
                  className="welcome-modal-cta-secondary"
                  onClick={onResend}
                  disabled={resending}
                >
                  {resending ? "…" : t("welcome_modal.anon.cta_resend", lc)}
                </button>
                {resendResult && (
                  <p className={`welcome-modal-resend-${resendResult.ok ? "ok" : "err"}`} role="status">
                    {resendResult.msg}
                  </p>
                )}
              </>
            );
          })()
        ) : (
          <>
            <h2 className="welcome-modal-headline">{t("welcome_modal.signedin.headline", lc)}</h2>
            <p className="welcome-modal-body">{t("welcome_modal.signedin.body", lc)}</p>
            <button
              type="button"
              className="welcome-modal-cta-primary"
              onClick={() => {
                track("welcome_modal.dismissed", { variant, action: "explore" });
                onClose();
              }}
            >
              {t("welcome_modal.signedin.cta_explore", lc)}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// ProUpsellModal — home-page Pulpo Pro acquisition overlay (PR-B.5).
//
// Mounted on / when the URL carries a campaign signal (utm_*, ?code=…,
// or ?upsell=1). Pro signed-in users never see it. The decision logic
// lives in lib/upsell-config.ts so flipping the trigger rules
// (e.g. enabling for direct traffic) is a one-line edit.
//
// Mirrors the /start single-button funnel: 3 canonical Pro USPs +
// geo-derived price + "Get access" CTA → POST /api/stripe/start-checkout
// → window.location.assign(stripeUrl). Same backend, same Stripe page,
// same /account?welcome=1 redirect on success.
//
// Soft-fail on bad `?code=`: silent retry without the code so the user
// always reaches Stripe.
function ProUpsellModal({ app, trigger, urlCode, utms, onClose }) {
  const lc = app.locale;
  const dialogRef = React.useRef(null);
  const [submitting, setSubmitting] = pUseState(false);
  const [error, setError] = pUseState(null);
  // Geo-derived display price. Starts with the synchronous default
  // (USD) and refines once /api/geo resolves the visitor's country.
  const [price, setPrice] = pUseState(() => priceForCountry(null));

  React.useEffect(() => {
    track("pro_upsell.shown", { trigger, has_code: !!urlCode });
    let cancelled = false;
    fetchPriceForCurrentGeo().then((p) => {
      if (!cancelled) setPrice(p);
    });
    return () => { cancelled = true; };
  }, [trigger, urlCode]);

  // ESC dismiss + focus trap entry.
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        track("pro_upsell.dismissed", { trigger, action: "esc" });
        markUpsellDismissed();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    if (dialogRef.current) dialogRef.current.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [trigger, onClose]);

  const onBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      track("pro_upsell.dismissed", { trigger, action: "backdrop" });
      markUpsellDismissed();
      onClose();
    }
  };

  // Shared with FreeMonthModal — single implementation of the
  // postCheckout / soft-fail-on-bad-code retry / rate-limited / network
  // error / redirect chain. Lives in lib/stripe-modal-checkout.ts.
  const onCta = async () => {
    setError(null);
    track("pro_upsell.cta_clicked", { trigger, had_promo_code: !!urlCode });
    setSubmitting(true);

    const result = await startCheckoutFromModal({
      locale: lc,
      utms,
      urlCode,
    });

    if (result.kind === "redirect") {
      track("pro_upsell.checkout_redirected", {
        trigger, had_promo_code: !!urlCode,
      });
      window.location.assign(result.url);
      return;
    }
    // rate_limited and error both surface the same user-visible copy;
    // the helper already fired api.error for non-rate-limited failures.
    setError(t("pro_upsell.error", lc));
    setSubmitting(false);
  };

  const onMaybeLater = () => {
    track("pro_upsell.dismissed", { trigger, action: "maybe_later" });
    markUpsellDismissed();
    onClose();
  };

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onClick={onBackdropClick}
    >
      <div
        ref={dialogRef}
        className="modal pro-upsell-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t("pro_upsell.aria.dialog", lc)}
        tabIndex={-1}
      >
        <button
          type="button"
          className="modal-close"
          aria-label={t("pro_upsell.aria.close", lc)}
          onClick={() => {
            track("pro_upsell.dismissed", { trigger, action: "close" });
            markUpsellDismissed();
            onClose();
          }}
        >
          ×
        </button>
        <div className="pro-upsell-eyebrow">{t("pro_upsell.eyebrow", lc)}</div>
        <h2 className="pro-upsell-headline">{t("pro_upsell.headline", lc)}</h2>
        <ul className="pro-upsell-usps">
          <li>
            <span className="pro-upsell-usp-headline">{t("pro.usp.alerts.headline", lc)}</span>
            <span className="pro-upsell-usp-body">{t("pro.usp.alerts.body", lc)}</span>
          </li>
          <li>
            <span className="pro-upsell-usp-headline">{t("pro.usp.browse.headline", lc)}</span>
            <span className="pro-upsell-usp-body">{t("pro.usp.browse.body", lc)}</span>
          </li>
          <li>
            <span className="pro-upsell-usp-headline">{t("pro.usp.links.headline", lc)}</span>
            <span className="pro-upsell-usp-body">{t("pro.usp.links.body", lc)}</span>
          </li>
        </ul>
        <div className="pro-upsell-price">
          {t("pro_upsell.price", lc, { price: price.displayString })}
        </div>
        <button
          type="button"
          className="pro-upsell-cta-primary"
          onClick={onCta}
          disabled={submitting}
        >
          {submitting
            ? t("pro_upsell.cta_primary_submitting", lc)
            : t("pro_upsell.cta_primary", lc, { price: price.displayString })}
        </button>
        {urlCode && (
          <p className="pro-upsell-code-note" aria-live="polite">
            {t("pro_upsell.code_applied_note", lc)}
          </p>
        )}
        {error && (
          <p className="pro-upsell-error" role="alert">{error}</p>
        )}
        <button
          type="button"
          className="pro-upsell-cta-dismiss"
          onClick={onMaybeLater}
        >
          {t("pro_upsell.cta_dismiss", lc)}
        </button>
        <p className="pro-upsell-price-sub">{t("pro_upsell.price_sub", lc)}</p>
      </div>
    </div>
  );
}

export {
  PillRail, BrowsePage, ListingDetail,
  SavedPage, PlansPage, SignupModal, WelcomeModal, ProUpsellModal, ToastHost,
  makeDefaultFilters, applyFilters,
  ConsentBanner, DiscoverSkeleton, BrowseSkeleton, DataFetchFailed,
};
