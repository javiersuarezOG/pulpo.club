// api/telegram/_strings.js — bot chrome copy, EN + ES.
//
// Listing CONTENT is already bilingual in the catalog ({en, es} on
// every title and description), so the bot only needs its own labels
// and prompts translated. Per CLAUDE.md every user-visible string is
// looked up, never inlined at the call site.
//
// This is deliberately a small local table rather than web/app/i18n.jsx:
// that module is JSX and browser-bound, and these strings are
// channel-specific chrome that no other surface shows. Sharing it would
// mean importing React into a serverless webhook to reuse ten strings.

const STRINGS = {
  en: {
    "start.greeting":
      "🐙 *Pulpo* finds land and property for sale in El Salvador — every listing " +
      "we can find, ranked by value, location and how long it has been on the market.\n\n" +
      "Pick a language to begin.",
    "start.language_set": "Great — let's find you something.",
    "ask.type": "What are you looking for?",
    "ask.zone": "Where?",
    "ask.price": "What's your budget?",
    "type.land": "🏞 Land",
    "type.homes": "🏠 Houses",
    "type.condos": "🏢 Condos",
    "type.any": "Anything",
    "zone.any": "Anywhere",
    "price.any": "No limit",
    "results.header": "*{count}* matches. Here are the top {shown}:",
    "results.none":
      "No listings match that yet. Our catalog refreshes nightly — try a wider " +
      "budget or another area.",
    "results.more": "Show more",
    "results.restart": "New search",
    "results.footer": "Data as of {date}. Tap a listing to open it on pulpo.club.",
    "detail.open": "Open on pulpo.club",
    "detail.back": "Back to results",
    "listing.size": "{size} m²",
    "listing.ppm": "${ppm}/m²",
    "listing.unknown_price": "Price on request",
    "error.generic": "Something went wrong on our side. Please try again.",
    "error.unavailable": "Our catalog is briefly unavailable. Please try again shortly.",
    "error.stale_button": "That search expired. Start a new one with /start.",
    "help":
      "Send /start to search listings.\n\nPulpo aggregates land and property for " +
      "sale in El Salvador from brokers across the country and ranks it. " +
      "Everything here is also at pulpo.club.",
  },
  es: {
    "start.greeting":
      "🐙 *Pulpo* encuentra terrenos y propiedades en venta en El Salvador — todos los " +
      "anuncios que logramos reunir, ordenados por valor, ubicación y tiempo en el mercado.\n\n" +
      "Elegí un idioma para empezar.",
    "start.language_set": "Perfecto — busquemos algo para vos.",
    "ask.type": "¿Qué estás buscando?",
    "ask.zone": "¿Dónde?",
    "ask.price": "¿Cuál es tu presupuesto?",
    "type.land": "🏞 Terrenos",
    "type.homes": "🏠 Casas",
    "type.condos": "🏢 Apartamentos",
    "type.any": "Cualquiera",
    "zone.any": "Cualquier lugar",
    "price.any": "Sin límite",
    "results.header": "*{count}* resultados. Estos son los mejores {shown}:",
    "results.none":
      "Todavía no hay anuncios que coincidan. Nuestro catálogo se actualiza cada noche — " +
      "probá con más presupuesto u otra zona.",
    "results.more": "Ver más",
    "results.restart": "Nueva búsqueda",
    "results.footer": "Datos al {date}. Tocá un anuncio para abrirlo en pulpo.club.",
    "detail.open": "Abrir en pulpo.club",
    "detail.back": "Volver a los resultados",
    "listing.size": "{size} m²",
    "listing.ppm": "${ppm}/m²",
    "listing.unknown_price": "Precio a consultar",
    "error.generic": "Algo falló de nuestro lado. Intentá de nuevo.",
    "error.unavailable": "Nuestro catálogo no está disponible por un momento. Intentá en unos minutos.",
    "error.stale_button": "Esa búsqueda expiró. Empezá una nueva con /start.",
    "help":
      "Enviá /start para buscar anuncios.\n\nPulpo reúne terrenos y propiedades en venta " +
      "en El Salvador de corredores de todo el país y los ordena. Todo esto también está " +
      "en pulpo.club.",
  },
};

const DEFAULT_LOCALE = "en";

/**
 * Look up a bot string. Falls back to English, then to the key itself
 * so a missing translation shows something diagnosable rather than
 * "undefined" in a user's chat.
 */
function t(key, locale, vars) {
  const table = STRINGS[locale] || STRINGS[DEFAULT_LOCALE];
  let out = table[key] ?? STRINGS[DEFAULT_LOCALE][key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      out = out.split(`{${k}}`).join(String(v));
    }
  }
  return out;
}

/** Telegram sends an IETF tag like "es-419" or "en-GB"; we serve es/en. */
function localeFromTelegram(languageCode) {
  const code = String(languageCode || "").toLowerCase();
  // Spanish first: LATAM users are the core audience, and Telegram
  // reports many regional Spanish variants.
  if (code.startsWith("es")) return "es";
  return DEFAULT_LOCALE;
}

module.exports = { STRINGS, DEFAULT_LOCALE, t, localeFromTelegram };
