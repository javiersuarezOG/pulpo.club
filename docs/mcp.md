# Pulpo MCP server

`POST https://pulpo.club/api/mcp`

## What it is

MCP (Model Context Protocol) lets an LLM client call typed tools. Connecting
Pulpo turns "find me terrenos near El Tunco under $100k with an ocean view"
into a real query against live inventory — the client's model does the language
understanding, and Pulpo does the searching.

That is how Pulpo gets a natural-language interface without running an LLM or
parsing intent itself. The same three tools serve Claude Desktop, claude.ai
connectors, ChatGPT connectors, and Claude Code.

## Where it sits

Beside `/api/v1`, not on top of it. Both are thin adapters over `shared/` — the
tool handlers call the same catalog, adapter, filters and ranking **in-process**,
with no self-HTTP hop.

```
        shared/  (filters · sort · search · adapt · zones)
       /    |    \
website     |     \__ /api/v1/*  ──  Telegram bot   (HTTP)
(in-proc)   |
       /api/mcp  ──  Claude · ChatGPT   (MCP)
```

So an MCP answer, an API response and what a user sees on `/browse` cannot
disagree: there is one implementation of every rule.

## Connecting it

**claude.ai / Claude Desktop** — Settings → Connectors → Add custom connector,
URL `https://pulpo.club/api/mcp`. No auth needed.

**Claude Code**

```bash
claude mcp add --transport http pulpo https://pulpo.club/api/mcp
```

**Anything else that speaks streamable HTTP** — point it at the same URL.

**Local check without a client:**

```bash
npx @modelcontextprotocol/inspector
# then connect to http://localhost:3000/api/mcp (or the deployed URL)
```

## Tools

### `get_market_meta`
The vocabulary for a search: every zone slug with its display name and listing
count, plus categories, types, features, utilities, discovery tags, sorts and
the current price range. **Call this first** when a request mentions a place —
it is what stops a model inventing `el-tunco-beach`.

### `search_listings`
Ranked, filtered results. Returns a compact summary per listing plus
`total_matching`, so the model can say "of 297 matches, here are 10" rather than
implying it saw everything. Accepts `query`, `category`, `type`, `zones`,
`price_min/max`, `size_min/max`, `features`, `infra`, `tags`, `sort`, `limit`
(max 25), `offset`, `country`.

Zones accept either the slug or the display name — the server translates.

### `get_listing`
Full detail for one listing by canonical id (`source__source_id`): description,
reasons to buy, utilities, distances to beach/airport/town, and how the price
compares to others in the same zone.

## Design notes

**Stateless.** A server and transport are built per request with
`sessionIdGenerator: undefined`. Nothing is retained between invocations, which
suits both serverless and Pulpo's no-database rule.

**Public, read-only, rate-limited** (60/min/IP). The same data is already
downloadable at `/data/ranked.list.json`, so a key would add friction for every
client while protecting nothing. There are no write tools; nothing here can
change Pulpo's state.

**Compact responses.** A full `Listing` is ~90 fields; returning 25 of those
would flood the model's context with photo arrays and score internals it cannot
use. Search returns a summary, detail is one call away.

**Bilingual.** Titles and descriptions come back as `{en, es}` so the model can
answer in the language the user wrote in. There is no locale parameter — one
representation, one cache entry.

**Freshness.** Every response carries `data_as_of`, the nightly pipeline's own
timestamp. Sold and incomplete listings are excluded, exactly as on the website.

## Telemetry

`mcp.tool_called { tool, ok, has_results, error }` → PostHog. `has_results:false`
is the interesting signal: it means a model asked something the inventory could
not satisfy, which is inventory-gap feedback rather than a bug.
