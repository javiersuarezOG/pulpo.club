// Verifies the client-side emailDistinctId() helper produces the exact
// same Person ID as the server-side api/_posthog.js#emailDistinctId. The
// two paths MUST agree, otherwise:
//   - identify() on the client creates Person A
//   - alias() on the Stripe webhook creates Person B
//   - Person A and Person B never reconcile in PostHog
//   - retention cohorts split the same human into two records
// This test pins the contract by re-computing the server algorithm
// in Node's crypto module and comparing.

import { describe, it, expect } from "vitest";
import { createHash } from "node:crypto";

import { emailDistinctId } from "./client";

// Verbatim copy of api/_posthog.js#emailDistinctId — keep these two in
// lockstep. If you change either side, change both AND update this
// duplicate.
function serverEmailDistinctId(email: string | null | undefined): string | null {
  if (!email || typeof email !== "string") return null;
  const normalized = email.trim().toLowerCase();
  if (!normalized) return null;
  const hash = createHash("sha256").update(normalized).digest("hex").slice(0, 16);
  return `email:${hash}`;
}

describe("emailDistinctId — client mirror of server algorithm", () => {
  it("produces the same distinct_id for a canonical email", async () => {
    const email = "javier@suarez.ventures";
    const client = await emailDistinctId(email);
    const server = serverEmailDistinctId(email);
    expect(client).toBe(server);
    expect(client).toMatch(/^email:[0-9a-f]{16}$/);
  });

  it("normalizes case + whitespace identically on both sides", async () => {
    // The server lowercases + trims; the client must too.
    const variants = ["Foo@Bar.com", "  foo@bar.com  ", "foo@bar.com", "FOO@BAR.COM"];
    const ids = await Promise.all(variants.map((e) => emailDistinctId(e)));
    // All variants must hash to the same id.
    expect(new Set(ids).size).toBe(1);
    expect(ids[0]).toBe(serverEmailDistinctId("foo@bar.com"));
  });

  it("returns null for empty/missing inputs (no PII fallback)", async () => {
    expect(await emailDistinctId(null)).toBeNull();
    expect(await emailDistinctId(undefined)).toBeNull();
    expect(await emailDistinctId("")).toBeNull();
    expect(await emailDistinctId("   ")).toBeNull();
  });

  it("agrees with the server for a representative sample of emails", async () => {
    const samples = [
      "sebastian.honores@gmail.com",
      "user+tag@gmail.com",                       // Gmail plus-addressing
      "ñoño@español.es",                          // non-ASCII
      "very.long.email.address@subdomain.example.com",
      "a@b.co",                                   // minimal
    ];
    for (const email of samples) {
      const client = await emailDistinctId(email);
      const server = serverEmailDistinctId(email);
      expect(client).toBe(server);
    }
  });
});
