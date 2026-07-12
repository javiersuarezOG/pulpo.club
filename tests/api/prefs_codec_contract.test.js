// Free-member filter codec — JS side of the JS↔Python parity contract.
// The SAME fixture (tests/fixtures/prefs_codec_cases.json) is asserted by the
// Python side in tests/newsletter/test_prefs_codec.py. If you change the wire
// format, both tests move together or the pipeline silently mis-reads what the
// endpoint wrote.
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { encode, decode } from "../../api/_prefs_codec.js";

const here = dirname(fileURLToPath(import.meta.url));
const cases = JSON.parse(readFileSync(join(here, "../fixtures/prefs_codec_cases.json"), "utf8"));

describe("prefs codec (JS) — shared parity fixture", () => {
  for (const c of cases.encode) {
    it(`encode ${JSON.stringify(c.pref)} → ${JSON.stringify(c.out)}`, () => {
      expect(encode(c.pref)).toBe(c.out);
    });
  }
  for (const c of cases.decode) {
    it(`decode ${JSON.stringify(c.in)} → ${JSON.stringify(c.out)}`, () => {
      expect(decode(c.in)).toEqual(c.out);
    });
  }

  it("encode∘decode is stable for a canonical value", () => {
    const s = "pulpo-filter:pt=land,house;mx=500000";
    expect(encode(decode(s))).toBe(s);
  });

  it("decode never throws on hostile input", () => {
    for (const bad of [null, undefined, 42, {}, "pulpo-filter:pt=<script>;mx=;;;=x"]) {
      expect(() => decode(bad)).not.toThrow();
    }
  });
});
