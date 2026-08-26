// POST /api/mcp — Pulpo as an MCP server.
//
// WHAT THIS IS
// MCP (Model Context Protocol) lets an LLM client — Claude Desktop,
// claude.ai connectors, ChatGPT, Claude Code — call typed tools. So
// "find me terrenos near El Tunco under $100k with ocean view" becomes
// a real query against live inventory instead of a guess: the client's
// model does the language understanding, and this server does the
// searching. That is the natural-language interface, without Pulpo
// having to run an LLM or parse intent itself.
//
// WHERE IT SITS
// Beside /api/v1, not on top of it. Both are thin adapters over
// shared/; the tool handlers call the same catalog, adapter, filters
// and ranking in-process, with no self-HTTP hop. The Telegram bot is
// the adapter that goes over HTTP.
//
//     shared/  ──┬── website        (in-process)
//                ├── /api/v1/*      (HTTP skin)   ── Telegram bot
//                └── /api/mcp       (this file)   ── Claude / ChatGPT
//
// STATELESS BY DESIGN
// A new server + transport is built per request with
// `sessionIdGenerator: undefined`, so nothing is retained between
// invocations. That matches both serverless (any instance can serve any
// request) and Pulpo's no-database rule — there is nowhere to put a
// session even if we wanted one, and read-only tools do not need it.
//
// Public and read-only, rate-limited per IP: the same data is already
// downloadable at /data/ranked.list.json, so a key would add friction
// for every client while protecting nothing.
//
// Setup instructions live in docs/mcp.md.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

import { API_VERSION } from "../_core.js";
import {
  GET_LISTING_SCHEMA,
  META_SCHEMA,
  SEARCH_SCHEMA,
  getListing,
  getMarketMeta,
  searchListings,
  type ToolResult,
} from "./_tools";
import { makeRateLimiter, ipFromRequest, send429 } from "../_rate_limit.js";
import { logApi, type ApiRequest, type ApiResponse } from "../v1/_http";

const posthog = require("../_posthog");

const limiter = makeRateLimiter({ windowMs: 60_000, maxAttempts: 60, name: "mcp" });

/** MCP tool results are content blocks. JSON goes in a text block —
 *  models parse it reliably and it survives every client renderer. */
function wrap(result: ToolResult) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(result.payload, null, 2) }],
    isError: !result.ok,
  };
}

export function buildServer(): McpServer {
  const server = new McpServer(
    { name: "pulpo", version: API_VERSION },
    {
      instructions:
        "Pulpo indexes land and property for sale in El Salvador, aggregated nightly from " +
        "brokers and ranked by value, location and momentum. Call get_market_meta first to " +
        "learn the valid zone slugs and price range, then search_listings, then get_listing " +
        "for detail. Listing titles and descriptions are bilingual {en, es} — use the " +
        "language the user is writing in. Always cite the listing's url so the user can open " +
        "it. Prices are USD (El Salvador's currency).",
    },
  );

  server.registerTool(
    "search_listings",
    {
      title: "Search Pulpo listings",
      description:
        "Search ranked land and property listings in El Salvador. Returns a compact summary " +
        "per listing plus the total number of matches. Prefer zone slugs from get_market_meta " +
        "over free-text for locations. Results are ordered by Pulpo's ranking (value, " +
        "location, momentum) unless another sort is given.",
      inputSchema: SEARCH_SCHEMA,
    },
    async (args: Record<string, unknown>) => {
      const r = searchListings(args ?? {});
      track("search_listings", r);
      return wrap(r);
    },
  );

  server.registerTool(
    "get_listing",
    {
      title: "Get one Pulpo listing",
      description:
        "Full detail for a single listing by its canonical id: description, reasons to buy, " +
        "utilities, distances to beach/airport/town, and how its price compares to others in " +
        "the same zone. Use the id returned by search_listings.",
      inputSchema: GET_LISTING_SCHEMA,
    },
    async (args: Record<string, unknown>) => {
      const r = getListing(args ?? {});
      track("get_listing", r);
      return wrap(r);
    },
  );

  server.registerTool(
    "get_market_meta",
    {
      title: "Get Pulpo search vocabulary",
      description:
        "The valid values for a search: every zone slug with its display name and listing " +
        "count, plus categories, property types, features, utilities, discovery tags, sorts " +
        "and the current price range. Call this before searching by location so you use real " +
        "zone slugs rather than guessing.",
      inputSchema: META_SCHEMA,
    },
    async (args: Record<string, unknown>) => {
      const r = getMarketMeta(args ?? {});
      track("get_market_meta", r);
      return wrap(r);
    },
  );

  return server;
}

function track(tool: string, r: ToolResult) {
  try {
    const p: any = r.payload ?? {};
    posthog.capture("mcp:anon", "mcp.tool_called", {
      tool,
      ok: r.ok,
      // Zero-result answers are the interesting signal: they mean the
      // model asked something our inventory could not satisfy.
      has_results: r.ok ? (p.total_matching ?? (p.listing ? 1 : null)) !== 0 : false,
      error: r.ok ? null : p.error ?? "unknown",
    });
  } catch {
    // Telemetry must never break a tool call.
  }
}

export default async function handler(req: ApiRequest, res: ApiResponse) {
  const t0 = Date.now();

  // MCP's streamable-HTTP transport is POST-driven. GET is reserved for
  // the SSE stream, which a stateless server cannot offer, so answer it
  // honestly rather than hanging the client.
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({
      error: "method_not_allowed",
      hint: "This is an MCP endpoint; POST JSON-RPC. See docs/mcp.md.",
    });
  }

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) return send429(res, rl, "mcp");

  const server = buildServer();
  const transport = new StreamableHTTPServerTransport({
    // Stateless: no session is retained between requests.
    sessionIdGenerator: undefined,
    enableJsonResponse: true,
  });

  try {
    await server.connect(transport);
    await transport.handleRequest(req as any, res as any, (req as any).body);
    logApi("mcp", { status: 200, ms: Date.now() - t0 });
  } catch (err: any) {
    logApi("mcp", { status: 500, error_class: err?.constructor?.name, ms: Date.now() - t0 });
    if (!(res as any).headersSent) {
      res.status(500).json({ error: "mcp_transport_failed" });
    }
  } finally {
    try { await transport.close(); } catch { /* nothing to salvage */ }
    try { await server.close(); } catch { /* nothing to salvage */ }
    try { await posthog.flush(); } catch { /* never fail a call on telemetry */ }
  }
}
