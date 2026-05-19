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
  "nav.home_pro":            { en: "Home — Pulpo Pro member", es: "Inicio — Miembro Pulpo Pro" },
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
                               es: "★ Rankeado por valor" },
  "new_hero.headline":       { en: "Every beach and lake home in El Salvador, ranked by value.",
                               es: "Todas las casas de playa y lago de El Salvador, rankeadas por valor." },
  "new_hero.tagline":        { en: "No more scrolling through 50 listing sites. We rank every beach and lake listing by value and deliver the 10 best to your inbox every two weeks.",
                               es: "Olvídate de buscar en 50 sitios. Rankeamos cada propiedad de playa y lago por valor y te enviamos las 10 mejores al correo cada quince días." },
  "new_hero.email_placeholder": { en: "you@example.com",
                                  es: "tucorreo@ejemplo.com" },
  "new_hero.cta":            { en: "Get the 10 best",     es: "Quiero las 10 mejores" },
  "new_hero.cta_loading":    { en: "Sending…",            es: "Enviando…" },
  "new_hero.sub":            { en: "Free. Unsubscribe whenever.",
                               es: "Gratis. Te das de baja cuando quieras." },
  "new_hero.success":        { en: "Done — check your inbox.",
                                es: "Listo — revisa tu correo." },
  "new_hero.error_generic":  { en: "Couldn't sign you up. Try again?",
                               es: "No pudimos suscribirte. Inténtalo de nuevo." },
  "new_hero.error_invalid_email": { en: "That email looks off — check it?",
                                    es: "Ese correo no parece válido — revísalo." },
  "new_hero.error_already":  { en: "You're already on the list. Welcome back.",
                               es: "Ya estás en la lista. ¡Qué gusto tenerte de vuelta!" },

  // Proof row — "This week's top 3 deals"
  "proof_row.heading":       { en: "This week's top 3 deals",
                               es: "Las 3 mejores ofertas de la semana" },
  "proof_row.see_all":       { en: "See all",                es: "Ver todas" },
  "proof_row.empty":         { en: "Fresh picks land here every week.",
                               es: "Cada semana publicamos nuevas oportunidades aquí." },

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
                                   es: "Las 10 mejores ofertas, cada quince días" },
  "usp.col_1_body":              { en: "Matched to your location, budget, and size. Delivered to your inbox.",
                                   es: "Filtradas por ubicación, presupuesto y tamaño. Directo a tu correo." },
  "usp.col_2_title":             { en: "Full catalogue, anytime",
                                   es: "Catálogo completo, cuando quieras" },
  "usp.col_2_body":              { en: "Browse, sort, and save hundreds of vetted beach and lake properties.",
                                   es: "Explora, ordena y guarda cientos de propiedades de playa y lago, todas revisadas." },
  "usp.col_3_title":             { en: "Built by locals",
                                   es: "Hecho aquí, por gente local" },
  "usp.col_3_body":              { en: "We live on this coast. We know which listings are real and which are overpriced.",
                                   es: "Vivimos en la costa. Sabemos cuáles propiedades son reales y cuáles están infladas de precio." },

  // Star pill ARIA — "4.5 stars out of 5"
  "star_pill.aria":              { en: "{value} stars out of 5",
                                   es: "{value} estrellas de 5" },

  // Shelf rail ARIA wrapper (screen-reader landmark name).
  "shelf_rail.aria":             { en: "Activity shelves",
                                   es: "Secciones de actividad" },

  // ── Homepage v2 (redesign) ───────────────────────────────────────
  // Copy for the redesigned homepage. The previous new_hero.* / proof_row.* /
  // category_grid.* / discovery_pill.* / usp.* keys above are no longer
  // read by any homepage component — kept in this table to avoid breaking
  // imports anywhere unforeseen, and because they're cheap to keep.
  "home.header.cta":             { en: "Try a free month",
                                   es: "Prueba un mes gratis" },
  "home.header.signin":          { en: "Sign in",
                                   es: "Iniciar sesión" },
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
                                   es: "ESCANEANDO " },
  "home.hero.eyebrow_sources":   { en: "{n} SOURCES",
                                   es: "{n} FUENTES" },
  "home.hero.eyebrow_after":     { en: " EVERY 90 SECONDS",
                                   es: " CADA 90 SEGUNDOS" },
  "home.hero.h1.before":         { en: "Every beach and lake property in El Salvador,",
                                   es: "Todas las propiedades de playa y lago de El Salvador," },
  "home.hero.h1.italic":         { en: "ranked.",
                                   es: "rankeadas." },
  "home.hero.subhead":           { en: "We scan every site, rank every beach and lake listing by value, and deliver the 10 best to your inbox every two weeks.",
                                   es: "Revisamos todos los sitios, rankeamos cada propiedad de playa y lago por valor, y te enviamos las 10 mejores ofertas al correo cada quince días." },
  "home.hero.cta_primary":       { en: "Try a free month",
                                   es: "Pruébalo un mes gratis" },
  "home.hero.cta_secondary":     { en: "See this week's top 10",
                                   es: "Ver el Top 10 de la semana" },
  "home.hero.microcopy":         { en: "{price}/month after · cancel anytime",
                                   es: "Después {price}/mes · cancela cuando quieras" },
  // Live counter card (top-right, hides <768px).
  // Wave 5#7+#9 (hero_v4 flag) — white photo-led hero. Reuses
  // home.hero.h1.before / h1.italic / cta_primary / microcopy /
  // counter_template; the strings below cover the new kicker,
  // simplified subhead, photo aria, and featured-pill.
  "home.hero.v4.kicker":         { en: "PULPO · BEACH + LAKE",
                                   es: "PULPO · PLAYA + LAGO" },
  "home.hero.v4.subhead":        { en: "We score every listing. No ads. No fluff.",
                                   es: "Puntuamos cada propiedad. Sin publicidad. Sin relleno." },
  "home.hero.v4.featured_pill":  { en: "Featured this week",
                                   es: "Destacado esta semana" },
  "home.hero.v4.photo_aria":     { en: "Open this week's featured listing in {name}",
                                   es: "Abrir el destacado de esta semana en {name}" },

  "home.hero.counter_live":      { en: "LIVE NOW",
                                   es: "EN VIVO" },
  "home.hero.counter_template":  { en: "{count} listings · {sources} sources",
                                   es: "{count} propiedades · {sources} fuentes" },
  "home.hero.preview.label":     { en: "Pulpo weekly",
                                   es: "Pulpo semanal" },
  "home.hero.preview.headline":  { en: "Top 10 · updating live",
                                   es: "Top 10 · en vivo" },
  "home.hero.preview.live":      { en: "LIVE",
                                   es: "EN VIVO" },
  "home.hero.preview.sr":        { en: "Preview: top 10 listings ranked from A+ to C-",
                                   es: "Vista previa: las 10 mejores propiedades, de A+ a C-" },
  // Just In pill — clay-orange floating card that pops on each leaderboard cycle.
  "home.hero.just_in_label":     { en: "JUST IN",
                                   es: "RECIÉN" },
  "home.hero.just_in_position":  { en: "→ #{n}",
                                   es: "→ #{n}" },
  "home.hero.off_the_board":     { en: "off the board",
                                   es: "fuera del top 10" },
  "home.hero.just_in_aria":      { en: "Just in: {name} — sign up to see more",
                                   es: "Recién listada: {name} — regístrate para ver más" },
  "home.hero.new_badge":         { en: "NEW",
                                   es: "NUEVO" },

  "home.featured.eyebrow":       { en: "FEATURED DEAL",
                                   es: "OFERTA DESTACADA" },
  // Wave-5b: when featured_deal_real_v1 flag is on, the card renders a
  // real listing from featured.json. Title + body switch to generic
  // curation copy (the listing varies; the section narrative doesn't).
  // The hardcoded title/body below stay as the flag-off fallback so a
  // rollback is byte-for-byte identical to today.
  "home.featured.title":         { en: "3-bed lakefront at Lago de Coatepeque, 23% under comps.",
                                   es: "Casa de 3 habitaciones frente al Lago de Coatepeque, 23% bajo comparables." },
  "home.featured.body":          { en: "0.4 acre, private dock, listed two days ago and already scored A+ by our comp engine.",
                                   es: "0.16 ha, muelle privado, publicada hace dos días y ya con A+ de nuestro motor de comparables." },
  "home.featured.title_real":    { en: "This week's standout deal.",
                                   es: "El destacado de la semana." },
  "home.featured.body_real":     { en: "Hand-picked by our comp engine. Tap to see the full listing.",
                                   es: "Elegido por nuestro motor de comparables. Toca para ver el anuncio." },
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
  // home.featured.stat_value retained for flag-off rollback. The
  // value-estimate stat doesn't exist in the data model — Wave-5b
  // dropped it from the real-data variant.
  "home.featured.stat_value":    { en: "Est. value",
                                   es: "Valor estimado" },
  "home.featured.stat_days":     { en: "Days on market",
                                   es: "Días en venta" },

  "home.usp.eyebrow":            { en: "FOR SUBSCRIBERS ONLY",
                                   es: "SOLO PARA SUSCRIPTORES" },
  "home.usp.h2":                 { en: "What your {price} a month buys you.",
                                   es: "Esto es lo que te llevas por {price} al mes." },
  "home.usp.card1.title":        { en: "10 best deals,\never 2 weeks",
                                   es: "Las 10 mejores ofertas,\ncada quince días" },
  "home.usp.card1.body":         { en: "Matched to your location, budget, and size. Delivered to your inbox.",
                                   es: "Filtradas por ubicación, presupuesto y tamaño. Directo a tu correo." },
  "home.usp.card2.title":        { en: "Full catalogue,\nanytime",
                                   es: "Catálogo completo,\ncuando quieras" },
  "home.usp.card2.body":         { en: "Browse, sort, and save hundreds of vetted beach and lake properties.",
                                   es: "Explora, ordena y guarda cientos de propiedades de playa y lago, todas revisadas." },
  "home.usp.card3.title":        { en: "Built by locals",
                                   es: "Hecho aquí, por gente local" },
  "home.usp.card3.body":         { en: "We live on this coast. We know which listings are real and which are overpriced.",
                                   es: "Vivimos en la costa. Sabemos cuáles propiedades son reales y cuáles están infladas de precio." },

  "home.shoreline.h2":           { en: "Pick your shoreline.",
                                   es: "Escoge tu costa." },
  "home.shoreline.lake.label":   { en: "Lake",
                                   es: "Lago" },
  "home.shoreline.beach.label":  { en: "Beach",
                                   es: "Playa" },
  "home.shoreline.subtitle":     { en: "Gated community & independent properties",
                                   es: "Residenciales privados y propiedades independientes" },
  "home.shoreline.cta_aria":     { en: "Browse {shoreline} properties",
                                   es: "Ver propiedades de {shoreline}" },

  "home.shelf.top10.h2":         { en: "Top 10 deals right now",
                                   es: "Las 10 mejores ofertas ahora mismo" },
  "home.shelf.top10.sub":        { en: "The 10 best price-for-location lots in El Salvador. Ranked daily.",
                                   es: "Los 10 mejores lotes por precio-ubicación en El Salvador. Ranqueados a diario." },
  "home.shelf.dropsHeading":     { en: "Price drops",
                                   es: "Rebajas de precio" },
  "home.shelf.dropsSub":         { en: "Listings with a price cut this month.",
                                   es: "Listados con bajada de precio este mes." },
  "home.shelf.dropsCount":       { en: "↘ {n} cuts",
                                   es: "↘ {n} rebajas" },
  "home.shelf.newHeading":       { en: "New this week",
                                   es: "Nuevas esta semana" },
  "home.shelf.newSub":           { en: "Listings added in the last 7 days.",
                                   es: "Listados agregados en los últimos 7 días." },
  "home.shelf.newCount":         { en: "✦ {n} added",
                                   es: "✦ {n} agregadas" },
  "home.shelf.prev":             { en: "Show previous listings",
                                   es: "Ver propiedades anteriores" },
  "home.shelf.next":             { en: "Show next listings",
                                   es: "Ver más propiedades" },
  "home.shelf.view_all":         { en: "View all →",
                                   es: "Ver todas →" },
  "home.shelf.scroll_hint":      { en: "○ ○ ○  scroll for {n} more",
                                   es: "○ ○ ○  desliza para ver {n} más" },
  "home.shelf.aria":             { en: "Homepage activity shelves",
                                   es: "Secciones de la página de inicio" },

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
  // Inverse-semantic chip: OFF by default hides listings where the
  // broker hasn't shared price or size; ON brings them in at the
  // bottom of the ranking.
  "filter.show_incomplete":      { en: "Show missing details", es: "Ver con datos faltantes" },

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
  // Group headers for the three-tier filter rail (WHERE / RANKING / FILTERS).
  // Compose with the chips defined in data.jsx PILL_GROUPS.
  "pill.rail.aria":          { en: "Filter listings",     es: "Filtrar listados" },
  "pill.group.where":        { en: "Where",               es: "Dónde" },
  "pill.group.ranking":      { en: "Ranking",             es: "Ranking" },
  "pill.group.filters":      { en: "Filter",              es: "Filtros" },

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
  // Used on cards + detail keystats wherever price or size is null.
  // Surfaces the "broker hasn't shared" semantic instead of a bare
  // em-dash. The tooltip explains the next step.
  "value.notshared.short":   { en: "Not shared",          es: "No compartido" },
  "value.notshared.tooltip": { en: "The broker hasn't shared this. Contact them for details.",
                               es: "El broker no ha compartido este dato. Contáctalo para más información." },
  // Inline note rendered above the detail-page description for any
  // listing where price OR size is missing. Pairs with the per-field
  // "Not shared" copy.
  "detail.broker_note":      { en: "The broker hasn't shared full details for this listing. Contact them to confirm price and size.",
                               es: "El broker no ha compartido todos los datos de esta propiedad. Contáctalo para confirmar precio y tamaño." },

  // Saved — page title matches the nav-bar label ("Favorites"). The
  // URL is still /saved (Wave 3b renames it). Past-tense "saved"
  // strings (toast.saved, etc.) stay as-is — they're verbs, not the
  // page brand.
  "saved.title":             { en: "Favorites",           es: "Favoritos" },
  "saved.empty.title":       { en: "Your saved listings will appear here",
                               es: "Aquí van a aparecer las propiedades que guardes" },
  "saved.empty.body":        { en: "Browse listings and tap ♡ to save the ones that interest you.",
                               es: "Explora las propiedades y toca ♡ para guardar las que te interesen." },

  // Toasts
  "toast.saved":             { en: "Saved to your shortlist", es: "Guardado en tu lista" },
  "toast.removed":           { en: "Removed from saved",   es: "Eliminado de guardados" },
  "toast.welcome":           { en: "✓ Welcome! Your account is ready.",
                               es: "✓ ¡Bienvenido! Tu cuenta ya está lista." },
  "toast.logged_out":        { en: "Logged out",           es: "Sesión cerrada" },

  // Footer
  "footer.tagline":          { en: "Properties worth wanting in El Salvador.",
                               es: "Las propiedades que valen la pena en El Salvador." },
  "footer.country_badge":    { en: "Listings in El Salvador",
                               es: "Propiedades en El Salvador" },

  // Find Your Style carousel — deleted in the rewrite cutover (Phase 9)
  // with the legacy StyleCarousel component. Keys removed.

  // Live header stats (PR-4c)
  "stats.sources":           { en: "sources",  es: "fuentes" },
  "stats.listings":          { en: "listings", es: "propiedades" },
  "stats.updated":           { en: "updated",  es: "actualizado" },
  "stats.info_label":        { en: "Pulpo data freshness", es: "Última actualización de los datos de Pulpo" },

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
                               es: "Crea una cuenta gratis para ver el anuncio original" },
  "detail.view_on":          { en: "View on {source}",              es: "Ver en {source}" },
  "detail.off_market_inquire": { en: "Off-market — see Plans to inquire",
                               es: "Off-market — mira los planes para contactar" },
  "detail.save":             { en: "Save",                          es: "Guardar" },
  "detail.saved":            { en: "Saved",                         es: "Guardado" },
  // Single shared CTA for every gated upgrade point inside ListingDetail
  // (bottom CTA bar, locked gallery thumb, locked USP row). Names the
  // free-month offer because that's the actual offer at the other end:
  // the click opens FreeMonthModal which pre-applies PULPOFREEMONTH at
  // /api/stripe/start-checkout. Per-site copy variants ("see N more
  // reasons", "N+ photos") were dropped — the panel's lock-icon
  // affordances + this single CTA convey enough; reintroduce per-site
  // keys later if A/B tests show a lift.
  "detail.unlock_pro_free_month": { en: "Start Pulpo Pro — first month free",
                                     es: "Empieza con Pulpo Pro — primer mes gratis" },
  "detail.more_photos":      { en: "+{n} photos",                   es: "+{n} fotos" },
  "detail.signup_for_pin":   { en: "Sign up for precise pin",       es: "Crea una cuenta para ver la ubicación exacta" },
  "detail.sold_banner.title": { en: "This listing has been sold or removed.",
                               es: "Esta propiedad fue vendida o retirada." },
  "detail.sold_banner.days": { en: "It was on the market for {n} days.",
                               es: "Estuvo en el mercado durante {n} días." },
  "detail.sold_banner.cta":  { en: "Browse similar listings in {zone} →",
                               es: "Ver propiedades similares en {zone} →" },
  "detail.paywall.title":    { en: "Off-market deal",               es: "Oferta off-market" },
  "detail.paywall.body":     { en: "This listing isn't public anywhere else. Pulpo Pro members get direct access plus broker intros.",
                               es: "Esta propiedad no está publicada en ningún otro sitio. Los miembros Pulpo Pro reciben acceso directo y conexión con el corredor." },
  "detail.paywall.see_plans": { en: "See plans",                    es: "Ver planes" },
  "detail.paywall.have_account": { en: "I have an account",         es: "Ya tengo una cuenta" },
  "detail.gallery.open":     { en: "Open photo gallery",            es: "Abrir galería de fotos" },
  "detail.gallery.open_n":   { en: "Open photo {n}",                es: "Abrir foto {n}" },
  "detail.gallery.locked_aria": { en: "Sign up to unlock more photos",
                               es: "Crea una cuenta para desbloquear más fotos" },

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
                               es: "El problema es nuestro. El servidor de datos no respondió — inténtalo en un momento." },

  // Newsletter CTA — deleted in the rewrite cutover (Phase 9) with the
  // legacy NewsletterCTA component. The new homepage's hero email
  // form (Hero.jsx) reads the new_hero.* keys higher up in this file.

  // Plans page — full string set. PRO_PRICE_USD_PER_MONTH lives in
  // pages.jsx and mirrors automation/stripe_setup.mjs.
  "plans.head.title":        { en: "Pick a plan that fits how you invest.",
                               es: "Escoge el plan que mejor se ajuste a cómo inviertes." },
  "plans.head.subtitle":     { en: "Pulpo is free to browse. Upgrade for unlimited details, off-market access, and weekly alerts.",
                               es: "Explorar Pulpo es gratis. Hazte Pro para ver detalles sin límite, acceso off-market y alertas semanales." },
  // Free tier
  "plans.free.name":         { en: "Free",                    es: "Gratis" },
  "plans.free.tag":          { en: "Browse the catalogue",    es: "Explora el catálogo" },
  "plans.free.feat.browsing":         { en: "Unlimited card browsing",      es: "Explora tarjetas sin límite" },
  "plans.free.feat.detail_views":     { en: "8 detail views per month",     es: "8 fichas detalladas al mes" },
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
                               es: "Los precios de las propiedades aparecen en USD; la suscripciÃ³n de Pulpo Pro se cobra en EUR." },
  // Pro feature list — PlansPage now uses the three canonical `pro.usp.*.headline`
  // keys above, plus this single "Everything in Free" caboose. The five legacy
  // bullets (unlimited_details, off_market, newsletter, unlimited_saves,
  // price_alerts) were removed in PR-B.4a — their content is covered by the
  // three canonical USPs (alerts covers newsletter + price_alerts; browse
  // covers unlimited_details; links covers off_market access).
  "plans.pro.feat.everything_in_free": { en: "Everything in Free",        es: "Todo lo que incluye el plan Gratis" },
  // Agency tier (hidden by default — see SHOW_AGENCY_PLAN in pages.jsx).
  "plans.agency.name":       { en: "Agency",                   es: "Agencia" },
  "plans.agency.tag":        { en: "For investor groups & brokers",
                               es: "Para grupos de inversión y corredores" },
  "plans.agency.feat.everything_in_pro": { en: "Everything in Pro",       es: "Todo lo del plan Pro" },
  "plans.agency.feat.team_seats":        { en: "5 team seats",            es: "5 cuentas para tu equipo" },
  "plans.agency.feat.shared_lists":      { en: "Shared saved lists",      es: "Listas compartidas con el equipo" },
  "plans.agency.feat.csv_export":        { en: "CSV export",              es: "Exportación a CSV" },
  "plans.agency.feat.priority_off_market": { en: "Priority off-market intros",
                                             es: "Conexiones off-market prioritarias" },
  "plans.agency.cta_contact": { en: "Contact sales",           es: "Contactar ventas" },
  // Stripe-wired Pro CTA + error toast.
  "plans.upgrade_pro_cta":   { en: "Upgrade — €{price}/month",
                               es: "Hazte Pro — €{price}/mes" },
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

  // Consent banner (GDPR / ePrivacy / LGPD)
  //
  // Implements the 9-point ConsentBanner contract from
  // legal_documents/03-cookie-policy.md. EN + ES coverage from day one;
  // a Spanish-counsel review pass will follow before incorporation.
  "consent.aria":            { en: "Cookie consent",                es: "Consentimiento de cookies" },
  "consent.body":            { en: "Pulpo uses cookies to deliver the site, remember your preferences, and (with your permission) measure how the site is used. Strictly-necessary cookies are always on; everything else is off until you decide.",
                               es: "Pulpo usa cookies para que el sitio funcione, recordar tus preferencias y (con tu permiso) entender cómo se usa el sitio. Las estrictamente necesarias siempre están activas; el resto se queda desactivado hasta que tú decidas." },
  // Pre-rebuild keys kept for back-compat — no current call site after PR-E.
  "consent.decline":         { en: "Decline",                       es: "Rechazar" },
  "consent.accept":          { en: "Accept",                        es: "Aceptar" },
  // PR-E new keys.
  "consent.accept_all":      { en: "Accept all",                    es: "Aceptar todas" },
  "consent.decline_all":     { en: "Decline all",                   es: "Rechazar todas" },
  "consent.manage":          { en: "Manage preferences",            es: "Gestionar preferencias" },
  "consent.save":            { en: "Save preferences",              es: "Guardar preferencias" },
  "consent.prefs.title":     { en: "Cookie preferences",            es: "Preferencias de cookies" },
  "consent.prefs.lede":      { en: "Strictly-necessary cookies are always on — the site can't function without them. The rest you can switch on or off.",
                               es: "Las cookies estrictamente necesarias siempre están activas — el sitio no funciona sin ellas. El resto puedes activarlas o desactivarlas." },
  "consent.category.always_active":               { en: "Always active",
                                                    es: "Siempre activas" },
  "consent.category.strictly_necessary.label":    { en: "Strictly necessary",
                                                    es: "Estrictamente necesarias" },
  "consent.category.strictly_necessary.desc":     { en: "Authentication, checkout session continuity, your stored preferences. These cannot be switched off.",
                                                    es: "Autenticación, continuidad del pago en Stripe, tus preferencias guardadas. No se pueden desactivar." },
  "consent.category.analytics.label":             { en: "Analytics",
                                                    es: "Analíticas" },
  "consent.category.analytics.desc":              { en: "PostHog product analytics + 10% session replay sample (input-masked, EU-hosted in Frankfurt). Helps us see what works.",
                                                    es: "Analíticas de producto con PostHog + grabación de sesiones al 10% (con los campos enmascarados, alojado en Frankfurt). Nos ayuda a entender qué funciona." },
  "consent.category.functional.label":            { en: "Functional",
                                                    es: "Funcionales" },
  "consent.category.functional.desc":             { en: "Mapbox map-tile caching and Resend newsletter open/click tracking. Improves the experience but not required.",
                                                    es: "Caché de mosaicos de Mapbox y seguimiento de aperturas/clics del newsletter por Resend. Mejora la experiencia pero no es necesario." },

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
  "nav.account_pro":         { en: "Account — Pulpo Pro member",    es: "Cuenta — Miembro Pulpo Pro" },
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
                                        es: "Alertas de rebajas de precio" },
  "account.notif.price_drops.desc":  { en: "Email when a saved listing drops in price.",
                                        es: "Te avisamos por correo cuando una propiedad guardada baja de precio." },
  "account.notif.new_in_zones.title":{ en: "New listings in saved zones",
                                        es: "Nuevas propiedades en zonas guardadas" },
  "account.notif.new_in_zones.desc": { en: "Get early notice when something new appears in areas you've explored.",
                                        es: "Entérate temprano cuando aparece algo nuevo en zonas que ya exploraste." },

  // Free for everyone — product news, not premium content.
  "account.notif.platform_updates.title": { en: "Platform updates",
                                             es: "Novedades de Pulpo" },
  "account.notif.platform_updates.desc":  { en: "Occasional product news and feature announcements.",
                                             es: "Noticias del producto y novedades, sin saturarte el correo." },

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
                                       es: "Te vamos a enviar alertas al {number}. Puedes desactivarlas cuando quieras." },

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
                                              es: "Nuevas esta semana" },
  "account.notif.pref_cat.price_drops":    { en: "Price drops",
                                              es: "Rebajas de precio" },
  "account.notif.pref_cat.beachfront":     { en: "Beachfront / near the beach",
                                              es: "Frente al mar / cerca de la playa" },
  "account.notif.pref_cat.water_features": { en: "Lakefront / near water",
                                              es: "Frente al lago / cerca del agua" },
  "account.notif.pref_cat.under_50k":      { en: "Under $50K",
                                              es: "Menos de $50.000" },
  "account.notif.pref_cat.under_100k":     { en: "$50K–$100K",
                                              es: "Entre $50.000 y $100.000" },

  // ── Newsletter filter (PR-NL-3) ──────────────────────────────────────
  // Persists to publicMetadata.profile.newsletter and is read by the
  // fortnightly cron (automation/newsletter/build_issue.py). Strings are
  // separate from the broader category-preferences block above because
  // the newsletter filter is more specific (department × type × price
  // band) and the surface needs its own copy.
  "account.notif.newsletter_filter.heading":
    { en: "Newsletter filter",
      es: "Filtro del boletín" },
  "account.notif.newsletter_filter.intro":
    { en: "Pulpo will scan the next 14 days against this filter and ship the ten that match. Leave a row unselected to keep that axis open.",
      es: "Pulpo revisará los próximos 14 días contra este filtro y enviará las diez que coincidan. Deja una fila sin seleccionar para mantener ese eje abierto." },
  "account.notif.newsletter_filter.departments":
    { en: "Departments",                                  es: "Departamentos" },
  "account.notif.newsletter_filter.property_types":
    { en: "Property type",                                es: "Tipo de propiedad" },
  "account.notif.newsletter_filter.price_band":
    { en: "Price ceiling",                                es: "Precio máximo" },
  "account.notif.newsletter_filter.locale":
    { en: "Language",                                     es: "Idioma" },
  "account.notif.newsletter_filter.type.land":
    { en: "Land",                                         es: "Terreno" },
  "account.notif.newsletter_filter.type.house":
    { en: "House",                                        es: "Casa" },
  "account.notif.newsletter_filter.type.condo":
    { en: "Condo",                                        es: "Apartamento" },
  "account.notif.newsletter_filter.locale.en":
    { en: "English",                                      es: "Inglés" },
  "account.notif.newsletter_filter.locale.es":
    { en: "Spanish",                                      es: "Español" },

  // Pro upsell shown to free / anonymous users in this subsection.
  "account.notif.upsell.title": { en: "Get deal alerts with Pulpo Pro",
                                  es: "Recibe alertas de ofertas con Pulpo Pro" },
  "account.notif.upsell.body":  { en: "Email alerts on saved listings, new listings in your zones, and the curated weekly digest are part of Pulpo Pro.",
                                  es: "Las alertas por email de anuncios guardados, los nuevos en tus zonas y el boletín semanal son parte de Pulpo Pro." },
  "account.notif.upsell.cta":   { en: "Upgrade to Pro",
                                  es: "Hazte Pro" },
  // Shared "Upgrade to Pro" button label — also used by the
  // Subscription-section free-tier CTA. Prefer this over duplicating
  // the literal in any new surface.
  "common.upgrade_to_pro_cta":  { en: "Upgrade to Pro",
                                  es: "Hazte Pro" },

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
                               es: "Stripe guarda tu historial completo de pagos." },
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
                                es: "Propiedades en El Salvador, antes de que las vea el resto del internet." },
  "start.hero.sub":           { en: "Pulpo curates properties in El Salvador — land, homes, commercial — before they hit the big portals. One weekly digest. No noise.",
                                es: "Pulpo selecciona propiedades en El Salvador — terrenos, casas y locales — antes de que lleguen a los portales grandes. Un resumen semanal. Sin ruido." },
  "start.hero.cta_primary":   { en: "Get access — {price}/month",
                                es: "Quiero acceso — {price}/mes" },
  "start.hero.trust_micro":   { en: "Cancel anytime. No commitment.",
                                es: "Cancela cuando quieras. Sin compromiso." },
  // Canonical Pro USPs — short variants, used in /start hero + join card
  // bullets and any future tight slot. Long variants live below as
  // `pro.usp.*` and are used in /plans + the home-page upsell modal.
  // Do NOT duplicate or shadow these keys; if a new slot needs USP copy,
  // reference these.
  "pro.usp.alerts.short":     { en: "Weekly 10 picks in your inbox",
                                es: "El Top 10 cada semana en tu correo" },
  "pro.usp.browse.short":     { en: "Filters + smart sorting",
                                es: "Filtros + orden inteligente" },
  "pro.usp.links.short":      { en: "Direct seller links",
                                es: "Enlaces directos al vendedor" },
  // Long variants — /plans Pro card + home-page upsell modal.
  "pro.usp.alerts.headline":  { en: "Weekly 10 picks, in your inbox.",
                                es: "El Top 10 de la semana, en tu correo." },
  "pro.usp.alerts.body":      { en: "Set your filters once. Pulpo emails you the best new matches every week.",
                                es: "Configura tus filtros una vez. Cada semana Pulpo te manda las mejores propiedades que coinciden." },
  "pro.usp.browse.headline":  { en: "Filter and sort by what matters.",
                                es: "Filtra y ordena por lo que de verdad importa." },
  "pro.usp.browse.body":      { en: "Beachfront. Under €50k. Build-ready. Pulpo gives you the precision tool — free is just the raw list.",
                                es: "Frente al mar. Menos de $50K. Listo para construir. Pulpo te da la precisión — la versión gratis es solo la lista en crudo." },
  "pro.usp.links.headline":   { en: "Direct links to every listing.",
                                es: "Enlace directo a cada propiedad." },
  "pro.usp.links.body":       { en: "Free shows you the photo. Pro hands you the link to the seller.",
                                es: "Con el plan gratis ves la foto. Con Pro recibes el enlace directo al vendedor." },
  "start.value.a.label":      { en: "Before the portals",
                                es: "Antes que los portales" },
  "start.value.a.body":       { en: "Most El Salvador real estate never makes it to Encuentra24 or Facebook. Sellers move fast, deals close over WhatsApp. Pulpo taps into that network and brings it to your inbox.",
                                es: "La mayoría de las propiedades en El Salvador nunca llegan a Encuentra24 ni a Facebook. Los vendedores se mueven rápido, las ofertas se cierran por WhatsApp. Pulpo se conecta a esa red y te la trae al correo." },
  "start.value.b.label":      { en: "Land, homes, commercial",
                                es: "Terrenos, casas y locales" },
  "start.value.b.body":       { en: "Residential plots, beachfront land, homes, and commercial properties — all in one place, with the data you actually need.",
                                es: "Terrenos residenciales, lotes frente al mar, casas y locales comerciales — todo en un mismo lugar, con la información que de verdad necesitas." },
  "start.value.c.label":      { en: "Investment-grade signals",
                                es: "Datos de inversionista" },
  "start.value.c.body":       { en: "Price history, days on market, road access, utilities — the data points serious buyers need, in plain language.",
                                es: "Historial de precios, días en el mercado, acceso vial, servicios — los datos que un comprador serio necesita, en lenguaje claro." },
  "start.trust.stat":         { en: "{n}+ properties tracked across El Salvador",
                                es: "MÃ¡s de {n} propiedades revisadas en todo El Salvador" },
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
                                es: "Quiero acceso" },
  "start.join.paid.cta_submitting": { en: "Opening checkout…",
                                      es: "Abriendo el pago…" },
  "start.join.paid.sub":      { en: "Cancel anytime · Stripe-secured payment · Email collected at checkout",
                                es: "Cancela cuando quieras · Pago seguro con Stripe · Tu correo se registra al pagar" },
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
                                es: "Pagos protegidos por Stripe" },
  "start.sticky_cta":         { en: "Get access — {price}/month",
                                es: "Quiero acceso — {price}/mes" },
  "start.cancelled_notice":   { en: "Checkout cancelled. Try again whenever you're ready.",
                                es: "Pago cancelado. Inténtalo de nuevo cuando quieras." },
  // /account?welcome=1 popup — fired after Stripe redirect (anon
  // variant, user hasn't accepted the Clerk invitation yet) and
  // after Clerk invitation sign-up completes (signed_in variant).
  // Copy intentionally avoids the "magic link" phrasing — the
  // mechanism is a Clerk invitation that prompts the user to set
  // a password, NOT a passwordless magic-link sign-in. Mismatching
  // copy here caused the post-Stripe loop reported on 2026-05-19.
  "welcome_modal.eyebrow":              { en: "You're in",
                                          es: "Ya está" },
  "welcome_modal.anon.headline":        { en: "Welcome to Pulpo Pro",
                                          es: "Bienvenido a Pulpo Pro" },
  "welcome_modal.anon.body":            { en: "Your subscription is active. We just sent an invitation to your inbox so you can finish setting up your account. Open it from any device — once you set your password you'll land back here, signed in.",
                                          es: "Tu suscripción ya está activa. Acabamos de enviarte una invitación al correo para que termines de configurar tu cuenta. Ábrela desde cualquier dispositivo — al elegir tu contraseña vuelves a esta página con la sesión iniciada." },
  "welcome_modal.anon.cta_inbox":       { en: "Open my inbox →",
                                          es: "Abrir mi correo →" },
  "welcome_modal.anon.cta_resend":      { en: "Resend my invitation",
                                          es: "Reenviar la invitación" },
  "welcome_modal.anon.resend_done":     { en: "Sent. Check your inbox.",
                                          es: "Enviado. Revisa tu correo." },
  "welcome_modal.anon.resend_failed":   { en: "Couldn't resend. Email hello@pulpo.club if it doesn't arrive.",
                                          es: "No pudimos reenviar. Escribe a hello@pulpo.club si no llega." },
  // Distinct copy for the resend-but-user-already-exists branch
  // (Clerk returned a user; nothing to re-invite). Without this the
  // generic resend_done copy lies — there's no new inbox to check.
  "welcome_modal.anon.resend_user_exists": { en: "Looks like you're already signed up. Try refreshing this page.",
                                          es: "Parece que ya tienes una cuenta. Refresca la página para continuar." },
  // Status-branch copy — driven by /api/clerk/invitation-status on
  // modal mount. The default anon variant ("invitation_pending"
  // branch) keeps the existing body+resend wiring; these keys cover
  // the three OTHER discriminated outcomes from the webhook. Before
  // these existed the modal lied to users on any non-invitation
  // path (e.g. existing-user / no-email / webhook-not-yet-fired).
  "welcome_modal.anon.status.user_exists.headline": { en: "You already have a Pulpo account",
                                          es: "Ya tienes una cuenta de Pulpo" },
  "welcome_modal.anon.status.user_exists.body": { en: "Your subscription is active and linked to {email_domain}. Sign in with your existing password — no new email was sent.",
                                          es: "Tu suscripción ya está activa y vinculada a {email_domain}. Inicia sesión con la contraseña que ya tienes — no enviamos un correo nuevo." },
  "welcome_modal.anon.status.user_exists.cta": { en: "Sign in →",
                                          es: "Iniciar sesión →" },
  "welcome_modal.anon.status.no_email.headline": { en: "We couldn't read your email",
                                          es: "No pudimos leer tu correo" },
  "welcome_modal.anon.status.no_email.body": { en: "Your subscription is active but your Stripe receipt didn't include an email we could match. Please email hello@pulpo.club so we can attach your subscription.",
                                          es: "Tu suscripción ya está activa, pero el recibo de Stripe no traía un correo que pudiéramos vincular. Escríbenos a hello@pulpo.club para conectarla a tu cuenta." },
  "welcome_modal.anon.status.no_email.cta": { en: "Email hello@pulpo.club →",
                                          es: "Escribir a hello@pulpo.club →" },
  "welcome_modal.anon.status.webhook_pending.body": { en: "Your subscription is active. We're finishing your account setup — your activation email should arrive in a moment. If it doesn't show up in 5 minutes, email hello@pulpo.club.",
                                          es: "Tu suscripción ya está activa. Estamos terminando de configurar tu cuenta — el correo de activación debería llegar en un momento. Si no aparece en 5 minutos, escríbenos a hello@pulpo.club." },
  "welcome_modal.signedin.headline":    { en: "You're all set",
                                          es: "Todo listo" },
  "welcome_modal.signedin.body":        { en: "Welcome to Pulpo Pro. Your account is active — start exploring the marketplace.",
                                          es: "Bienvenido a Pulpo Pro. Tu cuenta ya está activa — empieza a explorar el catálogo." },
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
                                es: "Botón fijo para hacerse Pro" },
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
                                      es: "Cancela cuando quieras · Pago seguro con Stripe" },
  "pro_upsell.cta_primary":         { en: "Get access — {price}/month",
                                      es: "Quiero acceso — {price}/mes" },
  "pro_upsell.cta_primary_submitting": { en: "Opening checkout…",
                                         es: "Abriendo el pago…" },
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

  // Free-month conversion modal. Opens from hero CTA, USP section,
  // and listing-card clicks for anon + free users (paid users skip).
  // Replaces the previous "redirect to /start?intent=upgrade" page
  // jump with an in-page modal that POSTs to /api/stripe/start-checkout.
  "free_month_modal.headline":         { en: "Property in El Salvador, before the rest of the internet sees it.",
                                          es: "Propiedades en El Salvador, antes de que las vea el resto del internet." },
  "free_month_modal.body":             { en: "Pulpo curates properties in El Salvador — land, homes, commercial — before they hit the big portals. One weekly digest. No noise.",
                                          es: "Pulpo selecciona propiedades en El Salvador — terrenos, casas, locales — antes de que lleguen a los portales grandes. Un resumen semanal. Sin ruido." },
  "free_month_modal.bullet.1":         { en: "Weekly 10 picks in your inbox",
                                          es: "10 propiedades cada semana, en tu correo" },
  "free_month_modal.bullet.2":         { en: "Filters + smart sorting",
                                          es: "Filtros y orden inteligente" },
  "free_month_modal.bullet.3":         { en: "Direct seller links",
                                          es: "Enlaces directos al vendedor" },
  "free_month_modal.cta_primary":      { en: "Try a free month — {price}/month after",
                                          es: "Pruébalo un mes gratis — luego {price}/mes" },
  "free_month_modal.cta_primary_submitting": { en: "Opening checkout…",
                                          es: "Abriendo el pago…" },
  "free_month_modal.cta_dismiss":      { en: "Maybe later",
                                          es: "Quizás más tarde" },
  "free_month_modal.aria.dialog":      { en: "Try a free month",
                                          es: "Prueba un mes gratis" },
  "free_month_modal.aria.close":       { en: "Close",
                                          es: "Cerrar" },
  "free_month_modal.error":            { en: "Couldn't open checkout. Try again.",
                                          es: "No pudimos abrir el pago. Inténtalo de nuevo." },
  "free_month_modal.code_applied_note":{ en: "✓ First month free, applied at checkout",
                                          es: "✓ Primer mes gratis, se aplica al pagar" },

  // Trimmed footer (home + browse + all legal-suite pages).
  "footer.fine_print":                 { en: "© {year} Pulpo",
                                          es: "© {year} Pulpo" },
  "footer.fine_print_full":            { en: "© {year} Pulpo · A discovery-first land investment marketplace",
                                          es: "© {year} Pulpo · Un marketplace para descubrir inversiones en bienes raíces" },
  "footer.link.terms":                 { en: "Terms",
                                          es: "Términos" },
  "footer.link.privacy":               { en: "Privacy",
                                          es: "Privacidad" },
  "footer.link.cookies":               { en: "Cookies",
                                          es: "Cookies" },
  "footer.link.subscription":          { en: "Subscription & Refunds",
                                          es: "Suscripción y reembolsos" },
  "footer.link.imprint":               { en: "Imprint",
                                          es: "Aviso legal" },
  "footer.link.contact":               { en: "Contact",
                                          es: "Contacto" },
  "footer.link.cookie_preferences":    { en: "Cookie Preferences",
                                          es: "Preferencias de cookies" },

  // Full footer column headings + items (saved / plans / account-when-enabled).
  "footer.col.discover.heading":       { en: "Discover",
                                          es: "Descubrir" },
  "footer.col.discover.beachfront":    { en: "Beachfront",
                                          es: "Frente al mar" },
  "footer.col.discover.build_ready":   { en: "Build-ready",
                                          es: "Listo para construir" },
  "footer.col.discover.off_market":    { en: "Off-market",
                                          es: "Off-market" },
  "footer.col.discover.agricultural":  { en: "Agricultural",
                                          es: "Agrícola" },
  "footer.col.pulpo.heading":          { en: "Pulpo",
                                          es: "Pulpo" },
  "footer.col.pulpo.plans":            { en: "Plans",
                                          es: "Planes" },
  "footer.col.legal.heading":          { en: "Legal",
                                          es: "Legal" },

  // Legal-suite pages (/terms, /privacy, /cookies, /subscription, /imprint).
  // Body prose lives in web/app/config/legal-content.ts (typed
  // LegalDocument records); these keys are page chrome only.
  "legal.back_to_home":                { en: "Back to home",
                                          es: "Volver al inicio" },
  "legal.last_updated":                { en: "Last updated",
                                          es: "Actualizado" },
  "legal.draft_banner":                { en: "This page is a working draft pending counsel review. Lawyer-blessed prose will replace this copy before the first live Stripe Checkout session.",
                                          es: "Esta página es un borrador pendiente de revisión legal. El texto definitivo reemplazará este contenido antes del primer pago real con Stripe Checkout." },
  "legal.incorporation_banner":        { en: "Pulpo is currently being incorporated. The entity details on this page will be finalised once incorporation completes.",
                                          es: "Pulpo está en proceso de constitución. Los datos de la empresa en esta página se finalizarán al completarse la constitución." },

  // /contact page.
  "contact.page.title":                { en: "Contact Pulpo",
                                          es: "Contactar con Pulpo" },
  "contact.page.description":          { en: "Get in touch with the Pulpo team — general enquiries, billing, privacy requests, takedowns.",
                                          es: "Ponte en contacto con el equipo de Pulpo — consultas generales, facturación, privacidad o eliminación de contenido." },
  "contact.page.lede":                 { en: "We'd love to hear from you. Pick the right inbox below to reach the right person fast.",
                                          es: "Nos encantaría saber de ti. Escoge la bandeja correcta para llegar más rápido a la persona indicada." },
  "contact.page.form_coming_soon":     { en: "A web form for contacting us is being added shortly. In the meantime, please email the inbox that best matches your enquiry.",
                                          es: "Pronto vamos a tener un formulario de contacto. Mientras tanto, escríbenos al correo que mejor coincida con tu consulta." },
  "contact.page.inbox_list_label":     { en: "Or email us directly",
                                          es: "O escríbenos directamente" },
  "contact.page.success":              { en: "Message sent. We'll get back to you shortly.",
                                          es: "Mensaje enviado. Te respondemos pronto." },
  "contact.page.error":                { en: "We couldn't send your message just now. Please try again, or email the inbox that best matches your enquiry directly.",
                                          es: "No pudimos enviar tu mensaje en este momento. Inténtalo de nuevo, o escríbenos directamente al correo que mejor coincida con tu consulta." },

  // /contact form fields.
  "contact.form.name_label":           { en: "Your name (optional)",
                                          es: "Tu nombre (opcional)" },
  "contact.form.email_label":          { en: "Your email",
                                          es: "Tu correo electrónico" },
  "contact.form.topic_label":          { en: "What's this about?",
                                          es: "¿Sobre qué nos escribes?" },
  "contact.form.subject_label":        { en: "Subject (optional)",
                                          es: "Asunto (opcional)" },
  "contact.form.message_label":        { en: "Message",
                                          es: "Mensaje" },
  "contact.form.submit":               { en: "Send message",
                                          es: "Enviar mensaje" },
  "contact.form.submitting":           { en: "Sending…",
                                          es: "Enviando…" },

  // Contact topic labels (also used by the topic dropdown when the
  // form lands in feat/contact-form). Default copy mirrors
  // CONTACT_TOPIC_DEFAULT_COPY in web/app/config/contact-routing.ts.
  "contact.topic.general":             { en: "General enquiry",
                                          es: "Consulta general" },
  "contact.topic.billing":             { en: "Billing or subscription",
                                          es: "Facturación o suscripción" },
  "contact.topic.privacy":             { en: "Privacy / data request",
                                          es: "Privacidad / solicitud de datos" },
  "contact.topic.legal":               { en: "Legal / terms",
                                          es: "Legal / términos" },
  "contact.topic.press":               { en: "Press / partnerships",
                                          es: "Prensa / colaboraciones" },
  "contact.topic.abuse":               { en: "Takedown or abuse report",
                                          es: "Eliminación de contenido o reporte de abuso" },
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
const localeMap = { en: "en-US", es: "es-SV" };
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
