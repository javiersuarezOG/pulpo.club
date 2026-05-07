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

function getStoredLocale() {
  try { return localStorage.getItem("pulpo-locale") || DEFAULT_LOCALE; }
  catch { return DEFAULT_LOCALE; }
}

// React hook + global setter
function useLocale() {
  const [locale, setLocaleState] = React.useState(getStoredLocale);
  const setLocale = React.useCallback((next) => {
    if (!LOCALES.includes(next)) return;
    localStorage.setItem("pulpo-locale", next);
    setLocaleState(next);
    document.documentElement.lang = next;
  }, []);
  React.useEffect(() => { document.documentElement.lang = locale; }, [locale]);
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
  "nav.tab.home":            { en: "Home",                es: "Inicio" },
  "nav.tab.browse":          { en: "Browse",              es: "Explorar" },
  "nav.tab.saved":           { en: "Saved",               es: "Guardados" },
  "nav.tab.profile":         { en: "Profile",             es: "Perfil" },
  "nav.tab.signin":          { en: "Sign in",             es: "Entrar" },

  // Hero
  "hero.sub":                { en: "Find land worth wanting in El Salvador. Pulpo brings together titled and off-market land deals in one place.",
                               es: "Encuentra tierra que vale la pena en El Salvador. Pulpo reúne terrenos titulados y off-market en un solo lugar." },
  "hero.cta.browse":         { en: "Browse all listings", es: "Ver todos los terrenos" },
  "hero.cta.see_listing":    { en: "See this listing",    es: "Ver este terreno" },
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
  "footer.tagline":          { en: "Land worth wanting in El Salvador.",
                               es: "Tierra que vale la pena en El Salvador." },
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
  "detail.km_to_beach":      { en: "{n}km to beach",                es: "{n}km a la playa" },
  "detail.on_beach":         { en: "On beach",                      es: "En la playa" },
  "detail.km_to_airport":    { en: "{n}km to airport",              es: "{n}km al aeropuerto" },
  "detail.km_to_town":       { en: "{n}km to town",                 es: "{n}km al pueblo" },
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
  "newsletter.title":        { en: "Get the top 10 land deals every week",
                               es: "Recibe los 10 mejores terrenos cada semana" },
  "newsletter.sub":          { en: "Beachfront, build-ready and off-market — straight to your inbox. Unsubscribe anytime.",
                               es: "Frente a la playa, listos para construir y off-market — directo a tu correo. Cancela cuando quieras." },
  "newsletter.placeholder":  { en: "your@email.com",                es: "tu@correo.com" },
  "newsletter.subscribe":    { en: "Subscribe",                     es: "Suscribirme" },
  "newsletter.success":      { en: "You're in. First digest Monday.",
                               es: "Listo. Primer resumen el lunes." },

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
  "account.profile.lang":    { en: "Preferred language",            es: "Idioma preferido" },
  "account.profile.save":    { en: "Save changes",                  es: "Guardar cambios" },
  "account.profile.saved":   { en: "Changes saved.",                es: "Cambios guardados." },
  "account.profile.email_note": { en: "Email change requires verification.", es: "Cambiar el correo requiere verificación." },
  "account.notif.intro":     { en: "Choose what Pulpo sends you, and how.",
                               es: "Elige qué te envía Pulpo y cómo." },
  "account.notif.saved":     { en: "Preference saved.",             es: "Preferencia guardada." },
  "account.sub.intro":       { en: "Your plan, billing history, and payment details — all in one place.",
                               es: "Tu plan, historial de pagos y detalles — todo en un solo lugar." },
  "account.sub.discover_nudge": { en: "Ready to keep exploring? Head back to Discover →",
                               es: "¿Listo para seguir explorando? Vuelve a Descubrir →" },
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
