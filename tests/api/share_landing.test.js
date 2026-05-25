// Unit tests for api/l/[token].js — the crawler-aware HTML endpoint
// that injects per-listing og:title / og:description / og:image into
// the SPA shell at the <!--OG_TAGS--> sentinel.
//
// Focus areas:
//   1. Token decode is byte-for-byte compatible with web/app/lib/share.ts
//      (broken contract here = busted share links).
//   2. Caption hook prioritization matches SharePicker + card.js so all
//      three surfaces speak with one voice.
//   3. Attribute escaping is strict — any listing with a `"` or `<` in
//      the title can't break out of the meta tag's `content="…"`.
//   4. Source-opacity guarantee: NO field in the og block contains the
//      broker/source name as a substring, even when derived from a
//      listing whose title happens to include the source label.

import { describe, it, expect } from "vitest";

import landingHandler from "../../api/l/[token].js";
const { decodeShareToken, captionHook, buildOgFields, escapeAttr } = landingHandler._internal;

describe("decodeShareToken (Node side)", () => {
  it("decodes a valid base64url token to the original id", () => {
    // btoa("remax__001461165132") with URL-safe alphabet, no padding.
    // Computed once here so we lock the encoding format in tests, not
    // just the round-trip.
    const token = Buffer.from("remax__001461165132", "utf-8")
      .toString("base64")
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(decodeShareToken(token)).toBe("remax__001461165132");
  });

  it("rejects tokens containing base64 padding or non-url-safe chars", () => {
    expect(decodeShareToken("foo+bar")).toBeNull();
    expect(decodeShareToken("foo/bar")).toBeNull();
    expect(decodeShareToken("foo=")).toBeNull();
    expect(decodeShareToken("")).toBeNull();
  });

  it("rejects a token whose decoded payload would smuggle a path traversal", () => {
    const malicious = Buffer.from("../../etc/passwd", "utf-8")
      .toString("base64")
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(decodeShareToken(malicious)).toBeNull();
  });
});

describe("captionHook", () => {
  const baseListing = { dist_beach_km: null, is_walk_to_beach: false, is_on_lake: false };

  it("walk-to-beach + sub-1km → '{minutes} min walk to beach'", () => {
    const l = { ...baseListing, is_walk_to_beach: true, dist_beach_km: 0.4 };
    expect(captionHook(l, "en")).toMatch(/^\d+ min walk to beach$/);
  });

  it("walks round to 5-min steps so we never say '7 min'", () => {
    const l = { ...baseListing, is_walk_to_beach: true, dist_beach_km: 0.55 };
    // 0.55 km * 12 = 6.6 → rounded to nearest 5 = 5 (Math.round(6.6/5)*5 = 5)
    expect(captionHook(l, "en")).toBe("5 min walk to beach");
  });

  it("short drive (km < 5) → '{k} km from the beach'", () => {
    const l = { ...baseListing, dist_beach_km: 3.2 };
    expect(captionHook(l, "en")).toBe("3 km from the beach");
  });

  it("lake listing falls back to 'On the lake' when no beach is near", () => {
    const l = { ...baseListing, is_on_lake: true };
    expect(captionHook(l, "en")).toBe("On the lake");
  });

  it("generic hook for landlocked / inland listings", () => {
    expect(captionHook(baseListing, "en")).toBe("On Pulpo");
  });

  it("Spanish locale renders the hook in Spanish", () => {
    const l = { ...baseListing, is_walk_to_beach: true, dist_beach_km: 0.4 };
    expect(captionHook(l, "es")).toMatch(/^\d+ min a pie a la playa$/);
  });
});

describe("buildOgFields — source-opacity contract", () => {
  // Real-shape listing modeled on web/data/ranked.json. Includes the
  // broker name in `source` / `source_label` to prove neither leaks
  // into any field we render.
  const listing = {
    source: "remax",
    source_id: "001461165132",
    source_label: "Remax El Salvador",
    title: "Lot near El Tunco",
    price_usd: 60000,
    area_m2: 1263.59,
    dist_beach_km: 0.4,
    is_walk_to_beach: true,
    municipality: "Tamanique",
    department: "La Libertad",
  };

  const SAMPLE_TOKEN = "cmVtYXhfXzAwMTQ2MTE2NTEzMg";

  it("never echoes the source name in og:title, og:description, og:image, or og:url", () => {
    const og = buildOgFields({
      listing,
      token: SAMPLE_TOKEN,
      lang: "en",
      baseUrl: "https://pulpo.club",
    });
    // Permutations a crawler might index: brand label, source key,
    // source label (with broker company name).
    const forbidden = ["remax", "Remax", "REMAX", "Remax El Salvador"];
    for (const field of [og.ogTitle, og.ogDescription, og.ogImage, og.ogUrl]) {
      for (const banned of forbidden) {
        expect(field.toLowerCase()).not.toContain(banned.toLowerCase());
      }
    }
  });

  it("og:title combines title + formatted price with em-dash separator", () => {
    const og = buildOgFields({ listing, token: SAMPLE_TOKEN, lang: "en", baseUrl: "https://pulpo.club" });
    expect(og.ogTitle).toBe("Lot near El Tunco — $60,000");
  });

  it("og:description joins area, hook, and location with ' · '", () => {
    const og = buildOgFields({ listing, token: SAMPLE_TOKEN, lang: "en", baseUrl: "https://pulpo.club" });
    expect(og.ogDescription).toBe("1,264 m² · 5 min walk to beach · La Libertad");
  });

  it("og:image points at /api/social/card with the token query param", () => {
    const og = buildOgFields({ listing, token: SAMPLE_TOKEN, lang: "en", baseUrl: "https://pulpo.club" });
    expect(og.ogImage).toBe(`https://pulpo.club/api/social/card?token=${SAMPLE_TOKEN}`);
  });

  it("og:image carries &lang=es when the request locale is Spanish", () => {
    const og = buildOgFields({ listing, token: SAMPLE_TOKEN, lang: "es", baseUrl: "https://pulpo.club" });
    expect(og.ogImage).toBe(`https://pulpo.club/api/social/card?token=${SAMPLE_TOKEN}&lang=es`);
  });

  it("listings without price or area still produce a clean og:description", () => {
    const skinny = { ...listing, price_usd: null, area_m2: null };
    const og = buildOgFields({ listing: skinny, token: SAMPLE_TOKEN, lang: "en", baseUrl: "https://pulpo.club" });
    // No dangling " ·  · " separator when parts are missing.
    expect(og.ogDescription).not.toMatch(/·\s+·/);
    expect(og.ogTitle).toBe("Lot near El Tunco");
  });
});

describe("escapeAttr", () => {
  it("escapes the four meta-content-attribute critical chars", () => {
    expect(escapeAttr(`Lot <near> "El Tunco" & more`))
      .toBe("Lot &lt;near&gt; &quot;El Tunco&quot; &amp; more");
  });

  it("escape order doesn't double-encode the ampersand", () => {
    // & must escape FIRST or we end up with &amp;quot; instead of &quot;.
    expect(escapeAttr(`&quot;`)).toBe("&amp;quot;");
  });
});
