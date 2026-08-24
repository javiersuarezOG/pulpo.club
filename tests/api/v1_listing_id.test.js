// shared/listing-id.ts — the canonical (source, source_id) join.
//
// These ids are in live URLs (Instagram/Facebook UTM links, newsletter
// deep links, every /listing/<id> the site has emitted), so the format
// is a compatibility surface, not an implementation detail.

import { describe, expect, it } from "vitest";
import {
  ID_SEPARATOR,
  buildListingId,
  isListingId,
  parseListingId,
} from "../../shared/listing-id.ts";

describe("buildListingId", () => {
  it("joins with the separator that is baked into live URLs", () => {
    expect(ID_SEPARATOR).toBe("__");
    expect(buildListingId("remax", "001461165132")).toBe("remax__001461165132");
  });

  it("accepts the punctuation real source_ids contain", () => {
    // csbr uses full slugs as source_ids, hyphens and all.
    expect(buildListingId("csbr", "terreno-en-venta-juayua.2")).toBe(
      "csbr__terreno-en-venta-juayua.2",
    );
  });

  it("trims incidental whitespace", () => {
    expect(buildListingId("  remax ", " 123 ")).toBe("remax__123");
  });

  it("returns null rather than minting a malformed id", () => {
    for (const [source, sourceId] of [
      ["", "123"],
      ["remax", ""],
      [null, "123"],
      ["remax", null],
      [undefined, undefined],
      [42, "123"],
      ["   ", "123"],
    ]) {
      expect(buildListingId(source, sourceId)).toBeNull();
    }
  });

  it("accepts the percent-encoded slugs csbr actually publishes", () => {
    // 14 live listings carry percent-encoded emoji in their source_id.
    // Rejecting them would make /listings return rows whose detail
    // lookup 400s. Safe here because the id is only ever compared for
    // equality, never used as a path.
    expect(
      buildListingId("csbr", "terreno-en-juayua-%f0%9f%8c%bf"),
    ).toBe("csbr__terreno-en-juayua-%f0%9f%8c%bf");
    expect(parseListingId("csbr__terreno-%f0%9f%8c%bf")).toEqual({
      source: "csbr",
      sourceId: "terreno-%f0%9f%8c%bf",
    });
  });

  it("rejects path-traversal and separator-injection characters", () => {
    expect(buildListingId("../../etc", "passwd")).toBeNull();
    expect(buildListingId("remax", "a/b")).toBeNull();
    expect(buildListingId("remax", "a b")).toBeNull();
  });
});

describe("parseListingId", () => {
  it("round-trips a built id", () => {
    const id = buildListingId("remax", "001461165132");
    expect(parseListingId(id)).toEqual({ source: "remax", sourceId: "001461165132" });
  });

  it("splits on the FIRST separator so a source_id may contain one", () => {
    // The source half must be recovered exactly; a broker-supplied
    // source_id containing "__" must not steal characters from it.
    expect(parseListingId("csbr__lote__frente__al__mar")).toEqual({
      source: "csbr",
      sourceId: "lote__frente__al__mar",
    });
  });

  it("rejects malformed, unsafe, and absurdly long input", () => {
    for (const bad of [
      "",
      "remax",             // no separator
      "__123",             // empty source
      "remax__",           // empty source_id
      "remax|123",         // the featured.json format is not canonical
      "remax-123",         // the sitemap format is not canonical
      "remax__../../etc/passwd",
      "remax__a/b",
      "remax__a b",
      null,
      undefined,
      123,
      `remax__${"x".repeat(300)}`,
    ]) {
      expect(parseListingId(bad)).toBeNull();
      expect(isListingId(bad)).toBe(false);
    }
  });
});
