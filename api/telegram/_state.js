// api/telegram/_state.js — conversation state, encoded into the buttons.
//
// Pulpo has no database, by design (see CLAUDE.md "Persistence &
// backups"): every byte of user state lives in a third-party SaaS. A
// chat bot normally wants a session store, so this encodes the whole
// conversation into Telegram's own callback_data instead. Each button
// carries the full search that produced it, which means:
//
//   * no store to provision, back up, or leak
//   * any lambda instance can serve any tap
//   * a button still works tomorrow, after a redeploy
//
// THE CONSTRAINT THAT SHAPES EVERYTHING HERE: Telegram hard-limits
// callback_data to 64 BYTES. Not characters — bytes, UTF-8. Exceeding
// it is rejected by the Bot API at send time, so the keyboard simply
// fails to appear. Hence the terse pipe format and short codes, and
// hence encode() returning null rather than an oversized payload.
//
// Format:  s|<type>|<zone>|<band>|<page>     search / results
//          d|<listing id>                    detail
//          l|<locale>                        language pick
// "-" means "unset" in any slot.

const MAX_CALLBACK_BYTES = 64;

/** Byte length, which is what Telegram actually measures. */
function byteLength(s) {
  return Buffer.byteLength(String(s), "utf8");
}

function encodeSearch(state) {
  const parts = [
    "s",
    state.type || "-",
    state.zone || "-",
    state.band == null ? "-" : String(state.band),
    String(state.page ?? 0),
  ];
  const out = parts.join("|");
  return byteLength(out) <= MAX_CALLBACK_BYTES ? out : null;
}

function encodeDetail(id) {
  const out = `d|${id}`;
  // Long broker slugs (csbr publishes full-sentence source_ids) blow
  // the budget. Callers fall back to a URL button, which has no such
  // limit, rather than shipping a keyboard Telegram will reject.
  return byteLength(out) <= MAX_CALLBACK_BYTES ? out : null;
}

function encodeLocale(locale) {
  return `l|${locale}`;
}

/** Parse callback_data back into an action. Never throws: this is
 *  attacker-reachable (anyone can send arbitrary callback data) and a
 *  malformed payload should be ignored, not crash the webhook. */
function decode(data) {
  const raw = typeof data === "string" ? data : "";
  if (!raw) return { kind: "unknown" };

  const parts = raw.split("|");
  switch (parts[0]) {
    case "l":
      return parts[1] === "es" || parts[1] === "en"
        ? { kind: "locale", locale: parts[1] }
        : { kind: "unknown" };
    case "s": {
      if (parts.length !== 5) return { kind: "unknown" };
      const [, type, zone, band, page] = parts;
      const bandNum = band === "-" ? null : Number(band);
      const pageNum = Number(page);
      if (band !== "-" && !Number.isInteger(bandNum)) return { kind: "unknown" };
      if (!Number.isInteger(pageNum) || pageNum < 0 || pageNum > 200) return { kind: "unknown" };
      return {
        kind: "search",
        state: {
          type: type === "-" ? null : type,
          zone: zone === "-" ? null : zone,
          band: bandNum,
          page: pageNum,
        },
      };
    }
    case "d": {
      const id = parts.slice(1).join("|");
      return id ? { kind: "detail", id } : { kind: "unknown" };
    }
    default:
      return { kind: "unknown" };
  }
}

// Price bands, in USD. Indexes are what travel in callback_data, so
// REORDERING THESE INVALIDATES LIVE BUTTONS in users' chat history —
// append instead. Chosen against the real catalog: the median listing
// is well under $250k and the long tail runs to $18M.
const PRICE_BANDS = [
  { max: 50_000, label: "< $50k" },
  { max: 100_000, label: "$50k – $100k" },
  { max: 250_000, label: "$100k – $250k" },
  { max: 500_000, label: "$250k – $500k" },
  { max: null, label: "$500k +" },
];

const PRICE_BAND_MINS = [0, 50_000, 100_000, 250_000, 500_000];

/** Turn the encoded state into the API's query dialect. */
function stateToQuery(state, limit) {
  const p = new URLSearchParams();
  if (state.type) p.set("sub", state.type);
  if (state.zone) p.set("zones", state.zone);
  if (state.band != null && PRICE_BANDS[state.band]) {
    const min = PRICE_BAND_MINS[state.band];
    const max = PRICE_BANDS[state.band].max;
    if (min > 0) p.set("pmin", String(min));
    if (max != null) p.set("pmax", String(max));
  }
  p.set("limit", String(limit));
  p.set("offset", String((state.page ?? 0) * limit));
  return p.toString();
}

module.exports = {
  MAX_CALLBACK_BYTES,
  PRICE_BANDS,
  PRICE_BAND_MINS,
  byteLength,
  decode,
  encodeDetail,
  encodeLocale,
  encodeSearch,
  stateToQuery,
};
