// Routing for `/l/<token>` source-opaque share URLs. The complementary
// encode/decode contract lives in share.test.ts; this file proves that
// a well-formed token round-trips to openListingId at the SPA boundary
// and that any malformed token falls back to home without surfacing
// broker-bearing state.

import { describe, expect, it } from "vitest";
import { parseLocation } from "./url-routing";
import { encodeShareToken } from "./share";

describe("parseLocation — /l/<token>", () => {
  it("decodes a valid token and surfaces the listing id like /listing/<id>", () => {
    const id = "remax__001461165132";
    const token = encodeShareToken(id);
    const parsed = parseLocation(`/l/${token}`);
    expect(parsed.openListingId).toBe(id);
    expect(parsed.isListingPath).toBe(true);
  });

  it("decodes tokens for non-remax sources too", () => {
    const cases = [
      "oceanside__15463",
      "encuentra24-cr_12345",
      "idealista.es_678901",
    ];
    for (const id of cases) {
      const parsed = parseLocation(`/l/${encodeShareToken(id)}`);
      expect(parsed.openListingId).toBe(id);
    }
  });

  it("malformed token → home, NEVER any listing surface", () => {
    // Garbage in the path. The SPA must not render a detail panel and
    // must not echo any source-bearing state back.
    const bogus = [
      "/l/not-a-real-token!!!",
      "/l/+++",
      "/l/",                  // empty token
      "/l/a",                 // too short to be valid base64
    ];
    for (const path of bogus) {
      const parsed = parseLocation(path);
      expect(parsed.openListingId).toBeNull();
      expect(parsed.isListingPath).toBe(false);
      expect(parsed.route).toBe("home");
    }
  });

  it("a token whose decoded payload contains slashes is rejected", () => {
    // Forged token: base64url of "../../etc/passwd". The SAFE_LISTING_ID_RE
    // post-decode check must drop it before it reaches React state.
    const malicious = encodeShareToken("../../etc/passwd");
    const parsed = parseLocation(`/l/${malicious}`);
    expect(parsed.openListingId).toBeNull();
    expect(parsed.isListingPath).toBe(false);
  });
});
