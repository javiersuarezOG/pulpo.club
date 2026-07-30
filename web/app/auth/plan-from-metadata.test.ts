import { describe, expect, it } from "vitest";
import { planFromMetadata } from "./plan-from-metadata";

describe("planFromMetadata", () => {
  it("preserves both paid tiers (pro AND agency)", () => {
    // The regression this guards: agency was collapsed to "free" here,
    // reinstating the €4.99 upsell for agency users on the Clerk path.
    expect(planFromMetadata({ plan: "pro" })).toBe("pro");
    expect(planFromMetadata({ plan: "agency" })).toBe("agency");
  });

  it("defaults free/unknown/missing to 'free'", () => {
    expect(planFromMetadata({ plan: "free" })).toBe("free");
    expect(planFromMetadata({ plan: "enterprise" })).toBe("free"); // unknown tier
    expect(planFromMetadata({})).toBe("free");
    expect(planFromMetadata(null)).toBe("free");
    expect(planFromMetadata(undefined)).toBe("free");
    // Non-string junk never masquerades as a paid tier.
    expect(planFromMetadata({ plan: 1 as unknown as string })).toBe("free");
    expect(planFromMetadata({ plan: true as unknown as string })).toBe("free");
  });
});
