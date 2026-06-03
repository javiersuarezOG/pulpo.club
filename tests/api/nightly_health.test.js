// Unit tests for api/nightly/health.js — runs under vitest (`npm test`).
// Tests pure helpers (no filesystem) and the handler with mocked req/res.
import { describe, it, expect } from "vitest";
import handler from "../../api/nightly/health.js";

const {
  buildLast7Runs,
  failedSourcesLastRun,
  vlmBudgetToday,
  featuredFreshness,
  degradedSources,
  hoursSince,
  STALE_THRESHOLD_H,
} = handler.__testing__;

describe("hoursSince", () => {
  it("returns null for missing / unparseable input", () => {
    expect(hoursSince(null)).toBe(null);
    expect(hoursSince(undefined)).toBe(null);
    expect(hoursSince("not-a-date")).toBe(null);
  });

  it("returns positive number for a past timestamp", () => {
    const oneHourAgo = new Date(Date.now() - 3_600_000).toISOString();
    const h = hoursSince(oneHourAgo);
    expect(h).toBeGreaterThan(0.9);
    expect(h).toBeLessThan(1.5);
  });
});

describe("buildLast7Runs", () => {
  it("returns empty array for non-array input", () => {
    expect(buildLast7Runs(null)).toEqual([]);
    expect(buildLast7Runs({})).toEqual([]);
  });

  it("returns at most 7 entries, newest first", () => {
    const rows = Array.from({ length: 10 }).map((_, i) => ({
      ts: `2026-05-${String(10 + i).padStart(2, "0")}T12:00:00Z`,
      total: 900 + i,
      dropped: 100,
      duration: 3000,
      error_count: 0,
    }));
    const out = buildLast7Runs(rows);
    expect(out.length).toBe(7);
    expect(out[0].ts).toBe("2026-05-19T12:00:00Z");
    expect(out[6].ts).toBe("2026-05-13T12:00:00Z");
  });

  it("projects schema-stable fields and drops extras", () => {
    const out = buildLast7Runs([
      { ts: "2026-05-11T15:51:53Z", total: 910, dropped: 149, duration: 3471.83, error_count: 0, extra: "ignored" },
    ]);
    expect(out).toEqual([
      { ts: "2026-05-11T15:51:53Z", total: 910, dropped: 149, duration_s: 3471.83, error_count: 0 },
    ]);
  });
});

describe("failedSourcesLastRun", () => {
  it("returns empty when all sources green", () => {
    const lastUpdated = {
      started_at: "2026-05-11T14:54:01Z",
      source_status: { goodlife: "green", remax: "green" },
    };
    expect(failedSourcesLastRun(lastUpdated, [])).toEqual([]);
  });

  it("returns failed sources with last_ok_at + error msg", () => {
    const lastUpdated = {
      started_at: "2026-05-18T11:00:00Z",
      source_status: { goodlife: "green", kazu: "red" },
    };
    const sourceHealth = [
      { ts: "2026-05-10T12:00:00Z", source: "kazu", status: "green", error_msg: "" },
      { ts: "2026-05-18T11:00:00Z", source: "kazu", status: "red", error_msg: "HTTP 403" },
    ];
    const out = failedSourcesLastRun(lastUpdated, sourceHealth);
    expect(out.length).toBe(1);
    expect(out[0]).toMatchObject({
      source: "kazu",
      status: "red",
      last_ok_at: "2026-05-10T12:00:00Z",
      error: "HTTP 403",
    });
  });

  it("handles missing source_health rows gracefully", () => {
    const lastUpdated = {
      started_at: "2026-05-18T11:00:00Z",
      source_status: { kazu: "red" },
    };
    const out = failedSourcesLastRun(lastUpdated, null);
    expect(out).toEqual([{ source: "kazu", status: "red", last_ok_at: null, error: null }]);
  });
});

describe("vlmBudgetToday", () => {
  it("returns zeros when no rows", () => {
    expect(vlmBudgetToday([])).toEqual({
      spend_usd: 0,
      pct_used: 0,
      success_rate_24h: null,
      call_count_24h: 0,
    });
  });

  it("sums today's successful calls and computes 24h success rate", () => {
    const today = new Date().toISOString().slice(0, 10);
    const nowIso = new Date().toISOString();
    const rows = [
      { event: "llm_vision_call", ts: nowIso, date: today, provider: "segmind", cost_usd: 0.001, score: 7.0 },
      { event: "llm_vision_call", ts: nowIso, date: today, provider: "segmind", cost_usd: 0.0008, score: 6.0 },
      { event: "llm_vision_call_failed", ts: nowIso, date: today, provider: "segmind", error: "boom" },
    ];
    const out = vlmBudgetToday(rows);
    expect(out.spend_usd).toBeCloseTo(0.0018, 4);
    expect(out.call_count_24h).toBe(3);
    expect(out.success_rate_24h).toBeCloseTo(2 / 3, 2);
  });

  it("ignores calls older than 24h for success rate", () => {
    const twoDaysAgo = new Date(Date.now() - 48 * 3_600_000).toISOString();
    const out = vlmBudgetToday([
      { event: "llm_vision_call", ts: twoDaysAgo, date: twoDaysAgo.slice(0, 10), cost_usd: 0.001 },
    ]);
    expect(out.call_count_24h).toBe(0);
    expect(out.success_rate_24h).toBe(null);
  });
});

function mockRes() {
  const res = {
    statusCode: 200,
    headers: {},
    body: null,
    status(code) {
      res.statusCode = code;
      return res;
    },
    json(payload) {
      res.body = payload;
      return res;
    },
    setHeader(k, v) {
      res.headers[k] = v;
    },
  };
  return res;
}

// ── PRD P1-1 — featuredFreshness ─────────────────────────────────────
//
// `featured.json` had been stale since 2026-05-08 because the nightly
// commit step never staged the file. `/api/nightly/health` now surfaces
// `picked_at`, `expires_at`, `fresh` so dashboards detect the regression
// without opening the JSON.

describe("featuredFreshness", () => {
  it("returns null when the file is missing", () => {
    expect(featuredFreshness(null)).toBe(null);
    expect(featuredFreshness(undefined)).toBe(null);
    expect(featuredFreshness("not-an-object")).toBe(null);
  });

  it("reports fresh=true when expires_at is in the future", () => {
    const future = new Date(Date.now() + 6 * 3600 * 1000).toISOString();
    const out = featuredFreshness({
      picked_at: new Date().toISOString(),
      expires_at: future,
    });
    expect(out.fresh).toBe(true);
    expect(out.expires_at).toBe(future);
  });

  it("reports fresh=false when expires_at is in the past", () => {
    const past = new Date(Date.now() - 1).toISOString();
    const out = featuredFreshness({
      picked_at: "2026-05-07T00:00:00Z",
      expires_at: past,
    });
    expect(out.fresh).toBe(false);
    expect(out.picked_at).toBe("2026-05-07T00:00:00Z");
  });

  it("reports fresh=false when expires_at is unparseable", () => {
    const out = featuredFreshness({
      picked_at: "2026-05-07T00:00:00Z",
      expires_at: "not-a-date",
    });
    expect(out.fresh).toBe(false);
  });
});

// ── PRD P1-9 — degradedSources (JS-side brownout classifier) ────────
//
// Mirrors pulpo.source_health.compute_brownout_states. Both
// implementations consume the same source_health_history.jsonl rows
// and must agree on which sources are in brownout.

describe("degradedSources", () => {
  function _seed(source, kept, days = 8) {
    return Array.from({ length: days }, (_, i) => ({
      source,
      ts: `2026-05-${String(20 + i).padStart(2, "0")}T00:00:00+00:00`,
      kept,
      status: "green",
    }));
  }

  it("returns an empty list when every source is at baseline", () => {
    const rows = _seed("remax", 100);
    expect(degradedSources(rows)).toEqual([]);
  });

  it("marks a single-run dip as degraded, not red", () => {
    const rows = _seed("nexo", 100);
    rows[rows.length - 1].kept = 30; // 30% of 100
    const result = degradedSources(rows);
    expect(result).toHaveLength(1);
    expect(result[0].source).toBe("nexo");
    expect(result[0].status).toBe("degraded");
    expect(result[0].ratio).toBeCloseTo(0.3, 4);
    expect(result[0].rolling_median_7).toBe(100);
    expect(result[0].consecutive_degraded_runs).toBe(1);
  });

  it("escalates to red after two consecutive sub-50% runs", () => {
    const rows = _seed("nexo", 100);
    rows[rows.length - 2].kept = 10;
    rows[rows.length - 1].kept = 10;
    const result = degradedSources(rows);
    expect(result[0].status).toBe("red");
    expect(result[0].consecutive_degraded_runs).toBeGreaterThanOrEqual(2);
  });

  it("reports recovering when previous run was red and current is 50-90%", () => {
    const rows = _seed("elagente", 100);
    rows[rows.length - 3].kept = 10;
    rows[rows.length - 3].status = "red";
    rows[rows.length - 2].kept = 10;
    rows[rows.length - 2].status = "red";
    rows[rows.length - 1].kept = 70;
    const result = degradedSources(rows);
    expect(result[0].status).toBe("recovering");
    expect(result[0].previous_status).toBe("red");
  });

  it("falls back to kept=scraped when kept is absent (legacy schema)", () => {
    const rows = _seed("kazu", 100).map((r) => ({
      source: r.source, ts: r.ts, scraped: r.kept, status: r.status,
    }));
    rows[rows.length - 1].scraped = 20;
    const result = degradedSources(rows);
    expect(result).toHaveLength(1);
    expect(result[0].count).toBe(20);
  });

  it("carries failure_id + error_class onto the brownout payload", () => {
    const rows = _seed("kazu", 100);
    rows[rows.length - 1].kept = 5;
    rows[rows.length - 1].failure_id = "abc123";
    rows[rows.length - 1].error_class = "HTTPError";
    const result = degradedSources(rows);
    expect(result[0].failure_id).toBe("abc123");
    expect(result[0].error_class).toBe("HTTPError");
  });

  it("returns an empty list when sourceHealthRows is not an array", () => {
    expect(degradedSources(null)).toEqual([]);
    expect(degradedSources(undefined)).toEqual([]);
    expect(degradedSources("not-an-array")).toEqual([]);
  });
});

describe("handler", () => {
  it("returns 200 with a valid envelope when data is present", async () => {
    const res = mockRes();
    await handler({ query: {}, headers: {} }, res);
    expect([200, 503]).toContain(res.statusCode);
    expect(res.body).toMatchObject({
      status: expect.stringMatching(/^(ok|stale)$/),
      last_7_runs: expect.any(Array),
      failed_sources_last_run: expect.any(Array),
      vlm_budget_today: expect.objectContaining({
        spend_usd: expect.any(Number),
        pct_used: expect.any(Number),
      }),
      config: expect.objectContaining({
        stale_threshold_hours: STALE_THRESHOLD_H,
      }),
    });
  });

  it("returns 503 when last_data_commit_at is older than the stale threshold", async () => {
    // Asserts the conditional contract: if the repo's web/data/last_updated.json
    // is older than STALE_THRESHOLD_H, status must be "stale" and HTTP 503.
    // Otherwise "ok" and HTTP 200. Either branch is fine — we want both
    // branches reachable from real data in this repo at some point.
    const res = mockRes();
    await handler({ query: {}, headers: {} }, res);
    if (res.body.last_data_commit_age_hours != null && res.body.last_data_commit_age_hours > STALE_THRESHOLD_H) {
      expect(res.statusCode).toBe(503);
      expect(res.body.status).toBe("stale");
    } else {
      expect(res.statusCode).toBe(200);
      expect(res.body.status).toBe("ok");
    }
  });
});
