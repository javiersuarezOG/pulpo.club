// Source-opacity round-trip: the share token must encode the listing
// id losslessly, must not contain the raw source name in any plausible
// substring search, and must decode back to the exact id on the SPA
// side. The matching `/l/<token>` route in parseLocation() (covered by
// url-routing.test.ts) reuses the same base64url alphabet — keep these
// in lockstep.

import { describe, expect, it, vi } from "vitest";
import { encodeShareToken, decodeShareToken, shareUrlFor } from "./share";

describe("share token", () => {
  it("encodes a remax id without revealing the source name in the token", () => {
    const id = "remax__001461165132";
    const token = encodeShareToken(id);
    // The whole reason this exists: a casual reader of the URL must not
    // be able to read "remax" out of it.
    expect(token.toLowerCase()).not.toContain("remax");
    expect(token).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it("encodes + decodes is a lossless round trip for every catalog id shape", () => {
    const ids = [
      "remax__001461165132",
      "oceanside__15463",
      "encuentra24-cr_12345",
      "idealista.es_678901",
      "pulpo__abc-def_ghi.jkl",
    ];
    for (const id of ids) {
      const token = encodeShareToken(id);
      expect(decodeShareToken(token)).toBe(id);
    }
  });

  it("rejects tokens with characters outside the base64url alphabet", () => {
    // `+` and `/` and `=` are NOT in base64url — the URL would have
    // pasted them as `%2B` / `%2F` / `%3D` and the route would 404
    // before we even got here. Verify decode bounces.
    expect(decodeShareToken("foo+bar")).toBeNull();
    expect(decodeShareToken("foo/bar")).toBeNull();
    expect(decodeShareToken("foo=bar")).toBeNull();
    // Trailing whitespace and other junk
    expect(decodeShareToken(" foo")).toBeNull();
    expect(decodeShareToken("")).toBeNull();
  });

  it("decodes only base64-valid input — random bytes return null", () => {
    // base64 atob throws on misaligned padding. The helper must swallow.
    // (Length-1 strings are always invalid base64 — too few bits.)
    expect(decodeShareToken("A")).toBeNull();
  });
});

describe("shareUrlFor", () => {
  it("uses pulpo.club as the canonical origin in SSR contexts", () => {
    // No window — simulates the build-time / Node fallback path.
    // vi.stubGlobal cleanly clears between tests.
    vi.stubGlobal("window", undefined);
    try {
      const url = shareUrlFor("remax__001461165132");
      expect(url.startsWith("https://pulpo.club/l/")).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("uses window.location.origin when in a browser", () => {
    vi.stubGlobal("window", { location: { origin: "http://localhost:5173" } });
    try {
      const url = shareUrlFor("remax__001461165132");
      expect(url.startsWith("http://localhost:5173/l/")).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("share URL contains no broker name regardless of the listing source", () => {
    vi.stubGlobal("window", { location: { origin: "https://pulpo.club" } });
    try {
      for (const id of ["remax__001461165132", "oceanside__15463", "idealista.es_678901"]) {
        const url = shareUrlFor(id);
        const broker = id.split("__")[0].split("_")[0];
        expect(url.toLowerCase()).not.toContain(broker.toLowerCase());
      }
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
