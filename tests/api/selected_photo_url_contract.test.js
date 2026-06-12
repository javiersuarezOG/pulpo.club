// Primary-image continuity contract: every surface that renders a listing's
// primary image MUST lead with the hero picker's `selected_photo_url`.
//
// Why this exists: plan 002 (continuity contract from PR #785) made four
// surfaces lead with `selected_photo_url` so the image a user clicks is the
// image the listing page shows first. A fifth future producer (a new share
// surface, a new email block) could render `photo_urls[0]` instead and
// silently re-break continuity — invisible to CI. This is a grep-based
// contract test mirroring tests/api/email_type_contract.test.js: it pins the
// known producers and fails if one drops the field.
//
// Adding a NEW primary-image surface = add it to PRODUCER_FILES in the SAME
// PR. The test failing on a producer-only edit that forgot the field is the
// guardrail working.
//
// This is a coarse grep guard (presence of the literal), not a semantic proof
// the field is preferred FIRST — that's covered by plan 002's behavioral unit
// tests. The two together: behavioral tests prove correctness, this proves no
// surface silently drops the field.

import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

// Files known to render a listing's primary image. Each must lead with
// `selected_photo_url` (the hero picker's choice), not `photo_urls[0]`.
// Adding a new primary-image surface? Append it here in the same PR.
const PRODUCER_FILES = [
  "api/social/card.js",
  "automation/newsletter/build_issue.py",
  "automation/ig_photo_gate.py",
  "web/app/data/listings.ts",
];

const LITERAL = "selected_photo_url";

describe("selected_photo_url primary-image continuity contract", () => {
  for (const rel of PRODUCER_FILES) {
    it(`${rel} references ${LITERAL}`, () => {
      const abs = path.join(REPO_ROOT, rel);
      expect(
        fs.existsSync(abs),
        `[selected_photo_url_contract] PRODUCER_FILES entry not found: ${rel}. ` +
          `A refactor moved this surface — update PRODUCER_FILES to match reality.`,
      ).toBe(true);
      const source = fs.readFileSync(abs, "utf8");
      expect(
        source.includes(LITERAL),
        `${rel} does not reference ${LITERAL}. This surface renders a ` +
          `listing's primary image and MUST lead with selected_photo_url ` +
          `(continuity contract, PR #785 / plan 002). Add the field or, if ` +
          `this file legitimately no longer renders a primary image, remove ` +
          `it from PRODUCER_FILES with a note.`,
      ).toBe(true);
    });
  }
});
