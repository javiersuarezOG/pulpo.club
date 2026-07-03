// Free→Pro linking contract. When an email-captured Free member converts,
// the captured email must thread into start-checkout (locking Stripe's
// customer_email so the eventual Clerk account links to the same person)
// and the conversion must be attributable via source=free_upgrade.
// Source-text contract (no Stripe mocking), mirroring create_checkout_session_locale.test.js.

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const REPO_ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "../..");
const read = (p) => fs.readFileSync(path.join(REPO_ROOT, p), "utf8");

describe("free→Pro linking: start-checkout server", () => {
  const src = read("api/stripe/start-checkout.js");

  it("whitelists the source to a closed set incl. free_upgrade", () => {
    expect(src).toContain('ALLOWED_SOURCES = new Set(["start", "free_upgrade", "account_upgrade"])');
  });

  it("defaults an unknown/absent source to 'start'", () => {
    expect(src).toMatch(/ALLOWED_SOURCES\.has\(rawSource\)\s*\?\s*rawSource\s*:\s*"start"/);
  });

  it("stamps the resolved source into session metadata (not a hardcoded literal)", () => {
    expect(src).toMatch(/sessionMetadata\s*=\s*\{\s*source,/);
    expect(src).not.toMatch(/sessionMetadata\s*=\s*\{\s*source:\s*"start"/);
  });

  it("locks Stripe customer_email to the passed email", () => {
    expect(src).toContain("sessionParams.customer_email = email");
  });
});

describe("free→Pro linking: client wiring", () => {
  it("checkout helper forwards email + source in the POST body", () => {
    const lib = read("web/app/lib/stripe-modal-checkout.ts");
    expect(lib).toContain("email: input.email || null");
    expect(lib).toContain("source: input.source || null");
  });

  it("AccessBlock Go-Pro passes the Free member's email + source=free_upgrade", () => {
    const block = read("web/app/components/AccessBlock.jsx");
    expect(block).toContain("const memberEmail = (app.user && app.user.email) || null");
    expect(block).toContain('source: memberEmail ? "free_upgrade" : "start"');
  });

  it("FreeMonthModal also marks a Free member's conversion as free_upgrade", () => {
    const modal = read("web/app/components/FreeMonthModal.jsx");
    expect(modal).toContain('source: app.user?.email ? "free_upgrade" : "start"');
  });
});
