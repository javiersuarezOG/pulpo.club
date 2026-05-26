// Routing for `/l/<token>` source-opaque share URLs. The complementary
// encode/decode contract lives in share.test.ts; this file proves that
// a well-formed token round-trips to openListingId at the SPA boundary
// and that any malformed token falls back to home without surfacing
// broker-bearing state.

import { describe, expect, it } from "vitest";
import { parseLocation } from "./url-routing";
import { encodeShareToken } from "./share";

describe("parseLocation — /l/<token>", () => {
  it("decodes a valid token and surfaces it via pinListingId (NOT openListingId)", () => {
    // Share-pin landing must NOT auto-open the detail panel. The panel
    // covers the catalogue (mobile) or backdrop-blurs it (desktop),
    // either way defeating the share-pin feature. Recipients land on
    // /browse with the pinned card visually highlighted; they tap it
    // to open the detail.
    const id = "remax__001461165132";
    const token = encodeShareToken(id);
    const parsed = parseLocation(`/l/${token}`);
    expect(parsed.openListingId).toBeNull();
    expect(parsed.isListingPath).toBe(false);
    expect(parsed.pinListingId).toBe(id);
  });

  // Share-pin landing — /l/<token> must surface route=browse and
  // pinListingId so the app shell can replaceState to /browse?pin=<token>
  // on cold-load. Regression guard for the dead-end bug where a shared
  // listing opened over /home with no catalogue underneath.
  it("share link lands route=browse with pinListingId set", () => {
    const id = "remax__001461165132";
    const parsed = parseLocation(`/l/${encodeShareToken(id)}`);
    expect(parsed.route).toBe("browse");
    expect(parsed.pinListingId).toBe(id);
  });

  // Non-share parse paths must NEVER populate pinListingId — pinListingId
  // is the one-shot signal that "the user landed via a share URL." If a
  // /listing/:id or /browse parse leaks pinListingId, the app shell will
  // wrongly rewrite their URL and break the close-listing flow.
  it("non-share paths never set pinListingId", () => {
    const paths = [
      "/",
      "/browse",
      "/saved",
      "/plans",
      "/account",
      "/account/notifications",
      "/listing/remax-12345",
    ];
    for (const path of paths) {
      const parsed = parseLocation(path);
      expect(parsed.pinListingId).toBeNull();
    }
  });

  it("decodes tokens for non-remax sources too", () => {
    const cases = [
      "oceanside__15463",
      "encuentra24-cr_12345",
      "idealista.es_678901",
    ];
    for (const id of cases) {
      const parsed = parseLocation(`/l/${encodeShareToken(id)}`);
      expect(parsed.pinListingId).toBe(id);
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
