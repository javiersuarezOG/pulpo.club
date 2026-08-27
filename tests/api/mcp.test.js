// The Pulpo MCP server.
//
// Two layers are tested:
//   1. the tool functions directly, on synthetic fixtures
//   2. the real JSON-RPC surface, by driving the SDK's in-memory
//      transport pair — initialize, tools/list, tools/call
//
// (2) matters because the tools could be perfect while the protocol
// wiring is wrong, and a broken handshake is invisible until a client
// fails to connect. Testing through the SDK's own client is the closest
// thing to Claude Desktop that runs in CI.

import { afterEach, describe, expect, it } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { buildServer } from "../../api/mcp/index.js";
import * as tools from "../../api/mcp/_tools.js";
import { argsToQuery, getListing, getMarketMeta, searchListings, summarize } from "../../api/mcp/_tools.js";
import { __testing__ } from "../../api/v1/_catalog.js";
import { selectListings } from "../../api/v1/_serve.js";
import { adaptAll } from "../../api/v1/_serve.js";

const row = (over = {}) => ({
  source: "remax",
  source_id: String(Math.random()).slice(2, 10),
  zone: "el-tunco",
  country: "SV",
  department: "La Libertad",
  title_canonical: { en: "Ocean-view lot", es: "Terreno con vista al mar" },
  short_description_canonical: { en: "A lot.", es: "Un terreno." },
  reasons_to_buy: [],
  price_usd: 100_000,
  area_m2: 1000,
  price_per_m2: 100,
  property_type: "land",
  subcategory: "land",
  master_category: "beach",
  discovery_tags: ["top_rated"],
  photo_urls: [],
  photos_count: 0,
  rank_score: 50,
  first_seen_at: new Date().toISOString(),
  is_sold: false,
  is_incomplete: false,
  ...over,
});

const seam = tools.__catalogTesting__ ?? __testing__;
const setCatalog = (rows, generatedAt = "2026-08-21T04:04:32Z") =>
  seam.setCatalog("SV", { rows, generatedAt, country: "SV" });

afterEach(() => seam.reset());

describe("argsToQuery", () => {
  it("translates structured args into the website's query dialect", () => {
    // Same dialect as a /browse share link, so MCP, the website and
    // /api/v1 resolve an equivalent request identically.
    const qs = argsToQuery({
      category: "beach", type: "land", price_max: 250000,
      features: ["ocean_view", "flat"], zones: ["el-tunco", "el-zonte"], limit: 5,
    });
    const p = new URLSearchParams(qs);
    expect(p.get("master")).toBe("beach");
    expect(p.get("sub")).toBe("land");
    expect(p.get("pmax")).toBe("250000");
    expect(p.get("features")).toBe("ocean_view,flat");
    // Slugs in, DISPLAY NAMES out: applyFilters matches on l.zone_name,
    // so passing the slug through unchanged would silently match zero.
    expect(p.get("zones")).toBe("El Tunco,El Zonte");
    expect(p.get("limit")).toBe("5");
  });

  it("accepts a display name as readily as a slug", () => {
    // The model is told to use slugs, but should not be punished for
    // echoing back the human-readable name it was also shown.
    expect(new URLSearchParams(argsToQuery({ zones: ["El Tunco"] })).get("zones")).toBe("El Tunco");
    expect(new URLSearchParams(argsToQuery({ zones: ["el-tunco"] })).get("zones")).toBe("El Tunco");
    // An unmapped slug Title-Cases to exactly what the adapter wrote
    // into zone_name, so new pipeline zones work without a table edit.
    expect(new URLSearchParams(argsToQuery({ zones: ["playa-las-tunas"] })).get("zones"))
      .toBe("Playa Las Tunas");
  });

  it("omits absent args rather than emitting empty params", () => {
    // `pmax=` would be parsed as a real cap and silently hide listings.
    const p = new URLSearchParams(argsToQuery({}));
    expect(p.has("pmax")).toBe(false);
    expect(p.has("q")).toBe(false);
    expect(p.get("limit")).toBe("10");
  });
});

describe("search_listings", () => {
  it("reports total matches separately from the page returned", () => {
    // So the model says "of 30 matches, here are 5" instead of
    // implying it saw the whole market.
    setCatalog(Array.from({ length: 30 }, (_, i) => row({ source_id: `l${i}` })));
    const r = searchListings({ limit: 5 });
    expect(r.ok).toBe(true);
    expect(r.payload.total_matching).toBe(30);
    expect(r.payload.returned).toBe(5);
    expect(r.payload.listings).toHaveLength(5);
  });

  it("finds listings when given the zone slug get_market_meta advertised", () => {
    // Regression guard for a bug found only by running against live
    // data: slugs went straight into a filter that matches display
    // names, so every zone search returned zero and read as "nothing
    // there" rather than as an error.
    setCatalog([row({ zone: "el-tunco" }), row({ zone: "mizata" })]);
    const slug = getMarketMeta({}).payload.zones[0].slug;
    const r = searchListings({ zones: [slug] });
    expect(r.payload.total_matching).toBeGreaterThan(0);
  });

  it("stamps the catalog date so the model can say how fresh this is", () => {
    setCatalog([row()]);
    expect(searchListings({}).payload.data_as_of).toBe("2026-08-21T04:04:32Z");
  });

  it("gives every listing a citable pulpo.club URL tagged to the channel", () => {
    setCatalog([row({ source_id: "12345" })]);
    const l = searchListings({}).payload.listings[0];
    expect(l.id).toBe("remax__12345");
    expect(l.url).toBe("https://pulpo.club/listing/remax__12345?utm_source=mcp");
  });

  it("keeps titles bilingual so the model can answer in the user's language", () => {
    setCatalog([row()]);
    const l = searchListings({}).payload.listings[0];
    expect(l.title.en).toBe("Ocean-view lot");
    expect(l.title.es).toBe("Terreno con vista al mar");
  });

  it("hides sold and incomplete listings, like every other surface", () => {
    setCatalog([
      row({ source_id: "ok" }),
      row({ source_id: "sold", is_sold: true }),
      row({ source_id: "partial", is_incomplete: true }),
    ]);
    const r = searchListings({});
    expect(r.payload.total_matching).toBe(1);
  });

  it("caps limit so a huge request cannot flood the model's context", () => {
    setCatalog(Array.from({ length: 40 }, (_, i) => row({ source_id: `l${i}` })));
    expect(searchListings({ limit: 999 }).payload.returned).toBeLessThanOrEqual(25);
  });

  it("returns a structured error, not a throw, for bad country / missing data", () => {
    setCatalog([row()]);
    expect(searchListings({ country: "PA" })).toMatchObject({ ok: false });

    seam.setCatalog("SV", null);
    const gone = searchListings({});
    expect(gone.ok).toBe(false);
    expect(gone.payload.error).toBe("data_unavailable");
  });
});

describe("get_listing", () => {
  it("returns detail including the zone price context a buyer needs", () => {
    setCatalog([row({ source_id: "12345", price_vs_zone_pct: -30, zone_comp_count: 23 })]);
    const r = getListing({ id: "remax__12345" });
    expect(r.ok).toBe(true);
    expect(r.payload.listing.id).toBe("remax__12345");
    expect(r.payload.listing.zone_price_context.vs_zone_median_pct).toBe(-30);
    expect(r.payload.listing.infrastructure).toBeDefined();
    expect(r.payload.listing.distances_km).toBeDefined();
  });

  it("rejects malformed ids and 404s hidden ones without throwing", () => {
    setCatalog([row({ source_id: "sold", is_sold: true })]);
    expect(getListing({ id: "remax__../../etc/passwd" }).payload.error).toBe("invalid_id");
    expect(getListing({ id: "remax__nope" }).payload.error).toBe("not_found");
    expect(getListing({ id: "remax__sold" }).payload.error).toBe("not_found");
  });
});

describe("get_market_meta", () => {
  it("returns the zone vocabulary with display names and counts", () => {
    setCatalog([row({ zone: "el-tunco" }), row({ zone: "el-tunco" }), row({ zone: "mizata" })]);
    const r = getMarketMeta({});
    expect(r.ok).toBe(true);
    expect(r.payload.zones).toEqual([
      { slug: "el-tunco", name: "El Tunco", count: 2 },
      { slug: "mizata", name: "Mizata", count: 1 },
    ]);
    expect(r.payload.total_listings).toBe(3);
  });

  it("enumerates every axis search_listings accepts", () => {
    // If these drift from SEARCH_SCHEMA the model is told about filters
    // it cannot use, or misses ones it can.
    setCatalog([row()]);
    const p = getMarketMeta({}).payload;
    expect(p.types).toEqual(["land", "homes", "condos"]);
    expect(p.categories).toEqual(["beach", "lake"]);
    expect(p.features).toContain("ocean_view");
    expect(p.infrastructure).toContain("power");
    expect(p.discovery_tags).toContain("top_rated");
    expect(p.sorts).toContain("rank");
  });
});

describe("parity — MCP answers match the website's engine", () => {
  const rows = [
    row({ source_id: "a", subcategory: "land", price_usd: 50_000, rank_score: 80 }),
    row({ source_id: "b", subcategory: "land", price_usd: 300_000, rank_score: 90 }),
    row({ source_id: "c", subcategory: "homes", price_usd: 50_000, rank_score: 70 }),
  ];

  it("returns the same ids /api/v1/listings would for the same request", () => {
    setCatalog(rows);
    const adapted = adaptAll(rows, "SV");

    const viaMcp = searchListings({ type: "land", price_max: 250_000, limit: 25 })
      .payload.listings.map((l) => l.id).sort();
    const viaApi = selectListings(adapted, "sub=land&pmax=250000&limit=25")
      .listings.map((l) => l.id).sort();

    expect(viaMcp).toEqual(viaApi);
  });
});

describe("JSON-RPC protocol surface", () => {
  // Drives the real SDK client against the real server over the SDK's
  // in-memory transport pair. If the handshake or tool registration is
  // wrong, these fail here rather than in Claude Desktop.
  async function connect() {
    const server = buildServer();
    const client = new Client({ name: "test", version: "1.0.0" });
    const [clientT, serverT] = InMemoryTransport.createLinkedPair();
    await Promise.all([server.connect(serverT), client.connect(clientT)]);
    return { client, server };
  }

  it("completes the initialize handshake and advertises the server", async () => {
    const { client, server } = await connect();
    expect(client.getServerVersion()).toMatchObject({ name: "pulpo" });
    await server.close();
  });

  it("lists exactly the three tools, each with a description and schema", async () => {
    const { client, server } = await connect();
    const { tools } = await client.listTools();

    expect(tools.map((t) => t.name).sort()).toEqual([
      "get_listing", "get_market_meta", "search_listings",
    ]);
    for (const t of tools) {
      // A tool without a description is a tool the model will misuse.
      expect(t.description, t.name).toBeTruthy();
      expect(t.inputSchema, t.name).toBeDefined();
    }
    await server.close();
  });

  it("executes a real tools/call round trip", async () => {
    setCatalog([row({ source_id: "12345" })]);
    const { client, server } = await connect();

    const res = await client.callTool({
      name: "search_listings",
      arguments: { type: "land", limit: 5 },
    });

    expect(res.isError).toBeFalsy();
    const payload = JSON.parse(res.content[0].text);
    expect(payload.total_matching).toBe(1);
    expect(payload.listings[0].id).toBe("remax__12345");
    await server.close();
  });

  it("surfaces a tool-level failure as isError, not a transport crash", async () => {
    seam.setCatalog("SV", null);
    const { client, server } = await connect();

    const res = await client.callTool({ name: "search_listings", arguments: {} });
    expect(res.isError).toBe(true);
    expect(JSON.parse(res.content[0].text).error).toBe("data_unavailable");
    await server.close();
  });

  it("refuses an unknown tool instead of fabricating an answer", async () => {
    // Per the MCP spec a tool failure is reported in the RESULT
    // (isError) rather than as a JSON-RPC protocol error, so the model
    // can see and recover from it. What matters is that the server
    // neither invents a result nor takes the transport down.
    const { client, server } = await connect();

    const res = await client.callTool({ name: "drop_database", arguments: {} });
    expect(res.isError).toBe(true);
    expect(JSON.stringify(res.content)).toMatch(/not found|unknown|invalid/i);

    // Still usable afterwards — one bad call must not poison the session.
    setCatalog([row()]);
    const ok = await client.callTool({ name: "get_market_meta", arguments: {} });
    expect(ok.isError).toBeFalsy();

    await server.close();
  });
});
