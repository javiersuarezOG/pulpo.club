import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import handler from "../../api/stripe/billing-portal.js";

const REPO_ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "../..");
const source = fs.readFileSync(path.join(REPO_ROOT, "api/stripe/billing-portal.js"), "utf8");

describe("billing portal locale contract", () => {
  it("normalizes locale for Stripe Customer Portal", () => {
    expect(handler.normalizePortalLocale("es")).toBe("es");
    expect(handler.normalizePortalLocale("en")).toBe("en");
    expect(handler.normalizePortalLocale(undefined)).toBe("auto");
    expect(handler.normalizePortalLocale("garbage")).toBe("auto");
  });

  it("passes locale to billingPortal.sessions.create", () => {
    expect(source).toMatch(/billingPortal\.sessions\.create\(\{[\s\S]*locale,\s*[\s\S]*\}\)/);
  });

  it("stamps preferred_locales on the Stripe Customer for explicit locales", () => {
    expect(source).toContain("preferred_locales: [locale]");
    expect(source).toContain('locale !== "auto"');
  });

  it("emits billing portal and customer locale telemetry", () => {
    expect(source).toContain('"stripe.billing_portal_session_created"');
    expect(source).toContain('"stripe.customer_locale_set"');
  });
});
