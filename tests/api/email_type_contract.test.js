// Producer/consumer contract for the `email_type` Resend tag.
//
// Why this exists: the post-2026-05-28 audit (docs/email-audit.md) traced
// a months-long silent observability bug to the producer (api/_activation_email.js)
// stamping `email_type=activation` on outbound mail while the consumer
// (api/resend-webhook.js#pickPostHogProps) ignored it. Adding a new
// `email_type` literal at a sender site without updating the allowlist
// reverts the system to the same broken state — the new value buckets to
// "unknown" downstream and dashboards stop discriminating cleanly.
//
// What this test does: grep every outbound-sender file for the literal
// string values stamped on the `email_type` tag and the `X-Pulpo-Email-Type`
// header, then assert every literal is in KNOWN_EMAIL_TYPES exported by
// api/resend-webhook.js. CI failure here is a 30-second fix: either add
// the new literal to KNOWN_EMAIL_TYPES, or remove the unused literal.
//
// This test deliberately does NOT enforce the reverse direction (every
// KNOWN_EMAIL_TYPES member must have a producer). "contact" and
// "admin_test" were added forward-looking; the day a producer ships,
// we want this test to PASS, not start failing because the producer
// landed before the inline-Python contract test got an update.

import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { KNOWN_EMAIL_TYPES } from "../../api/resend-webhook.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

// Files known to stamp the `email_type` tag or `X-Pulpo-Email-Type` header
// on outbound Resend payloads. Adding a new outbound sender? Append it
// here AND add the literal to KNOWN_EMAIL_TYPES — the contract test then
// covers it. Listing files explicitly (vs. globbing api/ + automation/)
// keeps the test fast and the surface obvious.
const PRODUCER_FILES = [
  "api/_activation_email.js",
  "api/contact.js",
  "scripts/send_newsletter.py",
  "automation/newsletter/welcome_dispatch.py",
  "automation/newsletter/free_welcome_dispatch.py",
];

// Patterns covering both the JS object-tag form
// (`{ name: "email_type", value: "<X>" }`) and the JS/Python header form
// (`"x-pulpo-email-type": "<X>"`, `"X-Pulpo-Email-Type": "<X>"`) and the
// Python tags-dict form (`"email_type": "<X>"`).
const PATTERNS = [
  // JS: { name: "email_type", value: "<X>" }
  /\bname:\s*["']email_type["']\s*,\s*value:\s*["']([^"']+)["']/gi,
  // JS/Python: "x-pulpo-email-type": "<X>"  (case-insensitive header key)
  /["']x-pulpo-email-type["']\s*:\s*["']([^"']+)["']/gi,
  // Python: "email_type": "<X>"
  /["']email_type["']\s*:\s*["']([^"']+)["']/gi,
];

function collectStampedValues() {
  const found = new Map(); // value → [files…]
  for (const rel of PRODUCER_FILES) {
    const abs = path.join(REPO_ROOT, rel);
    if (!fs.existsSync(abs)) {
      // Don't silently skip — the producer list is supposed to track reality.
      // A missing file here means a refactor moved the sender; the test author
      // needs to update PRODUCER_FILES.
      throw new Error(
        `[email_type_contract] PRODUCER_FILES entry not found: ${rel}. ` +
        `Update the list to match the current outbound-sender topology.`,
      );
    }
    const source = fs.readFileSync(abs, "utf8");
    for (const re of PATTERNS) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(source)) !== null) {
        const value = m[1];
        if (!found.has(value)) found.set(value, []);
        found.get(value).push(rel);
      }
    }
  }
  return found;
}

describe("email_type producer/consumer contract", () => {
  it("finds at least one email_type literal across producer files", () => {
    // Defense against a future refactor that breaks the regex set or
    // moves producers out from under PRODUCER_FILES — without this check
    // an empty grep would silently pass.
    const found = collectStampedValues();
    expect(
      found.size,
      "Greps returned zero email_type literals — has the producer surface " +
      "moved? Update PRODUCER_FILES or the PATTERNS list above.",
    ).toBeGreaterThan(0);
  });

  it("every stamped email_type value is in KNOWN_EMAIL_TYPES", () => {
    const found = collectStampedValues();
    const orphans = [];
    for (const [value, files] of found) {
      if (!KNOWN_EMAIL_TYPES.has(value)) {
        orphans.push({ value, files: [...new Set(files)] });
      }
    }
    expect(
      orphans,
      "Producer stamped an email_type literal not in KNOWN_EMAIL_TYPES. " +
      "Fix: add the literal to KNOWN_EMAIL_TYPES in api/resend-webhook.js — " +
      "otherwise lifecycle events from this sender bucket as " +
      "email_type='unknown' downstream and dashboards lose the discriminator.",
    ).toEqual([]);
  });

  it("KNOWN_EMAIL_TYPES exports as a Set with the four current members", () => {
    // Lock the current allowlist so accidental edits (e.g. converting to
    // an array, dropping a member during a refactor) trip a clear test
    // failure rather than a subtle dashboard regression.
    expect(KNOWN_EMAIL_TYPES).toBeInstanceOf(Set);
    expect([...KNOWN_EMAIL_TYPES].sort()).toEqual(
      ["activation", "admin_test", "contact", "newsletter"],
    );
  });
});
