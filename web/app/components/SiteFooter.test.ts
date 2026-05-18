// Regression guard for SiteFooter mount predicate + variant selection.
//
// Post-Wave-5 contract:
//   * home → trimmed footer renders
//   * browse → trimmed footer renders
//   * saved / plans → full footer renders
//   * account → renders only when showFooterOnAccount opts in
//
// If this file goes red, either the predicate flipped accidentally
// (regressing landing-surface UX) or someone is about to ship a
// behavior change without updating the spec.

import { describe, expect, it } from "vitest";
import { shouldShowSiteFooter, siteFooterVariant } from "./SiteFooter.jsx";

describe("shouldShowSiteFooter", () => {
  it("renders the footer on home (post-Wave-5)", () => {
    expect(shouldShowSiteFooter("home")).toBe(true);
  });

  it("renders the footer on browse (post-Wave-5)", () => {
    expect(shouldShowSiteFooter("browse")).toBe(true);
  });

  it("renders the footer on saved / plans (unchanged)", () => {
    expect(shouldShowSiteFooter("saved")).toBe(true);
    expect(shouldShowSiteFooter("plans")).toBe(true);
  });

  it("hides the footer on account by default", () => {
    expect(shouldShowSiteFooter("account")).toBe(false);
  });

  it("renders the footer on account when the tweak is opted in", () => {
    expect(shouldShowSiteFooter("account", { showFooterOnAccount: true })).toBe(true);
  });
});

describe("siteFooterVariant", () => {
  it("returns trimmed for home and browse (marketing surfaces)", () => {
    expect(siteFooterVariant("home")).toBe("trimmed");
    expect(siteFooterVariant("browse")).toBe("trimmed");
  });

  it("returns full for utility routes", () => {
    expect(siteFooterVariant("saved")).toBe("full");
    expect(siteFooterVariant("plans")).toBe("full");
    expect(siteFooterVariant("account")).toBe("full");
  });
});
