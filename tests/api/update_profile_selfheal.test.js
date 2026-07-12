// Behavioral test for the publicMetadata self-heal in
// api/clerk/update-profile.js. Reported bug: a heavily-stamped Pro account
// pushed publicMetadata over Clerk's ~8KB cap, so EVERY newsletter-preference
// save 500'd (the chip rolled back). On a size failure the handler now drops
// only non-critical data (attribution UTMs + webhook breadcrumbs + the legacy
// profile.newsletter blob) and retries — never billing/plan/welcome stamps or
// the live filters.
import { describe, it, expect, vi, beforeEach } from "vitest";
import handler from "../../api/clerk/update-profile.js";

// Inject clerkClient / authenticateClerkRequest via the handler's `deps`
// param (mirrors api/newsletter.js's resendImpl) — no CJS-require stubbing.
const state = { clerk: null, userId: "user_1" };
const deps = () => ({
  clerkClient: () => state.clerk,
  authenticateClerkRequest: async () => state.userId,
});

function mockRes() {
  const res = { statusCode: 200, body: null, headers: {} };
  res.status = vi.fn((c) => { res.statusCode = c; return res; });
  res.json = vi.fn((b) => { res.body = b; return res; });
  res.setHeader = vi.fn((k, v) => { res.headers[k] = v; });
  return res;
}
const mockReq = (patch) => ({ method: "POST", headers: {}, body: { patch } });

function sizeError() {
  const e = new Error("Unprocessable Entity");
  e.status = 422;
  e.errors = [{ code: "form_param_value_too_long", message: "Public metadata exceeds maximum size" }];
  return e;
}

beforeEach(() => { state.clerk = null; state.userId = "user_1"; });

describe("update-profile self-heal", () => {
  it("size failure → slims non-critical keys, retries, 200 — keeps billing + live filters + patch", async () => {
    const bloated = {
      plan: "pro",
      subscription_status: "active",
      welcome_newsletter_sent_at: 1,
      acquisition_utm_source: "reddit",
      acquisition_utm_campaign: "camp",
      pulpo_last_event_id: "evt_1",
      profile: {
        discover_filters: { features: ["beachfront"] },
        newsletter: { departments: ["x"] },
        preferred_categories: ["new_this_week"],
      },
    };
    let call = 0;
    const writes = [];
    state.clerk = { users: {
      getUser: vi.fn(async () => ({ publicMetadata: bloated })),
      updateUserMetadata: vi.fn(async (id, arg) => {
        call += 1; writes.push(arg.publicMetadata);
        if (call === 1) throw sizeError();   // full write over cap
        return {};                            // slim retry fits
      }),
    } };

    const res = mockRes();
    await handler(mockReq({ preferred_categories: ["price_drops"] }), res, deps());

    expect(res.statusCode).toBe(200);
    expect(call).toBe(2);                     // retried once
    const slim = writes[1];
    // dropped: attribution + breadcrumb + legacy newsletter
    expect(slim.acquisition_utm_source).toBeUndefined();
    expect(slim.acquisition_utm_campaign).toBeUndefined();
    expect(slim.pulpo_last_event_id).toBeUndefined();
    expect(slim.profile.newsletter).toBeUndefined();
    // KEPT: billing, welcome stamp, live filters, and the new patch value
    expect(slim.plan).toBe("pro");
    expect(slim.subscription_status).toBe("active");
    expect(slim.welcome_newsletter_sent_at).toBe(1);
    expect(slim.profile.discover_filters).toEqual({ features: ["beachfront"] });
    expect(slim.profile.preferred_categories).toEqual(["price_drops"]);
  });

  it("non-size failure → NO data dropped, single attempt, returns write_failed", async () => {
    state.clerk = { users: {
      getUser: vi.fn(async () => ({ publicMetadata: { plan: "pro", acquisition_utm_source: "reddit", profile: {} } })),
      updateUserMetadata: vi.fn(async () => {
        const e = new Error("rate limited"); e.status = 429;
        e.errors = [{ code: "rate_limit_exceeded", message: "Too many requests" }];
        throw e;
      }),
    } };
    const res = mockRes();
    await handler(mockReq({ language: "en" }), res, deps());
    expect(res.statusCode).toBe(500);
    expect(res.body.error).toBe("write_failed");
    expect(state.clerk.users.updateUserMetadata).toHaveBeenCalledTimes(1); // no slim retry
    expect(res.body.detail).toContain("["); // byte/top-key breakdown appended
  });

  it("only preferred_categories set → legacy newsletter NOT dropped (no discover_filters guard)", async () => {
    // Safety: never drop profile.newsletter unless discover_filters exists to
    // supersede it — else a user with only the legacy blob loses their prefs.
    let call = 0; const writes = [];
    state.clerk = { users: {
      getUser: vi.fn(async () => ({ publicMetadata: { plan: "pro", profile: { newsletter: { departments: ["x"] } } } })),
      updateUserMetadata: vi.fn(async (id, arg) => { call += 1; writes.push(arg.publicMetadata); if (call === 1) throw sizeError(); return {}; }),
    } };
    const res = mockRes();
    await handler(mockReq({ preferred_categories: ["price_drops"] }), res, deps());
    // No safe-drop keys present → slim finds nothing to drop → falls through to 500.
    expect(res.statusCode).toBe(500);
    expect(call).toBe(1);
  });
});
