// Unit tests for api/_svix.js — the shared Svix verifier used by both
// api/resend-webhook.js (newsletter) and api/clerk/webhook.js (auth).
// Lives next to the shared code; webhook-specific tests live in
// tests/api/{newsletter_resend_webhook,clerk_webhook}.test.js.

import { describe, it, expect } from "vitest";
import crypto from "node:crypto";

import { verifySvixSignature, readRawBody, TIMESTAMP_TOLERANCE_S, MAX_BODY_SIZE } from "../../api/_svix.js";

const TEST_SECRET = "whsec_dGVzdC1zZWNyZXQtZm9yLXVuaXQtdGVzdHM=";

function sign(secret, id, ts, body) {
  const stripped = secret.startsWith("whsec_") ? secret.slice(6) : secret;
  let key;
  try { key = Buffer.from(stripped, "base64"); } catch { key = Buffer.from(secret, "utf8"); }
  if (key.length === 0) key = Buffer.from(secret, "utf8");
  const sig = crypto.createHmac("sha256", key).update(`${id}.${ts}.${body}`).digest("base64");
  return `v1,${sig}`;
}

describe("verifySvixSignature (shared)", () => {
  const id = "msg_abc";
  const body = '{"hello":"world"}';

  it("accepts a freshly-signed payload", () => {
    const ts = Math.floor(Date.now() / 1000).toString();
    expect(verifySvixSignature({
      secret: TEST_SECRET, svixId: id, svixTimestamp: ts,
      svixSignature: sign(TEST_SECRET, id, ts, body), body,
    })).toBe(true);
  });

  it("rejects a timestamp outside the ±5min window", () => {
    const old = (Math.floor(Date.now() / 1000) - TIMESTAMP_TOLERANCE_S - 60).toString();
    expect(verifySvixSignature({
      secret: TEST_SECRET, svixId: id, svixTimestamp: old,
      svixSignature: sign(TEST_SECRET, id, old, body), body,
    })).toBe(false);
  });

  it("rejects when signature doesn't match", () => {
    const ts = Math.floor(Date.now() / 1000).toString();
    const sig = sign(TEST_SECRET, id, ts, body);
    const tampered = sig.replace(/.$/, "X");
    expect(verifySvixSignature({
      secret: TEST_SECRET, svixId: id, svixTimestamp: ts,
      svixSignature: tampered, body,
    })).toBe(false);
  });

  it("accepts when one of multiple space-separated signatures matches", () => {
    const ts = Math.floor(Date.now() / 1000).toString();
    const sig = sign(TEST_SECRET, id, ts, body);
    const combined = `v1,wrongone ${sig}`;
    expect(verifySvixSignature({
      secret: TEST_SECRET, svixId: id, svixTimestamp: ts,
      svixSignature: combined, body,
    })).toBe(true);
  });

  it("returns false when any required input is empty", () => {
    const ts = Math.floor(Date.now() / 1000).toString();
    const valid = { secret: TEST_SECRET, svixId: id, svixTimestamp: ts, svixSignature: sign(TEST_SECRET, id, ts, body), body };
    for (const k of Object.keys(valid)) {
      expect(verifySvixSignature({ ...valid, [k]: "" })).toBe(false);
    }
  });

  it("rejects non-numeric timestamps", () => {
    const ts = "not-a-number";
    expect(verifySvixSignature({
      secret: TEST_SECRET, svixId: id, svixTimestamp: ts,
      svixSignature: "v1,anything", body,
    })).toBe(false);
  });

  it("constants are sane (±5min, 64KB)", () => {
    expect(TIMESTAMP_TOLERANCE_S).toBe(300);
    expect(MAX_BODY_SIZE).toBe(64 * 1024);
  });
});

describe("readRawBody", () => {
  it("returns string body unchanged (truncated to MAX_BODY_SIZE)", async () => {
    const raw = await readRawBody({ body: "hello" });
    expect(raw).toBe("hello");
  });

  it("re-serializes parsed object body (Vercel default)", async () => {
    const raw = await readRawBody({ body: { a: 1, b: "x" } });
    expect(raw).toBe('{"a":1,"b":"x"}');
  });

  it("reads from async iterable when body is absent (Vercel stream path)", async () => {
    // Real Vercel handlers receive a Node IncomingMessage; simulate by
    // making the request itself async-iterable with a single chunk.
    const req = {
      async *[Symbol.asyncIterator]() {
        yield Buffer.from("streamed-body");
      },
    };
    const raw = await readRawBody(req);
    expect(raw).toBe("streamed-body");
  });

  it("truncates oversized stream bodies at MAX_BODY_SIZE", async () => {
    const big = "x".repeat(MAX_BODY_SIZE + 1024);
    const req = {
      async *[Symbol.asyncIterator]() {
        yield Buffer.from(big);
      },
    };
    const raw = await readRawBody(req);
    expect(raw.length).toBeLessThanOrEqual(MAX_BODY_SIZE);
  });
});
