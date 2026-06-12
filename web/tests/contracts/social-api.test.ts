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
// When true, a thin hires-4:5 pool hard-fails the run (scheduled monitor +
// Slack page). When false (the default on pull_request/push), the
// data-driven hires-floor warns-not-blocks so a single bad nightly can't
// turn the required `contract` check red on every PR in the repo. See plan
// 017 + the SOCIAL_HIRES_FLOOR_STRICT wiring in social-api-contract.yml.
const HIRES_FLOOR_STRICT = process.env.SOCIAL_HIRES_FLOOR_STRICT === "true";

function authHeaders(): Record<string, string> {
  // api/social/listings.js authenticates via `Authorization: Bearer …`,
  // matching pulpo-social's listingsFetcher. NOT a custom header.
  return PULPO_INTERNAL_API_KEY
    ? { authorization: `Bearer ${PULPO_INTERNAL_API_KEY}` }
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

    // Pick the first listing whose hires source is large enough for the 4:5
    // crop (the strictest of the two canonical sizes — 1080×1350). #255's
    // refuse-to-upscale guard returns 404 source_too_small for anything
    // smaller, so the rank-#1 listing isn't a safe pick unless its hires
    // bytes are ≥1080×1350. We page through the listings response, mirroring
    // pulpo-social's pre-filter logic.
    //
    // Reads quality.hires_width / quality.hires_height (populated by plan v2's
    // _download_hires_photos from the broker's NATIVE bytes). The legacy
    // quality.source_width / source_height fields report the post-clamp hero
    // derivative dims (≤1920×1080) and so never clear the 1080×1350 4:5 bar.
    async function findEligibleListingId(): Promise<string | null> {
      const res = await fetch(
        `${PULPO_API_BASE}/api/social/listings?limit=50`,
        { headers: authHeaders() }
      );
      expect(res.status).toBe(200);
      const data = (await res.json()) as {
        listings: Array<{
          id: string;
          quality?: {
            hires_width?: number | null;
            hires_height?: number | null;
            hires_available?: boolean | null;
          };
        }>;
      };
      const TARGET_W = 1080;
      const TARGET_H = 1350; // 4:5 is the tallest canonical
      const hit = data.listings.find((l) => {
        const w = l.quality?.hires_width ?? 0;
        const h = l.quality?.hires_height ?? 0;
        const available = l.quality?.hires_available !== false;
        return available && w >= TARGET_W && h >= TARGET_H;
      });
      if (!hit) {
        const msg =
          `no listing with hires source ≥${TARGET_W}×${TARGET_H} in top 50 — ` +
          `data drift or hires-backfill regression. ` +
          `Check the hires pipeline (PULPO_HIRES_ENABLED) and hires_width/` +
          `hires_height population in ranked.json.`;
        // The hires-4:5 pool is thin and volatile (a single nightly dropped
        // it to 0/50 on 2026-06-12; it recovered to ~2/50). Gating MERGES on
        // this data-driven floor turned the required `contract` check red on
        // every PR in the repo and forced admin-merges. So warn-not-block on
        // the merge path; stay strict ONLY on the scheduled monitor, where
        // SOCIAL_HIRES_FLOOR_STRICT=true preserves the hard page (plan 017).
        if (HIRES_FLOOR_STRICT) {
          throw new Error(msg);
        }
        console.warn(`::warning title=social-hires-floor::${msg}`);
        return null;
      }
      return hit.id;
    }

    it("GET /api/social/image?ratio=1:1 returns a valid JPEG for an eligible listing", async () => {
      const id = await findEligibleListingId();
      if (id === null) {
        console.warn("::warning title=social-hires-floor::no eligible listing in top-50; skipping image-render assertion (data-thin, not a code regression)");
        return; // pass — can't render-test without an eligible listing; this is a data condition
      }
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
      const id = await findEligibleListingId();
      if (id === null) {
        console.warn("::warning title=social-hires-floor::no eligible listing in top-50; skipping image-render assertion (data-thin, not a code regression)");
        return; // pass — can't render-test without an eligible listing; this is a data condition
      }
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
