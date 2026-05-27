import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import handler from "../../api/stripe/create-checkout-session.js";

const REPO_ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "../..");
const source = fs.readFileSync(path.join(REPO_ROOT, "api/stripe/create-checkout-session.js"), "utf8");

describe("signed-in checkout locale contract", () => {
  it("normalizes Pulpo UI locales into Stripe Checkout locales", () => {
    expect(handler.normalizeCheckoutLocale("es")).toBe("es-419");
    expect(handler.normalizeCheckoutLocale("en")).toBe("en");
    expect(handler.normalizeCheckoutLocale(undefined)).toBe(null);
    expect(handler.normalizeCheckoutLocale("garbage")).toBe(null);
  });

  it("passes locale to checkout.sessions.create when supported", () => {
    expect(source).toContain("if (locale) sessionParams.locale = locale;");
  });

  it("stamps locale into Session and Subscription metadata", () => {
    expect(source).toMatch(/metadata:\s*\{\s*clerkUserId:\s*userId,\s*locale:\s*locale \|\| ""/);
    expect(source).toMatch(/metadata:\s*\{\s*locale:\s*locale \|\| ""/);
  });

  it("emits checkout session locale telemetry", () => {
    expect(source).toContain('"stripe.checkout_session_created"');
    expect(source).toContain("locale: locale || \"auto\"");
  });
});
