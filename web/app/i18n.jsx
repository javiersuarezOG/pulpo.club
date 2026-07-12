import React from "react";
import { ACTIVE_COUNTRY } from "./config/countries";
import { track } from "./telemetry/client";

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
//
// Fallback uses truthiness (||), not nullishness (??), so an EMPTY slot
// falls through instead of rendering "". This matters for the honest-slot
// fix in the listings adapter: a Spanish-only listing is stored as
// { en: "", es: "…" } so its language is not mislabeled as English; an
// English-locale user must then fall back to the (non-empty) es string
// rather than seeing a blank title. Order: requested locale → default
// locale → first non-empty side → "".
function tr(value, locale) {
  if (value == null) return value;
  if (Array.isArray(value)) return value.map(v => tr(v, locale));
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    return (
      value[locale] ||
      value[DEFAULT_LOCALE] ||
      Object.values(value).find(v => typeof v === "string" && v) ||
      ""
    );
  }
  return value;
}

// UI strings table.
// Keep keys descriptive and grouped. In a real app this becomes en.json / es.json.
// Exported (read-only) so capability-contract tests can iterate the table —
// e.g. plans-copy.test.ts asserts the Free plan never advertises a Pro-gated
// capability. Do not mutate at runtime.
export const UI_STRINGS = {
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
  "new_hero.tagline":        { en: "No more scrolling through 50 listing sites. We rank every beach and lake listing by value and deliver the 10 best to your inbox every week.",
                               es: "Olvídate de buscar en 50 sitios. Rankeamos cada propiedad de playa y lago por valor y te enviamos las 10 mejores al correo cada semana." },
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
  "usp.col_1_title":             { en: "10 best deals, every week",
                                   es: "Las 10 mejores ofertas, cada semana" },
  "usp.col_1_body":              { en: "Matched to your filters. Straight to your inbox.",
                                   es: "Filtradas por lo que buscas. Directo a tu correo." },
  "usp.col_2_title":             { en: "Full catalogue, anytime",
                                   es: "Catálogo completo, cuando quieras" },
  "usp.col_2_body":              { en: `Every property in ${ACTIVE_COUNTRY.name_en}. Yours to filter, sort, and save.`,
                                   es: `Cada propiedad en ${ACTIVE_COUNTRY.name_es}. Tuya para filtrar, ordenar y guardar.` },
  "usp.col_3_title":             { en: "Built by locals",
                                   es: "Hecho por locales" },
  "usp.col_3_body":              { en: "We live on this coast. We know which listings are real and which are overpriced.",
                                   es: "Vivimos en la costa. Sabemos qué es real y qué está inflado." },

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
  "home.hero.h1.before":         { en: "Every beach and lake property in El Salvador,",
                                   es: "Todas las propiedades de playa y lago de El Salvador," },
  "home.hero.h1.italic":         { en: "ranked.",
                                   es: "rankeadas." },
  "home.hero.subhead":           { en: "We scan every site, rank every beach and lake listing by value, and deliver the 10 best to your inbox every week.",
                                   es: "Revisamos todos los sitios, rankeamos cada propiedad de playa y lago por valor, y te enviamos las 10 mejores ofertas al correo cada semana." },
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
  "home.hero.v4.subhead":        { en: "Your top deals — beach, lake, or both — in your inbox every Sunday.",
                                   es: "Tus mejores ofertas — playa, lago o ambos — en tu correo cada domingo." },
  "home.hero.v4.featured_today": { en: "Featured today",
                                   es: "Destacado hoy" },
  "home.hero.v4.photo_aria":     { en: "Open today's featured listing in {name}",
                                   es: "Abrir el destacado de hoy en {name}" },

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

  // ── HeroV5 (Wave-6) — "Sunday morning, coffee, your top 10 properties."
  // Renders when the `hero_v5` feature flag is on, replacing HeroV4 and
  // PickShoreline (the 5 destination cards absorb the shoreline picker).
  // Copy was iterated on with Javier in the Pulpo mockup at
  // /tmp/pulpo-home-hero-v2.html; tweaks below should keep the editorial
  // newsletter voice intact ("Domingo en la mañana, café, …").
  "home.hero.v5.h1_a":           { en: "Sunday morning, coffee, and…",
                                   es: "Domingo en la mañana, café, y…" },
  "home.hero.v5.h1_b":           { en: "your top 10 properties.",
                                   es: "tu top 10 propiedades." },
  // Identity line — niche emphasized for skimming.
  "home.hero.v5.sub_pre":        { en: "Pulpo is your personal real estate agent for ", es: "Pulpo es tu agente inmobiliario personal para " },
  "home.hero.v5.sub_em":         { en: "beach & lake property",                es: "propiedades de playa y lago" },
  "home.hero.v5.sub_post":       { en: " in El Salvador.",                     es: " en El Salvador." },
  // Deliverable line — the payoff, "Your top 10" emphasized.
  "home.hero.v5.sub2_em":        { en: "Your top 10",                          es: "Tu top 10" },
  "home.hero.v5.sub2_post":      { en: " straight to your inbox, every Sunday.", es: " directo a tu correo, cada domingo." },
  // Free-vs-Pro clarifier under the buttons (bold labels for skimming).
  "home.hero.v5.tier_free_label":{ en: "Free",                                 es: "Gratis" },
  "home.hero.v5.tier_free":      { en: " — a weekly email with your top 3.",
                                   es: " — un correo semanal con tu top 3." },
  "home.hero.v5.tier_pro_label": { en: "Pro",                                  es: "Pro" },
  "home.hero.v5.tier_pro":       { en: " — a weekly email with your top 10, plus the full listings catalogue unlocked.",
                                   es: " — un correo semanal con tu top 10, más el catálogo completo desbloqueado." },

  // ── Hero v6 (redesign): lead + 3-point checklist + inline email
  //    capture + the "Pulpo Free" Top-3 card with a locked 4–10 zone.
  "home.hero.v5.lead":           { en: "Pulpo is the best real estate agent you've ever had.",
                                   es: "Pulpo es el mejor agente inmobiliario que has tenido." },
  "home.hero.v5.usp_1":          { en: "Scans every beach & lake listing in El Salvador",
                                   es: "Rastrea cada propiedad de playa y lago en El Salvador" },
  "home.hero.v5.usp_2":          { en: "Ranks them by best value for money",
                                   es: "Las ordena por la mejor relación calidad-precio" },
  "home.hero.v5.usp_3":          { en: "Delivers your top picks to your inbox, every Sunday",
                                   es: "Te envía tus mejores opciones al correo, cada domingo" },
  "home.hero.v5.email_cta":      { en: "Get going — it's free",                 es: "Empieza — es gratis" },
  // Pulpo Free Top-3 card
  "home.hero.v5.card_free_tag":  { en: "Free",                                  es: "Gratis" },
  "home.hero.v5.card_live":      { en: "Live · 6:00 AM",                        es: "En vivo · 6:00 AM" },
  "home.hero.v5.card_title_a":   { en: "Your",                                  es: "Tu" },
  "home.hero.v5.card_title_b":   { en: "Top 3",                                 es: "Top 3" },
  "home.hero.v5.card_title_c":   { en: "this week",                             es: "esta semana" },
  "home.hero.v5.card_kick":      { en: "Ranked by value · filtered to your preferences",
                                   es: "Ordenado por valor · filtrado a tus preferencias" },
  // Personalisation filter bubbles — sample chips that show the list is
  // tuned to the reader (category, zone, budget, property type).
  "home.hero.v5.card_filters_lead": { en: "Your filters",                       es: "Tus filtros" },
  "home.hero.v5.card_filter_1":  { en: "Beach",                                 es: "Playa" },
  "home.hero.v5.card_filter_2":  { en: "Surf City II",                          es: "Surf City II" },
  "home.hero.v5.card_filter_3":  { en: "Under $500k",                           es: "Menos de $500k" },
  "home.hero.v5.card_filter_4":  { en: "Lot",                                   es: "Terreno" },
  "home.hero.v5.grade_value":    { en: "value",                                 es: "valor" },
  "home.hero.v5.lock_more":      { en: "+{n} more in your top 10",              es: "+{n} más en tu top 10" },
  "home.hero.v5.lock_sub":       { en: "Free gives you the top 3 each Sunday. Unlock all 10 — plus the full catalogue — with Pulpo Pro.",
                                   es: "Gratis te da el top 3 cada domingo. Desbloquea las 10 — y el catálogo completo — con Pulpo Pro." },
  "home.hero.v5.lock_cta":       { en: "Unlock with Pulpo Pro",                 es: "Desbloquea con Pulpo Pro" },

  // Hero CTAs (two-state): primary = free newsletter ("Your property
  // tracker", email captured in a modal — no account, Resend only),
  // secondary = Go Pro.
  // Free = "your property tracker": a tool that watches every property
  // site for you and sends the best new listings weekly. Framed as a
  // tracker you start (a utility), not a "Sunday edition" (a magazine).
  "home.hero.v5.cta_free":       { en: "Try Pulpo for free",                   es: "Prueba Pulpo gratis" },
  // Pro CTA — short, with the PRO badge supplying the "Pro" (renders
  // "Get Pulpo [PRO]"). Pro filters to your preferences + unlocks all.
  "home.hero.v5.cta_pro":        { en: "Get Pulpo",                            es: "Consigue Pulpo" },
  // Newsletter capture modal.
  "home.hero.v5.nl_modal_title": { en: "Meet Pulpo, your property agent",      es: "Conoce a Pulpo, tu agente inmobiliario" },
  "home.hero.v5.nl_modal_body":  { en: "Pulpo finds the best properties for sale in El Salvador and emails them to you each week. Free — no account needed.",
                                   es: "Pulpo encuentra las mejores propiedades en venta en El Salvador y te las envía por correo cada semana. Gratis — sin cuenta." },
  "home.hero.v5.nl_placeholder": { en: "you@email.com",                        es: "tu@email.com" },
  "home.hero.v5.nl_cta":         { en: "Put Pulpo to work",                    es: "Pon a Pulpo a trabajar" },
  "home.hero.v5.nl_cta_loading": { en: "Setting it up…",                       es: "Activando…" },
  "home.hero.v5.nl_success_title": { en: "Pulpo's on it.",                     es: "Pulpo está en ello." },
  "home.hero.v5.nl_success":     { en: "Check your inbox to confirm — your first picks land this Sunday.",
                                   es: "Revisa tu inbox para confirmar — tus primeras propiedades llegan este domingo." },
  "home.hero.v5.nl_already":     { en: "You're already on the list — see you Sunday.",
                                   es: "Ya estás en la lista — nos vemos el domingo." },
  "home.hero.v5.nl_error":       { en: "Couldn't sign you up — try again in a moment.",
                                   es: "No pudimos suscribirte — inténtalo de nuevo en un momento." },
  "home.hero.v5.nl_invalid":     { en: "Enter a valid email address.",         es: "Ingresa un correo válido." },
  "home.hero.v5.nl_aria":        { en: "Email address for the free weekly property tracker",
                                   es: "Correo para el rastreador semanal de propiedades gratis" },
  "home.hero.v5.nl_modal_aria":  { en: "Subscribe to the free weekly property tracker",
                                   es: "Suscríbete al rastreador semanal gratis" },
  "home.hero.v5.nl_close":       { en: "Close",                                es: "Cerrar" },

  // "Where to start" subsection above the 5 destination cards.
  "home.hero.v5.section_title":  { en: "Where to start",
                                   es: "Por dónde empezar" },
  "home.hero.v5.section_sub":    { en: "Or keep scrolling for more.",
                                   es: "O seguí bajando para ver más." },

  // 5 destination cards. Slugs (surf_city_1 / surf_city_2 / coatepeque /
  // ilopango) are recognized by pages.jsx#buildFiltersForCategory.
  "home.hero.v5.dest.all.label": { en: "All listings",
                                   es: "Todo el catálogo" },
  "home.hero.v5.dest.all.tag":   { en: "The full catalogue",
                                   es: "Las cuatro regiones" },
  "home.hero.v5.dest.s1.label":  { en: "Surf City I",
                                   es: "Surf City I" },
  "home.hero.v5.dest.s1.tag":    { en: "El Tunco · Sunzal · Zonte",
                                   es: "El Tunco · Sunzal · Zonte" },
  "home.hero.v5.dest.s2.label":  { en: "Surf City II",
                                   es: "Surf City II" },
  "home.hero.v5.dest.s2.tag":    { en: "Las Flores · Punta Mango",
                                   es: "Las Flores · Punta Mango" },
  "home.hero.v5.dest.cp.label":  { en: "Lago Coatepeque",
                                   es: "Lago Coatepeque" },
  "home.hero.v5.dest.cp.tag":    { en: "Santa Ana",
                                   es: "Santa Ana" },
  "home.hero.v5.dest.il.label":  { en: "Lago Ilopango",
                                   es: "Lago Ilopango" },
  "home.hero.v5.dest.il.tag":    { en: "San Salvador",
                                   es: "San Salvador" },

  // Newsletter postcard preview (right column). Editorial format
  // mirroring the Sunday newsletter "MARKET CONTEXT" section. Static —
  // updated by hand alongside the newsletter cadence.
  "home.hero.v5.pc.brand":            { en: "pulpo",
                                        es: "pulpo" },
  "home.hero.v5.pc.issue":            { en: "Issue Nº 47",
                                        es: "Edición Nº 47" },
  "home.hero.v5.pc.date":             { en: "Sunday · June 1, 2026",
                                        es: "Domingo · 1 de junio, 2026" },
  "home.hero.v5.pc.market_eyebrow":   { en: "Market context",
                                        es: "Contexto de mercado" },
  "home.hero.v5.pc.market_title_a":   { en: "What's moving",
                                        es: "Qué se está" },
  "home.hero.v5.pc.market_title_b":   { en: "this week.",
                                        es: "moviendo." },
  // Three numbered insights. `body` allows inline <strong> bolding for
  // place names — rendered with dangerouslySetInnerHTML (i18n-trusted
  // strings only; never user input).
  "home.hero.v5.pc.insight_0_lead":   { en: "Biggest mover:",
                                        es: "Mayor movimiento:" },
  "home.hero.v5.pc.insight_0_body":   { en: "76,259m² lot in <strong>Chiltiupán</strong> cut its ask — developer-scale.",
                                        es: "Lote de 76,259m² en <strong>Chiltiupán</strong> bajó su precio — escala desarrollador." },
  "home.hero.v5.pc.insight_1_lead":   { en: "Second mover:",
                                        es: "Segundo movimiento:" },
  "home.hero.v5.pc.insight_1_body":   { en: "Beachfront home in <strong>Tamanique</strong> dropped $40K — no project tag.",
                                        es: "Casa frente al mar en <strong>Tamanique</strong> bajó $40K — sin tag de proyecto." },
  "home.hero.v5.pc.insight_2_lead":   { en: "The take:",
                                        es: "La toma:" },
  "home.hero.v5.pc.insight_2_body":   { en: "Both moves on Surf City I. Western coast sellers are open to negotiating.",
                                        es: "Ambos movimientos en Surf City I. Los vendedores de la costa oeste están abiertos a negociar." },
  "home.hero.v5.pc.more":             { en: "Read full edition →",
                                        es: "Leé la edición completa →" },
  "home.hero.v5.pc.foot_left":        { en: "Delivered Sundays · 7am",
                                        es: "Cada domingo · 7am" },
  "home.hero.v5.pc.foot_right":       { en: "pulpo.club",
                                        es: "pulpo.club" },

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
  "home.usp.card1.title":        { en: "10 best deals,\nevery week",
                                   es: "Las 10 mejores ofertas,\ncada semana" },
  "home.usp.card1.body":         { en: "Matched to your filters. Straight to your inbox.",
                                   es: "Filtradas por lo que buscas. Directo a tu correo." },
  "home.usp.card2.title":        { en: "Full catalogue,\nanytime",
                                   es: "Catálogo completo,\ncuando quieras" },
  "home.usp.card2.body":         { en: `Every property in ${ACTIVE_COUNTRY.name_en}. Yours to filter, sort, and save.`,
                                   es: `Cada propiedad en ${ACTIVE_COUNTRY.name_es}. Tuya para filtrar, ordenar y guardar.` },
  "home.usp.card3.title":        { en: "Built by locals",
                                   es: "Hecho por locales" },
  "home.usp.card3.body":         { en: "We live on this coast. We know which listings are real and which are overpriced.",
                                   es: "Vivimos en la costa. Sabemos qué es real y qué está inflado." },

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

  // Phase 3 — six type-specific Top 10 shelves replacing the single
  // top10 / dropsHeading / newHeading trio. Beach-first by type
  // ascending (terrenos → condos → homes). Each shelf renders only
  // when ≥5 listings qualify; otherwise the section is hidden. NEW
  // and PRICE-DROP signals now ride on per-card chips (PR #421) so
  // no dedicated shelves for those any more.
  // Wave-6: titles name the actual regions (Surf City I + II,
  // Coatepeque + Ilopango) instead of generic "beach"/"lake". Subs
  // lead with geographic spread + a value-add so each shelf answers
  // "is this for me?". Spanish uses SV "vos"-form ("construí",
  // "mudarte") and "apartamentos" (not "condos") for the unit type.
  "home.shelf.top_beach_terrenos.h2":  { en: "Top 10 lots · Surf City I + II",
                                          es: "Top 10 terrenos · Surf City I + II" },
  "home.shelf.top_beach_terrenos.sub": { en: "El Tunco to Punta Mango — build your own beach place.",
                                          es: "Desde El Tunco hasta Punta Mango — construí tu casa de playa." },
  "home.shelf.top_beach_condos.h2":    { en: "Top 10 condos · Surf City I + II",
                                          es: "Top 10 apartamentos · Surf City I + II" },
  "home.shelf.top_beach_condos.sub":   { en: "Walk-to-surf apartments, low maintenance.",
                                          es: "Apartamentos a la playa caminando, bajo mantenimiento." },
  "home.shelf.top_beach_homes.h2":     { en: "Top 10 homes · Surf City I + II",
                                          es: "Top 10 casas · Surf City I + II" },
  "home.shelf.top_beach_homes.sub":    { en: "Move-in-ready beach houses across both coasts.",
                                          es: "Casas de playa listas para mudarte, en ambas costas." },
  "home.shelf.top_lake_terrenos.h2":   { en: "Top 10 lots · Coatepeque + Ilopango",
                                          es: "Top 10 terrenos · Coatepeque e Ilopango" },
  "home.shelf.top_lake_terrenos.sub":  { en: "Lake-rim land in Santa Ana and San Salvador.",
                                          es: "Terrenos frente al lago, en Santa Ana y San Salvador." },
  "home.shelf.top_lake_condos.h2":     { en: "Top 10 condos · Coatepeque + Ilopango",
                                          es: "Top 10 apartamentos · Coatepeque e Ilopango" },
  "home.shelf.top_lake_condos.sub":    { en: "Turn-key lakeside weekenders on both lakes.",
                                          es: "Escapadas al lago, llave en mano — en ambos lagos." },
  "home.shelf.top_lake_homes.h2":      { en: "Top 10 homes · Coatepeque + Ilopango",
                                          es: "Top 10 casas · Coatepeque e Ilopango" },
  "home.shelf.top_lake_homes.sub":     { en: "Lake-view houses, cooler than the coast — 30–60 min from the capital.",
                                          es: "Casas con vista al lago, más fresco que la costa — a 30–60 min de la capital." },
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
  // PRD A3 — placeholder copy for shelf cards whose listing didn't ship
  // a photo yet. The shelf-aware photo waiver tops up thin shelves with
  // loose-eligible listings (no photo) and stamps `_needs_photo_placeholder`
  // so the card renders this copy in place of <Photo>. Card is still
  // fully clickable; only the visual differs.
  "home.shelf.photo_pending":      { en: "Photo pending",
                                     es: "Foto aún no disponible" },
  "home.shelf.photo_pending_aria": { en: "Photo not yet shared by the listing agent",
                                     es: "El agente aún no ha compartido fotos" },

  "home.badge.today":            { en: "today",
                                   es: "hoy" },
  "home.badge.days_ago":         { en: "{n} days ago",
                                   es: "hace {n} días" },

  // ── Browse filters — Phase 4 rebuild ───────────────────────────────
  // Primary tier: Where / Type / Ranking. Always visible at the top of
  // the FilterPanel — these are the three axes a buyer thinks in.
  "filter.primary.where":        { en: "Where",           es: "Dónde" },
  "filter.primary.type":         { en: "Type",            es: "Tipo" },
  // Price-range "no upper bound" label — replaces an inline
  // `locale === "es" ? "sin tope" : "no max"` ternary at the active-chip
  // and slider-aria sites so the string routes through t() like everything
  // else. ES canary asserts "sin tope" never leaks into the EN UI.
  "filter.price.no_cap":         { en: "no max",          es: "sin tope" },
  // Max-price input placeholder (empty field). EN reads "any" here (not
  // "no max"); ES shares "sin tope".
  "filter.price.max_placeholder": { en: "any",            es: "sin tope" },
  // JSON-LD breadcrumb labels (Browse + Detail). Own keys rather than
  // reusing nav.* so the SEO breadcrumb text ("Browse"/"Explorar") stays
  // independent of the nav tab label ("Discover"/"Descubrir").
  "breadcrumb.home":             { en: "Home",            es: "Inicio" },
  "breadcrumb.browse":           { en: "Browse",          es: "Explorar" },
  "breadcrumb.listing":          { en: "Listing",         es: "Anuncio" },
  "filter.primary.ranking":      { en: "Ranking",         es: "Ranking" },
  "filter.ranking.top10":        { en: "Top 10",          es: "Top 10" },
  "filter.ranking.price_drops":  { en: "Price drops",     es: "Bajó de precio" },
  "filter.ranking.new":          { en: "New this week",   es: "Nuevos esta semana" },
  // Master/sub chip labels — single source of truth for both the
  // Primary tier and the active-filter chips above the result grid.
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
  // Shown in place of the sort dropdown when a search query is active —
  // results are ordered by keyword relevance, not the chosen sort.
  "browse.sort.by_relevance":    { en: "Best match",      es: "Mejor coincidencia" },

  // Map view placeholder — disabled toggle next to cards/table view.
  "view.map_coming_soon":        { en: "Map (coming soon)",
                                   es: "Mapa (próximamente)" },
  // Map view (WS4 PR-7).
  "view.map":                    { en: "Map view",      es: "Vista en mapa" },
  "map.aria":                    { en: "Property listings map", es: "Mapa de propiedades" },
  "map.skeleton.loading":        { en: "Loading map…",   es: "Cargando mapa…" },
  "map.approx_legend":           { en: "Locations are approximate",
                                   es: "Las ubicaciones son aproximadas" },
  "map.mapped_count":            { en: "{shown} of {total} listings mapped",
                                   es: "{shown} de {total} propiedades en el mapa" },
  "map.hide_approx":             { en: "Hide approximate ({n})",
                                   es: "Ocultar aproximadas ({n})" },
  "map.unavailable_for_filter":  { en: "Map unavailable — no mapped listings for this filter.",
                                   es: "Mapa no disponible — no hay propiedades ubicadas para este filtro." },
  "map.marker.aria":             { en: "{price} · {zone} — press Enter to preview",
                                   es: "{price} · {zone} — presiona Enter para ver" },
  "map.cluster.aria":            { en: "{n} listings in this area — click to zoom in",
                                   es: "{n} propiedades en esta zona — haz clic para acercar" },
  "map.popup.approx_location":   { en: "Approximate location",
                                   es: "Ubicación aproximada" },
  "map.popup.view_listing":      { en: "View listing →", es: "Ver propiedad →" },
  "map.search_as_i_move":        { en: "Search as I move", es: "Buscar al mover" },
  "map.search_as_i_move.aria":   { en: "Search as I move the map",
                                   es: "Buscar mientras muevo el mapa" },
  "map.sheet.handle_aria":       { en: "Drag to expand the listings",
                                   es: "Arrastra para ver las propiedades" },
  "map.sheet.results_aria":      { en: "Map listing results",
                                   es: "Resultados del mapa" },
  "map.sheet.row_aria":          { en: "{title}, {price}. Open listing",
                                   es: "{title}, {price}. Abrir propiedad" },
  "map.empty_in_view.title":     { en: "No results in this view",
                                   es: "Sin resultados en esta vista" },
  "map.empty_in_view.show_all":  { en: "Show all {n}",
                                   es: "Mostrar las {n}" },
  "map.empty_in_view.turn_off_saim": { en: "Turn off search as I move",
                                   es: "Desactivar buscar al mover" },

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
  // of land specifically — see `filter.feature.flat`.
  "card.listings_count":     { en: "listings",            es: "propiedades" },
  "card.in":                 { en: "in",                  es: "en" },
  "card.see_all":            { en: "See all",             es: "Ver todos" },
  "browse.in_country":       { en: "listings in El Salvador",    es: "propiedades en El Salvador" },
  // /browse search bar (PR-S1). Exact-lookup substring match over
  // id / source_id / URL / zone / title / source_label / province_state.
  // The placeholder examples — Pulpo id, URL fragment, zone slug — are
  // the lookups the user actually does today (paste an id from a
  // listing card, paste a broker URL, find every listing in a zone).
  "browse.search.placeholder":
    { en: "Search by id, URL, zone, or title",
      es: "Buscar por id, URL, zona o título" },
  "browse.search.aria_label":
    { en: "Search listings",
      es: "Buscar propiedades" },
  "browse.search.clear_aria":
    { en: "Clear search",
      es: "Borrar búsqueda" },
  // Autocomplete dropdown (PR-2) — listbox aria + per-suggestion count.
  "browse.search.suggest.aria":
    { en: "Search suggestions",
      es: "Sugerencias de búsqueda" },
  "browse.search.suggest.count":
    { en: "{n} listings",
      es: "{n} propiedades" },
  "browse.list.use":
    { en: "Use",
      es: "Uso" },
  "browse.list.size":
    { en: "Size",
      es: "Tamaño" },
  "browse.list.price":
    { en: "Price",
      es: "Precio" },
  "browse.list.ppm":
    { en: "{suffix}",
      es: "{suffix}" },
  "browse.list.listed":
    { en: "Listed",
      es: "Publicado" },
  "browse.list.signal":
    { en: "Signal",
      es: "Señal" },
  "browse.list.facts_aria":
    { en: "Listing facts",
      es: "Datos de la propiedad" },
  // No-results-for-query empty state (PR-3) + category-pill shortcuts.
  "browse.search.no_results":
    { en: "No listings matched “{q}”.",
      es: "Ninguna propiedad coincide con “{q}”." },
  "browse.search.no_results.try":
    { en: "Try a category:",
      es: "Prueba una categoría:" },
  "browse.search.pill.beachfront":
    { en: "Beachfront",        es: "Frente al mar" },
  "browse.search.pill.under_100k":
    { en: "Under $100k",       es: "Menos de $100k" },
  "browse.search.pill.new_this_week":
    { en: "New this week",     es: "Nuevas esta semana" },
  "browse.search.pill.price_drops":
    { en: "Price drops",       es: "Rebajas de precio" },
  "browse.search.pill.build_ready":
    { en: "Build-ready",       es: "Listo para construir" },
  "browse.clear_category":   { en: "Clear category",             es: "Quitar categoría" },
  // Top 10 chip header — shows "Top 10" + a count meta like "6 of 10"
  // so a user sees the slice when combining with Beach / Waterfront /
  // price chips. Count = number of global Top 10 that match active
  // filters; the "of 10" anchors the user to the global list.
  "browse.top10.title":      { en: "Top 10",                     es: "Top 10" },
  "browse.top10.of_ten":     { en: "of 10",                      es: "de 10" },
  "browse.top10.clear":      { en: "Clear Top 10 filter",        es: "Quitar filtro Top 10" },
  "card.listed_days_ago":    { en: "Listed {n} days ago", es: "Publicado hace {n} días" },
  "card.listed_1_month":     { en: "Listed 1 month ago",  es: "Publicado hace 1 mes" },
  "card.listed_n_months":    { en: "Listed {n} months ago", es: "Publicado hace {n} meses" },

  // Property-type filter chips. Three values for the Salvadoran market:
  // Residencial (homes for living), Uso comercial (zoned for business),
  // Uso turístico (zoned for hospitality / short-let / Airbnb).
  // 'mixed' + 'raw' removed alongside the chip reduction — they were
  // mock-data-only values that the backend's land_type field never
  // emits. 'agricultural' removed earlier (purged at the pipeline).
  "type.residential":        { en: "Residential",         es: "Residencial" },
  "type.commercial":         { en: "Commercial use",      es: "Uso comercial" },
  "type.tourist":            { en: "Tourism use",         es: "Uso turístico" },

  // Badges
  "badge.price_drop":        { en: "Price drop",          es: "Bajó de precio" },
  "badge.off_market":        { en: "Off-market",          es: "Off-market" },
  "badge.new":               { en: "New",                 es: "Nuevo" },
  "badge.stale":             { en: "Recently missing",    es: "No visto recientemente" },
  "badge.build_ready":       { en: "Build-ready",         es: "Listo para construir" },
  "badge.motivated":         { en: "Motivated seller",    es: "Vendedor motivado" },
  "badge.ocean_view":        { en: "Ocean view",          es: "Vista al mar" },
  "badge.flat":              { en: "Flat",                es: "Plano" },

  // Phase 5 — editorial deal-grade chip on ListingCard. Derived from
  // rank_score thresholds (≥85 / ≥75 / ≥65 / else hidden) and shown
  // below the price as Pulpo's editorial signal: "we say this is an
  // A+ deal." Kept short — the chip is a one-glance read.
  "deal_grade.a_plus":       { en: "A+ deal",             es: "Oferta A+" },
  "deal_grade.a":            { en: "A deal",              es: "Oferta A" },
  "deal_grade.b_plus":       { en: "B+ deal",             es: "Oferta B+" },

  // Filter / browse
  "filter.title":            { en: "Filters",             es: "Filtros" },
  "filter.clear":            { en: "Clear all",           es: "Limpiar todo" },
  "filter.zone":             { en: "Location",            es: "Ubicación" },
  "filter.zone.more_places": { en: "More places",         es: "Otros lugares" },
  "filter.price":            { en: "Price",               es: "Precio" },
  // Filter values cover residential / commercial / tourist / mixed /
  // raw — broad use categories, not strictly plots-of-land
  // (agricultural was removed alongside the agricultural-listing
  // purge). Renamed to "Property type" / "Tipo de propiedad"
  // to match Pulpo's broadened scope (houses + lots, not just land).
  // The i18n key keeps `land_type` for back-compat with the filter
  // state shape — only the user-visible label changes.
  // filter.land_type → filter.use (Phase 4 rename). "Tipo de propiedad"
  // is now the Type primary tier (Homes/Condos/Land); the Use accordion
  // surfaces Residencial/Uso comercial/Uso turístico.
  "filter.use":              { en: "Use",                 es: "Uso" },
  "filter.land_type":        { en: "Use",                 es: "Uso" },
  "filter.size":             { en: "Size",                es: "Tamaño" },
  "filter.features":         { en: "Key features",        es: "Características" },
  "filter.infrastructure":   { en: "Infrastructure",      es: "Infraestructura" },
  // filter.status + filter.readiness section labels removed alongside
  // their FilterGroups (Phase 1 of the rewrite). New + Price-drop now
  // surface via the PillRail Ranking group + per-card badges;
  // Off-market + Motivated retired as ambiguous; Readiness was opaque.

  // "Tune the ranking" advanced panel — the collapsible block below
  // the primary filters that lets power users move the composite-score
  // weights. Paired with the methodology modal below (rank.method.*).
  "filter.ranking.tune":          { en: "Tune the ranking",         es: "Ajusta el ranking" },
  "filter.ranking.how":           { en: "How we rank",              es: "¿Cómo calculamos esto?" },
  "filter.ranking.min_score":     { en: "Investment score",         es: "Puntaje mínimo" },
  "filter.ranking.weight_value":  { en: "Price vs. comps",          es: "Precio vs. comparables" },
  "filter.ranking.weight_loc":    { en: "Location",                 es: "Ubicación" },
  "filter.ranking.weight_mom":    { en: "Area momentum",            es: "Momentum del área" },
  "filter.ranking.reset":         { en: "Reset to defaults",        es: "Restablecer" },
  "filter.ranking.hint":          {
    en: `Pick "Best match (your weights)" in the sort dropdown to use your weights.`,
    es: `Elige "Mejor coincidencia (tus pesos)" en el orden para usar tus pesos.`,
  },

  // "How we rank" methodology modal — explains the composite the
  // ranker.py weights produce.
  "rank.method.title":            { en: "How we rank",                                                                          es: "Cómo clasificamos" },
  "rank.method.tagline":          { en: "Every listing gets a 0–100 composite score from three plain-English dimensions.",      es: "Cada propiedad recibe un puntaje compuesto de 0–100 basado en tres dimensiones simples." },
  "rank.method.value_h":          { en: "Price vs. comparable lots",                                                            es: "Precio vs. comparables" },
  "rank.method.value_p":          {
    en: "How cheap this listing is per square meter compared to similar lots in the same area. 100 = cheapest comparable; 0 = most expensive.",
    es: "Qué tan barato es por m² comparado con lotes similares en la misma zona. 100 = el más barato; 0 = el más caro.",
  },
  "rank.method.loc_h":            { en: "Location & accessibility",                                                             es: "Ubicación y accesibilidad" },
  "rank.method.loc_p":            {
    en: "Zone tier, beachfront, paved access, water/power on the lot, and proximity to the nearest international airport.",
    es: "Posición y acceso del lote — beneficio de zona, frente al mar, acceso pavimentado, agua y luz, cercanía al aeropuerto.",
  },
  "rank.method.mom_h":            { en: "Area momentum",                                                                        es: "Momentum del área" },
  "rank.method.mom_p":            {
    en: "How often listings get repriced down (motivated sellers) and how quickly new inventory appears in each zone.",
    es: "Qué tan caliente está la zona — re-precios indican vendedores motivados; nuevo inventario indica demanda creciente.",
  },
  "rank.method.composite_h":      { en: "The composite",                                                                        es: "El compuesto" },
  "rank.method.composite_f":      {
    en: "composite = 0.40 × Price vs Comps + 0.35 × Location + 0.25 × Momentum",
    es: "compuesto = 0.40 × Precio + 0.35 × Ubicación + 0.25 × Momentum",
  },
  "rank.method.footer":           {
    en: `Move the weights under "Tune the ranking" to see your own composite.`,
    es: `Mueve los pesos en "Ajusta el ranking" para ver tu propio compuesto.`,
  },

  // Detail
  "detail.back":             { en: "Back to results",     es: "Volver a resultados" },
  "detail.reasons":          { en: "Reasons to buy",      es: "Razones para comprar" },
  "detail.key_facts":        { en: "Key facts",           es: "Datos clave" },
  "detail.location":         { en: "Location",            es: "Ubicación" },
  // Location-precision note rendered next to the zone label on the
  // detail page. Drives off ranked.json's `geocoding_source` field via
  // web/app/lib/location-precision.ts. The "approximate" copy carries
  // the visit-time warning explicitly because the FE has been silently
  // plotting zone-centroid coordinates as if they were exact.
  "detail.location.precision.precise.title":
    { en: "Exact location from broker",
      es: "Ubicación exacta confirmada por el corredor" },
  "detail.location.precision.approximate.title":
    { en: "Approximate location",
      es: "Ubicación aproximada" },
  "detail.location.precision.approximate.body":
    { en: "Based on the broker's published area. Confirm the exact address before visiting.",
      es: "Basada en la zona publicada por el corredor. Confirma la dirección exacta antes de visitar." },
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
  "stats.listings":          { en: "listings", es: "propiedades" },

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
  // Results table (desktop) column headers + the per-row rank screen-reader label.
  "browse.table.col.listing": { en: "Listing",  es: "Propiedad" },
  "browse.table.col.zone":    { en: "Zone",     es: "Zona" },
  "browse.table.col.type":    { en: "Type",     es: "Tipo" },
  "browse.table.col.size":    { en: "Size",     es: "Tamaño" },
  "browse.table.col.price":   { en: "Price",    es: "Precio" },
  "browse.table.col.days":    { en: "Days",     es: "Días" },
  "browse.table.col.signal":  { en: "Signal",   es: "Señal" },
  "browse.table.rank_aria":   { en: "Pulpo ranked {rank}", es: "Clasificación Pulpo {rank}" },

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
  // Built-property (house/condo) fact tiles — plan 010. Presence-gated
  // on sparse ranked.json fields; plan 009/011 raise coverage.
  "detail.fact.bedrooms":       { en: "Bedrooms",        es: "Habitaciones" },
  "detail.fact.bathrooms":      { en: "Bathrooms",       es: "Baños" },
  "detail.fact.built_area":     { en: "Built area",      es: "Área construida" },
  "detail.fact.year_built":     { en: "Year built",      es: "Año de construcción" },
  "detail.fact.year_renovated": { en: "Renovated",       es: "Remodelado" },
  "detail.fact.parking":        { en: "Parking",         es: "Estacionamiento" },
  "detail.fact.floor":          { en: "Floor",           es: "Piso" },
  "detail.fact.hoa":            { en: "HOA fee",         es: "Cuota de mantenimiento" },
  "detail.fact.furnished":      { en: "Furnished",       es: "Amueblado" },
  "detail.fact.pool":           { en: "Pool",            es: "Piscina" },
  "detail.fact.per_month":      { en: "/month",          es: "/mes" },
  // PriceContextBlock — "How this price compares" section on the
  // detail page. Pill copy + caption. Peer-kind adapts to subcategory
  // (homes / condos / lots / listings). Scope label adapts to the
  // backend cascade tier — same zone / broader macro region / country
  // (zone_comparison_scope on Listing). The unavailable_* keys below
  // are kept for back-compat but are no longer read — the block now
  // renders `null` when no comparison pool qualifies at any tier.
  "detail.price_context.header":             { en: "How this price compares",
                                               es: "Cómo se compara este precio" },
  "detail.price_context.below_avg":          { en: "{pct}% cheaper than typical {kind} in {scope}",
                                               es: "{pct}% más barato que {kind} similares en {scope}" },
  "detail.price_context.near_avg":           { en: "About average for {kind} in {scope}",
                                               es: "En el promedio para {kind} en {scope}" },
  "detail.price_context.above_avg":          { en: "{pct}% above average for {kind} in {scope}",
                                               es: "{pct}% sobre el promedio para {kind} en {scope}" },
  "detail.price_context.caption":            { en: "Average in {scope}: {median} · across {n} similar listings.",
                                               es: "Promedio en {scope}: {median} · de {n} propiedades similares." },
  "detail.price_context.unavailable":        { en: "Not enough listings in {zone} yet to compare prices.",
                                               es: "Aún no hay suficientes propiedades en {zone} para comparar precios." },
  "detail.price_context.unavailable_no_zone": { en: "Not enough listings in this zone yet to compare prices.",
                                                es: "Aún no hay suficientes propiedades en esta zona para comparar precios." },
  "detail.price_context.peer_kind.homes":    { en: "homes",     es: "casas" },
  "detail.price_context.peer_kind.condos":   { en: "condos",    es: "condominios" },
  "detail.price_context.peer_kind.land":     { en: "lots",      es: "lotes" },
  "detail.price_context.peer_kind.listings": { en: "listings",  es: "propiedades" },
  // Scope labels — substituted into {scope} in the pill + caption when
  // the backend cascade falls back from zone to macro or country tier.
  // Currently only SV; add country.GT / country.PA / etc. as MC-N
  // deployments come online.
  "zone.macro.central-pacific":              { en: "the central Pacific region",
                                               es: "la región del Pacífico central" },
  "zone.macro.eastern-pacific":              { en: "the eastern Pacific region",
                                               es: "la región del Pacífico oriental" },
  "zone.macro.gulf-fonseca":                 { en: "the Gulf of Fonseca region",
                                               es: "la región del Golfo de Fonseca" },
  "country.SV":                              { en: "El Salvador",
                                               es: "El Salvador" },
  "detail.signup_to_view_source": { en: "Sign up free to view source listing",
                               es: "Crea una cuenta gratis para ver el anuncio original" },
  "detail.view_on":          { en: "View on {source}",              es: "Ver en {source}" },
  "detail.off_market_inquire": { en: "Off-market — see Plans to inquire",
                               es: "Off-market — mira los planes para contactar" },
  "detail.save":             { en: "Save",                          es: "Guardar" },
  "detail.saved":            { en: "Saved",                         es: "Guardado" },
  "detail.share":            { en: "Share",                         es: "Compartir" },
  // Share picker (Airbnb-style modal opened from the Compartir button).
  // Caption strings are kept short so they fit the WhatsApp pre-fill on
  // one screen; the receiving client renders the rich OG card from the
  // /l/<token> URL once PR #2 ships the card generator. Until then the
  // text alone still travels through every channel.
  "share.modal.title":       { en: "Share this listing",            es: "Comparte esta propiedad" },
  "share.channel.whatsapp":  { en: "WhatsApp",                      es: "WhatsApp" },
  "share.channel.sms":       { en: "Messages",                      es: "Mensajes" },
  "share.channel.copy":      { en: "Copy link",                     es: "Copiar enlace" },
  "share.channel.email":     { en: "Email",                         es: "Correo electrónico" },
  "share.channel.facebook":  { en: "Facebook",                      es: "Facebook" },
  "share.channel.tiktok":    { en: "TikTok",                        es: "TikTok" },
  "share.toast.copied":      { en: "Link copied",                   es: "Enlace copiado" },
  "share.toast.tiktok":      { en: "Link copied — paste in TikTok", es: "Enlace copiado — pega en TikTok" },
  // Caption hook chosen from listing facts, in priority order. Pulpo
  // brand never includes broker name — see the rule in CLAUDE.md.
  "share.hook.beach_walk":   { en: "{minutes} min walk to beach 🌊", es: "{minutes} min a pie a la playa 🌊" },
  "share.hook.beach_drive":  { en: "{km} km from the beach 🌊",      es: "a {km} km de la playa 🌊" },
  "share.hook.lake":         { en: "On the lake",                   es: "Frente al lago" },
  "share.hook.generic":      { en: "On Pulpo",                      es: "En Pulpo" },
  "share.email.subject":     { en: "{title} on Pulpo",              es: "{title} en Pulpo" },
  "share.aria.dialog":       { en: "Share this listing",            es: "Compartir esta propiedad" },
  "share.aria.close":        { en: "Close share menu",              es: "Cerrar menú de compartir" },
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
  // Pinned-card tag for share-link landings (BrowsePage reads ?pin).
  // Renders only on the one card the share recipient was sent to; the
  // moment they filter/sort/close the panel the tag and ?pin both clear.
  "card.shared_pill":        { en: "Shared with you",               es: "Compartido contigo" },

  // DataFetchFailed — hard error UI shown when /data/ranked.json
  // doesn't load. Was full English; same i18n sweep.
  "data_fetch_failed.title": { en: "We couldn't load the listings.",
                               es: "No pudimos cargar las propiedades." },
  "data_fetch_failed.body":  { en: "This is on us. The data feed didn't respond — try again in a moment.",
                               es: "El problema es nuestro. El servidor de datos no respondió — inténtalo en un momento." },

  // Newsletter CTA — deleted in the rewrite cutover (Phase 9) with the
  // legacy NewsletterCTA component. The new homepage's hero email
  // form (Hero.jsx) reads the new_hero.* keys higher up in this file.

  // Plans page — full string set. The displayed Pro price comes from
  // web/app/lib/pricing.ts (geo-aware: EUR or USD). The {price}
  // placeholder used below already includes the currency glyph, so
  // these templates must NOT hard-code € or $.
  "plans.head.title":        { en: "Pick a plan that fits how you invest.",
                               es: "Escoge el plan que mejor se ajuste a cómo inviertes." },
  "plans.head.subtitle":     { en: "Pulpo is free to browse. Upgrade for unlimited details, off-market access, and weekly alerts.",
                               es: "Explorar Pulpo es gratis. Hazte Pro para ver detalles sin límite, acceso off-market y alertas semanales." },
  // Free tier
  "plans.free.name":         { en: "Free",                    es: "Gratis" },
  "plans.free.tag":          { en: "Browse the catalogue",    es: "Explora el catálogo" },
  "plans.free.feat.browsing":         { en: "Unlimited card browsing",      es: "Explora tarjetas sin límite" },
  "plans.free.feat.top3_detail":      { en: "Full details on this week's top 3", es: "Ficha completa del top 3 de la semana" },
  "plans.free.feat.weekly_email":     { en: "Weekly top-3 email every Sunday",   es: "Correo semanal con tu top 3 cada domingo" },
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
  // Listings remain in USD (El Salvador's currency); the Pulpo Pro
  // subscription is geo-billed — EUR for EU diaspora, USD for
  // everyone else (mirrors api/stripe/_geo.js + web/app/lib/pricing.ts).
  // This footnote keeps the listing-vs-subscription currency story
  // explicit for both audiences.
  "plans.pro.currency_note": { en: "Listings are priced in USD. Pulpo Pro is billed in your local currency (EUR or USD).",
                               es: "Los precios de las propiedades aparecen en USD. Pulpo Pro se factura en tu moneda local (EUR o USD)." },
  // Pro feature list — PlansPage now uses the three canonical `pro.usp.*.headline`
  // keys above, plus this single "Everything in Free" caboose. The five legacy
  // bullets (unlimited_details, off_market, newsletter, unlimited_saves,
  // price_alerts) were removed in PR-B.4a — their content is covered by the
  // three canonical USPs (alerts covers newsletter + price_alerts; browse
  // covers unlimited_details; links covers off_market access).
  "plans.pro.feat.everything_in_free": { en: "Everything in Free",        es: "Todo lo que incluye el plan Gratis" },
  // Pro-user state on the Pro card — replaces the upgrade CTA so a paying
  // member doesn't see a re-checkout button on their own plan.
  "plans.pro.cta_current":   { en: "Your plan",                es: "Tu plan" },
  "plans.pro.current_ribbon": { en: "Your current plan",       es: "Tu plan actual" },
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
  "plans.upgrade_pro_cta":   { en: "Upgrade — {price}/month",
                               es: "Hazte Pro — {price}/mes" },
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
  // filter.status.* + filter.readiness.* removed alongside their UI
  // (Phase 1 of the rewrite). State + predicate stay so URL routing
  // and PillRail still work.
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
  // Free-member settings view (email-only, no Clerk account).
  "account.free.title":       { en: "Your Pulpo",                    es: "Tu Pulpo" },
  "account.free.badge":       { en: "Pulpo Free",                    es: "Pulpo Free" },
  "account.free.value":       { en: "This week's top 3 — the best new beach & lake listings — in your inbox every Sunday.", es: "El top 3 de esta semana — las mejores propiedades nuevas de playa y lago — en tu correo cada domingo." },
  "account.free.email_label": { en: "Your email",                    es: "Tu correo" },
  "account.free.email_hint":  { en: "This is where your weekly picks land. To stop them, use the unsubscribe link in any Pulpo email.", es: "Aquí llegan tus selecciones semanales. Para detenerlas, usa el enlace para darte de baja en cualquier correo de Pulpo." },
  "account.free.signout":     { en: "Sign out",                      es: "Cerrar sesión" },
  "account.guest.title":      { en: "Your account",                 es: "Tu cuenta" },
  "account.guest.body":       { en: "Sign in to manage your subscription and preferences — or head back to this week's picks.", es: "Inicia sesión para gestionar tu suscripción y preferencias, o vuelve a las selecciones de esta semana." },
  "account.guest.home":       { en: "Back to home",                 es: "Volver al inicio" },
  "account.profile":         { en: "Profile",                       es: "Perfil" },
  // Renamed `notifications` → `newsletter` 2026-05-29. The legacy key
  // is preserved for back-compat with cached bundles during rollout.
  "account.notifications":   { en: "Newsletter",                    es: "Newsletter" },
  "account.newsletter":      { en: "Newsletter",                    es: "Newsletter" },
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
  "account.profile.saving":  { en: "Saving…",                       es: "Guardando…" },
  "account.profile.saved":   { en: "Changes saved.",                es: "Cambios guardados." },
  "account.profile.email_note": { en: "Email change requires verification.", es: "Cambiar el correo requiere verificación." },
  "account.profile.email_change_link": { en: "Change in Security",  es: "Cambiar en Seguridad" },
  // Photo upload helper + states. The numeric "2 MB" stays in both
  // locales because it's a hard client-side limit, not a copy choice.
  "account.profile.upload_helper":     { en: "JPG, PNG or WebP, up to 2 MB.",
                                          es: "JPG, PNG o WebP, hasta 2 MB." },
  "account.profile.uploading":         { en: "Uploading…",          es: "Subiendo…" },
  "account.profile.upload_failed":     { en: "Couldn't upload — please try again.",
                                          es: "No pudimos subir — inténtalo de nuevo." },
  "account.profile.upload_too_big":    { en: "Image must be 2 MB or smaller.",
                                          es: "La imagen debe ser de 2 MB o menos." },
  "account.profile.upload_wrong_type": { en: "JPG, PNG or WebP only.",
                                          es: "Solo JPG, PNG o WebP." },
  "account.profile.remove_photo":      { en: "Remove photo",        es: "Quitar foto" },
  // Surfaced when an optimistic profile update (preferred categories,
  // future fields) fails to persist to Clerk and the UI rolls back.
  "account.profile.sync_failed": { en: "Couldn't save your preferences — please try again.",
                                    es: "No pudimos guardar tus preferencias — inténtalo de nuevo." },
  "account.notif.intro":     { en: "Choose what Pulpo sends you, and how.",
                               es: "Elige qué te envía Pulpo y cómo." },
  // Cadence is weekly (Sundays at 9 AM) post-2026-05-29; copy here
  // reflects that.
  "account.notif.cadence_note": { en: "Pulpo sends a weekly newsletter on Sunday mornings. Tune what you receive with the filters below.",
                                   es: "Pulpo envía un boletín semanal los domingos por la mañana. Ajusta qué recibes con los filtros de abajo." },

  // Upsell card. Title + bullet text re-use "newsletter.title" deliberately
  // so the upsell mirrors what the user lands on once they convert.
  "account.notif.newsletter.title":  { en: "Weekly newsletter",
                                        es: "Boletín semanal" },

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
  "account.notif.newsletter_filter.locations":
    { en: "Locations to follow",                          es: "Ubicaciones a seguir" },
  "account.notif.newsletter_filter.locations_help":
    { en: "Tap a zone to follow every place in it, or pick individual spots.",
      es: "Toca una zona para seguir todos sus lugares, o elige sitios individuales." },
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
  // ── Grace-period banner (14-day window after a failed payment) ───
  // Renders above the plan card on /account?section=subscription when
  // publicMetadata.subscription_status === "past_due" and the grace
  // window hasn't closed yet. CTA bounces to Stripe Customer Portal.
  "account.sub.grace.head":         { en: "Your card couldn't be charged",
                                      es: "No pudimos cobrar tu tarjeta" },
  "account.sub.grace.copy":         { en: "Pulpo Pro stays active for {days} more days and expires on {date}. Update your card to keep it.",
                                      es: "Pulpo Pro sigue activo por {days} días más y vence el {date}. Actualiza tu tarjeta para mantenerlo." },
  "account.sub.grace.cta_update_card": { en: "Update card", es: "Actualizar tarjeta" },
  // Grace expired — user is back on Free, but we say "reactivate"
  // rather than "upgrade" because their subscription history is intact.
  "account.sub.grace_expired.head": { en: "Pulpo Pro paused — payment overdue",
                                      es: "Pulpo Pro en pausa — pago vencido" },
  "account.sub.grace_expired.copy": { en: "Your 14-day grace period has ended. Reactivate to get Pro back.",
                                      es: "Tu periodo de gracia de 14 días terminó. Reactiva para recuperar Pulpo Pro." },
  "account.sub.grace_expired.cta_reactivate": { en: "Reactivate", es: "Reactivar" },

  // ── Subscription plan card — period + cancellation copy (post-2026-05-27) ──
  // Replaces hardcoded "Renews on 5 Jun 2026" placeholder. Branches by
  // sub-state display value derived in lib/subscription.ts:
  //   active     → renews_on copy + status_active pill
  //   canceling  → cancels_on copy + status_canceling pill (NEVER "Renews on")
  //   canceled   → ended_on copy + status_canceled pill
  //   past_due   → grace banner already handles copy; pill = status_past_due
  // {date} is a localized date (no time) from current_period_end / canceled_at.
  "account.sub.plan_meta.renews_on":   { en: "Renews on {date}",
                                          es: "Se renueva el {date}" },
  "account.sub.plan_meta.cancels_on":  { en: "Cancels on {date}",
                                          es: "Se cancela el {date}" },
  "account.sub.plan_meta.ended_on":    { en: "Subscription ended on {date}",
                                          es: "Suscripción finalizada el {date}" },
  "account.sub.plan_meta.free":        { en: "Browse the catalogue, no card required.",
                                          es: "Explora el catálogo, sin tarjeta." },
  // Status copy line below the plan name. Mirrors plan_meta with a
  // softer, longer-form phrasing.
  "account.sub.status_copy.active":    { en: "Your plan is active — renews on {date}.",
                                          es: "Tu plan está activo — se renueva el {date}." },
  "account.sub.status_copy.canceling": { en: "You've cancelled. Pulpo Pro stays active until {date}, then your account drops back to Free.",
                                          es: "Has cancelado. Pulpo Pro permanece activo hasta el {date}, luego tu cuenta vuelve a Gratis." },
  "account.sub.status_copy.canceled":  { en: "Your Pulpo Pro subscription ended on {date}. Resubscribe anytime to get Pro back.",
                                          es: "Tu suscripción a Pulpo Pro terminó el {date}. Vuelve a suscribirte cuando quieras." },
  "account.sub.status_copy.free":      { en: "You're on the free plan. Upgrade for off-market access and weekly alerts.",
                                          es: "Estás en el plan Gratis. Hazte Pro para acceder a propiedades off-market y al digest semanal." },
  "account.sub.refreshing":            { en: "Refreshing your plan…",
                                          es: "Actualizando tu plan…" },
  // Status pill labels.
  "account.sub.pill.active":           { en: "Active",     es: "Activa" },
  "account.sub.pill.canceling":        { en: "Canceling",  es: "Cancelando" },
  "account.sub.pill.canceled":         { en: "Canceled",   es: "Cancelada" },
  "account.sub.pill.past_due":         { en: "Payment issue", es: "Problema de pago" },
  // Reactivate CTA shown to canceling + canceled users instead of "Manage plan".
  "account.sub.reactivate":            { en: "Resubscribe →",
                                          es: "Volver a suscribirme →" },
  // Post-cancel "you're on Free now" panel — frames the downgrade as a
  // real choice: keep the free weekly, or resubscribe for the full thing.
  "account.sub.free_panel.head":       { en: "You're on Pulpo Free",
                                          es: "Estás en Pulpo Free" },
  "account.sub.free_panel.body":       { en: "Your weekly top 3 — the best new beach & lake listings — still lands in your inbox every Sunday. Resubscribe to Pro for all 10 plus the full listings catalogue.",
                                          es: "Tu top 3 semanal — las mejores propiedades nuevas de playa y lago — sigue llegando a tu correo cada domingo. Vuelve a Pro para las 10 y el catálogo completo." },

  // ── /start landing + /welcome (acquisition funnel — PR-B) ────────
  // Public marketing surfaces that funnel cold visitors into Stripe
  // Checkout without a Clerk sign-up wall. EN + ES from day one — the
  // smoke-test guardrail at tests/e2e/preview-smoke.spec.ts fails if a
  // canary EN word leaks into the ES render.
  // Login link → opens Clerk hosted sign-in modal (PR-B.4). Keep wording
  // identical to the in-app TopNav so the user sees a consistent "Log in"
  // across surfaces.
  "start.meta.title":        { en: "Pulpo — Beach and lake homes in El Salvador, ranked by value",
                                es: "Pulpo — Casas de playa y de lago en El Salvador, ordenadas por valor" },
  "start.meta.description":  { en: "Get unlimited access to ranked listings across El Salvador. One-time setup, monthly access, cancel anytime.",
                                es: "Acceso ilimitado a propiedades ordenadas en El Salvador. Configuración única, acceso mensual, cancela cuando quieras." },
  "start.hero.eyebrow":       { en: "Real estate in El Salvador",
                                es: "Bienes raíces en El Salvador" },
  "start.hero.h1":            { en: "Property in El Salvador, before the rest of the internet sees it.",
                                es: "Propiedades en El Salvador, antes de que las vea el resto del internet." },
  "start.hero.sub":           { en: "Pulpo curates properties in El Salvador — land, homes, commercial — before they hit the big portals. One weekly digest. No noise.",
                                es: "Pulpo selecciona propiedades en El Salvador — terrenos, casas y locales — antes de que lleguen a los portales grandes. Un resumen semanal. Sin ruido." },
  "start.hero.cta_primary":   { en: "Try a free month — then {price}/month",
                                es: "Pruébalo un mes gratis — luego {price}/mes" },
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
  "start.join.paid.cta":      { en: "Try a free month",
                                es: "Probar un mes gratis" },
  "start.join.paid.cta_submitting": { en: "Opening checkout…",
                                      es: "Abriendo el pago…" },
  "start.join.paid.sub":      { en: "Cancel anytime · Stripe-secured payment · Email collected at checkout",
                                es: "Cancela cuando quieras · Pago seguro con Stripe · Tu correo se registra al pagar" },
  "start.code.applied_note":  { en: "✓ First month free at checkout",
                                es: "✓ Primer mes gratis al pagar" },
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
  "start.sticky_cta":         { en: "Try a free month — then {price}/month",
                                es: "Pruébalo un mes gratis — luego {price}/mes" },
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
  "welcome_modal.anon.body":            { en: "We've sent an email to set up your password. Open it to activate your account.",
                                          es: "Te enviamos un correo para activar tu cuenta. Ábrelo y crea tu contraseña." },
  "welcome_modal.anon.sent_ago":        { en: "Sent {time}.",
                                          es: "Enviado {time}." },
  "welcome_modal.anon.body_postscript": { en: "If you don't see it in a few minutes, check Promotions or Spam.",
                                          es: "Si no aparece en unos minutos, revisa Promociones o Spam." },
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
  "welcome_modal.anon.status.user_exists.forgot_cta": { en: "Forgot your password? Reset it by email.",
                                          es: "¿Olvidaste tu contraseña? Recupérala por correo." },
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
  "start.already_pro.cta":    { en: "Manage your plan",
                                es: "Administrar tu plan" },
  "start.already_pro.note":   { en: "You're already on Pulpo Pro.",
                                es: "Ya tienes Pulpo Pro." },
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
  // Plain, non-native-friendly copy (2026-06-08): short words, one idea
  // per line, concrete benefits. Shared by every Pro-conversion CTA
  // (listing gate, hero, USP, etc.), so it stays generic to the value,
  // not to one entry point.
  // ── Auth chooser (logged-out avatar / account click) ───────────────
  // Two-state model: the account icon offers two clear paths — log in
  // (existing Pro members) or go Pro (new visitors). No free signup.
  "auth_choice.headline":              { en: "Welcome to Pulpo.",                            es: "Bienvenido a Pulpo." },
  "auth_choice.body":                  { en: "Log in to your account, or go Pro to unlock every listing.",
                                          es: "Inicia sesión en tu cuenta, o pasá a Pro para desbloquear cada propiedad." },
  "auth_choice.login":                 { en: "Log in",                                       es: "Iniciar sesión" },
  "auth_choice.get_pro":               { en: "Get Pulpo Pro",                                es: "Obtené Pulpo Pro" },

  // Access v2 — unified "3 ways in" block (hero + every modal), Pulpo voice.
  "access.or":                         { en: "or",                            es: "o" },
  "access.email.placeholder":          { en: "Your email",                    es: "Tu correo" },
  "access.email.aria":                 { en: "Email address",                 es: "Correo electrónico" },
  "access.free.cta":                   { en: "Send me my top 3 →",            es: "Envíame mi top 3 →" },
  "access.free.cta_loading":           { en: "Joining…",                      es: "Uniéndote…" },
  "access.free.note":                  { en: "No account, no card — just your email", es: "Sin cuenta, sin tarjeta — solo tu correo" },
  "access.free.already":               { en: "You're already on the list — see you Sunday.", es: "Ya estás en la lista — nos vemos el domingo." },
  "access.go_pro.cta":                 { en: "Unlock everything — $9.99/mo",  es: "Desbloquea todo — $9.99/mes" },
  "access.go_pro.cta_loading":         { en: "Taking you to checkout…",       es: "Llevándote al pago…" },
  "access.go_pro.sub":                 { en: "Every listing + all 10 of our weekly picks. First month's on us.", es: "Todas las propiedades + las 10 selecciones de la semana. El primer mes va por nuestra cuenta." },
  "access.signin.prefix":              { en: "Already one of us?",            es: "¿Ya eres de los nuestros?" },
  "access.signin.link":                { en: "Sign in",                       es: "Inicia sesión" },
  "access.error.invalid":              { en: "Enter a valid email address.",  es: "Ingresa un correo válido." },
  "access.error.generic":              { en: "Something went wrong. Try again.", es: "Algo salió mal. Inténtalo de nuevo." },
  "access.error.rate_limited":         { en: "Too many attempts just now. Wait a moment and try again.", es: "Demasiados intentos por ahora. Espera un momento e inténtalo de nuevo." },
  "access.modal.top3.title":           { en: "We've picked this week's top 3 for you.", es: "Elegimos el top 3 de esta semana para ti." },
  "access.modal.top3.lead":            { en: "We read every new beach & lake listing in El Salvador and keep the three best. They're yours to open in full — free.", es: "Leemos cada propiedad nueva de playa y lago en El Salvador y nos quedamos con las tres mejores. Son tuyas para abrir completas — gratis." },
  "access.modal.welcome.title":        { en: "Welcome to Pulpo.",             es: "Bienvenido a Pulpo." },
  "access.modal.welcome.lead":         { en: "Start free with this week's top 3, go Pro for everything, or sign in if you're already one of us.", es: "Empieza gratis con el top 3 de esta semana, hazte Pro para todo, o inicia sesión si ya eres de los nuestros." },
  "access.modal.gopro.title":          { en: "Want the whole coast?",         es: "¿Quieres toda la costa?" },
  "access.modal.gopro.lead":           { en: "You've got your free top 3. Go Pro to open every listing and get all 10 of our weekly picks.", es: "Ya tienes tu top 3 gratis. Hazte Pro para abrir todas las propiedades y recibir las 10 selecciones de la semana." },
  "access.modal.aria":                 { en: "Get started with Pulpo",        es: "Empieza con Pulpo" },
  "access.modal.aria.close":           { en: "Close",                         es: "Cerrar" },

  // Free-join celebration — the branded octopus reveal shown on every
  // free-signup success (hero + every gated modal). Deep-sea moment.
  "access.join.title":                 { en: "You're in!",                    es: "¡Ya estás dentro!" },
  "access.join.back_title":            { en: "Welcome back!",                 es: "¡Bienvenido de nuevo!" },
  "access.join.body":                  { en: "The pulpo just sent your top 3 to your inbox. Fresh picks land every Sunday.", es: "El pulpo acaba de enviar tu top 3 a tu correo. Nuevas opciones llegan cada domingo." },
  "access.join.cta":                   { en: "See my picks",                  es: "Ver mis opciones" },
  "access.join.aria":                  { en: "You're now a Pulpo Free member", es: "Ahora eres miembro de Pulpo Free" },
  "access.join.aria.close":            { en: "Close",                         es: "Cerrar" },

  // Email-first "start free" capture modal (anonymous → Free member).
  "email_capture.headline":            { en: "See this week's top 3 — free.",
                                          es: "Mira el top 3 de la semana — gratis." },
  "email_capture.body":                { en: "Add your email to open Pulpo's 3 best new listings in full — and get them in your inbox every Sunday.",
                                          es: "Agrega tu correo para abrir las 3 mejores propiedades nuevas de Pulpo completas — y recíbelas en tu correo cada domingo." },
  "email_capture.bullet.1":            { en: "Open this week's top 3 in full",
                                          es: "Abre el top 3 de la semana completo" },
  "email_capture.bullet.2":            { en: "The 3 best new listings, every Sunday",
                                          es: "Las 3 mejores propiedades nuevas, cada domingo" },
  "email_capture.bullet.3":            { en: "No account, no card — just your email",
                                          es: "Sin cuenta, sin tarjeta — solo tu correo" },
  "email_capture.placeholder":         { en: "you@email.com",                  es: "tu@correo.com" },
  "email_capture.cta":                 { en: "Get the top 3",                  es: "Ver el top 3" },
  "email_capture.cta_loading":         { en: "Joining…",                       es: "Uniéndote…" },
  "email_capture.go_pro":              { en: "Want every listing? Go Pro →",   es: "¿Quieres todas? Hazte Pro →" },
  "email_capture.dismiss":             { en: "Not now",                        es: "Ahora no" },
  "email_capture.invalid":             { en: "Enter a valid email address.",   es: "Ingresa un correo válido." },
  "email_capture.error":               { en: "Something went wrong. Try again.", es: "Algo salió mal. Inténtalo de nuevo." },
  "email_capture.aria.dialog":         { en: "Start free with Pulpo",          es: "Empieza gratis con Pulpo" },
  "email_capture.aria.close":          { en: "Close",                          es: "Cerrar" },
  "email_capture.aria.email":          { en: "Email address",                  es: "Correo electrónico" },

  "free_month_modal.headline":         { en: "Unlock every listing with Pulpo Pro.",
                                          es: "Desbloquea cada propiedad con Pulpo Pro." },
  "free_month_modal.body":             { en: "See full details, all photos, the price, and how to contact the seller. Plus the 10 best new listings in your inbox each week.",
                                          es: "Ve todos los detalles, todas las fotos, el precio y cómo contactar al vendedor. Más las 10 mejores propiedades nuevas en tu correo cada semana." },
  "free_month_modal.bullet.1":         { en: "Open any listing in full",
                                          es: "Abre cualquier propiedad completa" },
  "free_month_modal.bullet.2":         { en: "The 10 best new listings each week",
                                          es: "Las 10 mejores propiedades nuevas cada semana" },
  "free_month_modal.bullet.3":         { en: "Contact sellers directly",
                                          es: "Contacta a los vendedores directamente" },
  "free_month_modal.cta_primary":      { en: "Start free month — then {price}/month",
                                          es: "Empieza gratis un mes — luego {price}/mes" },
  "free_month_modal.cta_primary_submitting": { en: "Opening checkout…",
                                          es: "Abriendo el pago…" },
  "free_month_modal.cta_dismiss":      { en: "Not now",
                                          es: "Ahora no" },
  "free_month_modal.aria.dialog":      { en: "Subscribe to Pulpo Pro",
                                          es: "Suscríbete a Pulpo Pro" },
  "free_month_modal.aria.close":       { en: "Close",
                                          es: "Cerrar" },
  "free_month_modal.error":            { en: "Couldn't open checkout. Try again.",
                                          es: "No pudimos abrir el pago. Inténtalo de nuevo." },
  "free_month_modal.code_applied_note":{ en: "✓ First month free. Cancel anytime.",
                                          es: "✓ Primer mes gratis. Cancela cuando quieras." },

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
  "contact.page.lede":                 { en: "We'd love to hear from you. Send a message below or write to us at hello@pulpo.club.",
                                          es: "Nos encantaría saber de ti. Envíanos un mensaje abajo o escríbenos a hello@pulpo.club." },
  "contact.page.form_coming_soon":     { en: "A web form for contacting us is being added shortly. In the meantime, please email the inbox that best matches your enquiry.",
                                          es: "Pronto vamos a tener un formulario de contacto. Mientras tanto, escríbenos al correo que mejor coincida con tu consulta." },
  "contact.page.inbox_list_label":     { en: "Or email us directly",
                                          es: "O escríbenos directamente" },
  "contact.page.inbox_single_label":   { en: "Email us",
                                          es: "Escríbenos" },
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

  // ── /admin/ig-review (IgReviewWidget) ───────────────────────────────
  // Strings for the IG batch queue admin surface.  Per CLAUDE.md every
  // user-visible string in web/app/ flows through t() — the existing
  // NewsletterWidget inlines English and that's a pre-existing
  // violation we're not propagating into the new widgets.
  "admin.ig_review.aria_root":         { en: "IG batch queue review",
                                          es: "Revisión de la cola de IG" },
  "admin.ig_review.loading":           { en: "Loading queue…",
                                          es: "Cargando cola…" },
  "admin.ig_review.error_heading":     { en: "Couldn't load the queue",
                                          es: "No se pudo cargar la cola" },
  "admin.ig_review.error_body":        { en: "The /api/admin/ig-queue endpoint returned an error: {detail}.",
                                          es: "El endpoint /api/admin/ig-queue devolvió un error: {detail}." },
  "admin.ig_review.empty_heading":     { en: "No queue yet",
                                          es: "Sin cola todavía" },
  "admin.ig_review.empty_body":        { en: "Run the queue builder once the next nightly's ig_candidates.json is committed.",
                                          es: "Corré el queue builder cuando el próximo nightly haya commiteado ig_candidates.json." },
  "admin.ig_review.list_aria":         { en: "Queued items",
                                          es: "Posts en cola" },
  "admin.ig_review.item_aria":         { en: "Day {day}, shelf {shelf}",
                                          es: "Día {day}, shelf {shelf}" },
  "admin.ig_review.poster_alt":        { en: "Poster preview for day {day}",
                                          es: "Vista previa del poster del día {day}" },
  "admin.ig_review.no_poster":         { en: "no poster",
                                          es: "sin poster" },
  "admin.ig_review.listings":          { en: "listings",
                                          es: "listings" },
  "admin.ig_review.caption_expand":    { en: "Show full caption",
                                          es: "Ver caption completo" },
  "admin.ig_review.caption_collapse":  { en: "Collapse caption",
                                          es: "Colapsar caption" },
  "admin.ig_review.lint_alert":        { en: "Caption lint violations",
                                          es: "Violaciones de lint en el caption" },
  "admin.ig_review.lint_prefix":       { en: "Lint flagged",
                                          es: "Lint marcó" },
  "admin.ig_review.action.approve":    { en: "Approve",
                                          es: "Aprobar" },
  "admin.ig_review.action.skip":       { en: "Skip",
                                          es: "Saltar" },
  "admin.ig_review.action.clear":      { en: "Clear",
                                          es: "Quitar" },
  "admin.ig_review.status.pending":    { en: "Pending",
                                          es: "Pendiente" },
  "admin.ig_review.status.approved":   { en: "Approved",
                                          es: "Aprobado" },
  "admin.ig_review.status.skipped":    { en: "Skipped",
                                          es: "Saltado" },
  "admin.ig_review.status.needs_human": { en: "Needs review",
                                           es: "Requiere revisión" },
  "admin.ig_review.status.posted":     { en: "Posted",
                                          es: "Publicado" },
  "admin.ig_review.status.superseded": { en: "Superseded",
                                          es: "Reemplazado" },
  "admin.ig_review.status.scheduled":  { en: "Approved · queued",
                                          es: "Aprobado · en cola" },
  "admin.ig_review.first_comment":     { en: "First comment",
                                          es: "Primer comentario" },
  "admin.ig_review.stat.total":        { en: "Total",
                                          es: "Total" },
  "admin.ig_review.stat.approved":     { en: "Approved",
                                          es: "Aprobado" },
  "admin.ig_review.stat.skipped":      { en: "Skipped",
                                          es: "Saltado" },
  "admin.ig_review.stat.needs_human":  { en: "Needs review",
                                          es: "Requiere revisión" },
  "admin.ig_review.stat.pending":      { en: "Pending",
                                          es: "Pendiente" },
  "admin.ig_review.stat.posted":       { en: "Posted",
                                          es: "Publicado" },
  "admin.ig_review.submit_button":     { en: "Submit batch",
                                          es: "Enviar batch" },
  "admin.ig_review.submit_button_count": {
    en: "Submit {count} decision(s)",
    es: "Enviar {count} decisión(es)",
  },
  "admin.ig_review.submit_disabled_hint": {
    en: "Mark at least one item as Approve or Skip to submit.",
    es: "Marcá al menos un ítem como Approve o Skip para enviar.",
  },
  "admin.ig_review.submit_ready_hint": {
    en: "Send {count} decision(s) to the queue workflow.",
    es: "Enviar {count} decisión(es) al workflow de la cola.",
  },
  "admin.ig_review.submit_submitting": { en: "Submitting…",
                                          es: "Enviando…" },
  "admin.ig_review.submit_submitted":  { en: "Submitted ✓",
                                          es: "Enviado ✓" },
  "admin.ig_review.submit_retry":      { en: "Retry submit",
                                          es: "Reintentar envío" },
  "admin.ig_review.submit_view_run":   { en: "View workflow run →",
                                          es: "Ver workflow →" },
  "admin.ig_review.submit_error_prefix": {
    en: "Submit failed",
    es: "Falló el envío",
  },
  "admin.ig_review.publish_now":       { en: "⚡ Publish now",
                                          es: "⚡ Publicar ahora" },
  "admin.ig_review.publish_now_hint": {
    en: "Test-publish this item to Instagram now (bypasses scheduled_for).",
    es: "Test-publicar este ítem en Instagram ahora (omite scheduled_for).",
  },
  "admin.ig_review.publish_now_submitting": {
    en: "Dispatching…",
    es: "Disparando…",
  },
  "admin.ig_review.publish_now_dispatched": {
    en: "Dispatched ✓",
    es: "Disparado ✓",
  },
  "admin.ig_review.publish_now_retry": {
    en: "Retry publish",
    es: "Reintentar publicación",
  },
  "admin.ig_review.publish_now_error_prefix": {
    en: "Dispatch failed",
    es: "Falló el disparo",
  },
  "admin.ig_review.preview_loading":   { en: "loading…",
                                          es: "cargando…" },
  "admin.ig_review.preview_empty":     { en: "no queue yet",
                                          es: "sin cola todavía" },
  "admin.ig_review.preview_title":     { en: "{total} ITEMS QUEUED",
                                          es: "{total} POSTS EN COLA" },
  "admin.ig_review.preview_items":     { en: "items queued",
                                          es: "posts en cola" },

  // PR-5: full IG-style preview + live dashboard strings
  "admin.ig_review.carousel_aria":     { en: "Day {day} carousel preview",
                                          es: "Vista previa del carrusel del día {day}" },
  "admin.ig_review.slide_alt":         { en: "Slide {n}",
                                          es: "Diapositiva {n}" },
  "admin.ig_review.scheduled":         { en: "Scheduled",
                                          es: "Programado" },
  "admin.ig_review.primary":           { en: "Primary listing",
                                          es: "Listing principal" },
  "admin.ig_review.posted_at":         { en: "Posted at",
                                          es: "Publicado" },
  "admin.ig_review.media_id":          { en: "Media ID",
                                          es: "ID de media" },
  "admin.ig_review.health.next_due":   { en: "Next due",
                                          es: "Próximo" },
  "admin.ig_review.health.nothing_due": { en: "nothing due",
                                           es: "nada pendiente" },
  "admin.ig_review.health.last_posted": { en: "Last posted",
                                           es: "Última publicación" },
  "admin.ig_review.health.never_posted": { en: "never",
                                            es: "nunca" },
  "admin.ig_review.health.cron":       { en: "Cron",
                                          es: "Cron" },
  "admin.ig_review.health.paused":     { en: "paused",
                                          es: "pausado" },
  "admin.ig_review.health.enabled":    { en: "enabled",
                                          es: "activo" },
  "admin.ig_review.health.blockers_aria": { en: "Active blockers",
                                             es: "Bloqueadores activos" },
};

// i18n leak canary — a non-default-locale user who falls back to English (or
// to the raw key) is the silent failure mode that shipped to prod twice. Make
// it observable: fire i18n.fallback_used ONCE per (locale, key) per session so
// the hot render path never spams PostHog, and never let reporting break t().
const _reportedI18nFallbacks = new Set();
function reportI18nFallback(key, locale) {
  if (typeof window === "undefined") return; // build/SSR/node: no-op
  const sig = `${locale}:${key}`;
  if (_reportedI18nFallbacks.has(sig)) return;
  _reportedI18nFallbacks.add(sig);
  try {
    track("i18n.fallback_used", { key, locale });
  } catch {
    /* telemetry must never break a render */
  }
}

// `t("nav.discover")` → string in current locale, with simple {var} interpolation
function t(key, locale, vars) {
  const entry = UI_STRINGS[key];
  const localized = entry ? entry[locale] : undefined;
  // A real leak only when a NON-default locale was asked for and missed — the
  // entry has no row for this locale (or the key doesn't exist at all).
  if (localized == null && locale && locale !== DEFAULT_LOCALE) {
    reportI18nFallback(key, locale);
  }
  if (!entry) return key; // fallback so missing keys are visible
  let s = localized ?? entry[DEFAULT_LOCALE] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
  }
  return s;
}

// Locale-aware number / currency / size formatters.
// PR-MC-i18n — locales come from the active country's manifest so a GT
// deployment gets es-GT / en-US (or whatever the GT manifest specifies)
// for free. The "currency: 'USD'" hardcode in formatPriceI18n below is
// a follow-up — listings carry their price in their source-broker's
// currency and the manifest's `currency` field is the deployment-wide
// default; need a per-listing currency override before flipping.
const localeMap = { en: ACTIVE_COUNTRY.locale_en, es: ACTIVE_COUNTRY.locale_es };
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
