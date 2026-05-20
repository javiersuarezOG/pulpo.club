// Unit tests for api/_plan.js — the backend founder-email override.
//
// The FOUNDER_EMAILS set is captured at module load, so each test
// resets the module registry and re-imports with a fresh env. Mirrors
// the pattern in web/app/lib/founder-emails.test.ts (frontend twin).

import { describe, it, expect, beforeEach, afterEach } from "vitest";

const ORIGINAL_FOUNDER = process.env.FOUNDER_EMAILS;
const ORIGINAL_VITE = process.env.VITE_FOUNDER_EMAILS;

async function loadHelperWith({ founder, vite } = {}) {
  delete process.env.FOUNDER_EMAILS;
  delete process.env.VITE_FOUNDER_EMAILS;
  if (founder !== undefined) process.env.FOUNDER_EMAILS = founder;
  if (vite !== undefined) process.env.VITE_FOUNDER_EMAILS = vite;
  // Bust the require cache — Node caches CommonJS modules by absolute
  // path, and our helper captures FOUNDER_EMAILS at top-level.
  const path = require.resolve("../../api/_plan.js");
  delete require.cache[path];
  return require("../../api/_plan.js");
}

function clerkUser({ email = null, plan = null } = {}) {
  return {
    primaryEmailAddress: email ? { emailAddress: email } : null,
    publicMetadata: plan ? { plan } : {},
  };
}

beforeEach(() => {
  delete process.env.FOUNDER_EMAILS;
  delete process.env.VITE_FOUNDER_EMAILS;
});

afterEach(() => {
  if (ORIGINAL_FOUNDER !== undefined) process.env.FOUNDER_EMAILS = ORIGINAL_FOUNDER;
  if (ORIGINAL_VITE !== undefined) process.env.VITE_FOUNDER_EMAILS = ORIGINAL_VITE;
});

describe("isFounderEmail", () => {
  it("returns false when env is empty", async () => {
    const { isFounderEmail } = await loadHelperWith({});
    expect(isFounderEmail("a@b.com")).toBe(false);
  });

  it("matches FOUNDER_EMAILS exactly", async () => {
    const { isFounderEmail } = await loadHelperWith({ founder: "a@b.com,c@d.com" });
    expect(isFounderEmail("a@b.com")).toBe(true);
    expect(isFounderEmail("c@d.com")).toBe(true);
    expect(isFounderEmail("z@z.com")).toBe(false);
  });

  it("falls back to VITE_FOUNDER_EMAILS when FOUNDER_EMAILS is unset", async () => {
    const { isFounderEmail } = await loadHelperWith({ vite: "a@b.com" });
    expect(isFounderEmail("a@b.com")).toBe(true);
  });

  it("prefers FOUNDER_EMAILS when both are set", async () => {
    const { isFounderEmail } = await loadHelperWith({
      founder: "a@b.com",
      vite: "different@vite.com",
    });
    expect(isFounderEmail("a@b.com")).toBe(true);
    expect(isFounderEmail("different@vite.com")).toBe(false);
  });

  it("is case-insensitive and trims whitespace", async () => {
    const { isFounderEmail } = await loadHelperWith({ founder: " A@B.com , c@d.com " });
    expect(isFounderEmail("a@b.com")).toBe(true);
    expect(isFounderEmail("C@D.COM")).toBe(true);
  });

  it("returns false for null/empty email", async () => {
    const { isFounderEmail } = await loadHelperWith({ founder: "a@b.com" });
    expect(isFounderEmail(null)).toBe(false);
    expect(isFounderEmail("")).toBe(false);
  });
});

describe("effectivePlan", () => {
  it("returns 'free' for a null user", async () => {
    const { effectivePlan } = await loadHelperWith({});
    expect(effectivePlan(null)).toBe("free");
  });

  it("returns 'pro' when publicMetadata.plan === 'pro'", async () => {
    const { effectivePlan } = await loadHelperWith({});
    expect(effectivePlan(clerkUser({ plan: "pro" }))).toBe("pro");
  });

  it("returns 'agency' when publicMetadata.plan === 'agency'", async () => {
    const { effectivePlan } = await loadHelperWith({});
    expect(effectivePlan(clerkUser({ plan: "agency" }))).toBe("agency");
  });

  it("returns 'pro' for a founder email even when metadata is empty", async () => {
    const { effectivePlan } = await loadHelperWith({ founder: "a@b.com" });
    expect(effectivePlan(clerkUser({ email: "a@b.com" }))).toBe("pro");
  });

  it("never demotes a real pro for a non-founder email", async () => {
    const { effectivePlan } = await loadHelperWith({ founder: "x@y.com" });
    expect(effectivePlan(clerkUser({ email: "a@b.com", plan: "pro" }))).toBe("pro");
  });

  it("returns 'free' when neither metadata nor founder match", async () => {
    const { effectivePlan } = await loadHelperWith({ founder: "x@y.com" });
    expect(effectivePlan(clerkUser({ email: "a@b.com" }))).toBe("free");
  });

  it("matches founder email case-insensitively", async () => {
    const { effectivePlan } = await loadHelperWith({ founder: "JAVIER@suarez.ventures" });
    expect(effectivePlan(clerkUser({ email: "javier@suarez.ventures" }))).toBe("pro");
  });
});
