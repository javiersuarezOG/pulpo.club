// Pulpo pages: Home (discovery), Browse, Detail, Saved, Plans, Modals
import React, {
  useState as pUseState,
  useEffect as pUseEffect,
  useRef as pUseRef,
  useMemo as pUseMemo,
  useCallback as pUseCallback,
} from "react";
import { t, tr, LOCALES } from "./i18n.jsx";
// Static-only imports from the prototype data file (shelves, pills, zones).
// The LISTINGS array is now live data, accessed per-component via
// useListings() / useListingsState().
import { SHELVES, PILLS, ZONES } from "./data.jsx";
import { useListings, useListingsState } from "./data/use-listings.tsx";
import {
  readFilterFromURL,
  readSortFromURL,
  writeFilterToURL,
} from "./data/filter-url.ts";
import { track } from "./telemetry/hook";
import { useDebouncedValue } from "./lib/use-debounced-value.ts";
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
  currentLocale,
  currentUnits,
} from "./components.jsx";
import { LiveStats } from "./components/LiveStats.jsx";
import { useUnits } from "./i18n.jsx";

// ====== TopNav ======
function TopNav({ app }) {
  const lc = app.locale;
  return (
    <header className="topnav">
      <div className="topnav-inner">
        <button className="logo-btn" onClick={() => app.go("home")} aria-label={t("nav.tab.home", lc)}>
          <PulpoLogo />
        </button>
        <nav className="topnav-links">
          <button className={app.route === "home" ? "active" : ""} onClick={() => app.go("home")}>{t("nav.discover", lc)}</button>
          <button className={app.route === "browse" ? "active" : ""} onClick={() => app.go("browse")}>{t("nav.browse", lc)}</button>
          <button className={app.route === "saved" ? "active" : ""} onClick={() => app.go("saved")}>
            {t("nav.saved", lc)} {app.savedIds.size > 0 && <span className="count-badge">{app.savedIds.size}</span>}
          </button>
        </nav>
        <div className="topnav-right">
          <LiveStats locale={lc} />
          <LocaleToggle app={app} />
          {app.user ? (
            <div className="profile-chip">
              <button
                className="avatar avatar-btn"
                onClick={() => app.go("account")}
                title={t("nav.account", lc)}
                aria-label={t("nav.account", lc)}
              >{app.user.email[0].toUpperCase()}</button>
              <button className="link-btn" onClick={() => app.signout()}>{t("nav.logout", lc)}</button>
            </div>
          ) : (
            <>
              <button className="link-btn" onClick={() => app.openSignup({ mode: "login" })}>{t("nav.login", lc)}</button>
              <button className="btn-primary" onClick={() => app.openSignup({ mode: "signup" })}>{t("nav.signup_free", lc)}</button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

// Compact EN/ES toggle. In production this would be a proper menu with full
// language names and flag-free regional labels (CR, MX, etc.) plus URL routing.
function LocaleToggle({ app }) {
  return (
    <div className="locale-toggle" role="group" aria-label={t("locale.toggle_aria", app.locale)}>
      {LOCALES.map(lc => (
        <button
          key={lc}
          className={app.locale === lc ? "active" : ""}
          onClick={() => {
            const prev = app.locale;
            if (prev !== lc) {
              track("locale.changed", { from: prev, to: lc });
            }
            app.setLocale(lc);
          }}
        >
          {lc.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

// ====== Mobile bottom tab bar ======
function BottomNav({ app }) {
  const tabs = [
    { key: "home", label: "Discover", icon: "home" },
    { key: "browse", label: "Browse", icon: "search" },
    { key: "saved", label: "Saved", icon: "heart" },
    { key: "profile", label: app.user ? "Profile" : "Sign in", icon: "user" },
  ];
  return (
    <nav className="bottomnav">
      {tabs.map(t => (
        <button
          key={t.key}
          className={(app.route === t.key || (t.key === "profile" && app.route === "account")) ? "active" : ""}
          onClick={() => {
            if (t.key === "profile") {
              if (!app.user) app.openSignup({ mode: "login" });
              else app.go("account");
            } else app.go(t.key);
          }}
        >
          <Icon name={t.icon} size={20} />
          <span>{t.label}</span>
          {t.key === "saved" && app.savedIds.size > 0 && <span className="tab-count">{app.savedIds.size}</span>}
        </button>
      ))}
    </nav>
  );
}

// ====== Pill rail ======
function PillRail({ app, active }) {
  return (
    <div className="pill-rail-wrap">
      <div className="pill-rail">
        <button
          className={`pill-chip ${!active ? "is-active" : ""}`}
          onClick={() => app.goBrowse({ category: null })}
        >
          <span className="pill-icon" aria-hidden="true"><Icon name="cat_all" size={15} strokeWidth={1.6}/></span> {t("pill.all", app.locale)}
        </button>
        {PILLS.map(p => (
          <button
            key={p.key}
            className={`pill-chip ${active === p.key ? "is-active" : ""}`}
            onClick={() => app.goBrowse({ category: p.key })}
          >
            <span className="pill-icon" aria-hidden="true"><Icon name={p.icon} size={15} strokeWidth={1.6}/></span>{tr(p.label, app.locale)}
          </button>
        ))}
      </div>
      <div className="pill-rail-fade" />
    </div>
  );
}

// ====== Home — Hero ======
function Hero({ app }) {
  const LISTINGS = useListings();
  // Pick highest-photo-count, freshest listing
  const featured = pUseMemo(() => {
    return [...LISTINGS]
      .filter(l => l.photos_count > 0 && !l.is_sold)
      .sort((a, b) => (b.photos_count - a.photos_count) || (a.first_seen_date - b.first_seen_date))[0];
  }, [LISTINGS]);
  if (!featured) return null;
  return (
    <section className="hero">
      <img className="hero-bg" src={featured.photos[0]} alt="" />
      <div className="hero-overlay" />
      <div className="hero-content">
        <div className="hero-eyebrow">
          <span>{featured.zone_name}, {featured.province_state}</span>
          <span className="dot">·</span>
          <span>{landTypeLabel(featured.land_type)}</span>
        </div>
        <h1 className="hero-title">{tr(featured.title, app.locale)}</h1>
        <p className="hero-sub">{t("hero.sub", app.locale)}</p>
        <div className="hero-ctas">
          <button
            className="btn-primary lg"
            onClick={() => {
              track("hero.cta_clicked", { destination: "browse" });
              app.go("browse");
            }}
          >
            {t("hero.cta.browse", app.locale)} <Icon name="arrow_right" size={16} strokeWidth={2}/>
          </button>
          <button
            className="btn-ghost lg"
            onClick={() => {
              track("hero.cta_clicked", { destination: "see_listing" });
              app.openListing(featured.id);
            }}
          >{t("hero.cta.see_listing", app.locale)}</button>
        </div>
      </div>
      <div className="hero-attrib">{t("hero.featured_today", app.locale)} · {formatPrice(featured.price)} · {formatSize(featured.size_m2)}</div>
    </section>
  );
}

// ====== Horizontal shelf ======
function Shelf({ shelf, app, locked = false, layout = "standard", expanded = false, onToggleExpand, registerRef }) {
  const LISTINGS = useListings();
  const scrollRef = pUseRef(null);
  const sectionRef = pUseRef(null);

  // Register section ref so parent can scroll to it on style-tile click.
  pUseEffect(() => {
    if (registerRef) registerRef(shelf.key, sectionRef.current);
  }, [shelf.key]);

  const allItems = pUseMemo(() =>
    LISTINGS.filter(l => !l.is_sold).filter(shelf.filter),
    [shelf, LISTINGS]
  );
  const items = expanded ? allItems : allItems.slice(0, 12);
  if (allItems.length < 6 && !locked) return null;
  const scrollBy = (dir) => {
    const el = scrollRef.current;
    if (el) el.scrollBy({ left: dir * (el.clientWidth * 0.85), behavior: "smooth" });
  };

  const isMagazine = layout === "magazine";

  return (
    <section className={`shelf ${isMagazine ? "shelf-magazine" : ""} ${expanded ? "is-expanded" : ""}`} ref={sectionRef}>
      <div className="shelf-head">
        <div className="shelf-head-text">
          <h2 className="shelf-title">
            <span className="shelf-icon" aria-hidden="true"><Icon name={shelf.icon} size={20} strokeWidth={1.6}/></span>{tr(shelf.label, app.locale)}
          </h2>
          {shelf.subline && (
            <p className="shelf-subline">{tr(shelf.subline, app.locale)}</p>
          )}
        </div>
        <div className="shelf-actions">
          <button
            className="link-btn"
            onClick={() => {
              if (!expanded) track("shelf.see_all_clicked", { shelf_key: shelf.key });
              if (onToggleExpand) onToggleExpand(shelf.key);
            }}
          >
            {expanded
              ? t("shelf.show_less", app.locale)
              : <>{t("card.see_all", app.locale)} <Icon name="arrow_right" size={14} strokeWidth={2}/></>}
          </button>
          {!expanded && (
            <div className="shelf-scroll-btns">
              <button onClick={() => scrollBy(-1)} aria-label={t("common.scroll_left", app.locale)}><Icon name="chevron_left" size={18}/></button>
              <button onClick={() => scrollBy(1)} aria-label={t("common.scroll_right", app.locale)}><Icon name="chevron_right" size={18}/></button>
            </div>
          )}
        </div>
      </div>
      {expanded ? (
        <div className={isMagazine ? "shelf-magazine-grid" : "shelf-expanded-grid"}>
          {items.map(l => (
            <ListingCard
              key={l.id} listing={l} app={app}
              onOpen={() => {
                track("card.clicked", { listing_id: l.id, source_view: "discover", source_shelf: shelf.key });
                app.openListing(l.id);
              }}
              variant={isMagazine ? "magazine" : "default"}
            />
          ))}
        </div>
      ) : (
        // PR-4c: magazine + standard now share the carousel rail. The rail
        // gets a `shelf-rail-magazine` modifier class that swaps card width
        // to --card-w-magazine so the editorial language stays distinct.
        <div className={`shelf-rail ${isMagazine ? "shelf-rail-magazine" : ""}`} ref={scrollRef}>
          {items.map(l => (
            <div className="shelf-item" key={l.id}>
              <ListingCard
                listing={l}
                app={app}
                onOpen={() => {
                  track("card.clicked", { listing_id: l.id, source_view: "discover", source_shelf: shelf.key });
                  app.openListing(l.id);
                }}
                variant={isMagazine ? "magazine" : "default"}
              />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ====== Find Your Style — orientation carousel (A.2) ======
// Sits between hero and shelves. Lets users navigate by mood/type before
// they encounter the full shelf feed. Each tile filters Browse to that style.
//
// Per spec:
//   - Tiles use a Pulpo PILL key as their style — clicking is equivalent to
//     selecting the matching pill in the pill rail.
//   - Min 3 active listings per style or the tile is suppressed.
//   - If <3 styles meet the threshold, the entire carousel is suppressed.
//   - Photo fallback: render style name on offset surface (no broken image).
//   - Order: most-populated styles first.
function StyleCarousel({ app, onPickStyle }) {
  const LISTINGS = useListings();
  const scrollRef = pUseRef(null);

  // Map a PILL key → a representative listing photo. We don't carry photos
  // in PILLS, so derive: first listing matching that pill's filter that has
  // a photo. Falls back to null → tile uses surface-offset background.
  const styles = pUseMemo(() => {
    // Subset of PILLS that meaningfully describe "style/mood" (per spec set:
    // Beachfront · Ocean View · Mountain View · Flat & Buildable · Off-Market
    // · Agricultural · Commercial · Build-Ready)
    const STYLE_KEYS = [
      "beachfront", "ocean_view", "mountain_view", "flat_buildable",
      "off_market", "agricultural", "commercial", "build_ready",
    ];
    return STYLE_KEYS
      .map(key => {
        const pill = PILLS.find(p => p.key === key);
        const shelf = SHELVES.find(s => s.key === key);
        if (!pill || !shelf) return null;
        const matches = LISTINGS.filter(l => !l.is_sold).filter(shelf.filter);
        const photoFull = matches.find(l => l.photos[0])?.photos[0] || null;
        // Serve a smaller crop for the carousel — tiles are ~280×210.
        let photo = null;
        if (photoFull) {
          try {
            const u = new URL(photoFull);
            u.searchParams.set("w", "560");
            u.searchParams.set("h", "360");
            u.searchParams.set("fit", "crop");
            u.searchParams.set("q", "70");
            photo = u.toString();
          } catch { photo = photoFull; }
        }
        return { key, label: pill.label, count: matches.length, photo };
      })
      .filter(s => s && s.count >= 3)        // min inventory threshold
      .sort((a, b) => b.count - a.count);    // most-populated first
  }, [LISTINGS]);

  // Min 3 tiles to show the carousel at all.
  if (styles.length < 3) return null;

  const scrollBy = (dir) => {
    const el = scrollRef.current;
    if (el) el.scrollBy({ left: dir * (el.clientWidth * 0.7), behavior: "smooth" });
  };

  return (
    <section className="style-carousel">
      <div className="style-carousel-head">
        <div className="shelf-head-text">
          <h2 className="shelf-title">{t("style.title", app.locale)}</h2>
          <p className="shelf-subline">{t("style.sub", app.locale)}</p>
        </div>
        <div className="shelf-scroll-btns">
          <button onClick={() => scrollBy(-1)} aria-label={t("common.scroll_left", app.locale)}><Icon name="chevron_left" size={18}/></button>
          <button onClick={() => scrollBy(1)} aria-label={t("common.scroll_right", app.locale)}><Icon name="chevron_right" size={18}/></button>
        </div>
      </div>
      <div className="style-rail" ref={scrollRef}>
        {styles.map(s => (
          <button
            key={s.key}
            className={`style-tile ${s.photo ? "" : "no-photo"}`}
            onClick={() => {
              track("style_carousel.tile_clicked", { style_key: s.key });
              if (onPickStyle) onPickStyle(s.key);
              else app.goBrowse({ category: s.key });
            }}
            aria-label={tr(s.label, app.locale)}
          >
            {s.photo && <img src={s.photo} alt="" loading="lazy" />}
            <div className="style-tile-overlay" />
            <span className="style-tile-label">{tr(s.label, app.locale)}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

// ====== Home page ======
function HomePage({ app }) {
  // === ALL HOOKS UP TOP — Rules of Hooks. Don't insert early returns
  // between any of these or React errors out (#310). ===
  const LISTINGS = useListings();
  const listingsState = useListingsState();
  const [expandedKey, setExpandedKey] = pUseState(null);
  const shelfRefs = pUseRef({});
  const [layout, setLayout] = pUseState(() => {
    // Default to "standard" so the 1-row carousel scroll affordance from
    // PR-4 is visible immediately. Magazine layout is opt-in via the
    // toggle (renders a static 6-card grid, no scroll). PR-4c will
    // refactor magazine to also carousel.
    try { return localStorage.getItem("pulpo-discover-layout") || "standard"; }
    catch { return "standard"; }
  });

  const orderedShelves = pUseMemo(() => {
    const pinned = ["new_this_week", "price_drops", "off_market"];
    const counts = SHELVES.map(s => ({ s, n: LISTINGS.filter(l => !l.is_sold).filter(s.filter).length }));
    const filtered = counts.filter(x => x.n >= 6);
    const pinnedOrdered = pinned.map(k => filtered.find(x => x.s.key === k)).filter(Boolean);
    const rest = filtered.filter(x => !pinned.includes(x.s.key)).sort((a, b) => b.n - a.n);
    return [...pinnedOrdered, ...rest].map(x => x.s);
  }, [LISTINGS]);

  const registerRef = pUseCallback((key, el) => { if (el) shelfRefs.current[key] = el; }, []);
  const toggleExpand = pUseCallback((key) => {
    setExpandedKey(prev => prev === key ? null : key);
  }, []);
  const pickStyle = pUseCallback((key) => {
    setExpandedKey(key);
    setTimeout(() => {
      const el = shelfRefs.current[key];
      if (el) {
        const top = el.getBoundingClientRect().top + window.scrollY - 80;
        window.scrollTo({ top, behavior: "smooth" });
      }
    }, 80);
  }, []);
  const setLayoutPersist = (v) => {
    setLayout(v);
    try { localStorage.setItem("pulpo-discover-layout", v); } catch {}
  };

  // === Hooks done — branch on load state. ===
  if (listingsState.state.status === "loading") return <DiscoverSkeleton />;
  if (listingsState.state.status === "error") {
    return <DataFetchFailed onRetry={listingsState.reload} />;
  }

  return (
    <div className={`page page-home discover-${layout}`}>
      <Hero app={app} />
      {app.tweaks?.showStyleCarousel !== false && (
        <StyleCarousel app={app} onPickStyle={pickStyle} />
      )}

      <div className="discover-controls">
        <div className="layout-toggle" role="tablist" aria-label={t("layout.aria", app.locale)}>
          <button
            role="tab"
            aria-selected={layout === "magazine"}
            className={layout === "magazine" ? "is-active" : ""}
            onClick={() => setLayoutPersist("magazine")}
          >
            <Icon name="grid" size={14}/> {t("layout.magazine", app.locale)}
          </button>
          <button
            role="tab"
            aria-selected={layout === "standard"}
            className={layout === "standard" ? "is-active" : ""}
            onClick={() => setLayoutPersist("standard")}
          >
            <Icon name="list" size={14}/> {t("layout.standard", app.locale)}
          </button>
        </div>
      </div>

      <div className="shelves">
        {orderedShelves.map((shelf) => (
          <Shelf
            key={shelf.key}
            shelf={shelf}
            app={app}
            layout={layout}
            expanded={expandedKey === shelf.key}
            onToggleExpand={toggleExpand}
            registerRef={registerRef}
          />
        ))}
        {!app.user && (
          <NewsletterCTA app={app} />
        )}
      </div>
    </div>
  );
}

// ====== Newsletter sticky CTA (compact inline version) ======
function NewsletterCTA({ app }) {
  const [submitted, setSubmitted] = pUseState(false);
  const lc = app.locale;
  return (
    <section className="newsletter-cta">
      <div className="nl-inner">
        <div className="nl-text">
          <Icon name="bell" size={18} />
          <div>
            <div className="nl-title">{t("newsletter.title", lc)}</div>
            <div className="nl-sub">{t("newsletter.sub", lc)}</div>
          </div>
        </div>
        {submitted ? (
          <div className="nl-success">
            <Icon name="check" size={16} strokeWidth={2.4} /> {t("newsletter.success", lc)}
          </div>
        ) : (
          <form className="nl-form" onSubmit={(e) => { e.preventDefault(); setSubmitted(true); }}>
            <input type="email" placeholder={t("newsletter.placeholder", lc)} required aria-label={t("newsletter.placeholder", lc)}/>
            <button type="submit" className="btn-primary">{t("newsletter.subscribe", lc)}</button>
          </form>
        )}
      </div>
    </section>
  );
}

// ====== Browse — filter sidebar ======
function FilterPanel({ filters, setFilters, count, onClose, app }) {
  const update = (patch) => setFilters({ ...filters, ...patch });
  const toggleSet = (key, val) => {
    const s = new Set(filters[key]);
    if (s.has(val)) s.delete(val); else s.add(val);
    update({ [key]: s });
  };
  const zoneList = ZONES.map(z => z.name);
  const activeCount = (filters.zones?.size || 0)
    + filters.land_types.size + filters.features.size
    + filters.infra.size + filters.status.size
    + (filters.price_max < 1000000 || filters.price_min > 0 ? 1 : 0);
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
            ? "Cada terreno recibe un puntaje compuesto de 0–100 basado en tres dimensiones simples."
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

function PriceHistogram({ filters, setFilters }) {
  const LISTINGS = useListings();
  // Compute histogram from full listings
  const max = 1000000;
  const buckets = 24;
  const counts = pUseMemo(() => {
    const arr = new Array(buckets).fill(0);
    LISTINGS.forEach(l => {
      if (typeof l.price !== "number" || l.price <= 0) return;
      const b = Math.min(buckets - 1, Math.floor(l.price / max * buckets));
      arr[b] += 1;
    });
    return arr;
  }, [LISTINGS]);
  const peak = Math.max(...counts, 1);
  return (
    <div className="histo">
      <div className="histo-bars">
        {counts.map((c, i) => {
          const inRange = (i / buckets * max) >= filters.price_min && (i / buckets * max) <= filters.price_max;
          return <div key={i} className={`histo-bar ${inRange ? "active" : ""}`} style={{ height: `${(c/peak)*100}%` }} />;
        })}
      </div>
      <div className="price-inputs">
        <div className="price-input">
          <label>Min</label>
          <input type="number" value={filters.price_min} onChange={(e) => setFilters({ price_min: +e.target.value })} />
        </div>
        <div className="price-input">
          <label>Max</label>
          <input type="number" value={filters.price_max} onChange={(e) => setFilters({ price_max: +e.target.value })} />
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
    price_max: 1000000,
    size_min: 0,
    readiness: 0,
    // PR-4b — feature parity with legacy:
    score_min: 0,                             // 0–100 score floor
    weights: { ...WEIGHT_DEFAULTS },          // V/L/M weights, sum = 100
    photos: "all",                            // "all" | "with" | "none"
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

function applyFilters(listings, f) {
  return listings.filter(l => {
    if (l.is_sold) return false;
    if (f.zones.size && !f.zones.has(l.zone_name)) return false;
    if (f.land_types.size && !f.land_types.has(l.land_type)) return false;
    if (l.price < f.price_min || l.price > f.price_max) return false;
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
    if (f.status.has("motivated") && l.days_listed < 90) return false;
    if (l.readiness_score < f.readiness) return false;
    if ((f.score_min ?? 0) > 0 && (l.rank_score ?? 0) < f.score_min) return false;
    if (f.photos === "with" && (l.photos_count ?? 0) === 0) return false;
    if (f.photos === "none" && (l.photos_count ?? 0) > 0) return false;
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

  // When the category in the URL changes (incl. "All" which is null), resync
  // filters to match. Without this, useState's lazy initializer only runs once
  // and stale filters carry over — clicking "All" leaves the previous category's
  // chips still applied.
  pUseEffect(() => {
    const f = buildFiltersForCategory(app.routeParams.category);
    // Allow callers to seed additional filters via routeParams (e.g. zone scoping
    // from "Browse similar listings in {zone}").
    if (Array.isArray(app.routeParams.zones) && app.routeParams.zones.length > 0) {
      f.zones = new Set(app.routeParams.zones);
    }
    setFilters(f);
  }, [app.routeParams.category, app.routeParams.zones]);

  // Persist filter + sort + category to URLSearchParams (replaceState
  // — no new history entries on every chip toggle).
  pUseEffect(() => {
    writeFilterToURL(filters, app.routeParams.category ?? null, sort);
  }, [filters, sort, app.routeParams.category]);

  pUseEffect(() => { localStorage.setItem("pulpo-view", view); }, [view]);

  // Debounce the slider-driven filter values 300ms so a single drag
  // doesn't fire dozens of applyFilters() passes. Chip toggles still
  // feel instant — the debounced snapshot tracks the live value.
  const debouncedFilters = useDebouncedValue(filters, 300);

  const results = pUseMemo(() => {
    const r = applyFilters(LISTINGS, debouncedFilters);
    const sorters = {
      recent: (a, b) => a.first_seen_date - b.first_seen_date,
      price_asc: (a, b) => (a.price ?? Infinity) - (b.price ?? Infinity),
      price_desc: (a, b) => (b.price ?? -1) - (a.price ?? -1),
      size_desc: (a, b) => (b.size_m2 ?? 0) - (a.size_m2 ?? 0),
      ppm_asc: (a, b) => (a.price_per_m2 ?? Infinity) - (b.price_per_m2 ?? Infinity),
      days_asc: (a, b) => a.days_listed - b.days_listed,
      ready_desc: (a, b) => b.readiness_score - a.readiness_score,
      stars_desc: (a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0),
      // Composite using user-overridden weights (PR-4b — feature parity).
      composite_desc: (a, b) =>
        recomputeComposite(b, debouncedFilters.weights) -
        recomputeComposite(a, debouncedFilters.weights),
    };
    return [...r].sort(sorters[sort] || sorters.recent);
  }, [debouncedFilters, sort, LISTINGS]);

  const activeFilterCount = filters.zones.size + filters.land_types.size + filters.features.size + filters.infra.size + filters.status.size + (filters.price_max < 1000000 || filters.price_min > 0 ? 1 : 0) + (filters.readiness > 0 ? 1 : 0);

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
      <PillRail app={app} active={app.routeParams.category} />
      <div className="browse-layout">
        <div className="filter-desktop">
          <FilterPanel filters={filters} setFilters={setFilters} count={results.length} app={app} />
        </div>
        <div className="results-col">
          <div className="results-header">
            <div className="results-count">
              {app.routeParams.category ? (() => {
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
              <select className="sort-select" value={sort} onChange={(e) => setSortTelemeter(e.target.value)}>
                <option value="recent">{t("sort.recent", app.locale)}</option>
                <option value="price_asc">{t("sort.price_asc", app.locale)}</option>
                <option value="price_desc">{t("sort.price_desc", app.locale)}</option>
                <option value="size_desc">{t("sort.size_desc", app.locale)}</option>
                <option value="ppm_asc">{t("sort.ppm_asc_suffix", app.locale, { suffix: `$${ppmSuffix()}` })}</option>
                <option value="days_asc">{t("sort.days_asc", app.locale)}</option>
                <option value="ready_desc">{t("sort.ready_desc", app.locale)}</option>
                <option value="stars_desc">{t("sort.stars_desc", app.locale)}</option>
                <option value="composite_desc">{t("sort.composite_desc", app.locale)}</option>
              </select>
              <div className="view-toggle">
                <button className={view === "table" ? "active" : ""} onClick={() => setViewTelemeter("table")} aria-label={t("view.table", app.locale)}>
                  <Icon name="list" size={16}/>
                </button>
                <button className={view === "cards" ? "active" : ""} onClick={() => setViewTelemeter("cards")} aria-label={t("view.cards", app.locale)}>
                  <Icon name="grid" size={16}/>
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
              {(filters.price_min > 0 || filters.price_max < 1000000) && <span className="active-chip" onClick={() => setFilters({...filters, price_min: 0, price_max: 1000000})}>{formatPrice(filters.price_min)}–{formatPrice(filters.price_max)} <Icon name="close" size={12}/></span>}
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
            <div className="card-grid">
              {results.map(l => (
                <ListingCard
                  key={l.id}
                  listing={l}
                  app={app}
                  onOpen={() => {
                    track("card.clicked", { listing_id: l.id, source_view: "browse" });
                    app.openListing(l.id);
                  }}
                />
              ))}
            </div>
          ) : (
            <ResultsTable results={results} app={app} sort={sort} setSort={setSortTelemeter} />
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
function ResultsTable({ results, app, sort, setSort }) {
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
                {l.photos[0] ? <img src={l.photos[0]} alt=""/> : <div className="thumb-placeholder"/>}
              </td>
              <td className="title-cell">{tr(l.title, app.locale)}</td>
              <td>{l.zone_name}</td>
              <td><span className={`type-pill type-${l.land_type}`}>{landTypeLabel(l.land_type)}</span></td>
              <td className="num">{formatSize(l.size_m2)}</td>
              <td className="num bold">{formatPrice(l.price)}</td>
              <td className="num muted">{formatPpm(l.price_per_m2)}</td>
              <td className={`num tone-${daysListedTone(l.days_listed)}`}>{l.days_listed}d</td>
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
function ListingDetail({ listing, app, asPanel = true }) {
  const [galleryIdx, setGalleryIdx] = pUseState(0);
  const [lightbox, setLightbox] = pUseState(false);
  const isSold = listing.is_sold;
  const isOffMarket = listing.source_type === "off_market";
  const isPaid = app.user && app.user.plan && app.user.plan !== "free";
  // Off-market = paid-only. Anonymous and free users hit a paywall.
  const offMarketLocked = isOffMarket && !isPaid;
  // Free signup unlocks: source URL, full gallery, all USPs, precise location.
  const needsSignup = !app.user;

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
    setGalleryIdx(idx);
    setLightbox(true);
    track("detail.photo_lightbox_opened", { listing_id: listing.id });
  };

  const lc = app.locale;
  const facts = [
    { icon: "road", label: t("detail.fact.road", lc), value: listing.road_access_type ? capitalize(listing.road_access_type) : "—" },
    { icon: "droplet", label: t("detail.fact.water", lc), value: listing.has_water ? t("detail.fact.water_on", lc) : "—" },
    { icon: "bolt", label: t("detail.fact.electricity", lc), value: listing.has_power ? t("detail.fact.power_at", lc) : "—" },
    { icon: "leaf", label: t("detail.fact.topography", lc), value: listing.is_flat ? t("detail.fact.flat_yes", lc) : t("detail.fact.flat_no", lc) },
    { icon: "wave", label: t("detail.fact.beachfront_tier", lc), value: listing.beachfront_tier ? capitalize(listing.beachfront_tier.replace("_"," ")) : "—" },
    { icon: "sun", label: t("detail.fact.ocean_view", lc), value: listing.has_ocean_view ? t("detail.fact.yes", lc) : "—" },
    { icon: "zone", label: t("detail.fact.zoning", lc), value: capitalize(listing.zoning_use) },
    { icon: "camera", label: t("detail.fact.photos", lc), value: `${listing.photos_count}` },
  ];

  return (
    <div className={`detail ${asPanel ? "as-panel" : "as-page"}`}>
      <div className="detail-head">
        <button className="link-btn" onClick={() => app.closeListing()}>
          <Icon name="arrow_left" size={16} strokeWidth={2}/> Back to results
        </button>
        <div className="detail-head-right">
          <HeartButton listingId={listing.id} app={app} variant="inline" size={20}/>
        </div>
      </div>

      {isSold && (
        <div className="sold-banner">
          <strong>{t("detail.sold_banner.title", lc)}</strong>
          <span>{t("detail.sold_banner.days", lc, { n: listing.days_listed })}</span>
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
            {[1,2,3,4].map(i => listing.photos[i] && (
              <button
                key={i}
                className={`gallery-thumb ${needsSignup && i >= 2 ? "locked" : ""}`}
                aria-label={needsSignup && i >= 2 ? t("detail.gallery.locked_aria", lc) : t("detail.gallery.open_n", lc, { n: i + 1 })}
                onClick={() => {
                  if (needsSignup && i >= 2) {
                    app.openSignup({ mode: "signup", pendingListing: listing.id });
                  } else {
                    openLightbox(i);
                  }
                }}
              >
                <img src={listing.photos[i]} alt=""/>
                {needsSignup && i >= 2 && (
                  <div className="thumb-lock"><Icon name="lock" size={16}/></div>
                )}
                {!needsSignup && i === 4 && listing.photos.length > 5 && (
                  <div className="more-photos">{t("detail.more_photos", lc, { n: listing.photos.length - 5 })}</div>
                )}
                {needsSignup && i === 4 && (
                  <div className="more-photos">{t("detail.signup_more_photos", lc, { n: listing.photos.length - 2 })}</div>
                )}
              </button>
            ))}
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

        <div className="detail-keystats">
          <div className="kstat">
            <div className="kstat-label">{t("detail.price", lc)}</div>
            <div className="kstat-value">{formatPrice(listing.price)}</div>
            {listing.previous_price && <div className="kstat-sub strike">{formatPrice(listing.previous_price)}</div>}
          </div>
          <div className="kstat">
            <div className="kstat-label">{t("detail.size", lc)}</div>
            <div className="kstat-value">{formatSize(listing.size_m2)}</div>
          </div>
          <div className="kstat">
            <div className="kstat-label">{`$${ppmSuffix()}`}</div>
            <div className="kstat-value">{formatPpm(listing.price_per_m2)}</div>
          </div>
          <div className="kstat">
            <div className="kstat-label">{t("detail.days_listed", lc)}</div>
            <div className={`kstat-value tone-${daysListedTone(listing.days_listed)}`}>{listing.days_listed}</div>
          </div>
        </div>

        <div className="detail-section">
          <p className="detail-description">{tr(listing.description, app.locale)}</p>
        </div>

        <div className="detail-section">
          <h3 className="section-title">{t("detail.reasons", app.locale)}</h3>
          <ul className="usp-list">
            {(needsSignup ? listing.usps.slice(0, 1) : listing.usps).map((u, i) => (
              <li key={i}><Icon name="check" size={16} strokeWidth={2.4}/> {tr(u, app.locale)}</li>
            ))}
            {needsSignup && listing.usps.length > 1 && (
              <li className="usp-locked">
                <Icon name="lock" size={14} strokeWidth={2}/>
                <button className="link-btn" onClick={() => app.openSignup({ mode: "signup", pendingListing: listing.id })}>
                  {listing.usps.length - 1 === 1
                    ? t("detail.signup_more_reasons_one", lc)
                    : t("detail.signup_more_reasons_other", lc, { n: listing.usps.length - 1 })}
                </button>
              </li>
            )}
          </ul>
        </div>

        <div className="detail-section">
          <h3 className="section-title">{t("detail.key_facts", lc)}</h3>
          <div className="facts-grid">
            {facts.map(f => (
              <div className="fact-tile" key={f.label}>
                <div className="fact-icon"><Icon name={f.icon} size={18}/></div>
                <div className="fact-text">
                  <div className="fact-label">{f.label}</div>
                  <div className={`fact-value ${f.value === "—" ? "muted" : ""}`}>{f.value}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="detail-section">
          <h3 className="section-title">{t("detail.location", lc)}</h3>
          <div className="location-block">
            <div className="map-chip">
              <Icon name="map_pin" size={16}/>
              <span><strong>{listing.zone_name}</strong>, {listing.province_state}</span>
            </div>
            <div className="distance-pills">
              {listing.dist_beach_km != null && <span className="dpill"><Icon name="cat_beachfront" size={13} strokeWidth={1.6}/> {listing.dist_beach_km < 1 ? t("detail.on_beach", lc) : t("detail.km_to_beach", lc, { n: listing.dist_beach_km })}</span>}
              <span className="dpill"><Icon name="plane" size={13} strokeWidth={1.6}/> {t("detail.km_to_airport", lc, { n: listing.dist_airport_km })}</span>
              <span className="dpill"><Icon name="cat_commercial" size={13} strokeWidth={1.6}/> {t("detail.km_to_town", lc, { n: listing.dist_nearest_town_km })}</span>
            </div>
            <div className={`static-map ${needsSignup ? "zone-only" : ""}`}>
              <div className="static-map-grid"/>
              {needsSignup ? (
                <div className="static-map-zone-blob">
                  <Icon name="map_pin" size={20} strokeWidth={1.4}/>
                  <span>{t("detail.zone_area", lc, { zone: listing.zone_name })}</span>
                </div>
              ) : (
                <div className="static-map-pin"><Icon name="map_pin" size={28} strokeWidth={1.4}/></div>
              )}
              <div className="static-map-zone">{listing.zone_name}</div>
              {needsSignup && (
                <button className="map-unlock-chip" onClick={() => app.openSignup({ mode: "signup", pendingListing: listing.id })}>
                  <Icon name="lock" size={12}/> {t("detail.signup_for_pin", lc)}
                </button>
              )}
            </div>
          </div>
        </div>

        {offMarketLocked && (
          <div className="paywall-overlay hard">
            <div className="pw-card">
              <Icon name="cat_off_market" size={28}/>
              <h3>{t("detail.paywall.title", lc)}</h3>
              <p>{t("detail.paywall.body", lc)}</p>
              <button className="btn-primary lg" onClick={() => app.go("plans")}>{t("detail.paywall.see_plans", lc)}</button>
              {!app.user && (
                <button className="btn-ghost" onClick={() => app.openSignup({ mode: "login" })}>{t("detail.paywall.have_account", lc)}</button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Sticky bottom CTA */}
      {!isSold && !offMarketLocked && (
        <div className="detail-cta-bar">
          {needsSignup ? (
            <button
              className="btn-primary lg block"
              onClick={() => app.openSignup({ mode: "signup", pendingListing: listing.id })}
            >
              <Icon name="lock" size={16}/> {t("detail.signup_to_view_source", lc)}
            </button>
          ) : listing.original_url ? (
            <a
              className="btn-primary lg block"
              href={listing.original_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => track("view_original.clicked", {
                listing_id: listing.id,
                source_label: listing.source_label,
              })}
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

  const sorted = pUseMemo(() => {
    const arr = [...items];
    switch (sort) {
      case "price_asc": arr.sort((a,b) => a.price - b.price); break;
      case "price_desc": arr.sort((a,b) => b.price - a.price); break;
      case "size_desc": arr.sort((a,b) => b.size_m2 - a.size_m2); break;
      case "ppm_asc": arr.sort((a,b) => a.price_per_m2 - b.price_per_m2); break;
      case "days_asc": arr.sort((a,b) => a.days_listed - b.days_listed); break;
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
          {sorted.map(l => (
            <ListingCard
              key={l.id}
              listing={l}
              app={app}
              onOpen={() => {
                track("card.clicked", { listing_id: l.id, source_view: "saved" });
                app.openListing(l.id);
              }}
            />
          ))}
        </div>
      ) : (
        <ResultsTable results={sorted} app={app} sort={sort} setSort={setSort} />
      )}
    </div>
  );
}

// ====== Plans page ======
function PlansPage({ app }) {
  const [annual, setAnnual] = pUseState(true);
  return (
    <div className="page page-plans">
      <div className="plans-head">
        <h1>Pick a plan that fits how you invest.</h1>
        <p>Pulpo is free to browse. Upgrade for unlimited details, off-market access, and weekly alerts.</p>
        <div className="annual-toggle">
          <button className={!annual ? "active" : ""} onClick={() => setAnnual(false)}>Monthly</button>
          <button className={annual ? "active" : ""} onClick={() => setAnnual(true)}>Annual <span className="save">Save 20%</span></button>
        </div>
      </div>
      <div className="plans-grid">
        <div className="plan-card">
          <div className="plan-name">Free</div>
          <div className="plan-price"><span>$0</span></div>
          <div className="plan-tag">Browse the catalogue</div>
          <ul className="plan-features">
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Unlimited card browsing</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> 8 detail views per month</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Save up to 10 listings</li>
            <li className="muted">— Off-market deals</li>
            <li className="muted">— Weekly newsletter</li>
          </ul>
          <button className="btn-ghost block" disabled={!app.user}>{app.user ? "Your plan" : "Sign up free"}</button>
        </div>
        <div className="plan-card featured">
          <div className="plan-ribbon">Most popular</div>
          <div className="plan-name">Pulpo Pro</div>
          <div className="plan-price">
            <span>${annual ? 19 : 24}</span><span className="per">/month</span>
          </div>
          <div className="plan-tag">{annual ? "Billed $228/yr" : "Billed monthly"}</div>
          <ul className="plan-features">
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Everything in Free</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Unlimited listing details</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Off-market deal access</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Weekly curated newsletter</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Save unlimited listings</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Price-drop alerts on saved</li>
          </ul>
          <button className="btn-primary block lg">Start 7-day free trial</button>
        </div>
        <div className="plan-card">
          <div className="plan-name">Agency</div>
          <div className="plan-price">
            <span>${annual ? 79 : 99}</span><span className="per">/month</span>
          </div>
          <div className="plan-tag">For investor groups & brokers</div>
          <ul className="plan-features">
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Everything in Pro</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> 5 team seats</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Shared saved lists</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> CSV export</li>
            <li><Icon name="check" size={14} strokeWidth={2.4}/> Priority off-market intros</li>
          </ul>
          <button className="btn-ghost block">Contact sales</button>
        </div>
      </div>
      <div className="social-proof">
        <Icon name="star" size={14}/> <Icon name="star" size={14}/> <Icon name="star" size={14}/> <Icon name="star" size={14}/> <Icon name="star" size={14}/>
        <span>247 investors are using Pulpo this month</span>
      </div>
    </div>
  );
}

// ====== Sign-up modal ======
function SignupModal({ app }) {
  const m = app.signupModal;
  if (!m) return null;
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
          <h2>{mode === "signup" ? "Discover land deals before they go public." : "Welcome back."}</h2>
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
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@email.com" autoFocus/>
          </label>
          <label>Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 6 characters"/>
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
    if (filters.price_max < 1_000_000) {
      tryWithout("any budget", "cualquier presupuesto", (n) => {
        n.price_min = 0;
        n.price_max = 1_000_000;
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
          ? "Ningún terreno coincide con tus filtros."
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
function DataFetchFailed({ onRetry }) {
  return (
    <div className="empty-state lg" role="alert">
      <h2>We couldn't load the listings.</h2>
      <p>This is on us. The data feed didn't respond — try again in a moment.</p>
      <button className="btn-primary" onClick={onRetry}>Retry</button>
    </div>
  );
}

// ====== Cookie-consent banner shim ======
// Defaults to opt-in outside the EU. EU detection is best-effort via
// timezone — accurate enough for a non-binding consent prompt; the real
// determination of GDPR applicability lives server-side once the
// auth+legal stack lands.
function detectEuRegion() {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    return /^Europe\//.test(tz);
  } catch { return false; }
}
function ConsentBanner({ locale = "en" }) {
  const [decided, setDecided] = pUseState(() => {
    try { return localStorage.getItem("pulpo-consent") || ""; }
    catch { return ""; }
  });
  if (decided === "granted" || decided === "declined") return null;
  const region = detectEuRegion() ? "eu" : "non-eu";
  // Outside the EU, default to silent opt-in (don't show the banner).
  if (region === "non-eu") {
    if (!decided) {
      try { localStorage.setItem("pulpo-consent", "granted"); } catch { /* ignore */ }
    }
    return null;
  }
  const set = (decision) => {
    try { localStorage.setItem("pulpo-consent", decision); } catch { /* ignore */ }
    setDecided(decision);
  };
  return (
    <div className="consent-banner" role="dialog" aria-label={t("consent.aria", locale)}>
      <div className="consent-text">
        {t("consent.body", locale)}
      </div>
      <div className="consent-actions">
        <button className="btn-ghost" onClick={() => set("declined")}>{t("consent.decline", locale)}</button>
        <button className="btn-primary" onClick={() => set("granted")}>{t("consent.accept", locale)}</button>
      </div>
    </div>
  );
}

export {
  TopNav, BottomNav, PillRail, HomePage, BrowsePage, ListingDetail,
  SavedPage, PlansPage, SignupModal, ToastHost, makeDefaultFilters, applyFilters,
  ConsentBanner, DiscoverSkeleton, BrowseSkeleton, DataFetchFailed,
};
