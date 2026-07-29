// Pins the quarantine contract on api/img.js for root=photos-hires
// (image-pipeline audit 2026-07-29, PR-B). Hires files flagged by
// resdet as broker-upscaled carry a `.quarantine` sidecar; the social
// endpoint (api/social/image.js) honors it, and /api/img must too —
// otherwise ?root=photos-hires is a bypass that serves quarantined
// bytes. The quarantined response is a 404 with the standard negative
// cache so the edge/browser absorb retries like any missing asset.
//
// Harness style mirrors tests/api/img_error_cache.test.js (hand-rolled
// res mock + globalThis.fetch stub).
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import imgHandler from "../../api/img.js";

const handler = imgHandler.default || imgHandler;

function buildRes() {
  return {
    statusCode: null,
    headers: {},
    body: null,
    setHeader(k, v) {
      this.headers[k] = v;
    },
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(b) {
      this.body = b;
      return this;
    },
    send(b) {
      this.body = b;
      return this;
    },
  };
}

const NEGATIVE_CACHE = "public, max-age=60, s-maxage=300";

// 1x1 transparent PNG so sharp has a real buffer on success paths.
const onePx = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC",
  "base64",
);

function okImageResponse() {
  return {
    ok: true,
    status: 200,
    arrayBuffer: async () =>
      onePx.buffer.slice(onePx.byteOffset, onePx.byteOffset + onePx.byteLength),
  };
}

describe("api/img quarantine enforcement (root=photos-hires)", () => {
  let origFetch;

  beforeEach(() => {
    origFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = origFetch;
    vi.restoreAllMocks();
  });

  it("404s a quarantined hires asset without fetching its bytes", async () => {
    const calls = [];
    globalThis.fetch = vi.fn(async (url, opts) => {
      calls.push({ url: String(url), method: (opts && opts.method) || "GET" });
      if (String(url).endsWith(".quarantine")) return { ok: true, status: 200 };
      return okImageResponse();
    });

    const res = buildRes();
    await handler(
      {
        query: { src: "remax_001.hires.jpg", w: "800", root: "photos-hires" },
        headers: { accept: "image/webp" },
      },
      res,
    );

    expect(res.statusCode).toBe(404);
    expect(res.body).toMatchObject({ error: "quarantined" });
    expect(res.headers["Cache-Control"]).toBe(NEGATIVE_CACHE);
    // Marker probed via HEAD; the parent blob was never downloaded.
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("HEAD");
    expect(calls[0].url).toMatch(/\.quarantine$/);
  });

  it("serves a hires asset normally when no quarantine marker exists", async () => {
    globalThis.fetch = vi.fn(async (url, opts) => {
      if (((opts && opts.method) || "GET") === "HEAD") return { ok: false, status: 404 };
      return okImageResponse();
    });

    const res = buildRes();
    await handler(
      {
        query: { src: "remax_001.hires.jpg", w: "800", root: "photos-hires" },
        headers: { accept: "image/webp" },
      },
      res,
    );

    expect(res.statusCode).toBe(200);
    expect(res.headers["Cache-Control"]).toBe("public, max-age=31536000, immutable");
  });

  it("does not probe for quarantine markers on root=photos", async () => {
    const calls = [];
    globalThis.fetch = vi.fn(async (url, opts) => {
      calls.push({ url: String(url), method: (opts && opts.method) || "GET" });
      return okImageResponse();
    });

    const res = buildRes();
    await handler(
      {
        query: { src: "remax_001.jpg", w: "800", root: "photos" },
        headers: { accept: "image/webp" },
      },
      res,
    );

    expect(res.statusCode).toBe(200);
    expect(calls.every((c) => !c.url.includes(".quarantine"))).toBe(true);
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("treats a failing quarantine probe as not-quarantined (fail-open to the asset)", async () => {
    // The HEAD probe throwing must not take the endpoint down — same
    // fail-soft posture as fetchAsset. The asset itself still gates on
    // its own fetch.
    globalThis.fetch = vi.fn(async (url, opts) => {
      if (((opts && opts.method) || "GET") === "HEAD") throw new Error("network down");
      return okImageResponse();
    });

    const res = buildRes();
    await handler(
      {
        query: { src: "remax_001.hires.jpg", w: "800", root: "photos-hires" },
        headers: { accept: "image/webp" },
      },
      res,
    );

    expect(res.statusCode).toBe(200);
  });
});
