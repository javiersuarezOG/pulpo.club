// JS side of the recipient-hash cross-runtime parity guard.
//
// /api/unsubscribe.js hashEmail() MUST produce the same digest as Python's
// store.email_hash() — it re-derives the `r=` hash to find the Resend
// contact. Drift on salt / normalization / algorithm / truncation silently
// no-ops every unsubscribe link (has shipped before: unsalted / 16-char).
//
// This test and its Python twin (tests/newsletter/test_hash_parity.py) both
// assert the same golden vectors in tests/fixtures/hash_parity_vectors.json.
// A one-sided change fails that side against the shared `expected`.

import { describe, it, expect, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { hashEmail } from "../../api/unsubscribe.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(path.join(here, "..", "fixtures", "hash_parity_vectors.json"), "utf-8"),
);

describe("hashEmail — cross-runtime parity with Python store.email_hash", () => {
  const ORIG = process.env.PULPO_NEWSLETTER_SALT;
  afterEach(() => {
    if (ORIG === undefined) delete process.env.PULPO_NEWSLETTER_SALT;
    else process.env.PULPO_NEWSLETTER_SALT = ORIG;
  });

  for (const v of fixture.vectors) {
    it(`matches shared golden for ${v.email} (salt ${v.salt})`, () => {
      process.env.PULPO_NEWSLETTER_SALT = v.salt;
      const got = hashEmail(v.email);
      expect(got).toBe(v.expected);
      expect(got).toHaveLength(24);
    });
  }
});
