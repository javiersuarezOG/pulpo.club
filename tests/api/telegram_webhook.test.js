// The Telegram bot.
//
// Drives whole conversations by passing plain update objects and an
// injected fetch, so the flow is tested without Telegram, without HTTP
// and without the network.
//
// The assertions that matter most are the two rules that keep a webhook
// from becoming an incident: it must never return a non-2xx (Telegram
// retries those forever) and it must verify the shared secret (or the
// endpoint is a public "make our bot say things" API).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import handler, { handleUpdate } from "../../api/telegram/webhook.js";
import { decode, encodeDetail, encodeLocale, encodeSearch, byteLength, MAX_CALLBACK_BYTES, PRICE_BANDS, stateToQuery } from "../../api/telegram/_state.js";
import { STRINGS, localeFromTelegram, t } from "../../api/telegram/_strings.js";
import { nextStep, renderListing, renderResults, typeKeyboard, zoneKeyboard, priceKeyboard, pick } from "../../api/telegram/_flow.js";

const SECRET = "test-secret-value";

function mockRes() {
  return {
    statusCode: 200, headers: {}, body: null,
    setHeader(k, v) { this.headers[k] = v; return this; },
    status(c) { this.statusCode = c; return this; },
    json(p) { this.body = p; return this; },
  };
}

let chatSeq = 0;
const chatId = () => 100000 + chatSeq++;

function mockReq(body, opts = {}) {
  // NB: not a destructuring default. `{ secret = SECRET }` would treat
  // an explicit `undefined` as "not passed" and silently use the real
  // secret, so the missing-header case would never be exercised.
  const method = "method" in opts ? opts.method : "POST";
  const headers = {};
  if ("secret" in opts) {
    if (opts.secret !== undefined) headers["x-telegram-bot-api-secret-token"] = opts.secret;
  } else {
    headers["x-telegram-bot-api-secret-token"] = SECRET;
  }
  return { method, headers, body };
}

/** Records outbound Bot API calls instead of making them. */
function botSpy() {
  const calls = [];
  return {
    calls,
    fetch: async (url, init) => {
      calls.push({
        method: String(url).split("/").pop(),
        payload: JSON.parse(init.body),
      });
      return { ok: true, json: async () => ({ ok: true, result: {} }) };
    },
  };
}

/** Serves canned /api/v1 responses to the flow. */
function apiSpy(routes) {
  const seen = [];
  return {
    seen,
    fetch: async (url) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, "");
      seen.push(path);
      for (const [prefix, payload] of Object.entries(routes)) {
        if (path.startsWith(prefix)) {
          return { ok: true, status: 200, json: async () => payload };
        }
      }
      return { ok: false, status: 404, json: async () => ({}) };
    },
  };
}

const listing = (over = {}) => ({
  id: "remax__1",
  title: { en: "Ocean-view lot", es: "Terreno con vista al mar" },
  description: { en: "Nice.", es: "Lindo." },
  price: 60000,
  size_m2: 1263.59,
  price_per_m2: 47.48,
  zone_name: "El Tunco",
  url: "https://pulpo.club/listing/remax__1",
  ...over,
});

beforeEach(() => {
  process.env.TELEGRAM_BOT_TOKEN = "12345:test-token";
  process.env.TELEGRAM_WEBHOOK_SECRET = SECRET;
});
afterEach(() => {
  delete process.env.TELEGRAM_BOT_TOKEN;
  delete process.env.TELEGRAM_WEBHOOK_SECRET;
  vi.restoreAllMocks();
});

// ── The two webhook rules ───────────────────────────────────────────

describe("webhook contract", () => {
  it("rejects a wrong or missing secret", async () => {
    for (const secret of ["wrong-secret-val", "", undefined]) {
      const res = mockRes();
      await handler(mockReq({ message: { chat: { id: 1 }, text: "/start" } }, { secret }), res);
      expect(res.statusCode).toBe(401);
    }
  });

  it("compares the secret in constant time and length-safely", async () => {
    // A shorter/longer candidate must not throw out of timingSafeEqual.
    const res = mockRes();
    await handler(mockReq({}, { secret: "short" }), res);
    expect(res.statusCode).toBe(401);
  });

  it("503s when the bot is not configured, rather than 500ing", async () => {
    delete process.env.TELEGRAM_BOT_TOKEN;
    const res = mockRes();
    await handler(mockReq({}), res);
    expect(res.statusCode).toBe(503);
    expect(res.body.error).toBe("telegram_not_configured");
  });

  it("returns 200 even when the flow throws — Telegram retries non-2xx forever", async () => {
    // A handler that 500s on one bad update gets it redelivered
    // indefinitely; a retry storm is worse than a dropped message.
    const res = mockRes();
    const boom = { message: { chat: { get id() { throw new Error("boom"); } }, text: "/start" } };
    await handler(mockReq(boom), res);
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ ok: true });
  });

  it("returns 200 for update shapes it does not handle", async () => {
    const res = mockRes();
    await handler(mockReq({ edited_message: { text: "hi" } }), res);
    expect(res.statusCode).toBe(200);
  });

  it("rejects non-POST with 405 + Allow", async () => {
    const res = mockRes();
    await handler(mockReq({}, { method: "GET" }), res);
    expect(res.statusCode).toBe(405);
    expect(res.headers.Allow).toBe("POST");
  });

  it("drops a flooding chat with 200, not 429", async () => {
    // A 429 would make Telegram retry the very update we are shedding.
    const id = chatId();
    let last;
    for (let i = 0; i < 25; i++) {
      last = mockRes();
      await handler(mockReq({ message: { chat: { id }, text: "/help" } }), last);
    }
    expect(last.statusCode).toBe(200);
  });
});

// ── callback_data: the 64-byte constraint ───────────────────────────

describe("callback_data stays inside Telegram's 64-byte limit", () => {
  it("every search state encodes within budget", () => {
    // Over 64 bytes and the Bot API rejects the message, so the whole
    // keyboard silently fails to appear.
    for (const type of ["land", "homes", "condos", null]) {
      for (const zone of [null, "Puerto La Libertad", "Lago de Coatepeque", "San Diego (K59)"]) {
        for (let band = 0; band < PRICE_BANDS.length; band++) {
          for (const page of [0, 9, 99]) {
            const encoded = encodeSearch({ type, zone, band, page });
            expect(encoded, `${type}/${zone}/${band}/${page}`).not.toBeNull();
            expect(byteLength(encoded)).toBeLessThanOrEqual(MAX_CALLBACK_BYTES);
          }
        }
      }
    }
  });

  it("measures BYTES, not characters, for accented zone names", () => {
    // "La Unión" is 8 chars but 9 bytes in UTF-8.
    expect(byteLength("La Unión")).toBe(9);
    const encoded = encodeSearch({ type: "land", zone: "La Unión", band: 4, page: 0 });
    expect(byteLength(encoded)).toBeLessThanOrEqual(MAX_CALLBACK_BYTES);
  });

  it("returns null instead of an oversized payload", () => {
    // csbr publishes full-sentence source_ids; callers fall back to a
    // URL button, which has no length limit.
    expect(encodeDetail(`csbr__${"x".repeat(80)}`)).toBeNull();
    expect(encodeSearch({ type: "land", zone: "x".repeat(80), band: 0, page: 0 })).toBeNull();
  });

  it("round-trips every state faithfully", () => {
    const state = { type: "condos", zone: "El Zonte", band: 3, page: 2 };
    expect(decode(encodeSearch(state))).toEqual({ kind: "search", state });
    expect(decode(encodeLocale("es"))).toEqual({ kind: "locale", locale: "es" });
    expect(decode(encodeDetail("remax__1"))).toEqual({ kind: "detail", id: "remax__1" });
  });

  it("never throws on hostile or malformed callback data", () => {
    // Anyone can send arbitrary callback_data; a bad payload must be
    // ignored, not crash the webhook.
    for (const bad of ["", null, undefined, 42, "s|land", "s|a|b|c|d|e", "s|land|-|x|0",
                       "s|land|-|0|-5", "s|land|-|0|99999", "l|fr", "zzz", "|||"]) {
      expect(() => decode(bad)).not.toThrow();
      expect(decode(bad).kind === "unknown" || decode(bad).kind === "search").toBe(true);
    }
  });

  it("maps price bands to real query bounds", () => {
    expect(stateToQuery({ type: "land", band: 0, page: 0 }, 5))
      .toContain("pmax=50000");
    expect(stateToQuery({ band: 2, page: 0 }, 5)).toContain("pmin=100000");
    // The open-ended top band must not emit an empty pmax, which would
    // parse as a cap and hide everything above it.
    expect(stateToQuery({ band: 4, page: 0 }, 5)).not.toContain("pmax=");
    expect(stateToQuery({ page: 3 }, 5)).toContain("offset=15");
  });
});

// ── i18n ────────────────────────────────────────────────────────────

describe("bot copy is fully bilingual", () => {
  it("EN and ES define exactly the same keys", () => {
    // A missing ES key silently shows English to a Spanish user, which
    // is the leak class CLAUDE.md's i18n rules exist to stop.
    expect(Object.keys(STRINGS.es).sort()).toEqual(Object.keys(STRINGS.en).sort());
  });

  it("no ES string is left as its English text", () => {
    // Allowlisted because they are genuinely identical in both
    // languages — a number plus a unit, with no words to translate.
    // Keep this list short: it is the escape hatch that would hide a
    // real untranslated string.
    const IDENTICAL_BY_NATURE = new Set(["listing.size", "listing.ppm"]);
    for (const [key, en] of Object.entries(STRINGS.en)) {
      if (IDENTICAL_BY_NATURE.has(key)) continue;
      expect(STRINGS.es[key], `${key} is identical in EN and ES`).not.toBe(en);
    }
  });

  it("maps Telegram's regional language codes to a served locale", () => {
    expect(localeFromTelegram("es-419")).toBe("es");
    expect(localeFromTelegram("es")).toBe("es");
    expect(localeFromTelegram("en-GB")).toBe("en");
    expect(localeFromTelegram(undefined)).toBe("en");
    expect(localeFromTelegram("zz")).toBe("en");
  });

  it("interpolates variables and leaves no placeholder behind", () => {
    const out = t("results.header", "es", { count: 297, shown: 5 });
    expect(out).toContain("297");
    expect(out).not.toMatch(/\{.*\}/);
  });
});

// ── Rendering ───────────────────────────────────────────────────────

describe("message rendering", () => {
  it("renders a listing with price, size and a link", () => {
    const line = renderListing(listing(), "en", 1);
    expect(line).toContain("$60,000");
    expect(line).toContain("1,264 m²");
    expect(line).toContain("https://pulpo.club/listing/remax__1");
  });

  it("guards every nullable field — a bot must not print 'undefined m²'", () => {
    // CLAUDE.md's first rule, in chat form.
    const bare = listing({ price: null, size_m2: null, price_per_m2: null, zone_name: null });
    const line = renderListing(bare, "en", 1);
    expect(line).not.toMatch(/undefined|NaN|null/);
    expect(line).toContain("Price on request");
  });

  it("escapes Markdown in broker-written titles", () => {
    // Titles routinely contain * and _, which would otherwise break the
    // message or inject formatting.
    const line = renderListing(listing({ title: { en: "Lot *5* _prime_", es: "" } }), "en", 1);
    expect(line).toContain("\\*5\\*");
  });

  it("shows Spanish copy to a Spanish user", () => {
    const line = renderListing(listing(), "es", 1);
    expect(line).toContain("Terreno con vista al mar");
  });

  it("falls back by truthiness for a single-language listing", () => {
    // An es-only listing must show its Spanish to an EN user rather
    // than an empty line.
    expect(pick({ en: "", es: "Solo español" }, "en")).toBe("Solo español");
    expect(pick({ en: "English only" }, "es")).toBe("English only");
  });

  it("says how many matched, not just how many are shown", () => {
    const out = renderResults(
      { total: 297, generated_at: "2026-08-21T04:04:32Z", data: [listing(), listing({ id: "remax__2" })] },
      "en", { page: 0 },
    );
    expect(out.text).toContain("*297*");
    expect(out.text).toContain("2026-08-21");
  });

  it("offers an honest empty state rather than a dead end", () => {
    const out = renderResults({ total: 0, data: [] }, "es", { page: 0 });
    expect(out.text).toContain("no hay anuncios");
    expect(out.keyboard.inline_keyboard.length).toBeGreaterThan(0);
  });

  it("only offers 'show more' when more actually exist", () => {
    const labels = (payload, state) =>
      JSON.stringify(renderResults(payload, "en", state).keyboard);
    expect(labels({ total: 100, data: [listing()] }, { page: 0 })).toContain("Show more");
    expect(labels({ total: 3, data: [listing()] }, { page: 0 })).not.toContain("Show more");
  });
});

// ── Whole conversations ─────────────────────────────────────────────

describe("conversation flow", () => {
  it("/start greets and offers a language choice", async () => {
    const bot = botSpy();
    await handleUpdate({ message: { chat: { id: 1 }, from: { language_code: "es" }, text: "/start" } }, bot);

    expect(bot.calls[0].method).toBe("sendMessage");
    expect(bot.calls[0].payload.text).toContain("Pulpo");
    const kb = JSON.stringify(bot.calls[0].payload.reply_markup);
    expect(kb).toContain("English");
    expect(kb).toContain("Español");
  });

  it("walks type -> zone -> price -> results", async () => {
    const meta = { zones: [{ slug: "el-tunco", name: "El Tunco", count: 43 }] };
    const results = {
      total: 12, generated_at: "2026-08-21T04:04:32Z",
      data: [listing(), listing({ id: "remax__2" })],
    };
    const deps = apiSpy({ "/api/v1/meta": meta, "/api/v1/listings": results });

    // After picking a type, the bot asks for a zone.
    const askZone = await nextStep({ type: "land" }, "en", deps);
    expect(askZone.text).toBe("Where?");
    expect(JSON.stringify(askZone.keyboard)).toContain("El Tunco (43)");

    // After a zone, it asks for a budget.
    const askPrice = await nextStep({ type: "land", zone: "El Tunco" }, "en", deps);
    expect(askPrice.text).toBe("What's your budget?");

    // With everything set, it searches.
    const out = await nextStep({ type: "land", zone: "El Tunco", band: 1, page: 0 }, "en", deps);
    expect(out.text).toContain("*12*");
    const query = deps.seen.find((p) => p.startsWith("/api/v1/listings"));
    expect(query).toContain("sub=land");
    expect(query).toContain("zones=El+Tunco");
    expect(query).toContain("pmax=100000");
  });

  it("passes the zone DISPLAY NAME, which is what the filter matches", () => {
    // The v1 ?zones= filter compares against zone_name, so sending the
    // slug would silently return zero results.
    const kb = zoneKeyboard("en", {}, [{ slug: "el-tunco", name: "El Tunco", count: 4 }]);
    const btn = kb.inline_keyboard[0][0];
    expect(decode(btn.callback_data).state.zone).toBe("El Tunco");
  });

  it("apologises instead of going silent when the API is down", async () => {
    const down = { fetch: async () => ({ ok: false, status: 503, json: async () => ({}) }) };
    const out = await nextStep({ type: "land" }, "es", down);
    expect(out.text).toContain("no está disponible");
    expect(out.keyboard).toBeNull();
  });

  it("tells the user how to recover from a stale button", async () => {
    const bot = botSpy();
    await handleUpdate({
      callback_query: {
        id: "cb1", data: "OLD_FORMAT_FROM_A_PREVIOUS_DEPLOY",
        from: { language_code: "en" },
        message: { chat: { id: 1 }, message_id: 9 },
      },
    }, bot);

    // The callback is answered first so the button stops spinning...
    expect(bot.calls[0].method).toBe("answerCallbackQuery");
    // ...then the user is told what to do.
    expect(bot.calls[1].payload.text).toContain("/start");
  });

  it("always answers the callback query so no button spins forever", async () => {
    const deps = { ...botSpy(), ...apiSpy({ "/api/v1/meta": { zones: [] } }) };
    const bot = botSpy();
    const merged = {
      calls: bot.calls,
      fetch: async (url, init) => {
        if (String(url).includes("api.telegram.org")) return bot.fetch(url, init);
        return { ok: true, status: 200, json: async () => ({ zones: [] }) };
      },
    };
    await handleUpdate({
      callback_query: {
        id: "cb2", data: "s|land|-|-|0",
        from: { language_code: "en" },
        message: { chat: { id: 1 }, message_id: 9 },
      },
    }, merged);
    expect(bot.calls[0].method).toBe("answerCallbackQuery");
  });
});
