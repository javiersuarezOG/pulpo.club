import React from "react";

// Pulpo — minimal i18n layer.
//
// In a real app this is where you'd wire up react-i18next, next-intl, or FormatJS.
// For the prototype we keep it dead simple: a global `LOCALE` ref + a `t(key)` lookup
// + a `tr(field)` helper that picks {en,es} off a translatable field.
//
// HOW IT WORKS
//   Listings store translatable text as objects: { en: "...", es: "..." }
//   Plain non-translatable values (price, m², zone names, dates) stay as scalars.
//   `tr(value)` returns the right language and gracefully falls back to EN.
//
// In production a CMS like Sanity, Contentful, Payload or Storyblok would store
// the same shape natively — each translatable field marked "localized".

const LOCALES = ["en", "es"];
const DEFAULT_LOCALE = "en";

// 3-tier locale resolver, in priority order:
//   1. ?lang=es query param  — explicit user/share intent. URL wins so a
//      shared link always renders the language the sharer chose.
//   2. localStorage           — return-visit preference.
//   3. navigator.language     — first-visit users with no other signal.
//   4. DEFAULT_LOCALE         — final fallback.
//
// (1) sits above (2) so a Spanish-speaking user clicking ?lang=en doesn't
// have their localStorage Spanish preference override the link's intent.
function readUrlLocale() {
  if (typeof window === "undefined") return null;
  try {
    const v = new URLSearchParams(window.location.search).get("lang");
    if (v && LOCALES.includes(v)) return v;
  } catch { /* ignore */ }
  return null;
}

function readStoredLocale() {
  try {
    const v = localStorage.getItem("pulpo-locale");
    if (v && LOCALES.includes(v)) return v;
  } catch { /* ignore */ }
  return null;
}

function readBrowserLocale() {
  if (typeof navigator === "undefined") return null;
  // navigator.language can be "es", "es-MX", "es-419", etc. — match on prefix.
  const lang = (navigator.language || "").toLowerCase();
  if (lang.startsWith("es")) return "es";
  if (lang.startsWith("en")) return "en";
  return null;
}

function getInitialLocale() {
  return readUrlLocale() || readStoredLocale() || readBrowserLocale() || DEFAULT_LOCALE;
}

// Push the chosen locale into the URL via replaceState — same pattern as
// filter chips, no history pollution. Strips `?lang=` when the locale
// matches the default-resolution path (DEFAULT_LOCALE without storage)
// so we don't accumulate noise on links the user copies.
function syncLocaleToUrl(locale) {
  if (typeof window === "undefined") return;
  try {
    const params = new URLSearchParams(window.location.search);
    if (locale === DEFAULT_LOCALE) {
      params.delete("lang");
    } else {
      params.set("lang", locale);
    }
    const qs = params.toString();
    const url = `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`;
    window.history.replaceState(window.history.state, "", url);
  } catch { /* ignore */ }
}

// React hook + global setter
function useLocale() {
  const [locale, setLocaleState] = React.useState(getInitialLocale);
  const setLocale = React.useCallback((next) => {
    if (!LOCALES.includes(next)) return;
    try { localStorage.setItem("pulpo-locale", next); } catch {}
    setLocaleState(next);
    document.documentElement.lang = next;
    syncLocaleToUrl(next);
  }, []);
  React.useEffect(() => { document.documentElement.lang = locale; }, [locale]);

  // popstate sync: forward/back navigation may carry a different ?lang=,
  // so reseed locale from the URL on every history change. Skips the
  // write to localStorage — the URL is authoritative for that nav.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const onPop = () => {
      const next = readUrlLocale();
      if (next && next !== locale) setLocaleState(next);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [locale]);

  return [locale, setLocale];
}

// PR-4c — area-unit preference. Vrs² is the Salvadoran traditional unit
// (1 vr² ≈ 0.698896 m²). Stored alongside locale so it persists across
// sessions; mirrored to <html data-units> so format helpers can read it
// without prop-threading (same trick we use for locale).
const UNITS = ["m2", "vrs2"];
const DEFAULT_UNITS = "m2";
const M2_PER_VARA2 = 0.698896;
function getStoredUnits() {
  try { return localStorage.getItem("pulpo-units") || DEFAULT_UNITS; }
  catch { return DEFAULT_UNITS; }
}
function useUnits() {
  const [units, setUnitsState] = React.useState(getStoredUnits);
  const setUnits = React.useCallback((next) => {
    if (!UNITS.includes(next)) return;
    try { localStorage.setItem("pulpo-units", next); } catch {}
    setUnitsState(next);
    document.documentElement.dataset.units = next;
  }, []);
  React.useEffect(() => { document.documentElement.dataset.units = units; }, [units]);
  return [units, setUnits];
}

// Translate a localized field. Accepts:
//   - string                                   → returned as-is (legacy / non-translatable)
//   - { en: "...", es: "..." }                 → picks current locale, falls back to EN
//   - array of either                          → maps over and returns array
function tr(value, locale) {
  if (value == null) return value;
  if (Array.isArray(value)) return value.map(v => tr(v, locale));
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    return value[locale] ?? value[DEFAULT_LOCALE] ?? Object.values(value)[0];
  }
  return value;
}

// UI strings table.
// Keep keys descriptive and grouped. In a real app this becomes en.json / es.json.
const UI_STRINGS = {
  // Nav — Wave 3a renamed the three section labels:
  //   * Home tab stays "Home" (the /browse tab took the "Discover" label).
  //   * /browse is labelled "Discover" — catalog/search is where you discover.
  //   * /saved is labelled "Favorites" — consumer mental model.
  // URL paths still say /browse and /saved; the URL rename is Wave 3b
  // (gated on a PostHog dashboard audit). One key per surface concept;
  // SiteHeader and BottomNav read the same strings.
  "nav.home":                { en: "Home",                es: "Inicio" },
  "nav.discover":            { en: "Discover",            es: "Descubrir" },
  "nav.favorites":           { en: "Favorites",           es: "Favoritos" },
  "nav.login":               { en: "Log in",              es: "Iniciar sesión" },
  "nav.signup_free":         { en: "Sign up — free",      es: "Crear cuenta — gratis" },
  "nav.logout":              { en: "Log out",             es: "Cerrar sesión" },
  "nav.account_or_sign_in":  { en: "Sign in or create an account", es: "Inicia sesión o crea una cuenta" },
  "nav.tab.profile":         { en: "Profile",             es: "Perfil" },
  "nav.tab.signin":          { en: "Sign in",             es: "Entrar" },

  // ── Hero / New homepage rewrite (Phase 4) ─────────────────────────
  // Legacy "hero.*" keys (hero.sub, hero.cta.browse, hero.cta.see_listing,
  // hero.featured_today) were dropped in the rewrite cutover (Phase 9):
  // the legacy Hero in pages.jsx that consumed them no longer exists.
  // Everything below is the new-hero copy backing web/app/home/Hero.jsx.
  // All keys below land bilingual at write time per Q1 of the rewrite
  // plan. Spanish copy targets a SV audience — natural register, not
  // literal translation. Sebastian/colleague should still spot-check.
  //
  // Eyebrow + headline + tagline + CTA + sub-text per the brief.
  "new_hero.eyebrow":        { en: "★ Ranked by value",
                               es: "★ Ordenado por valor" },
  "new_hero.headline":       { en: "Every beach and lake home in El Salvador, ranked by value.",
                               es: "Cada casa de playa y lago en El Salvador, ordenada por valor." },
  "new_hero.tagline":        { en: "No more scrolling through 50 listing sites. We rank every beach and lake listing by value and deliver the 10 best to your inbox every two weeks.",
                               es: "Deja de revisar 50 sitios. Ordenamos cada anuncio de playa y lago por valor y te enviamos los 10 mejores al correo cada dos semanas." },
  "new_hero.email_placeholder": { en: "you@example.com",
                                  es: "tú@ejemplo.com" },
  "new_hero.cta":            { en: "Get the 10 best",     es: "Recibir los 10 mejores" },
  "new_hero.cta_loading":    { en: "Sending…",            es: "Enviando…" },
  "new_hero.sub":            { en: "Free. Unsubscribe whenever.",
                               es: "Gratis. Cancela cuando quieras." },
  "new_hero.success":        { en: "Done — check your inbox.",
                                es: "Listo — revisa tu correo." },
  "new_hero.error_generic":  { en: "Couldn't sign you up. Try again?",
                               es: "No pudimos suscribirte. ¿Intentas de nuevo?" },
  "new_hero.error_invalid_email": { en: "That email looks off — check it?",
                                    es: "Ese correo no se ve bien — ¿lo revisas?" },
  "new_hero.error_already":  { en: "You're already on the list. Welcome back.",
                               es: "Ya estás en la lista. Qué bueno verte." },

  // Proof row — "This week's top 3 deals"
  "proof_row.heading":       { en: "This week's top 3 deals",
                               es: "Los 3 mejores tratos de esta semana" },
  "proof_row.see_all":       { en: "See all",                es: "Ver todas" },
  "proof_row.empty":         { en: "Fresh picks land here every week.",
                               es: "Cada semana publicamos nuevos hallazgos aquí." },

  // Category grid — Beach × {Homes, Condos, Land} + Lake × same.
  // Section headers + tile titles + tile descriptions (bilingual tile
  // copy also lives in web/app/config/ia.ts; these strings are the
  // section-level UI chrome around the tiles).
  "category_grid.beach_heading": { en: "Beach properties", es: "Propiedades de playa" },
  "category_grid.lake_heading":  { en: "Lake properties",  es: "Propiedades de lago" },
  "category_grid.browse_all":    { en: "Browse all {n} →", es: "Ver las {n} →" },
  "category_grid.browse_all_aria": { en: "Browse all {n} {master} properties",
                                     es: "Ver las {n} propiedades de {master}" },

  // Discovery pills (All / ★ Top rated / Under $250K / Gated / Waterfront)
  "discovery_pill.all":          { en: "All",          es: "Todas" },
  "discovery_pill.heading":      { en: "Explore by",   es: "Explora por" },

  // USP row — three columns under the category grid.
  "usp.row_heading":             { en: "Why Pulpo",    es: "Por qué Pulpo" },
  "usp.col_1_title":             { en: "10 best deals, every 2 weeks",
                                   es: "10 mejores tratos, cada 2 semanas" },
  "usp.col_1_body":              { en: "Matched to your location, budget, and size. Delivered to your inbox.",
                                   es: "Filtrados por ubicación, presupuesto y tamaño. Directo a tu correo." },
  "usp.col_2_title":             { en: "Full catalogue, anytime",
                                   es: "Catálogo completo, cuando quieras" },
  "usp.col_2_body":              { en: "Browse, sort, and save hundreds of vetted beach and lake properties.",
                                   es: "Explora, ordena y guarda cientos de propiedades verificadas de playa y lago." },
  "usp.col_3_title":             { en: "Built by locals",
                                   es: "Hecho por locales" },
  "usp.col_3_body":              { en: "We live on this coast. We know which listings are real and which are overpriced.",
                                   es: "Vivimos en esta costa. Sabemos qué anuncios son reales y cuáles están sobrevalorados." },

  // Star pill ARIA — "4.5 stars out of 5"
  "star_pill.aria":              { en: "{value} stars out of 5",
                                   es: "{value} estrellas de 5" },

  // Shelf rail ARIA wrapper (screen-reader landmark name).
  "shelf_rail.aria":             { en: "Activity shelves",
                                   es: "Estantes de actividad" },

  // ── Homepage v2 (redesign) ───────────────────────────────────────
  // Copy for the redesigned homepage. The previous new_hero.* / proof_row.* /
  // category_grid.* / discovery_pill.* / usp.* keys above are no longer
  // read by any homepage component — kept in this table to avoid breaking
  // imports anywhere unforeseen, and because they're cheap to keep.
  "home.header.cta":             { en: "Try a free month",
                                   es: "Prueba un mes gratis" },
  "home.header.signin":          { en: "Sign in",
                                   es: "Inicia sesión" },
  "home.header.nav.lake":        { en: "Lake",
                                   es: "Lago" },
  "home.header.nav.beach":       { en: "Beach",
                                   es: "Playa" },
  "home.header.nav.how":         { en: "How it works",
                                   es: "Cómo funciona" },
  "home.header.nav.pricing":     { en: "Pricing",
                                   es: "Precios" },
  "home.header.open_menu":       { en: "Open menu",
                                   es: "Abrir menú" },
  "home.header.close_menu":      { en: "Close menu",
                                   es: "Cerrar menú" },
  "home.header.nav_aria":        { en: "Primary",
                                   es: "Principal" },
  "home.header.mobile_nav_aria": { en: "Mobile primary",
                                   es: "Principal móvil" },

  // Homepage v3 hero. `home.hero.coords` was removed when the top-right
  // coords label was replaced by the LIVE NOW counter card. The pre-label
  // eyebrow is split — "SCANNING " + "{n} SOURCES" (clay span at the call
  // site) + " EVERY 90 SECONDS" — so the count substitution does not need
  // a placeholder walk inside a styled span. {n} resolves at runtime from
  // /data/last_updated.json source_status; falls back to last-cached, then
  // to SOURCE_COUNT_FALLBACK in heroConfig.
  "home.hero.eyebrow_before":    { en: "SCANNING ",
                                   es: "REVISANDO " },
  "home.hero.eyebrow_sources":   { en: "{n} SOURCES",
                                   es: "{n} FUENTES" },
  "home.hero.eyebrow_after":     { en: " EVERY 90 SECONDS",
                                   es: " CADA 90 SEGUNDOS" },
  "home.hero.h1.before":         { en: "Every beach and lake property in El Salvador,",
                                   es: "Cada propiedad de playa y lago en El Salvador," },
  "home.hero.h1.italic":         { en: "ranked.",
                                   es: "ordenadas." },
  "home.hero.subhead":           { en: "We scan every site, rank every beach and lake listing by value, and deliver the 10 best to your inbox every two weeks.",
                                   es: "Revisamos cada sitio, ordenamos cada anuncio de playa y lago por valor y enviamos los 10 mejores a tu correo cada dos semanas." },
  "home.hero.cta_primary":       { en: "Try a free month",
                                   es: "Prueba un mes gratis" },
  "home.hero.cta_secondary":     { en: "See this week's top 10",
                                   es: "Ver el top 10 de la semana" },
  "home.hero.microcopy":         { en: "$5/month after · cancel anytime",
                                   es: "$5/mes luego · cancela cuando quieras" },
  // Live counter card (top-right, hides <768px).
  "home.hero.counter_live":      { en: "LIVE NOW",
                                   es: "EN VIVO" },
  "home.hero.counter_template":  { en: "{count} listings · {sources} sources",
                                   es: "{count} propiedades · {sources} fuentes" },
  "home.hero.preview.label":     { en: "Pulpo weekly",
                                   es: "Pulpo semanal" },
  "home.hero.preview.headline":  { en: "Top 10 · updating live",
                                   es: "Top 10 · en directo" },
  "home.hero.preview.live":      { en: "LIVE",
                                   es: "EN VIVO" },
  "home.hero.preview.sr":        { en: "Preview: top 10 listings ranked from A+ to C-",
                                   es: "Vista previa: 10 mejores anuncios, de A+ a C-" },
  // Just In pill — clay-orange floating card that pops on each leaderboard cycle.
  "home.hero.just_in_label":     { en: "JUST IN",
                                   es: "RECIÉN" },
  "home.hero.just_in_position":  { en: "→ #{n}",
                                   es: "→ #{n}" },
  "home.hero.off_the_board":     { en: "off the board",
                                   es: "fuera del top 10" },
  "home.hero.just_in_aria":      { en: "Just in: {name} — sign up to see more",
                                   es: "Recién: {name} — regístrate para ver más" },
  "home.hero.new_badge":         { en: "NEW",
                                   es: "NUEVO" },

  "home.featured.eyebrow":       { en: "FEATURED DEAL",
                                   es: "OFERTA DESTACADA" },
  "home.featured.title":         { en: "3-bed lakefront at Lago de Coatepeque, 23% under comps.",
                                   es: "Casa de 3 habitaciones frente al Lago de Coatepeque, 23% bajo comparables." },
  "home.featured.body":          { en: "0.4 acre, private dock, listed two days ago and already scored A+ by our comp engine.",
                                   es: "0.16 ha, muelle privado, publicada hace dos días y ya con A+ de nuestro motor de comparables." },
  "home.featured.cta_aria":      { en: "Open featured deal",
                                   es: "Ver oferta destacada" },
  "home.featured.zone":          { en: "Lago de Coatepeque",
                                   es: "Lago de Coatepeque" },
  "home.featured.tag":           { en: "A+ deal",
                                   es: "A+ trato" },
  "home.featured.discount":      { en: "−23%",
                                   es: "−23%" },
  "home.featured.stat_asking":   { en: "Asking",
                                   es: "Precio" },
  "home.featured.stat_value":    { en: "Est. value",
                                   es: "Valor estimado" },
  "home.featured.stat_days":     { en: "Days on market",
                                   es: "Días en venta" },

  "home.usp.eyebrow":            { en: "FOR SUBSCRIBERS ONLY",
                                   es: "SOLO PARA SUSCRIPTORES" },
  "home.usp.h2":                 { en: "What your $5 a month buys you.",
                                   es: "Lo que te trae $5 al mes." },
  "home.usp.card1.title":        { en: "10 best deals,\never 2 weeks",
                                   es: "10 mejores tratos,\ncada 2 semanas" },
  "home.usp.card1.body":         { en: "Matched to your location, budget, and size. Delivered to your inbox.",
                                   es: "Filtrados por ubicación, presupuesto y tamaño. Directo a tu correo." },
  "home.usp.card2.title":        { en: "Full catalogue,\nanytime",
                                   es: "Catálogo completo,\ncuando quieras" },
  "home.usp.card2.body":         { en: "Browse, sort, and save hundreds of vetted beach and lake properties.",
                                   es: "Explora, ordena y guarda cientos de propiedades verificadas de playa y lago." },
  "home.usp.card3.title":        { en: "Built by locals",
                                   es: "Hecho por locales" },
  "home.usp.card3.body":         { en: "We live on this coast. We know which listings are real and which are overpriced.",
                                   es: "Vivimos en esta costa. Sabemos qué anuncios son reales y cuáles están sobrevalorados." },

  "home.shoreline.h2":           { en: "Pick your shoreline.",
                                   es: "Elige tu costa." },
  "home.shoreline.lake.label":   { en: "Lake",
                                   es: "Lago" },
  "home.shoreline.beach.label":  { en: "Beach",
                                   es: "Playa" },
  "home.shoreline.subtitle":     { en: "Gated community & independent properties",
                                   es: "Comunidades cerradas y propiedades independientes" },
  "home.shoreline.cta_aria":     { en: "Browse {shoreline} properties",
                                   es: "Ver propiedades de {shoreline}" },

  "home.shelf.top10.h2":         { en: "Top 10 deals right now",
                                   es: "Top 10 tratos ahora mismo" },
  "home.shelf.dropsHeading":     { en: "Price drops",
                                   es: "Bajaron de precio" },
  "home.shelf.dropsCount":       { en: "↘ {n} cuts",
                                   es: "↘ {n} bajadas" },
  "home.shelf.newHeading":       { en: "New this week",
                                   es: "Nuevos esta semana" },
  "home.shelf.newCount":         { en: "✦ {n} added",
                                   es: "✦ {n} añadidos" },
  "home.shelf.view_all":         { en: "View all →",
                                   es: "Ver todas →" },
  "home.shelf.scroll_hint":      { en: "○ ○ ○  scroll for {n} more",
                                   es: "○ ○ ○  desliza para {n} más" },
  "home.shelf.aria":             { en: "Homepage activity shelves",
                                   es: "Estantes de actividad" },

  "home.badge.today":            { en: "today",
                                   es: "hoy" },
  "home.badge.days_ago":         { en: "{n} days ago",
                                   es: "hace {n} días" },

  // ── Browse filters — Phase 5B (new IA axes on the FilterPanel) ─────
  "filter.master_category":      { en: "Beach or lake",   es: "Playa o lago" },
  "filter.master.beach":         { en: "Beach",           es: "Playa" },
  "filter.master.lake":          { en: "Lake",            es: "Lago" },
  "filter.subcategory":          { en: "Property type",   es: "Tipo de propiedad" },
  "filter.sub.homes":            { en: "Homes",           es: "Casas" },
  "filter.sub.condos":           { en: "Condos",          es: "Condominios" },
  "filter.sub.land":             { en: "Land",            es: "Terrenos" },
  "filter.discovery_tags":       { en: "Quick filters",   es: "Filtros rápidos" },
  "filter.tag.top_rated":        { en: "★ Top rated",     es: "★ Mejor valorados" },
  "filter.tag.under_250k":       { en: "Under $250K",     es: "Menos de $250K" },
  "filter.tag.gated":            { en: "Gated",           es: "Privado / cerrado" },
  "filter.tag.waterfront":       { en: "Waterfront",      es: "Frente al agua" },

  // Sort dropdown — rewrite-canonical labels (existing sort keys
  // stay; only the visible label changes so saved URLs still work).
  "sort.highest_value":          { en: "Highest value",   es: "Mejor valor" },
  "sort.lowest_price":           { en: "Lowest price",    es: "Menor precio" },
  "sort.newest":                 { en: "Newest",          es: "Más recientes" },
  "sort.largest_plot":           { en: "Largest plot",    es: "Lote más grande" },

  // Map view placeholder — disabled toggle next to cards/table view.
  "view.map_coming_soon":        { en: "Map (coming soon)",
                                   es: "Mapa (próximamente)" },

  // Pill rail
  "pill.all":                { en: "All",                 es: "Todos" },

  // Card
  // Pulpo's catalog now includes houses + lots, not just plots of
  // land. Spanish copy uses "propiedades" (inclusive) rather than
  // "terrenos" (which would translate "listing" → "plot of land").
  // Keep "terreno" only where the string is genuinely about parcels
  // of land specifically — see `type.raw`, `filter.feature.flat`.
  "card.listings_count":     { en: "listings",            es: "propiedades" },
  "card.in":                 { en: "in",                  es: "en" },
  "card.see_all":            { en: "See all",             es: "Ver todos" },
  "browse.in_country":       { en: "listings in El Salvador",    es: "propiedades en El Salvador" },
  "browse.clear_category":   { en: "Clear category",             es: "Quitar categoría" },
  "card.listed_days_ago":    { en: "Listed {n} days ago", es: "Publicado hace {n} días" },
  "card.listed_1_month":     { en: "Listed 1 month ago",  es: "Publicado hace 1 mes" },
  "card.listed_n_months":    { en: "Listed {n} months ago", es: "Publicado hace {n} meses" },

  // Land types
  "type.residential":        { en: "Residential",         es: "Residencial" },
  "type.agricultural":       { en: "Agricultural",        es: "Agrícola" },
  "type.commercial":         { en: "Commercial",          es: "Comercial" },
  "type.tourist":            { en: "Tourist",             es: "Turístico" },
  "type.mixed":              { en: "Mixed Use",           es: "Uso Mixto" },
  "type.raw":                { en: "Raw Land",            es: "Terreno bruto" },

  // Badges
  "badge.price_drop":        { en: "Price drop",          es: "Bajó de precio" },
  "badge.off_market":        { en: "Off-market",          es: "Off-market" },
  "badge.new":               { en: "New",                 es: "Nuevo" },
  "badge.build_ready":       { en: "Build-ready",         es: "Listo para construir" },
  "badge.motivated":         { en: "Motivated seller",    es: "Vendedor motivado" },
  "badge.ocean_view":        { en: "Ocean view",          es: "Vista al mar" },
  "badge.flat":              { en: "Flat",                es: "Plano" },

  // Filter / browse
  "filter.title":            { en: "Filters",             es: "Filtros" },
  "filter.clear":            { en: "Clear all",           es: "Limpiar todo" },
  "filter.zone":             { en: "Zone",                es: "Zona" },
  "filter.price":            { en: "Price",               es: "Precio" },
  // Filter values cover residential / agricultural / commercial /
  // tourist / mixed / raw — broad use categories, not strictly
  // plots-of-land. Renamed to "Property type" / "Tipo de propiedad"
  // to match Pulpo's broadened scope (houses + lots, not just land).
  // The i18n key keeps `land_type` for back-compat with the filter
  // state shape — only the user-visible label changes.
  "filter.land_type":        { en: "Property type",       es: "Tipo de propiedad" },
  "filter.size":             { en: "Size",                es: "Tamaño" },
  "filter.features":         { en: "Key features",        es: "Características" },
  "filter.infrastructure":   { en: "Infrastructure",      es: "Infraestructura" },
  "filter.status":           { en: "Listing status",      es: "Estado" },
  "filter.readiness":        { en: "Build readiness",     es: "Listo para construir" },

  // Detail
  "detail.back":             { en: "Back to results",     es: "Volver a resultados" },
  "detail.reasons":          { en: "Reasons to buy",      es: "Razones para comprar" },
  "detail.key_facts":        { en: "Key facts",           es: "Datos clave" },
  "detail.location":         { en: "Location",            es: "Ubicación" },
  "detail.price":            { en: "Price",               es: "Precio" },
  "detail.size":             { en: "Size",                es: "Tamaño" },
  "detail.days_listed":      { en: "Days listed",         es: "Días publicado" },

  // Saved — page title matches the nav-bar label ("Favorites"). The
  // URL is still /saved (Wave 3b renames it). Past-tense "saved"
  // strings (toast.saved, etc.) stay as-is — they're verbs, not the
  // page brand.
  "saved.title":             { en: "Favorites",           es: "Favoritos" },
  "saved.empty.title":       { en: "Your saved listings will appear here",
                               es: "Tus propiedades guardadas aparecerán aquí" },
  "saved.empty.body":        { en: "Browse listings and tap ♡ to save the ones that interest you.",
                               es: "Explora las propiedades y toca ♡ para guardar las que te interesen." },

  // Toasts
  "toast.saved":             { en: "Saved to your shortlist", es: "Guardado en tu lista" },
  "toast.removed":           { en: "Removed from saved",   es: "Eliminado de guardados" },
  "toast.welcome":           { en: "✓ Welcome! Your account is ready.",
                               es: "✓ ¡Bienvenido! Tu cuenta está lista." },
  "toast.logged_out":        { en: "Logged out",           es: "Sesión cerrada" },

  // Footer
  "footer.tagline":          { en: "Properties worth wanting in El Salvador.",
                               es: "Propiedades que valen la pena en El Salvador." },
  "footer.country_badge":    { en: "Listings in El Salvador",
                               es: "Propiedades en El Salvador" },

  // Find Your Style carousel — deleted in the rewrite cutover (Phase 9)
  // with the legacy StyleCarousel component. Keys removed.

  // Live header stats (PR-4c)
  "stats.sources":           { en: "sources",  es: "fuentes" },
  "stats.listings":          { en: "listings", es: "propiedades" },
  "stats.updated":           { en: "updated",  es: "actualizado" },
  "stats.info_label":        { en: "Pulpo data freshness", es: "Frescura de los datos de Pulpo" },

  // Units toggle (PR-4c) — vrs² is the Salvadoran traditional area unit.
  "units.label":             { en: "Show areas in", es: "Mostrar áreas en" },
  "units.m2":                { en: "m²",       es: "m²" },
  "units.vrs2":              { en: "vrs²",     es: "vrs²" },
  "units.aria":              { en: "Choose area unit", es: "Elegir unidad de área" },

  // ===== PR-6 batch: i18n coverage of high-traffic surfaces =====

  // Sort options (Browse + Saved)
  "sort.recent":             { en: "Most recent",                   es: "Más recientes" },
  "sort.price_asc":          { en: "Price: low to high",            es: "Precio: menor a mayor" },
  "sort.price_desc":         { en: "Price: high to low",            es: "Precio: mayor a menor" },
  "sort.size_desc":          { en: "Size: largest first",           es: "Tamaño: mayor primero" },
  "sort.ppm_asc_suffix":     { en: "{suffix}: lowest first",        es: "{suffix}: menor primero" },
  "sort.days_asc":           { en: "Days listed: fewest first",     es: "Días publicado: menos primero" },
  "sort.ready_desc":         { en: "Most build-ready",              es: "Más listo para construir" },
  "sort.stars_desc":         { en: "Investment score: highest",     es: "Puntaje de inversión: mayor" },
  "sort.composite_desc":     { en: "Best match (your weights)",     es: "Mejor coincidencia (tus pesos)" },
  "sort.recently_saved":     { en: "Recently saved",                es: "Guardados recientemente" },

  // Browse view toggles + chips
  "view.cards":              { en: "Card view",                     es: "Vista en tarjetas" },
  "view.table":              { en: "Table view",                    es: "Vista en tabla" },
  "view.filters":            { en: "Filters",                       es: "Filtros" },

  // PillRail
  "pill.scroll_left":        { en: "Scroll left",                   es: "Desplazar a la izquierda" },
  "pill.scroll_right":       { en: "Scroll right",                  es: "Desplazar a la derecha" },

  // Discover layout toggle
  "layout.aria":             { en: "Discover layout",               es: "Diseño de Descubrir" },
  "layout.magazine":         { en: "Magazine",                      es: "Revista" },
  "layout.standard":         { en: "Standard",                      es: "Estándar" },
  "shelf.show_less":         { en: "Show less",                     es: "Mostrar menos" },

  // Detail-panel section labels (additions to existing detail.* keys)
  "detail.zone_area":        { en: "{zone} area",                   es: "Zona de {zone}" },
  "detail.km_to_beach":      { en: "{n}km to nearest beach",        es: "{n}km a la playa más cercana" },
  "detail.km_to_beach_approx": { en: "ca. {n}km to nearest beach",  es: "aprox. {n}km a la playa más cercana" },
  "detail.on_beach":         { en: "On beach",                      es: "En la playa" },
  "detail.km_to_airport":    { en: "{n}km to nearest airport",      es: "{n}km al aeropuerto más cercano" },
  "detail.km_to_airport_approx": { en: "ca. {n}km to nearest airport", es: "aprox. {n}km al aeropuerto más cercano" },
  "detail.km_to_town":       { en: "{n}km to nearest town",         es: "{n}km al pueblo más cercano" },
  "detail.km_to_town_approx": { en: "ca. {n}km to nearest town",    es: "aprox. {n}km al pueblo más cercano" },
  "detail.fact.road":        { en: "Road access",                   es: "Acceso vial" },
  // Per-enum-value labels for road_access_type — adapter emits one of
  // {paved, gravel, dirt, unknown}. Previously the FE called
  // `capitalize(value)` which produced "Paved" in Spanish too. Each
  // enum value gets its own row so the FE can do a typed lookup.
  "detail.fact.road.paved":  { en: "Paved",                         es: "Pavimentado" },
  "detail.fact.road.gravel": { en: "Gravel",                        es: "Ripio" },
  "detail.fact.road.dirt":   { en: "Dirt",                          es: "Tierra" },
  "detail.fact.water":       { en: "Water supply",                  es: "Suministro de agua" },
  "detail.fact.water_on":    { en: "On site",                       es: "En sitio" },
  "detail.fact.electricity": { en: "Electricity",                   es: "Electricidad" },
  "detail.fact.power_at":    { en: "At boundary",                   es: "En el lindero" },
  "detail.fact.topography":  { en: "Topography",                    es: "Topografía" },
  "detail.fact.flat_yes":    { en: "Mostly flat",                   es: "Mayormente plano" },
  "detail.fact.flat_no":     { en: "Sloped",                        es: "Inclinado" },
  "detail.fact.beachfront_tier": { en: "Beachfront tier",           es: "Nivel de playa" },
  // Per-enum-value labels for beachfront_tier — same fix as
  // detail.fact.road.* above. Backend emits {on_beach, walk_to_beach,
  // near_beach}; FE was rendering the underscored slug capitalized.
  "detail.fact.beachfront_tier.on_beach":      { en: "On the beach",      es: "Frente al mar" },
  "detail.fact.beachfront_tier.walk_to_beach": { en: "Walk to the beach", es: "A pasos del mar" },
  "detail.fact.beachfront_tier.near_beach":    { en: "Near the beach",    es: "Cerca de la playa" },
  "detail.fact.ocean_view":  { en: "Ocean view",                    es: "Vista al mar" },
  "detail.fact.yes":         { en: "Yes",                           es: "Sí" },
  "detail.fact.zoning":      { en: "Zoning",                        es: "Zonificación" },
  "detail.fact.photos":      { en: "Photos",                        es: "Fotos" },
  "detail.signup_to_view_source": { en: "Sign up free to view source listing",
                               es: "Crea cuenta gratis para ver la fuente" },
  "detail.view_on":          { en: "View on {source}",              es: "Ver en {source}" },
  "detail.off_market_inquire": { en: "Off-market — see Plans to inquire",
                               es: "Off-market — consulta los planes" },
  "detail.save":             { en: "Save",                          es: "Guardar" },
  "detail.saved":            { en: "Saved",                         es: "Guardado" },
  "detail.signup_more_reasons_one": { en: "Sign up to see 1 more reason we picked this listing",
                               es: "Crea cuenta para ver 1 razón más por la que elegimos esta propiedad" },
  "detail.signup_more_reasons_other": { en: "Sign up to see {n} more reasons we picked this listing",
                               es: "Crea cuenta para ver {n} razones más por las que elegimos esta propiedad" },
  // Free signed-in users: same gated row, but the CTA goes to
  // Stripe checkout instead of the signup modal. Pro users hide
  // the row entirely.
  "detail.upgrade_more_reasons_one":   { en: "Upgrade to Pro to see 1 more reason we picked this listing",
                                          es: "Contrata Pro para ver 1 razón más por la que elegimos esta propiedad" },
  "detail.upgrade_more_reasons_other": { en: "Upgrade to Pro to see {n} more reasons we picked this listing",
                                          es: "Contrata Pro para ver {n} razones más por las que elegimos esta propiedad" },
  // Source-listing link is Pro-only (PR after this one).
  // Anonymous → signup + chained checkout. Free signed-in → direct
  // checkout. Pro → outbound link (no prompt).
  "detail.signup_upgrade_to_view_source": { en: "Sign up + upgrade to Pro to view source listing",
                                             es: "Crea cuenta y contrata Pro para ver el anuncio original" },
  "detail.upgrade_to_view_source":         { en: "Upgrade to Pro to view source listing",
                                              es: "Contrata Pro para ver el anuncio original" },
  "detail.signup_more_photos": { en: "Sign up for {n}+ photos",
                               es: "Crea cuenta para ver {n}+ fotos" },
  "detail.more_photos":      { en: "+{n} photos",                   es: "+{n} fotos" },
  "detail.signup_for_pin":   { en: "Sign up for precise pin",       es: "Crea cuenta para ver el pin exacto" },
  "detail.sold_banner.title": { en: "This listing has been sold or removed.",
                               es: "Esta propiedad fue vendida o retirada." },
  "detail.sold_banner.days": { en: "It was on the market for {n} days.",
                               es: "Estuvo en el mercado durante {n} días." },
  "detail.sold_banner.cta":  { en: "Browse similar listings in {zone} →",
                               es: "Ver propiedades similares en {zone} →" },
  "detail.paywall.title":    { en: "Off-market deal",               es: "Trato off-market" },
  "detail.paywall.body":     { en: "This listing isn't public anywhere else. Pulpo Pro members get direct access plus broker intros.",
                               es: "Esta propiedad no es pública en ningún otro lugar. Los miembros Pulpo Pro tienen acceso directo y conexiones con corredores." },
  "detail.paywall.see_plans": { en: "See plans",                    es: "Ver planes" },
  "detail.paywall.have_account": { en: "I have an account",         es: "Ya tengo cuenta" },
  "detail.gallery.open":     { en: "Open photo gallery",            es: "Abrir galería de fotos" },
  "detail.gallery.open_n":   { en: "Open photo {n}",                es: "Abrir foto {n}" },
  "detail.gallery.locked_aria": { en: "Sign up to unlock more photos",
                               es: "Crea cuenta para desbloquear más fotos" },

  // Lightbox
  "lightbox.close":          { en: "Close photo gallery (Escape)",  es: "Cerrar galería (Escape)" },
  "lightbox.prev":           { en: "Previous photo (Left arrow)",   es: "Foto anterior (Flecha izquierda)" },
  "lightbox.next":           { en: "Next photo (Right arrow)",      es: "Foto siguiente (Flecha derecha)" },
  "lightbox.aria_label":     { en: "Photo {n} of {total}",          es: "Foto {n} de {total}" },

  // Misc
  "common.close":            { en: "Close",                         es: "Cerrar" },
  "common.scroll_left":      { en: "Scroll left",                   es: "Desplazar a la izquierda" },
  "common.scroll_right":     { en: "Scroll right",                  es: "Desplazar a la derecha" },
  "common.retry":            { en: "Retry",                         es: "Reintentar" },
  "locale.toggle_aria":      { en: "Language",                      es: "Idioma" },

  // Clerk handoff intro modal — shown before Pulpo hands authentication
  // off to the Clerk hosted modal. Clerk's branding is unfamiliar to
  // most users; without this they'd see a "share info with Clerk"
  // prompt with no context for who Clerk is. The intro shows once per
  // device (localStorage `pulpo-clerk-intro-seen`); subsequent sign-ins
  // skip straight to Clerk.
  "auth.clerk_intro.title":  { en: "Sign in securely with Clerk",
                               es: "Inicia sesión de forma segura con Clerk" },
  "auth.clerk_intro.body":   { en: "Pulpo uses Clerk to handle sign-in and account security. Clerk is a trusted authentication provider — your password and session are managed by them, never stored on Pulpo's servers.",
                               es: "Pulpo usa Clerk para gestionar el inicio de sesión y la seguridad de tu cuenta. Clerk es un proveedor de autenticación confiable — tu contraseña y sesión las gestiona Clerk, nunca se almacenan en los servidores de Pulpo." },
  "auth.clerk_intro.cta":    { en: "Continue to Clerk",
                               es: "Continuar con Clerk" },
  "auth.clerk_intro.cancel": { en: "Cancel",                         es: "Cancelar" },
  "auth.clerk_intro.dont_show": { en: "Don't show this next time",   es: "No mostrar la próxima vez" },
  "auth.clerk_provider_note":   { en: "Powered by Clerk — secure authentication.",
                                  es: "Con tecnología de Clerk — autenticación segura." },

  // ListingCard aria-labels (heart save/remove + photo carousel nav).
  // Were hardcoded English; surfaced by the i18n sweep tied to the
  // road_access "Paved"/"Pavimentado" report.
  "card.heart.save":         { en: "Save listing",                  es: "Guardar propiedad" },
  "card.heart.remove":       { en: "Remove from saved",             es: "Quitar de guardados" },
  "card.photo.prev":         { en: "Previous photo",                es: "Foto anterior" },
  "card.photo.next":         { en: "Next photo",                    es: "Foto siguiente" },

  // DataFetchFailed — hard error UI shown when /data/ranked.json
  // doesn't load. Was full English; same i18n sweep.
  "data_fetch_failed.title": { en: "We couldn't load the listings.",
                               es: "No pudimos cargar las propiedades." },
  "data_fetch_failed.body":  { en: "This is on us. The data feed didn't respond — try again in a moment.",
                               es: "Es de nuestro lado. El feed de datos no respondió — inténtalo en un momento." },

  // Newsletter CTA — deleted in the rewrite cutover (Phase 9) with the
  // legacy NewsletterCTA component. The new homepage's hero email
  // form (Hero.jsx) reads the new_hero.* keys higher up in this file.

  // Plans page — full string set. PRO_PRICE_USD_PER_MONTH lives in
  // pages.jsx and mirrors automation/stripe_setup.mjs.
  "plans.head.title":        { en: "Pick a plan that fits how you invest.",
                               es: "Elige un plan que se ajuste a cómo inviertes." },
  "plans.head.subtitle":     { en: "Pulpo is free to browse. Upgrade for unlimited details, off-market access, and weekly alerts.",
                               es: "Pulpo es gratis para explorar. Contrata Pro para detalles ilimitados, acceso off-market y alertas semanales." },
  // Free tier
  "plans.free.name":         { en: "Free",                    es: "Gratis" },
  "plans.free.tag":          { en: "Browse the catalogue",    es: "Explora el catálogo" },
  "plans.free.feat.browsing":         { en: "Unlimited card browsing",      es: "Exploración ilimitada de tarjetas" },
  "plans.free.feat.detail_views":     { en: "8 detail views per month",     es: "8 vistas de detalle al mes" },
  "plans.free.feat.saves_cap":        { en: "Save up to 10 listings",       es: "Guarda hasta 10 propiedades" },
  // The Free plan card "what Pro adds" mirrors live at pro.usp.*.short
  // (used with the featMuted variant). The two old `_excluded` keys are
  // gone with the rest of the deprecated Pro USP copy.
  "plans.free.cta_current":  { en: "Your plan",                es: "Tu plan" },
  "plans.free.cta_signup":   { en: "Sign up free",             es: "Crear cuenta gratis" },
  // Pro tier
  "plans.pro.ribbon":        { en: "Most popular",             es: "Más popular" },
  "plans.pro.name":          { en: "Pulpo Pro",                es: "Pulpo Pro" },
  "plans.pro.per_month":     { en: "/month",                   es: "/mes" },
  "plans.pro.tag":           { en: "Billed monthly",           es: "Facturación mensual" },
  // Listings remain in USD (El Salvador's currency); the Pro
  // subscription is billed in EUR via the European Stripe entity.
  // This footnote prevents "why is my plan in euros?" confusion.
  "plans.pro.currency_note": { en: "Listings are priced in USD; Pulpo Pro is billed in EUR.",
                               es: "Las propiedades aparecen en USD; Pulpo Pro se cobra en EUR." },
  // Pro feature list — PlansPage now uses the three canonical `pro.usp.*.headline`
  // keys above, plus this single "Everything in Free" caboose. The five legacy
  // bullets (unlimited_details, off_market, newsletter, unlimited_saves,
  // price_alerts) were removed in PR-B.4a — their content is covered by the
  // three canonical USPs (alerts covers newsletter + price_alerts; browse
  // covers unlimited_details; links covers off_market access).
  "plans.pro.feat.everything_in_free": { en: "Everything in Free",        es: "Todo lo del plan Gratis" },
  // Agency tier (hidden by default — see SHOW_AGENCY_PLAN in pages.jsx).
  "plans.agency.name":       { en: "Agency",                   es: "Agencia" },
  "plans.agency.tag":        { en: "For investor groups & brokers",
                               es: "Para grupos de inversión y corredores" },
  "plans.agency.feat.everything_in_pro": { en: "Everything in Pro",       es: "Todo lo del plan Pro" },
  "plans.agency.feat.team_seats":        { en: "5 team seats",            es: "5 asientos de equipo" },
  "plans.agency.feat.shared_lists":      { en: "Shared saved lists",      es: "Listas guardadas compartidas" },
  "plans.agency.feat.csv_export":        { en: "CSV export",              es: "Exportación a CSV" },
  "plans.agency.feat.priority_off_market": { en: "Priority off-market intros",
                                             es: "Acceso prioritario a off-market" },
  "plans.agency.cta_contact": { en: "Contact sales",           es: "Contactar ventas" },
  // Stripe-wired Pro CTA + error toast.
  "plans.upgrade_pro_cta":   { en: "Upgrade — €{price}/month",
                               es: "Contrata Pro — €{price}/mes" },
  "plans.checkout_error_toast": { en: "Couldn't start checkout — please try again.",
                                  es: "No pudimos iniciar el pago — inténtalo de nuevo." },
  "plans.checkout_auth_mismatch": { en: "Couldn't verify your session. Please log out and back in, then try again.",
                                    es: "No pudimos verificar tu sesión. Cierra sesión y vuelve a entrar." },
  "upgrade.success_toast":   { en: "You're now on Pulpo Pro. Enjoy!",
                               es: "¡Listo! Ahora tienes Pulpo Pro." },
  "upgrade.cancelled_toast": { en: "Checkout cancelled — no changes to your plan.",
                               es: "Pago cancelado — tu plan no cambió." },
  // Browse — Load more pagination
  "browse.load_more":        { en: "Load more ({n} remaining)",     es: "Ver más ({n} restantes)" },

  // Consent banner (GDPR)
  "consent.aria":            { en: "Cookie consent",                es: "Consentimiento de cookies" },
  "consent.body":            { en: "Pulpo uses analytics cookies to improve the site. No third-party ads.",
                               es: "Pulpo usa cookies analíticas para mejorar el sitio. Sin anuncios de terceros." },
  "consent.decline":         { en: "Decline",                       es: "Rechazar" },
  "consent.accept":          { en: "Accept",                        es: "Aceptar" },

  // Saved page CTA
  "saved.browse_cta":        { en: "Browse listings →",             es: "Ver propiedades →" },

  // Filter chip labels (PR-6)
  "filter.photos":           { en: "Photos",                        es: "Fotos" },
  "filter.size_min":         { en: "Min: {n} ha",                   es: "Mín: {n} ha" },
  "filter.show_count":       { en: "Show {n} listings",             es: "Ver {n} propiedades" },
  "filter.feature.beachfront":   { en: "Beachfront",     es: "Frente a la playa" },
  "filter.feature.ocean_view":   { en: "Ocean View",     es: "Vista al mar" },
  "filter.feature.mountain_view": { en: "Mountain View", es: "Vista a la montaña" },
  "filter.feature.flat":         { en: "Flat Land",      es: "Terreno plano" },
  "filter.feature.water_body":   { en: "Water Feature",  es: "Cuerpo de agua" },
  "filter.infra.water":      { en: "Water",                         es: "Agua" },
  "filter.infra.power":      { en: "Electricity",                   es: "Electricidad" },
  "filter.infra.paved":      { en: "Paved Road",                    es: "Camino pavimentado" },
  "filter.infra.sewage":     { en: "Sewage",                        es: "Drenaje" },
  "filter.status.new":       { en: "New",                           es: "Nuevo" },
  "filter.status.price_drop": { en: "Price drop",                   es: "Bajó de precio" },
  "filter.status.off_market": { en: "Off-market",                   es: "Off-market" },
  "filter.status.motivated":  { en: "Motivated seller",             es: "Vendedor motivado" },
  "filter.readiness.0":      { en: "Any",                           es: "Cualquiera" },
  "filter.readiness.1":      { en: "Basic",                         es: "Básico" },
  "filter.readiness.2":      { en: "Some",                          es: "Algo" },
  "filter.readiness.3":      { en: "Most",                          es: "Mayoría" },
  "filter.readiness.4":      { en: "Fully ready",                   es: "Totalmente listo" },
  "filter.photos_all":       { en: "All listings",                  es: "Todas las propiedades" },
  "filter.photos_with":      { en: "With photos",                   es: "Con fotos" },
  "filter.photos_none":      { en: "No photos",                     es: "Sin fotos" },

  // Account area (A.3)
  "nav.account":             { en: "Account",                       es: "Cuenta" },
  // Wave 3a: button navigates to `home` route (account.jsx:122). After
  // the nav rename "Discover" labels /browse, so this label moved to
  // "Home" to match the actual destination.
  "account.back":            { en: "← Back to Home",                es: "← Volver al Inicio" },
  "account.profile":         { en: "Profile",                       es: "Perfil" },
  "account.notifications":   { en: "Notifications",                 es: "Notificaciones" },
  "account.subscription":    { en: "Manage Subscription",           es: "Suscripción" },
  "account.security":        { en: "Security",                      es: "Seguridad" },
  "account.profile.name":    { en: "Full name",                     es: "Nombre completo" },
  "account.profile.email":   { en: "Email address",                 es: "Correo electrónico" },
  "account.profile.photo":   { en: "Profile photo",                 es: "Foto de perfil" },
  "account.profile.upload_photo": { en: "Upload photo",              es: "Subir foto" },
  "account.profile.name_placeholder": { en: "Your name",              es: "Tu nombre" },
  "account.profile.country": { en: "Country / region",              es: "País / región" },
  "account.profile.country_placeholder": { en: "Type to search…",   es: "Escribe para buscar…" },
  "account.profile.lang":    { en: "Preferred language",            es: "Idioma preferido" },
  "account.profile.save":    { en: "Save changes",                  es: "Guardar cambios" },
  "account.profile.saved":   { en: "Changes saved.",                es: "Cambios guardados." },
  "account.profile.email_note": { en: "Email change requires verification.", es: "Cambiar el correo requiere verificación." },
  // Surfaced when an optimistic profile update (preferred categories,
  // future fields) fails to persist to Clerk and the UI rolls back.
  "account.profile.sync_failed": { en: "Couldn't save your preferences — please try again.",
                                    es: "No pudimos guardar tus preferencias — inténtalo de nuevo." },
  "account.notif.intro":     { en: "Choose what Pulpo sends you, and how.",
                               es: "Elige qué te envía Pulpo y cómo." },
  "account.notif.saved":     { en: "Preference saved.",             es: "Preferencia guardada." },

  // Pro-gated notification categories. Free users see the upsell card
  // below in place of these toggles.
  "account.notif.newsletter.title":  { en: "Weekly newsletter",
                                        es: "Boletín semanal" },
  "account.notif.newsletter.desc":   { en: "The main Pulpo digest — new listings, price drops, curated picks.",
                                        es: "El resumen principal de Pulpo — nuevos anuncios, bajadas de precio, selecciones curadas." },
  "account.notif.price_drops.title": { en: "Price drop alerts",
                                        es: "Alertas de bajada de precio" },
  "account.notif.price_drops.desc":  { en: "Email when a saved listing drops in price.",
                                        es: "Email cuando un anuncio guardado baja de precio." },
  "account.notif.new_in_zones.title":{ en: "New listings in saved zones",
                                        es: "Nuevos anuncios en zonas guardadas" },
  "account.notif.new_in_zones.desc": { en: "Get early notice when something new appears in areas you've explored.",
                                        es: "Entérate temprano cuando aparece algo nuevo en zonas que ya exploraste." },

  // Free for everyone — product news, not premium content.
  "account.notif.platform_updates.title": { en: "Platform updates",
                                             es: "Novedades de Pulpo" },
  "account.notif.platform_updates.desc":  { en: "Occasional product news and feature announcements.",
                                             es: "Noticias y novedades del producto, sin spam." },

  // Channels.
  "account.notif.channels":     { en: "Channels",  es: "Canales" },
  "account.notif.email":        { en: "Email",     es: "Email" },
  "account.notif.email_desc":   { en: "Always on — primary product delivery channel.",
                                  es: "Siempre activado — canal principal del producto." },
  "account.notif.required":     { en: "Required",  es: "Obligatorio" },
  "account.notif.whatsapp":     { en: "WhatsApp",  es: "WhatsApp" },
  "account.notif.whatsapp_desc":{ en: "Optional opt-in. Stores your number for future deal alerts.",
                                  es: "Opcional. Guarda tu número para alertas de oportunidades." },
  "account.notif.whatsapp_confirm": { en: "We'll send deal alerts to {number}. You can opt out anytime.",
                                       es: "Enviaremos alertas a {number}. Puedes desactivarlo cuando quieras." },

  // Newsletter frequency (Pro-only — only renders when newsletter is on).
  "account.notif.frequency":    { en: "Newsletter frequency", es: "Frecuencia del boletín" },
  "account.notif.freq_weekly":  { en: "Weekly",   es: "Semanal" },
  "account.notif.freq_biweekly":{ en: "Bi-weekly", es: "Quincenal" },
  "account.notif.unsub_note":   { en: "You can also unsubscribe from any email using the link at the bottom of each message.",
                                  es: "También puedes darte de baja desde el enlace al final de cada email." },

  // Preferred-category chip selector (PR-B). Rendered under the newsletter
  // toggle for Pro users; captures up to PREFERENCE_CATEGORIES_MAX picks
  // that the newsletter generator + future personalization read off
  // user.profile.preferred_categories. The vocabulary itself lives in
  // web/app/lib/categories.ts — see README-categories.md for lifecycle.
  "account.notif.pref_cat.heading": { en: "Category preferences",
                                      es: "Preferencias de categoría" },
  "account.notif.pref_cat.intro":   { en: "Tell us what kind of land you're looking for and we'll prioritise it across alerts, the weekly digest, and future personalisation. Leave all unselected to keep the unfiltered experience.",
                                      es: "Cuéntanos qué tipo de propiedad buscas y la priorizaremos en las alertas, el resumen semanal y la futura personalización. Déjalo todo sin seleccionar para mantener la experiencia sin filtros." },
  "account.notif.pref_cat.limit_hint": { en: "You can select up to {max} categories.",
                                          es: "Puedes seleccionar hasta {max} categorías." },
  // Chip labels. Keep these short — the chip rail is responsive and
  // long phrases force two-line wrap on 320px viewports.
  "account.notif.pref_cat.new_this_week":  { en: "New this week",
                                              es: "Nuevos esta semana" },
  "account.notif.pref_cat.price_drops":    { en: "Price drops",
                                              es: "Bajadas de precio" },
  "account.notif.pref_cat.beachfront":     { en: "Beachfront / near the beach",
                                              es: "Frente al mar / cerca de la playa" },
  "account.notif.pref_cat.water_features": { en: "Lakefront / near water",
                                              es: "Frente al lago / cerca del agua" },
  "account.notif.pref_cat.under_50k":      { en: "Under $50K",
                                              es: "Menos de $50.000" },
  "account.notif.pref_cat.under_100k":     { en: "$50K–$100K",
                                              es: "Entre $50.000 y $100.000" },

  // Pro upsell shown to free / anonymous users in this subsection.
  "account.notif.upsell.title": { en: "Get deal alerts with Pulpo Pro",
                                  es: "Recibe alertas con Pulpo Pro" },
  "account.notif.upsell.body":  { en: "Email alerts on saved listings, new listings in your zones, and the curated weekly digest are part of Pulpo Pro.",
                                  es: "Las alertas por email de anuncios guardados, los nuevos en tus zonas y el boletín semanal son parte de Pulpo Pro." },
  "account.notif.upsell.cta":   { en: "Upgrade to Pro",
                                  es: "Contrata Pro" },
  // Shared "Upgrade to Pro" button label — also used by the
  // Subscription-section free-tier CTA. Prefer this over duplicating
  // the literal in any new surface.
  "common.upgrade_to_pro_cta":  { en: "Upgrade to Pro",
                                  es: "Contrata Pro" },

  // Account → Security (Clerk-managed). Single CTA opens Clerk's
  // hosted UserProfile modal — that one modal covers everything we
  // used to fake locally (password, sessions, MFA, OAuth, deletion).
  "account.security.clerk.heading": { en: "Account & security",
                                       es: "Cuenta y seguridad" },
  "account.security.clerk.intro":   { en: "Manage your account through Clerk — change your password, control active sessions, set up two-factor auth, and link or unlink Google. To delete your account, use the same panel.",
                                       es: "Administra tu cuenta a través de Clerk — cambia tu contraseña, gestiona sesiones activas, activa la verificación en dos pasos y conecta o desconecta Google. Para eliminar tu cuenta, usa el mismo panel." },
  "account.security.clerk.feat.password":  { en: "Change password",                       es: "Cambiar contraseña" },
  "account.security.clerk.feat.sessions":  { en: "View and revoke active sessions",       es: "Ver y revocar sesiones activas" },
  "account.security.clerk.feat.mfa":       { en: "Enable two-factor authentication",      es: "Activar autenticación en dos pasos" },
  "account.security.clerk.feat.connected": { en: "Connect or disconnect Google / Apple",  es: "Conectar o desconectar Google / Apple" },
  "account.security.clerk.feat.delete":    { en: "Delete your account",                   es: "Eliminar tu cuenta" },
  "account.security.clerk.cta":     { en: "Open account & security",
                                       es: "Abrir cuenta y seguridad" },
  "account.security.clerk.loading": { en: "Loading…",
                                       es: "Cargando…" },
  "account.security.clerk.error":   { en: "Couldn't open account settings. Please try again.",
                                       es: "No pudimos abrir la configuración de cuenta. Inténtalo de nuevo." },
  "account.security.signout.heading": { en: "Sign out",   es: "Cerrar sesión" },
  "account.security.signout.intro":   { en: "Sign out of this browser. To sign out of every device, use the sessions panel above.",
                                         es: "Cierra sesión en este navegador. Para cerrar sesión en todos los dispositivos, usa el panel de sesiones de arriba." },
  "account.security.signout.cta":     { en: "Sign out",   es: "Cerrar sesión" },

  "account.sub.intro":       { en: "Your plan, billing history, and payment details — all in one place.",
                               es: "Tu plan, historial de pagos y detalles — todo en un solo lugar." },
  "account.sub.discover_nudge": { en: "Ready to keep exploring? Head back to Discover →",
                               es: "¿Listo para seguir explorando? Vuelve a Descubrir →" },
  "account.sub.manage_plan": { en: "Manage plan →",
                               es: "Gestionar plan →" },
  "account.sub.portal_error": { en: "We couldn't open the billing portal. Please try again.",
                               es: "No pudimos abrir el portal de facturación. Inténtalo de nuevo." },
  "account.sub.portal_no_customer": { en: "We couldn't find your billing details. Please contact support.",
                               es: "No encontramos tus datos de facturación. Contacta soporte." },
  "account.sub.invoices_heading": { en: "Invoices",
                               es: "Facturas" },
  "account.sub.invoices_intro":   { en: "Stripe keeps your full billing history.",
                               es: "Stripe guarda tu historial de pagos completo." },
  "account.sub.invoices_cta":     { en: "View invoices in the Stripe portal →",
                               es: "Ver facturas en el portal de Stripe →" },
  "account.sub.invoices_empty":   { en: "No invoices yet — your billing history will appear in the Stripe portal once your first payment is processed.",
                               es: "Aún no hay facturas — tu historial aparecerá en el portal de Stripe tras tu primer pago." },

  // ── /start landing + /welcome (acquisition funnel — PR-B) ────────
  // Public marketing surfaces that funnel cold visitors into Stripe
  // Checkout without a Clerk sign-up wall. EN + ES from day one — the
  // smoke-test guardrail at tests/e2e/preview-smoke.spec.ts fails if a
  // canary EN word leaks into the ES render.
  // Login link → opens Clerk hosted sign-in modal (PR-B.4). Keep wording
  // identical to the in-app TopNav so the user sees a consistent "Log in"
  // across surfaces.
  "start.hero.eyebrow":       { en: "Real estate in El Salvador",
                                es: "Bienes raíces en El Salvador" },
  "start.hero.h1":            { en: "Property in El Salvador, before the rest of the internet sees it.",
                                es: "Propiedades en El Salvador, antes de que las vea el resto de internet." },
  "start.hero.sub":           { en: "Pulpo curates properties in El Salvador — land, homes, commercial — before they hit the big portals. One weekly digest. No noise.",
                                es: "Pulpo recopila propiedades en El Salvador — terrenos, casas, locales — antes de que lleguen a los portales. Un resumen semanal. Sin ruido." },
  "start.hero.cta_primary":   { en: "Get access — {price}/month",
                                es: "Obtener acceso — {price}/mes" },
  "start.hero.trust_micro":   { en: "Cancel anytime. No commitment.",
                                es: "Cancela cuando quieras. Sin compromiso." },
  // Canonical Pro USPs — short variants, used in /start hero + join card
  // bullets and any future tight slot. Long variants live below as
  // `pro.usp.*` and are used in /plans + the home-page upsell modal.
  // Do NOT duplicate or shadow these keys; if a new slot needs USP copy,
  // reference these.
  "pro.usp.alerts.short":     { en: "Weekly 10 picks in your inbox",
                                es: "Top-10 semanal en tu inbox" },
  "pro.usp.browse.short":     { en: "Filters + smart sorting",
                                es: "Filtros + orden inteligente" },
  "pro.usp.links.short":      { en: "Direct seller links",
                                es: "Enlaces directos al vendedor" },
  // Long variants — /plans Pro card + home-page upsell modal.
  "pro.usp.alerts.headline":  { en: "Weekly 10 picks, in your inbox.",
                                es: "Top 10 semanal, en tu inbox." },
  "pro.usp.alerts.body":      { en: "Set your filters once. Pulpo emails you the best new matches every week.",
                                es: "Configura tus filtros una vez. Pulpo te envía las mejores coincidencias cada semana." },
  "pro.usp.browse.headline":  { en: "Filter and sort by what matters.",
                                es: "Filtra y ordena por lo que importa." },
  "pro.usp.browse.body":      { en: "Beachfront. Under €50k. Build-ready. Pulpo gives you the precision tool — free is just the raw list.",
                                es: "Frente al mar. Bajo €50k. Listo para construir. Pulpo te da precisión — gratis es solo la lista cruda." },
  "pro.usp.links.headline":   { en: "Direct links to every listing.",
                                es: "Enlaces directos a cada propiedad." },
  "pro.usp.links.body":       { en: "Free shows you the photo. Pro hands you the link to the seller.",
                                es: "Gratis te muestra la foto. Pro te entrega el enlace al vendedor." },
  "start.value.a.label":      { en: "Before the portals",
                                es: "Antes que los portales" },
  "start.value.a.body":       { en: "Most El Salvador real estate never makes it to Encuentra24 or Facebook. Sellers move fast, deals close over WhatsApp. Pulpo taps into that network and brings it to your inbox.",
                                es: "La mayoría de los bienes raíces en El Salvador nunca llegan a Encuentra24 ni Facebook. Los vendedores se mueven rápido, los tratos se cierran por WhatsApp. Pulpo se conecta a esa red y te la trae al inbox." },
  "start.value.b.label":      { en: "Land, homes, commercial",
                                es: "Terrenos, casas, locales" },
  "start.value.b.body":       { en: "Residential plots, beachfront land, homes, and commercial properties — all in one place, with the data you actually need.",
                                es: "Terrenos residenciales, tierra frente al mar, casas y propiedades comerciales — todo en un solo lugar, con la información que realmente necesitas." },
  "start.value.c.label":      { en: "Investment-grade signals",
                                es: "Señales de nivel inversor" },
  "start.value.c.body":       { en: "Price history, days on market, road access, utilities — the data points serious buyers need, in plain language.",
                                es: "Historial de precios, días en mercado, acceso vial, servicios — los datos que los compradores serios necesitan, en lenguaje claro." },
  "start.trust.stat":         { en: "{n}+ properties tracked across El Salvador",
                                es: "{n}+ propiedades monitoreadas en todo El Salvador" },
  "start.join.heading":       { en: "Join Pulpo",
                                es: "Únete a Pulpo" },
  "start.join.paid.label":    { en: "Full access",
                                es: "Acceso completo" },
  "start.join.paid.price":    { en: "{price} / month",
                                es: "{price} / mes" },
  // /start join card features now use the canonical short USPs via
  // pro.usp.*.short — these `start.join.paid.feat_*` keys are kept as
  // aliases for now (deprecation path) so the diff is small. New code
  // should reference pro.usp.*.short directly.
  // (Aliases retained for one PR to avoid mass-rename churn; remove in
  // a follow-up.)
  "start.join.paid.cta":      { en: "Get access",
                                es: "Obtener acceso" },
  "start.join.paid.cta_submitting": { en: "Opening checkout…",
                                      es: "Abriendo pago…" },
  "start.join.paid.sub":      { en: "Cancel anytime · Stripe-secured payment · Email collected at checkout",
                                es: "Cancela cuando quieras · Pago seguro por Stripe · Correo recogido en el pago" },
  "start.code.applied_note":  { en: "✓ Discount applied at checkout",
                                es: "✓ Descuento aplicado al pagar" },
  "start.error.generic":      { en: "Something went wrong — please try again.",
                                es: "Algo salió mal — inténtalo de nuevo." },
  "start.error.rate_limited": { en: "Too many attempts. Wait a moment and try again.",
                                es: "Demasiados intentos. Espera un momento e inténtalo de nuevo." },
  "start.footer.privacy":     { en: "Privacy",
                                es: "Privacidad" },
  "start.footer.terms":       { en: "Terms",
                                es: "Términos" },
  "start.footer.stripe":      { en: "Payments secured by Stripe",
                                es: "Pagos asegurados por Stripe" },
  "start.sticky_cta":         { en: "Get access — {price}/month",
                                es: "Obtener acceso — {price}/mes" },
  "start.cancelled_notice":   { en: "Checkout cancelled. Try again whenever you're ready.",
                                es: "Pago cancelado. Inténtalo de nuevo cuando quieras." },
  // /account?welcome=1 popup — fired after Stripe redirect (anon
  // variant, user hasn't accepted the Clerk magic link yet) and after
  // Clerk magic-link sign-in completes (signed_in variant).
  "welcome_modal.eyebrow":              { en: "You're in",
                                          es: "Ya está" },
  "welcome_modal.anon.headline":        { en: "Welcome to Pulpo Pro",
                                          es: "Bienvenido a Pulpo Pro" },
  "welcome_modal.anon.body":            { en: "Your subscription is active. We just emailed you a magic link to sign in. Open it from any device and you'll land back here, signed in.",
                                          es: "Tu suscripción está activa. Te enviamos un enlace mágico por correo para iniciar sesión. Ábrelo desde cualquier dispositivo y volverás aquí con sesión iniciada." },
  "welcome_modal.anon.cta_inbox":       { en: "Open my inbox →",
                                          es: "Abrir mi correo →" },
  "welcome_modal.anon.cta_resend":      { en: "Resend the link",
                                          es: "Reenviar el enlace" },
  "welcome_modal.anon.resend_done":     { en: "Sent. Check your inbox.",
                                          es: "Enviado. Revisa tu correo." },
  "welcome_modal.anon.resend_failed":   { en: "Couldn't resend. Email hello@pulpo.club if it doesn't arrive.",
                                          es: "No pudimos reenviar. Escribe a hello@pulpo.club si no llega." },
  "welcome_modal.signedin.headline":    { en: "You're all set",
                                          es: "Todo listo" },
  "welcome_modal.signedin.body":        { en: "Welcome to Pulpo Pro. Start exploring the marketplace.",
                                          es: "Bienvenido a Pulpo Pro. Empieza a explorar el marketplace." },
  "welcome_modal.signedin.cta_explore": { en: "Start exploring →",
                                          es: "Empezar a explorar →" },
  "welcome_modal.aria.dialog":          { en: "Welcome to Pulpo Pro",
                                          es: "Bienvenido a Pulpo Pro" },
  "welcome_modal.aria.close":           { en: "Close",
                                          es: "Cerrar" },
  "start.aria.logo_home":     { en: "Pulpo home",
                                es: "Inicio Pulpo" },
  "start.aria.social_proof":  { en: "Social proof",
                                es: "Prueba social" },
  "start.aria.sticky_cta":    { en: "Sticky upgrade CTA",
                                es: "Botón fijo de mejora" },
  "start.aria.usps":          { en: "What's included",
                                es: "Qué incluye" },
  "start.nav.login_link":     { en: "Log in",
                                es: "Iniciar sesión" },
  // /  home-page Pro upsell modal (PR-B.5). Triggered when the URL
  // carries a campaign signal (utm_*, code, or ?upsell=1). Pro signed-in
  // users never see it. Mobile-first; reuses the .modal infra in index.css.
  "pro_upsell.eyebrow":             { en: "Get Pulpo Pro",
                                      es: "Hazte Pulpo Pro" },
  "pro_upsell.headline":            { en: "Find your next property — faster.",
                                      es: "Encuentra tu próxima propiedad — más rápido." },
  "pro_upsell.price":               { en: "{price} / month",
                                      es: "{price} / mes" },
  "pro_upsell.price_sub":           { en: "Cancel anytime · Stripe-secured",
                                      es: "Cancela cuando quieras · Pago seguro por Stripe" },
  "pro_upsell.cta_primary":         { en: "Get access — {price}/month",
                                      es: "Obtener acceso — {price}/mes" },
  "pro_upsell.cta_primary_submitting": { en: "Opening checkout…",
                                         es: "Abriendo pago…" },
  "pro_upsell.cta_dismiss":         { en: "Maybe later",
                                      es: "Quizás más tarde" },
  "pro_upsell.code_applied_note":   { en: "✓ Discount applied at checkout",
                                      es: "✓ Descuento aplicado al pagar" },
  "pro_upsell.error":               { en: "Something went wrong — please try again.",
                                      es: "Algo salió mal — inténtalo de nuevo." },
  "pro_upsell.aria.dialog":         { en: "Get Pulpo Pro",
                                      es: "Hazte Pulpo Pro" },
  "pro_upsell.aria.close":          { en: "Close",
                                      es: "Cerrar" },

  // Wave-5 USP popup. Reuses the USPBand 3-card content (home.usp.*)
  // for the body; these keys cover the CTAs and aria labels specific
  // to the popup. Separate from pro_upsell.* so analytics and copy
  // tweaks don't cross-contaminate between the two modals.
  "usp_popup.cta_primary":          { en: "Try a free month",
                                      es: "Prueba un mes gratis" },
  "usp_popup.cta_dismiss":          { en: "Maybe later",
                                      es: "Quizás más tarde" },
  "usp_popup.aria.dialog":          { en: "Why Pulpo Pro",
                                      es: "Por qué Pulpo Pro" },
  "usp_popup.aria.close":           { en: "Close",
                                      es: "Cerrar" },
};

// `t("nav.discover")` → string in current locale, with simple {var} interpolation
function t(key, locale, vars) {
  const entry = UI_STRINGS[key];
  if (!entry) return key; // fallback so missing keys are visible
  let s = entry[locale] ?? entry[DEFAULT_LOCALE] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
  }
  return s;
}

// Locale-aware number / currency / size formatters
const localeMap = { en: "en-US", es: "es-CR" };
function formatPriceI18n(n, locale) {
  if (n == null) return "—";
  return new Intl.NumberFormat(localeMap[locale] || "en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
  }).format(n);
}
function formatSizeI18n(m2, locale, units) {
  const lc = localeMap[locale] || "en-US";
  const u = units === "vrs2" ? "vrs2" : "m2";
  if (u === "vrs2") {
    // Convert m² → vrs². Show in manzanas (1 mz = 10000 vrs²) at large
    // magnitudes for parity with how Salvadoran agents quote land.
    const vrs2 = m2 / M2_PER_VARA2;
    if (vrs2 >= 10000) {
      return `${new Intl.NumberFormat(lc, { maximumFractionDigits: 2 }).format(vrs2 / 10000)} mz`;
    }
    return `${new Intl.NumberFormat(lc, { maximumFractionDigits: 0 }).format(vrs2)} vrs²`;
  }
  if (m2 >= 10000) return `${new Intl.NumberFormat(lc, { maximumFractionDigits: 1 }).format(m2/10000)} ha`;
  return `${new Intl.NumberFormat(lc).format(m2)} m²`;
}
function formatDaysListedI18n(d, locale) {
  if (d < 7) return null;
  if (d < 30) return t("card.listed_days_ago", locale, { n: d });
  if (d < 60) return t("card.listed_1_month", locale);
  return t("card.listed_n_months", locale, { n: Math.floor(d / 30) });
}

export {
  LOCALES, DEFAULT_LOCALE, useLocale, tr, t,
  UNITS, DEFAULT_UNITS, M2_PER_VARA2, useUnits,
  formatPriceI18n, formatSizeI18n, formatDaysListedI18n,
};
