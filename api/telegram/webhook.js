// POST /api/telegram/webhook — the Telegram bot's entry point.
//
// Phase 2 of the PRD: a chat channel reaching the same capabilities the
// website uses. The bot holds no business logic — it turns taps into
// /api/v1 calls and results into messages. Everything about what a
// listing is, which ones match, and how they rank lives in shared/.
//
// Talking to /api/v1 over HTTP (rather than importing shared/ directly
// like the MCP server does) is deliberate: it proves the HTTP contract
// works for an external channel, which is exactly what WhatsApp will
// need, and self-calls hit the CDN so a popular query is served from
// cache rather than re-reading the catalog.
//
// ── Two rules that shape this file ──────────────────────────────────
//
// 1. ALWAYS RETURN 200. Telegram retries non-2xx responses, so a
//    handler that 500s on a bad update gets that update redelivered
//    forever. Failures are logged and reported to PostHog; the user
//    sees an apology, and Telegram sees success.
//
// 2. VERIFY THE SECRET. setWebhook registers a secret_token which
//    Telegram echoes in X-Telegram-Bot-Api-Secret-Token. Without that
//    check the endpoint is a public "make our bot say things" API.
//
// Setup and the kill switch (deleteWebhook) are in docs/telegram-bot.md.

const crypto = require("crypto");

const posthog = require("../_posthog");
const { makeRateLimiter } = require("../_rate_limit");
const { t, localeFromTelegram } = require("./_strings");
const { decode, encodeSearch } = require("./_state");
const { detailStep, languageKeyboard, nextStep } = require("./_flow");
const tg = require("./_telegram");

// Per chat, not per IP: every request arrives from Telegram's servers,
// so an IP bucket would be one shared limit for all users.
const limiter = makeRateLimiter({ windowMs: 60_000, maxAttempts: 20, name: "telegram" });

function logApi(name, fields) {
  console.log(`[api] ${name} ${Object.entries(fields).map(([k, v]) => `${k}=${v}`).join(" ")}`);
}

/** Constant-time compare so the secret cannot be recovered by timing. */
function secretMatches(header) {
  const expected = (process.env.TELEGRAM_WEBHOOK_SECRET || "").trim();
  const got = String(header || "");
  if (!expected || !got) return false;
  const a = Buffer.from(expected);
  const b = Buffer.from(got);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

async function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  if (typeof req.body === "string") {
    try { return JSON.parse(req.body); } catch { return null; }
  }
  return null;
}

/**
 * Handle one update. Split out from the HTTP shell so tests can drive
 * whole conversations by passing plain update objects.
 */
async function handleUpdate(update, deps = {}) {
  const message = update?.message;
  const callback = update?.callback_query;

  if (message?.text) {
    const chatId = message.chat?.id;
    const locale = localeFromTelegram(message.from?.language_code);
    const text = String(message.text).trim();

    if (text.startsWith("/start")) {
      posthog.capture(`tg:${chatId}`, "bot.start", { locale });
      return tg.sendMessage(chatId, t("start.greeting", locale), {
        reply_markup: languageKeyboard(),
      }, deps);
    }
    if (text.startsWith("/help")) {
      return tg.sendMessage(chatId, t("help", locale), {}, deps);
    }
    // Free text is not an interface here — natural language lives on
    // the MCP server, where a real model does the understanding. Nudge
    // back to the guided flow rather than guessing at intent.
    return tg.sendMessage(chatId, t("help", locale), {}, deps);
  }

  if (callback) {
    const chatId = callback.message?.chat?.id;
    const messageId = callback.message?.message_id;
    const locale = localeFromTelegram(callback.from?.language_code);
    const action = decode(callback.data);

    // Answer first, always: an unanswered callback leaves the user's
    // button spinning regardless of what happens next.
    await tg.answerCallbackQuery(callback.id, {}, deps);

    if (action.kind === "locale") {
      const step = await nextStep({}, action.locale, deps);
      return tg.editMessageText(chatId, messageId, step.text, {
        reply_markup: step.keyboard || undefined,
      }, deps);
    }

    if (action.kind === "search") {
      const step = await nextStep(action.state, locale, deps);
      posthog.capture(`tg:${chatId}`, "bot.search_step", {
        locale,
        has_type: Boolean(action.state.type),
        has_zone: Boolean(action.state.zone),
        page: action.state.page,
      });
      return tg.editMessageText(chatId, messageId, step.text, {
        reply_markup: step.keyboard || undefined,
      }, deps);
    }

    if (action.kind === "detail") {
      const step = await detailStep(action.id, locale, deps);
      posthog.capture(`tg:${chatId}`, "bot.listing_viewed", { locale, id: action.id });
      return tg.sendMessage(chatId, step.text, {
        reply_markup: step.keyboard || undefined,
      }, deps);
    }

    // Unknown callback data: either a button from an older format after
    // a redeploy, or someone poking the API. Tell the user how to
    // recover instead of going silent.
    return tg.sendMessage(chatId, t("error.stale_button", locale), {}, deps);
  }

  // Updates we do not handle (edited messages, channel posts, reactions)
  // are acknowledged silently — Telegram only needs the 200.
  return { ok: true, ignored: true };
}

module.exports = async function handler(req, res) {
  const t0 = Date.now();

  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  if (!tg.isConfigured()) {
    // 503 distinguishes "the bot is not set up" from "the credentials
    // are wrong", matching the repo's not_configured convention.
    logApi("telegram_webhook", { status: 503, reason: "not_configured", ms: Date.now() - t0 });
    return res.status(503).json({ error: "telegram_not_configured" });
  }

  if (!secretMatches(req.headers?.["x-telegram-bot-api-secret-token"])) {
    logApi("telegram_webhook", { status: 401, ms: Date.now() - t0 });
    return res.status(401).json({ error: "unauthorized" });
  }

  // Everything from here is inside one try. Rule 1 is only actually
  // honoured if the guard covers parsing and chat-id extraction too —
  // a throw between readBody() and the flow would otherwise escape as
  // an unhandled rejection, Vercel would answer 500, and Telegram would
  // redeliver that same update forever. (A test with a throwing `id`
  // getter caught exactly that gap.)
  let chatId = "unknown";
  try {
    const update = await readBody(req);
    chatId =
      update?.message?.chat?.id ?? update?.callback_query?.message?.chat?.id ?? "unknown";

    // The heartbeat scripts/check_webhook_health.py watches. Emitted
    // before any work so it fires even when the flow later fails.
    posthog.capture(`tg:${chatId}`, "telegram.webhook_received", {
      kind: update?.callback_query ? "callback" : update?.message ? "message" : "other",
    });

    if (!limiter.hit(chatId).allowed) {
      // Drop silently with a 200: telling a flooding client it is rate
      // limited just adds a message, and a 429 would make Telegram
      // retry the very update we are shedding.
      logApi("telegram_webhook", { status: 200, reason: "rate_limited", ms: Date.now() - t0 });
      await posthog.flush().catch(() => {});
      return res.status(200).json({ ok: true });
    }

    await handleUpdate(update);
    logApi("telegram_webhook", { status: 200, ms: Date.now() - t0 });
  } catch (err) {
    logApi("telegram_webhook", {
      status: 200, outcome: "error",
      error_class: err?.constructor?.name, ms: Date.now() - t0,
    });
    posthog.capture(`tg:${chatId}`, "bot.error", { error_class: err?.constructor?.name });
    try {
      if (chatId !== "unknown") await tg.sendMessage(chatId, t("error.generic", "en"));
    } catch { /* the user is already having a bad time; do not compound it */ }
  }

  await posthog.flush().catch(() => {});
  return res.status(200).json({ ok: true });
};

module.exports.handleUpdate = handleUpdate;
module.exports.__testing__ = { secretMatches, readBody, limiter, encodeSearch };
