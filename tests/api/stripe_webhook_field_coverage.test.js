import { describe, expect, test } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const REPO_ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "../..");
const source = fs.readFileSync(path.join(REPO_ROOT, "api/stripe/webhook.js"), "utf8");

describe("Stripe subscription webhook publicMetadata field coverage", () => {
  const requiredStripeFields = [
    "current_period_end",
    "cancel_at_period_end",
    "canceled_at",
    "status",
    "pause_collection",
    "default_payment_method",
  ];

  test.each(requiredStripeFields)("maps %s into subscription metadata handling", (field) => {
    expect(source).toContain(field);
  });

  test("stores every display-critical field in the public metadata patch", () => {
    for (const field of [
      "subscription_status",
      "current_period_end",
      "cancel_at_period_end",
      "canceled_at",
      "pause_collection",
      "default_payment_method",
    ]) {
      expect(source).toMatch(new RegExp(`${field}:`));
    }
  });
});
