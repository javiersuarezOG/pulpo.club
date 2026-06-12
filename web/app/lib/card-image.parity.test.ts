// Parity test (plan 015): pin web/app/lib/card-image.ts::
// isCardImageDisplayable to the SAME canonical truth table the Python
// predicate (pulpo/display_gates.py::is_card_displayable) is pinned to
// in tests/test_display_gate_parity.py.
//
// Both predicates encode `card_eligible === true && has_text_overlay
// !== true`, but were tested independently — nothing asserted they
// AGREE. They WILL drift (someone tightens one, forgets the other) and
// a bad image leaks on whichever side lagged. This locks both to one
// shared truth (same defense as the dual-sitemap + email_type_contract
// precedents). JSON null is passed through as TS null.
//
// If this fails on a row, the TS predicate has drifted from the agreed
// contract — fix the predicate (or, if the contract genuinely changed,
// update BOTH predicates AND the truth table in one PR).

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { isCardImageDisplayable } from "./card-image";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE = resolve(
  __dirname,
  "../../../tests/fixtures/display_gate_truth_table.json",
);

type Row = {
  card_eligible: boolean | null;
  has_text_overlay: boolean | null;
  expected: boolean;
};

const rows: Row[] = JSON.parse(readFileSync(FIXTURE, "utf8")).rows;

describe("isCardImageDisplayable parity with Python is_card_displayable", () => {
  for (const row of rows) {
    it(`card_eligible=${row.card_eligible} has_text_overlay=${row.has_text_overlay} -> ${row.expected}`, () => {
      expect(
        isCardImageDisplayable({
          card_eligible: row.card_eligible,
          has_text_overlay: row.has_text_overlay,
        }),
      ).toBe(row.expected);
    });
  }

  it("covers the full 9-row cross-product", () => {
    const combos = new Set(
      rows.map((r) => `${r.card_eligible}|${r.has_text_overlay}`),
    );
    expect(combos.size).toBe(9);
  });

  // TS-only edge: both keys absent (the {} / missing-key case the JSON
  // null rows can't express). Mirrors the Python missing-key behavior.
  it("blocks when both keys are absent ({})", () => {
    expect(isCardImageDisplayable({})).toBe(false);
  });
});
