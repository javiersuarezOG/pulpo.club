// Referral-attribution (sr) contract. The share-link referrer token must
// survive the full chain: share URL → campaign capture → both Stripe
// checkout POST bodies → Stripe session metadata. This is a producer with
// a deferred consumer (the P1 referral webhook), so we pin the producer
// side here to prevent silent drift — the metadata.sr field is the
// durable spine the reward logic will read.
//
// Source-text contract (no Stripe mocking), mirroring
// start_checkout_free_upgrade.test.js.

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const REPO_ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "../..");
const read = (p) => fs.readFileSync(path.join(REPO_ROOT, p), "utf8");

// The shape guard is duplicated at each trust boundary on purpose (client
// share.ts, client campaign.ts, both server endpoints). Keep them
// identical so a token that passes one layer passes all.
const SHAPE = String.raw`/^[A-Za-z0-9._-]{1,64}$/`;

describe("sr attribution — client capture + forwarding", () => {
  it("share.ts embeds &sr= and shape-guards the referrer", () => {
    const src = read("web/app/lib/share.ts");
    expect(src).toContain("sanitizeReferrer");
    expect(src).toContain("&sr=");
    expect(src).toContain(SHAPE);
  });

  it("SharePicker passes the sharer distinct_id into shareUrlFor", () => {
    const src = read("web/app/components/SharePicker.jsx");
    expect(src).toContain("shareUrlFor(listing.id, getDistinctId())");
  });

  it("campaign.ts captures + persists sr with URL-wins/fallback", () => {
    const src = read("web/app/lib/campaign.ts");
    expect(src).toContain("shareReferrer");
    expect(src).toContain('"pulpo-sr"');
    expect(src).toContain(SHAPE);
  });

  it("both checkout wrappers forward sr in the POST body", () => {
    expect(read("web/app/auth/stripe-checkout.js")).toContain("payload.sr = shareReferrer");
    expect(read("web/app/lib/stripe-modal-checkout.ts")).toContain("shareReferrer");
  });

  it("telemetry allowlist preserves the sr URL param", () => {
    expect(read("web/app/telemetry/client.ts")).toMatch(/"sr",/);
  });
});

describe("sr attribution — server stamps Stripe metadata", () => {
  it("start-checkout shape-guards sr and stamps it into session metadata", () => {
    const src = read("api/stripe/start-checkout.js");
    expect(src).toContain(SHAPE);
    expect(src).toContain("shareReferrer ? { sr: shareReferrer }");
    // Boolean-only in PostHog (no raw token in event props).
    expect(src).toContain("has_referral: !!shareReferrer");
  });

  it("create-checkout-session mirrors sr into both metadata blocks", () => {
    const src = read("api/stripe/create-checkout-session.js");
    expect(src).toContain(SHAPE);
    expect(src).toContain("referralMeta");
    // Present on BOTH the session and subscription metadata.
    const count = (src.match(/\.\.\.referralMeta/g) || []).length;
    expect(count).toBe(2);
    expect(src).toContain("has_referral: !!shareReferrer");
  });
});
