// Contract test for /api/social/listings + /api/social/image.
//
// This is the pulpo.club-side mirror of pulpo-social's
// tests/contracts/pulpoclub.test.ts. Both repos depend on the response
// shape staying stable; a renaming PR landing in one repo without the
// other catching it would silently break daily Instagram + Facebook
// publishing.
//
// SKIP-WHEN-UNSET: gated on PULPO_API_BASE so `npm test` locally doesn't
// fail when developers aren't running the cron URL. CI sets
// PULPO_API_BASE (preview URL) + PULPO_INTERNAL_API_KEY from repo
// secrets via .github/workflows/social-api-contract.yml.

import { describe, it, expect } from "vitest";

const PULPO_API_BASE = process.env.PULPO_API_BASE;
const PULPO_INTERNAL_API_KEY = process.env.PULPO_INTERNAL_API_KEY;
const ENABLED = Boolean(PULPO_API_BASE);

function authHeaders(): Record<string, string> {
  return PULPO_INTERNAL_API_KEY
    ? { "x-pulpo-internal-key": PULPO_INTERNAL_API_KEY }
    : {};
}

(ENABLED ? describe : describe.skip)(
  "/api/social contract",
  () => {
    it("GET /api/social/listings?limit=1 returns the projected listing shape", async () => {
      const res = await fetch(`${PULPO_API_BASE}/api/social/listings?limit=1`, {
        headers: authHeaders(),
      });
      expect(res.status).toBe(200);
      const data = (await res.json()) as {
        listings?: Array<Record<string, unknown>>;
        total?: number;
      };
      expect(Array.isArray(data.listings)).toBe(true);
      expect(data.listings!.length).toBeGreaterThan(0);
      expect(typeof data.total).toBe("number");

      // These are the fields pulpo-social reads (see pulpo-social
      // src/core/types.ts ListingSchema). Renaming or removing any breaks
      // daily publishing — the test exists precisely to catch that.
      const listing = data.listings![0]!;
      expect(typeof listing.id).toBe("string");
      expect(typeof listing.title).toBe("string");
      expect(typeof listing.image_url).toBe("string");
      expect(typeof listing.listing_url).toBe("string");
      // price_usd is nullable for private-price listings; the field MUST
      // exist on the object even when null.
      expect("price_usd" in listing).toBe(true);
      // quality nesting: hero_photo_quality_score is what the daily
      // pulpo-social gate filters on.
      expect(listing.quality).toBeTruthy();
      const quality = listing.quality as { hero_photo_quality_score?: unknown };
      expect("hero_photo_quality_score" in quality).toBe(true);
    });

    it("GET /api/social/image?id=<first>&ratio=1:1 returns a valid JPEG", async () => {
      const listingsRes = await fetch(
        `${PULPO_API_BASE}/api/social/listings?limit=1`,
        { headers: authHeaders() }
      );
      const data = (await listingsRes.json()) as {
        listings: Array<{ id: string }>;
      };
      const id = data.listings[0]!.id;

      const imgRes = await fetch(
        `${PULPO_API_BASE}/api/social/image?id=${encodeURIComponent(id)}&ratio=1:1`,
        { headers: authHeaders() }
      );
      expect(imgRes.status).toBe(200);
      const contentType = imgRes.headers.get("content-type") ?? "";
      expect(contentType).toContain("image/jpeg");
    });

    it("GET /api/social/image?ratio=4:5 also returns a valid JPEG", async () => {
      // Catches a regression in the 4:5 (Reels-friendly) crop path. The 1:1
      // path is exercised every cron tick; the 4:5 path is rarer and would
      // otherwise rot.
      const listingsRes = await fetch(
        `${PULPO_API_BASE}/api/social/listings?limit=1`,
        { headers: authHeaders() }
      );
      const data = (await listingsRes.json()) as {
        listings: Array<{ id: string }>;
      };
      const id = data.listings[0]!.id;
      const imgRes = await fetch(
        `${PULPO_API_BASE}/api/social/image?id=${encodeURIComponent(id)}&ratio=4:5`,
        { headers: authHeaders() }
      );
      expect(imgRes.status).toBe(200);
      expect(imgRes.headers.get("content-type") ?? "").toContain("image/jpeg");
    });

    it("listings endpoint rejects unauthenticated requests", async () => {
      // Defense-in-depth — the endpoint is bearer-token gated. If the
      // gate disappears in a refactor, this test catches it before the
      // listing data leaks publicly.
      const res = await fetch(`${PULPO_API_BASE}/api/social/listings?limit=1`);
      expect([401, 403]).toContain(res.status);
    });
  }
);
