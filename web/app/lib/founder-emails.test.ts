// Unit tests for the founder-email override. The FOUNDER_EMAILS set
// is built at module load from import.meta.env.VITE_FOUNDER_EMAILS, so
// each test stubs the env, resets the module cache, and dynamically
// imports the helper to get a fresh capture.

import { describe, it, expect, beforeEach, vi } from "vitest";

async function loadHelperWith(rawEnv: string | undefined) {
  vi.resetModules();
  if (rawEnv === undefined) {
    vi.stubEnv("VITE_FOUNDER_EMAILS", "");
  } else {
    vi.stubEnv("VITE_FOUNDER_EMAILS", rawEnv);
  }
  return import("./founder-emails");
}

beforeEach(() => {
  vi.unstubAllEnvs();
});

describe("isFounderEmail", () => {
  it("returns false when the env list is empty", async () => {
    const { isFounderEmail } = await loadHelperWith("");
    expect(isFounderEmail("javier@suarez.ventures")).toBe(false);
  });

  it("returns true for an email in the comma list", async () => {
    const { isFounderEmail } = await loadHelperWith("javier@suarez.ventures,sebas@example.com");
    expect(isFounderEmail("javier@suarez.ventures")).toBe(true);
    expect(isFounderEmail("sebas@example.com")).toBe(true);
  });

  it("matches case-insensitively", async () => {
    const { isFounderEmail } = await loadHelperWith("Javier@Suarez.Ventures");
    expect(isFounderEmail("javier@suarez.ventures")).toBe(true);
    expect(isFounderEmail("JAVIER@SUAREZ.VENTURES")).toBe(true);
  });

  it("trims whitespace around list entries", async () => {
    const { isFounderEmail } = await loadHelperWith(" a@b.com , c@d.com ");
    expect(isFounderEmail("a@b.com")).toBe(true);
    expect(isFounderEmail("c@d.com")).toBe(true);
  });

  it("returns false for null/undefined/empty email", async () => {
    const { isFounderEmail } = await loadHelperWith("a@b.com");
    expect(isFounderEmail(null)).toBe(false);
    expect(isFounderEmail(undefined)).toBe(false);
    expect(isFounderEmail("")).toBe(false);
  });

  it("returns false for an email not on the list", async () => {
    const { isFounderEmail } = await loadHelperWith("a@b.com");
    expect(isFounderEmail("c@d.com")).toBe(false);
  });
});

describe("applyFounderPlan", () => {
  it("returns null/undefined inputs unchanged", async () => {
    const { applyFounderPlan } = await loadHelperWith("a@b.com");
    expect(applyFounderPlan(null)).toBe(null);
    expect(applyFounderPlan(undefined)).toBe(undefined);
  });

  it("returns the user unchanged when no email", async () => {
    const { applyFounderPlan } = await loadHelperWith("a@b.com");
    const u = { plan: "free" };
    expect(applyFounderPlan(u)).toBe(u);
  });

  it("promotes free user with founder email to pro", async () => {
    const { applyFounderPlan } = await loadHelperWith("a@b.com");
    const u = { email: "a@b.com", plan: "free" };
    expect(applyFounderPlan(u)).toEqual({ email: "a@b.com", plan: "pro" });
  });

  it("promotes user with no plan field to pro", async () => {
    const { applyFounderPlan } = await loadHelperWith("a@b.com");
    const u = { email: "a@b.com" };
    expect(applyFounderPlan(u)).toEqual({ email: "a@b.com", plan: "pro" });
  });

  it("never demotes — agency stays agency", async () => {
    const { applyFounderPlan } = await loadHelperWith("a@b.com");
    const u = { email: "a@b.com", plan: "agency" };
    expect(applyFounderPlan(u)).toBe(u);
  });

  it("never demotes — existing pro stays pro", async () => {
    const { applyFounderPlan } = await loadHelperWith("a@b.com");
    const u = { email: "a@b.com", plan: "pro" };
    expect(applyFounderPlan(u)).toBe(u);
  });

  it("does not promote a non-founder user", async () => {
    const { applyFounderPlan } = await loadHelperWith("a@b.com");
    const u = { email: "z@z.com", plan: "free" };
    expect(applyFounderPlan(u)).toBe(u);
  });

  it("preserves all other fields when promoting", async () => {
    const { applyFounderPlan } = await loadHelperWith("a@b.com");
    const u = { email: "a@b.com", plan: "free", clerkId: "user_x", profile: { country: "es" } };
    expect(applyFounderPlan(u)).toEqual({
      email: "a@b.com",
      plan: "pro",
      clerkId: "user_x",
      profile: { country: "es" },
    });
  });
});
