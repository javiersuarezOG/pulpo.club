// Audit: `web/app/home/versions.json` ↔ `blockRegistry.BLOCK_ORDER` sync.
//
// `versions.json` is the single source of truth read by both the
// `GET /api/home/version` endpoint and any future consumers (analytics,
// CI drift detection, etc.). If a block is added to or removed from
// the homepage but the JSON isn't updated, the endpoint silently
// serves wrong data — and downstream queries break weeks later when
// nobody remembers why.
//
// This spec asserts the two are always in sync. It fails loud in CI
// whenever someone:
//   * Adds a new block to `BLOCK_ORDER` without adding a `blocks.<id>`
//     entry to versions.json.
//   * Removes a block from `BLOCK_ORDER` without removing the stale
//     entry from versions.json.
//
// To fix a failure: edit `web/app/home/versions.json` so its
// `blocks` keys exactly match the `BLOCK_ORDER` array.

import { describe, expect, it } from "vitest";
import { BLOCK_ORDER } from "./blockRegistry";
import versions from "./versions.json";

describe("versions.json ↔ blockRegistry.BLOCK_ORDER sync", () => {
  const versionedBlockIds = new Set(Object.keys(versions.blocks));
  const registryBlockIds = new Set(BLOCK_ORDER);

  it("every block in BLOCK_ORDER has a version entry", () => {
    for (const id of BLOCK_ORDER) {
      expect(
        versionedBlockIds.has(id),
        `Missing version entry for block "${id}" in web/app/home/versions.json. ` +
          `Add a "${id}" key under "blocks" with the component's current version string.`,
      ).toBe(true);
    }
  });

  it("every version entry corresponds to a block in BLOCK_ORDER", () => {
    for (const id of Object.keys(versions.blocks)) {
      expect(
        registryBlockIds.has(id as never),
        `Stale version entry "${id}" in web/app/home/versions.json — ` +
          `block was removed from BLOCK_ORDER. Delete the "${id}" key under "blocks".`,
      ).toBe(true);
    }
  });

  it("versions.layout is a non-empty string", () => {
    expect(typeof versions.layout).toBe("string");
    expect(versions.layout.length).toBeGreaterThan(0);
  });

  it("every version value is a non-empty string", () => {
    for (const [id, v] of Object.entries(versions.blocks)) {
      expect(typeof v, `versions.blocks.${id} should be a string`).toBe("string");
      expect((v as string).length, `versions.blocks.${id} should be non-empty`).toBeGreaterThan(0);
    }
  });
});
