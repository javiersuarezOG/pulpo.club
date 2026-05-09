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
  // Nav
  "nav.discover":            { en: "Discover",            es: "Descubrir" },
  "nav.browse":              { en: "Browse",              es: "Explorar" },
  "nav.saved":               { en: "Saved",               es: "Guardados" },
  "nav.login":               { en: "Log in",              es: "Iniciar sesión" },
  "nav.signup_free":         { en: "Sign up — free",      es: "Crear cuenta — gratis" },
  "nav.logout":              { en: "Log out",             es: "Cerrar sesión" },
  "nav.account_or_sign_in":  { en: "Sign in or create an account", es: "Inicia sesión o crea una cuenta" },
  "nav.tab.home":            { en: "Home",                es: "Inicio" },
  "nav.tab.browse":          { en: "Browse",              es: "Explorar" },
  "nav.tab.saved":           { en: "Saved",               es: "Guardados" },
  "nav.tab.profile":         { en: "Profile",             es: "Perfil" },
  "nav.tab.signin":          { en: "Sign in",             es: "Entrar" },

  // Hero
  "hero.sub":                { en: "Find properties worth wanting in El Salvador. Pulpo brings together titled and off-market listings — land, beachfront homes, and more — in one place.",
                               es: "Encuentra propiedades que valen la pena en El Salvador. Pulpo reúne anuncios titulados y off-market — terrenos, casas frente al mar y más — en un solo lugar." },
  "hero.cta.browse":         { en: "Browse all listings", es: "Ver todas las propiedades" },
  "hero.cta.see_listing":    { en: "See this listing",    es: "Ver este anuncio" },
  "hero.featured_today":     { en: "Featured today",      es: "Destacado hoy" },

  // Pill rail
  "pill.all":                { en: "All",                 es: "Todos" },

  // Card
  "card.listings_count":     { en: "listings",            es: "terrenos" },
  "card.in":                 { en: "in",                  es: "en" },
  "card.see_all":            { en: "See all",             es: "Ver todos" },
  "browse.in_country":       { en: "listings in El Salvador",    es: "terrenos en El Salvador" },
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
  "filter.land_type":        { en: "Land type",           es: "Tipo de terreno" },
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

  // Saved
  "saved.title":             { en: "Saved",               es: "Guardados" },
  "saved.empty.title":       { en: "Your saved listings will appear here",
                               es: "Tus terrenos guardados aparecerán aquí" },
  "saved.empty.body":        { en: "Browse listings and tap ♡ to save the ones that interest you.",
                               es: "Explora los terrenos y toca ♡ para guardar los que te interesen." },

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
                               es: "Terrenos en El Salvador" },

  // Find Your Style carousel (A.2)
  "style.title":             { en: "Find Your Style",  es: "Encuentra tu estilo" },
  "style.sub":               { en: "Every property in Pulpo has a mood. Pick yours.",
                               es: "Cada propiedad en Pulpo tiene una vibra. Elige la tuya." },

  // Live header stats (PR-4c)
  "stats.sources":           { en: "sources",  es: "fuentes" },
  "stats.listings":          { en: "listings", es: "terrenos" },
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
  "detail.fact.water":       { en: "Water supply",                  es: "Suministro de agua" },
  "detail.fact.water_on":    { en: "On site",                       es: "En sitio" },
  "detail.fact.electricity": { en: "Electricity",                   es: "Electricidad" },
  "detail.fact.power_at":    { en: "At boundary",                   es: "En el lindero" },
  "detail.fact.topography":  { en: "Topography",                    es: "Topografía" },
  "detail.fact.flat_yes":    { en: "Mostly flat",                   es: "Mayormente plano" },
  "detail.fact.flat_no":     { en: "Sloped",                        es: "Inclinado" },
  "detail.fact.beachfront_tier": { en: "Beachfront tier",           es: "Nivel de playa" },
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
                               es: "Crea cuenta para ver 1 razón más por la que elegimos este terreno" },
  "detail.signup_more_reasons_other": { en: "Sign up to see {n} more reasons we picked this listing",
                               es: "Crea cuenta para ver {n} razones más por las que elegimos este terreno" },
  // Free signed-in users: same gated row, but the CTA goes to
  // Stripe checkout instead of the signup modal. Pro users hide
  // the row entirely.
  "detail.upgrade_more_reasons_one":   { en: "Upgrade to Pro to see 1 more reason we picked this listing",
                                          es: "Contrata Pro para ver 1 razón más por la que elegimos este terreno" },
  "detail.upgrade_more_reasons_other": { en: "Upgrade to Pro to see {n} more reasons we picked this listing",
                                          es: "Contrata Pro para ver {n} razones más por las que elegimos este terreno" },
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
                               es: "Este terreno fue vendido o retirado." },
  "detail.sold_banner.days": { en: "It was on the market for {n} days.",
                               es: "Estuvo en el mercado durante {n} días." },
  "detail.sold_banner.cta":  { en: "Browse similar listings in {zone} →",
                               es: "Ver terrenos similares en {zone} →" },
  "detail.paywall.title":    { en: "Off-market deal",               es: "Trato off-market" },
  "detail.paywall.body":     { en: "This listing isn't public anywhere else. Pulpo Pro members get direct access plus broker intros.",
                               es: "Este terreno no es público en ningún otro lugar. Los miembros Pulpo Pro tienen acceso directo y conexiones con corredores." },
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
  "locale.toggle_aria":      { en: "Language",                      es: "Idioma" },

  // Newsletter CTA (Discover footer + dedicated form)
  "newsletter.title":        { en: "Get the top 10 property deals every week",
                               es: "Recibe las 10 mejores propiedades cada semana" },
  "newsletter.sub":          { en: "Beachfront, build-ready and off-market — straight to your inbox. Unsubscribe anytime.",
                               es: "Frente a la playa, listas para construir y off-market — directo a tu correo. Cancela cuando quieras." },
  "newsletter.placeholder":  { en: "your@email.com",                es: "tu@correo.com" },
  "newsletter.subscribe":    { en: "Subscribe",                     es: "Suscribirme" },
  "newsletter.signup_cta":   { en: "Sign up to unlock the weekly digest",
                               es: "Crea cuenta para recibir el resumen semanal" },
  "newsletter.success":      { en: "You're in. First digest Monday.",
                               es: "Listo. Primer resumen el lunes." },

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
  "plans.free.feat.off_market_excluded": { en: "Off-market deals",          es: "Ofertas off-market" },
  "plans.free.feat.newsletter_excluded": { en: "Weekly newsletter",         es: "Boletín semanal" },
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
  "plans.pro.feat.everything_in_free": { en: "Everything in Free",        es: "Todo lo del plan Gratis" },
  "plans.pro.feat.unlimited_details":  { en: "Unlimited listing details", es: "Detalles de propiedades ilimitados" },
  "plans.pro.feat.off_market":         { en: "Off-market deal access",    es: "Acceso a ofertas off-market" },
  "plans.pro.feat.newsletter":         { en: "Weekly curated newsletter", es: "Boletín semanal curado" },
  "plans.pro.feat.unlimited_saves":    { en: "Save unlimited listings",   es: "Guarda propiedades ilimitadas" },
  "plans.pro.feat.price_alerts":       { en: "Price-drop alerts on saved",
                                         es: "Alertas de bajada de precio en guardados" },
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
  "saved.browse_cta":        { en: "Browse listings →",             es: "Ver terrenos →" },

  // Filter chip labels (PR-6)
  "filter.photos":           { en: "Photos",                        es: "Fotos" },
  "filter.size_min":         { en: "Min: {n} ha",                   es: "Mín: {n} ha" },
  "filter.show_count":       { en: "Show {n} listings",             es: "Ver {n} terrenos" },
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
  "filter.photos_all":       { en: "All listings",                  es: "Todos los terrenos" },
  "filter.photos_with":      { en: "With photos",                   es: "Con fotos" },
  "filter.photos_none":      { en: "No photos",                     es: "Sin fotos" },

  // Account area (A.3)
  "nav.account":             { en: "Account",                       es: "Cuenta" },
  "account.back":            { en: "← Back to Discover",            es: "← Volver a Descubrir" },
  "account.profile":         { en: "Profile",                       es: "Perfil" },
  "account.notifications":   { en: "Notifications",                 es: "Notificaciones" },
  "account.subscription":    { en: "Manage Subscription",           es: "Suscripción" },
  "account.security":        { en: "Security",                      es: "Seguridad" },
  "account.profile.name":    { en: "Full name",                     es: "Nombre completo" },
  "account.profile.email":   { en: "Email address",                 es: "Correo electrónico" },
  "account.profile.photo":   { en: "Profile photo",                 es: "Foto de perfil" },
  "account.profile.country": { en: "Country / region",              es: "País / región" },
  "account.profile.country_placeholder": { en: "Type to search…",   es: "Escribe para buscar…" },
  "account.profile.lang":    { en: "Preferred language",            es: "Idioma preferido" },
  "account.profile.save":    { en: "Save changes",                  es: "Guardar cambios" },
  "account.profile.saved":   { en: "Changes saved.",                es: "Cambios guardados." },
  "account.profile.email_note": { en: "Email change requires verification.", es: "Cambiar el correo requiere verificación." },
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
