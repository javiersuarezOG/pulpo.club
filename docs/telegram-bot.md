# Telegram bot — setup and runbook

`POST /api/telegram/webhook`

## What it is

Phase 2 of the API-first PRD: a chat channel reaching the same capabilities the
website uses. The bot holds **no business logic** — it turns taps into
`/api/v1` calls and results into messages. What a listing is, which ones match,
and how they rank all live in `shared/`.

It talks to `/api/v1` over HTTP rather than importing `shared/` directly (the
way the MCP server does). That is deliberate: it proves the HTTP contract works
for an external channel — exactly what WhatsApp will need — and self-calls hit
the CDN, so a popular query is served from cache instead of re-reading the
catalog.

## The flow

```
/start → language → property type → zone → price band → 5 results → detail
```

Inline keyboards throughout, no free-text parsing. Guided choice needs no
intent understanding, and natural language already has a home: the MCP server,
where a real model does the understanding. If a user types anything else the
bot points them back at `/start`.

## Setup (one time)

**1. Create the bot.** Message [@BotFather](https://t.me/botfather) → `/newbot`
→ pick a name and username. He replies with a token like `12345:AA...`.

**2. Generate a webhook secret.**

```bash
openssl rand -hex 32
```

**3. Set both in Vercel** (Project → Settings → Environment Variables):

| variable | value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the BotFather token |
| `TELEGRAM_WEBHOOK_SECRET` | the hex string from step 2 |
| `PULPO_PUBLIC_BASE_URL` | `https://pulpo.club` (optional; this is the default) |

Redeploy so the functions pick them up.

**4. Register the webhook.**

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://pulpo.club/api/telegram/webhook",
    "secret_token": "<SECRET>",
    "allowed_updates": ["message", "callback_query"]
  }'
```

**5. Add the monitoring inputs** so the active probe can check registration:
repo secret `TELEGRAM_BOT_TOKEN`, and repo *variable* `TELEGRAM_WEBHOOK_URL` =
`https://pulpo.club/api/telegram/webhook`.

**6. Walk it.** Open the bot in Telegram, send `/start`, and complete a search.

### Testing against a preview first

Use a **second BotFather bot** for previews and point its webhook at the preview
URL. One bot can only have one webhook, so pointing the production bot at a
preview takes production down.

## Kill switch

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```

Instant, and independent of deploys — the bot goes silent immediately without
touching `main`. Re-run step 4 to bring it back.

## Two rules the handler is built around

**1. Always return 200.** Telegram redelivers non-2xx responses, so a handler
that 500s on one bad update gets that update forever. Failures are logged and
sent to PostHog; the user gets an apology, Telegram gets a success. The
try-block deliberately covers body parsing and chat-id extraction, not just the
flow — a throw before the guard would escape as an unhandled rejection and
Vercel would answer 500.

**2. Verify the secret.** `setWebhook` registers a `secret_token` that Telegram
echoes in `X-Telegram-Bot-Api-Secret-Token`, compared here in constant time.
Without that check the endpoint is a public "make our bot say things" API.

## State, without a database

Pulpo has no database by design, so the whole conversation is encoded into
Telegram's own `callback_data`: each button carries the search that produced it.
Nothing to provision or leak, any instance can serve any tap, and a button still
works after a redeploy.

The constraint that shapes it: **`callback_data` is capped at 64 bytes** — bytes,
not characters, so accented zone names cost extra. Over the limit and the Bot
API rejects the message, meaning the keyboard silently fails to appear. Encoders
return `null` rather than an oversized payload, and a test walks every
type × zone × band × page combination to prove the budget holds.

Price-band **indexes** travel in `callback_data`, so reordering `PRICE_BANDS`
invalidates buttons already sitting in users' chat history. Append instead.

## Monitoring

Two complementary checks, because neither is sufficient alone:

**Passive** — the `telegram` family in `scripts/check_webhook_health.py` watches
for `telegram.webhook_received` and alerts after 7 days of silence. The window is
deliberately loose: this bot's traffic is organic, and "nobody messaged us" is a
growth fact, not an outage. An alert that cries wolf is one people learn to
ignore.

**Active** — `scripts/check_telegram_webhook.py` asks Telegram directly, every 6
hours, and catches what silence cannot distinguish:

- the webhook was deregistered, or a second `setWebhook` stole it
- the registered URL drifted from production
- Telegram is failing to deliver (`last_error_message` — this is how a rotated
  secret shows up)
- updates are piling up unacknowledged (a wedged or timing-out handler)

Both Slack via `SLACK_WEBHOOK_URL` and exit 0 — they page a human, they do not
fail the shared workflow.

## Telemetry

| event | meaning |
|---|---|
| `telegram.webhook_received` | heartbeat; consumed by `check_webhook_health.py` |
| `bot.start` | a user opened the bot |
| `bot.search_step` | a step of the guided flow |
| `bot.listing_viewed` | a user drilled into a listing |
| `bot.error` | the handler caught a throw |

## Out of scope for the MVP

Free-text natural language (that is the MCP server's job), saved searches,
alerts, and WhatsApp. WhatsApp reuses this same `/api/v1` path and the same
stateless-state approach; it needs Meta business verification and per-conversation
billing, which is why Telegram goes first.
