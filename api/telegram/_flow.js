// api/telegram/_flow.js — the conversation itself.
//
// Kept separate from webhook.js so the whole flow is unit-testable by
// calling functions, with no HTTP and no Telegram involved.
//
// Shape: /start -> language -> property type -> zone -> price band ->
// results (5 at a time) -> detail. Every step is inline keyboards
// rather than free text: guided choice needs no intent parsing, and
// natural language already has a home — the MCP server, where a real
// model does the understanding.
//
// This adapter talks to /api/v1 over HTTP rather than importing
// shared/ directly. That is deliberate: it proves the HTTP contract
// works for an external channel (WhatsApp will be the same code path),
// and self-calls hit the CDN, so a popular query is served from cache
// instead of re-reading the catalog.

const { t } = require("./_strings");
const {
  PRICE_BANDS,
  encodeDetail,
  encodeLocale,
  encodeSearch,
  stateToQuery,
} = require("./_state");
const { escapeMarkdown } = require("./_telegram");

const PAGE_SIZE = 5;
// Enough zones to be useful, few enough to tap. Ordered by inventory
// at build time from /api/v1/meta, so the list follows the catalog.
const ZONE_CHOICES = 8;

function baseUrl() {
  return (process.env.PULPO_PUBLIC_BASE_URL || "https://pulpo.club").replace(/\/$/, "");
}

/** Fetch JSON from our own v1 API. Returns null on any failure — the
 *  caller shows a friendly message rather than propagating an error. */
async function api(path, deps = {}) {
  const doFetch = deps.fetch || fetch;
  try {
    const res = await doFetch(`${baseUrl()}${path}`, {
      headers: { accept: "application/json" },
    });
    if (!res.ok) {
      console.log(`[api] telegram_api_failed path=${path} status=${res.status}`);
      return null;
    }
    return await res.json();
  } catch (err) {
    console.log(`[api] telegram_api_threw path=${path} error_class=${err?.constructor?.name}`);
    return null;
  }
}

// ── Keyboards ───────────────────────────────────────────────────────

function languageKeyboard() {
  return {
    inline_keyboard: [[
      { text: "🇬🇧 English", callback_data: encodeLocale("en") },
      { text: "🇸🇻 Español", callback_data: encodeLocale("es") },
    ]],
  };
}

function typeKeyboard(locale, state) {
  const row = (type, key) => ({
    text: t(key, locale),
    callback_data: encodeSearch({ ...state, type, page: 0 }),
  });
  return {
    inline_keyboard: [
      [row("land", "type.land"), row("homes", "type.homes")],
      [row("condos", "type.condos"), row("", "type.any")],
    ],
  };
}

function zoneKeyboard(locale, state, zones) {
  const buttons = zones.slice(0, ZONE_CHOICES).map((z) => ({
    // Zone display NAME, not slug: /api/v1's ?zones= filter matches on
    // zone_name, the same value the website's share links carry.
    text: `${z.name} (${z.count})`,
    callback_data: encodeSearch({ ...state, zone: z.name, page: 0 }),
  })).filter((b) => b.callback_data);

  const rows = [];
  for (let i = 0; i < buttons.length; i += 2) rows.push(buttons.slice(i, i + 2));
  rows.push([{
    text: t("zone.any", locale),
    callback_data: encodeSearch({ ...state, zone: null, page: 0 }),
  }]);
  return { inline_keyboard: rows };
}

function priceKeyboard(locale, state) {
  const buttons = PRICE_BANDS.map((band, i) => ({
    text: band.label,
    callback_data: encodeSearch({ ...state, band: i, page: 0 }),
  }));
  const rows = [];
  for (let i = 0; i < buttons.length; i += 2) rows.push(buttons.slice(i, i + 2));
  rows.push([{
    text: t("price.any", locale),
    callback_data: encodeSearch({ ...state, band: null, page: 0 }),
  }]);
  return { inline_keyboard: rows };
}

function resultsKeyboard(locale, state, total) {
  const rows = [];
  const shown = ((state.page ?? 0) + 1) * PAGE_SIZE;
  if (total > shown) {
    const more = encodeSearch({ ...state, page: (state.page ?? 0) + 1 });
    if (more) rows.push([{ text: t("results.more", locale), callback_data: more }]);
  }
  rows.push([{ text: t("results.restart", locale), callback_data: encodeSearch({ page: 0 }) }]);
  return { inline_keyboard: rows };
}

// ── Rendering ───────────────────────────────────────────────────────

function pick(localized, locale) {
  if (!localized || typeof localized !== "object") return String(localized ?? "");
  // Fall back by truthiness: an es-only listing must render its Spanish
  // to an English user rather than an empty line.
  return locale === "es"
    ? (localized.es || localized.en || "")
    : (localized.en || localized.es || "");
}

function money(n) {
  return typeof n === "number" ? `$${Math.round(n).toLocaleString("en-US")}` : null;
}

/** One result line. Every nullable field is guarded — CLAUDE.md's first
 *  rule, and a bot rendering "undefined m²" is the chat equivalent of a
 *  blank page. */
function renderListing(listing, locale, index) {
  const title = escapeMarkdown(pick(listing.title, locale)) || "—";
  const price = money(listing.price) ?? t("listing.unknown_price", locale);
  const bits = [price];
  if (typeof listing.size_m2 === "number") {
    bits.push(t("listing.size", locale, { size: Math.round(listing.size_m2).toLocaleString("en-US") }));
  }
  if (typeof listing.price_per_m2 === "number") {
    bits.push(t("listing.ppm", locale, { ppm: Math.round(listing.price_per_m2) }));
  }
  const zone = listing.zone_name && listing.zone_name !== "—"
    ? ` · ${escapeMarkdown(listing.zone_name)}` : "";
  return `${index}. *${title}*\n   ${bits.join(" · ")}${zone}\n   ${listing.url}`;
}

function renderResults(payload, locale, state) {
  const listings = Array.isArray(payload?.data) ? payload.data : [];
  if (listings.length === 0) {
    return { text: t("results.none", locale), keyboard: resultsKeyboard(locale, state, 0) };
  }
  const offset = (state.page ?? 0) * PAGE_SIZE;
  const lines = listings.map((l, i) => renderListing(l, locale, offset + i + 1));
  const date = (payload.generated_at || "").slice(0, 10);

  const header = t("results.header", locale, { count: payload.total, shown: listings.length });
  const footer = date ? `\n_${t("results.footer", locale, { date })}_` : "";

  return {
    text: `${header}\n\n${lines.join("\n\n")}\n${footer}`,
    keyboard: resultsKeyboard(locale, state, payload.total ?? 0),
  };
}

// ── Steps ───────────────────────────────────────────────────────────

/**
 * Decide what to show next for a given state.
 *
 * The bot asks for whatever is still missing, in order, then searches.
 * Returning a plain {text, keyboard} object rather than sending makes
 * the whole conversation testable without Telegram.
 */
async function nextStep(state, locale, deps = {}) {
  if (!state.type && state.type !== "") {
    return { text: t("ask.type", locale), keyboard: typeKeyboard(locale, state) };
  }
  if (state.zone === undefined) {
    const meta = await api("/api/v1/meta", deps);
    if (!meta) return { text: t("error.unavailable", locale), keyboard: null };
    return { text: t("ask.zone", locale), keyboard: zoneKeyboard(locale, state, meta.zones || []) };
  }
  if (state.band === undefined) {
    return { text: t("ask.price", locale), keyboard: priceKeyboard(locale, state) };
  }

  const payload = await api(`/api/v1/listings?${stateToQuery(state, PAGE_SIZE)}`, deps);
  if (!payload) return { text: t("error.unavailable", locale), keyboard: null };
  return renderResults(payload, locale, state);
}

async function detailStep(id, locale, deps = {}) {
  const payload = await api(`/api/v1/listings/${encodeURIComponent(id)}`, deps);
  if (!payload?.data) return { text: t("error.unavailable", locale), keyboard: null };

  const l = payload.data;
  const title = escapeMarkdown(pick(l.title, locale)) || "—";
  const desc = escapeMarkdown(pick(l.description, locale)).slice(0, 600);
  const price = money(l.price) ?? t("listing.unknown_price", locale);

  return {
    text: `*${title}*\n\n${price}\n\n${desc}\n\n${l.url}`,
    keyboard: { inline_keyboard: [[{ text: t("detail.open", locale), url: l.url }]] },
  };
}

module.exports = {
  PAGE_SIZE,
  ZONE_CHOICES,
  api,
  baseUrl,
  detailStep,
  languageKeyboard,
  nextStep,
  priceKeyboard,
  renderListing,
  renderResults,
  typeKeyboard,
  zoneKeyboard,
  pick,
};
