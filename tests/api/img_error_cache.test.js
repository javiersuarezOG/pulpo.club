// Pins the negative-cache contract on api/img.js's error paths (plan 007,
// step 1). A missing src on a Vercel preview (which races the photo commit)
// must NOT re-invoke this serverless function on every render — every error
// return (400 / 404 / 500) carries a short Cache-Control so the browser/edge
// absorbs the retry storm. The success path keeps its 1y-immutable header
// (covered implicitly: the helper only stamps the error TTL).
//
// Harness style mirrors tests/api/rate_limit.test.js (hand-rolled res mock).
// api/img.js is a CommonJS default-export handler; vitest imports it as the
// module default. The 404 path needs fetchAsset() to return null, which it
// does whenever fetch() resolves non-ok — so we stub globalThis.fetch.
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

// A valid request shape that passes the 400 guards and reaches the fetch.
function validReq() {
  return {
    query: { src: "remax__001.jpg", w: "800", root: "photos" },
    headers: { accept: "image/webp" },
  };
}

const NEGATIVE_CACHE = "public, max-age=60, s-maxage=300";

describe("api/img error-path negative cache", () => {
  let origFetch;

  beforeEach(() => {
    origFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = origFetch;
    vi.restoreAllMocks();
  });

  it("404 (asset not found) carries the short negative Cache-Control", async () => {
    // fetchAsset() returns null when the upstream responds non-ok →
    // handler returns 404.
    globalThis.fetch = vi.fn(async () => ({ ok: false, status: 404 }));
    const res = buildRes();
    await handler(validReq(), res);

    expect(res.statusCode).toBe(404);
    expect(res.body).toMatchObject({ error: "not_found" });
    expect(res.headers["Cache-Control"]).toBe(NEGATIVE_CACHE);
  });

  it("400 (bad_src) carries the short negative Cache-Control", async () => {
    const res = buildRes();
    // A slash in src trips the path-traversal guard before any fetch.
    await handler({ query: { src: "../etc/passwd", w: "800" }, headers: {} }, res);

    expect(res.statusCode).toBe(400);
    expect(res.body).toMatchObject({ error: "bad_src" });
    expect(res.headers["Cache-Control"]).toBe(NEGATIVE_CACHE);
  });

  it("400 (bad_width) carries the short negative Cache-Control", async () => {
    const res = buildRes();
    await handler({ query: { src: "ok.jpg", w: "999" }, headers: {} }, res);

    expect(res.statusCode).toBe(400);
    expect(res.body).toMatchObject({ error: "bad_width" });
    expect(res.headers["Cache-Control"]).toBe(NEGATIVE_CACHE);
  });

  it("does NOT stamp the negative cache on the immutable success path", async () => {
    // 1x1 transparent PNG so sharp has a real buffer to resize.
    const onePx = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC",
      "base64",
    );
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => onePx.buffer.slice(onePx.byteOffset, onePx.byteOffset + onePx.byteLength),
    }));
    const res = buildRes();
    await handler(validReq(), res);

    expect(res.statusCode).toBe(200);
    expect(res.headers["Cache-Control"]).toBe(
      "public, max-age=31536000, immutable",
    );
  });
});
