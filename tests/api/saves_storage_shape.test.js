// Shape regression for api/saves.js — guards the new enrichment +
// backward-compat contract added when the favorites-backend ships:
//
//   • Saves storage is now a MIXED array (legacy bare-ID strings +
//     new {id, saved_at, price_at_save_usd?} objects).
//   • GET response still emits a flat string-ID array (`_extractIds`).
//   • POST add looks up ranked.json server-side to capture
//     price_at_save_usd + saved_at at write time.
//   • POST remove drops the entry whether it's a legacy string or an
//     enriched object (`_removeById`).
//
// True behavioral coverage lives in tests/e2e/save-listing-smoke.spec.ts
// (mutates real Clerk + reads back). This shape test is the cheap
// regression net for refactors that silently break the contract.

import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const HANDLER = path.resolve(__dirname, "../../api/saves.js");
const src = fs.readFileSync(HANDLER, "utf8");

describe("api/saves enrichment + backward-compat", () => {
  it("normalizes mixed save entries via _normalizeSave", () => {
    // Both legacy strings AND new objects are accepted; junk returns null.
    expect(src).toMatch(/_normalizeSave/);
    expect(src).toMatch(/typeof entry === "string"/);
  });

  it("extracts bare IDs for the external API contract", () => {
    expect(src).toMatch(/_extractIds/);
    // GET response must serialize the ID-only array, not the raw mixed shape
    expect(src).toMatch(/_extractIds\(saves\)/);
  });

  it("enriches new saves with saved_at + ranked.json lookup", () => {
    expect(src).toMatch(/_enrichForSave/);
    expect(src).toMatch(/saved_at:\s*new Date\(\)\.toISOString\(\)/);
    expect(src).toMatch(/price_at_save_usd/);
    expect(src).toMatch(/rankedIndex\(\)/);
  });

  it("loads ranked.json from disk and caches across cold-start requests", () => {
    expect(src).toMatch(/let _rankedIndex = null/);
    expect(src).toMatch(/fs\.readFileSync/);
    expect(src).toMatch(/"web",\s*"data",\s*"ranked\.json"/);
  });

  it("falls back cleanly when ranked.json is unreadable", () => {
    // The save endpoint must NEVER fail because of an enrichment lookup
    // — a malformed ranked.json or filesystem hiccup should land a
    // bare {id, saved_at} entry, not a 500.
    expect(src).toMatch(/ranked_index_load_failed/);
    expect(src).toMatch(/_rankedIndex = new Map\(\)/);
  });

  it("dedupes by ID — legacy duplicates don't burn the cap slot", () => {
    // Cap check counts via _extractIds, not raw array length, so a
    // historical duplicate ID doesn't waste one of the user's slots.
    expect(src).toMatch(/_extractIds\(next\)\.length/);
  });

  it("removes by ID regardless of stored shape", () => {
    expect(src).toMatch(/_removeById/);
  });
});
