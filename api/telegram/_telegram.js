// api/telegram/_telegram.js — the slice of the Bot API this bot uses.
//
// Raw fetch, no library. grammY/telegraf exist to give you middleware,
// session stores and long-polling loops; this bot is a stateless
// request/response webhook with four API calls, so a framework would
// add a dependency to every deploy in exchange for nothing. The repo's
// other webhooks (stripe, clerk, resend) are bare handlers for the same
// reason.

const API_ROOT = "https://api.telegram.org";

function botToken() {
  return (process.env.TELEGRAM_BOT_TOKEN || "").trim();
}

function isConfigured() {
  return botToken().length > 0 && (process.env.TELEGRAM_WEBHOOK_SECRET || "").trim().length > 0;
}

/**
 * Call a Bot API method.
 *
 * Never throws: a Telegram-side failure must not turn into a 5xx to
 * Telegram, because Telegram retries 5xx and a retry storm on a broken
 * message is worse than a dropped one. Returns {ok:false} instead.
 */
async function call(method, payload, deps = {}) {
  const doFetch = deps.fetch || fetch;
  const token = botToken();
  if (!token) return { ok: false, error: "not_configured" };

  try {
    const res = await doFetch(`${API_ROOT}/bot${token}/${method}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      console.log(`[api] telegram_call_failed method=${method} description=${json.description || "?"}`);
    }
    return json;
  } catch (err) {
    console.log(`[api] telegram_call_threw method=${method} error_class=${err?.constructor?.name}`);
    return { ok: false, error: "fetch_failed" };
  }
}

const sendMessage = (chatId, text, extra = {}, deps) =>
  call("sendMessage", {
    chat_id: chatId,
    text,
    parse_mode: "Markdown",
    // Broker photos would otherwise expand into huge previews under
    // every result line.
    disable_web_page_preview: true,
    ...extra,
  }, deps);

const sendPhoto = (chatId, photo, caption, extra = {}, deps) =>
  call("sendPhoto", {
    chat_id: chatId,
    // A URL, not bytes: Telegram fetches the image itself, so no photo
    // data flows through the function and the response stays fast.
    photo,
    caption,
    parse_mode: "Markdown",
    ...extra,
  }, deps);

const editMessageText = (chatId, messageId, text, extra = {}, deps) =>
  call("editMessageText", {
    chat_id: chatId,
    message_id: messageId,
    text,
    parse_mode: "Markdown",
    disable_web_page_preview: true,
    ...extra,
  }, deps);

/** Every callback query must be answered or the user's button spins. */
const answerCallbackQuery = (id, extra = {}, deps) =>
  call("answerCallbackQuery", { callback_query_id: id, ...extra }, deps);

/** Escape Telegram Markdown so broker-authored titles cannot break the
 *  message or inject formatting. Titles routinely contain * and _. */
function escapeMarkdown(text) {
  return String(text ?? "").replace(/([*_`\[\]])/g, "\\$1");
}

module.exports = {
  API_ROOT,
  answerCallbackQuery,
  botToken,
  call,
  editMessageText,
  escapeMarkdown,
  isConfigured,
  sendMessage,
  sendPhoto,
};
