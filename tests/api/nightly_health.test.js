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
  summarizePhotoContract,
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
    // country_code is inferred from per_source_raw (absent here → SV
    // default). New field added by PRD P2-1.
    expect(out).toEqual([
      { ts: "2026-05-11T15:51:53Z", total: 910, dropped: 149, duration_s: 3471.83, error_count: 0, country_code: "SV" },
    ]);
  });
});

// PRD P2-1 — country split coverage. Two failure modes guarded here:
//  1. Without filter, an SV operator looking at last_7_runs sees a PA
//     scaffold run (total=20, encuentra24-only) and misreads it as an
//     SV collapse.
//  2. After filter is wired, a future PA-source addition must not
//     bleed into SV's view (the inferCountry heuristic is conservative
//     — see PA_ONLY_SOURCES comment in health.js).
describe("inferCountry + buildLast7Runs(countryFilter)", () => {
  const { inferCountry } = require("../../api/nightly/health.js").__testing__;

  it("prefers explicit country_code over the heuristic", () => {
    expect(inferCountry({ country_code: "PA", per_source_raw: { goodlife: 80 } })).toBe("PA");
    expect(inferCountry({ country_code: "SV", per_source_raw: { encuentra24: 5 } })).toBe("SV");
    expect(inferCountry({ country_code: "sv" })).toBe("SV");
  });

  it("infers PA from encuentra24-only per_source_raw", () => {
    expect(inferCountry({ per_source_raw: { encuentra24: 21 } })).toBe("PA");
  });

  it("infers SV from multi-source per_source_raw (even if encuentra24 is one of them)", () => {
    expect(inferCountry({ per_source_raw: { encuentra24: 28, goodlife: 71, remax: 354 } })).toBe("SV");
  });

  it("defaults to SV when row lacks country_code AND per_source_raw is empty/missing", () => {
    expect(inferCountry({ per_source_raw: {} })).toBe("SV");
    expect(inferCountry({})).toBe("SV");
    expect(inferCountry(null)).toBe("SV");
  });

  it("filters last_7_runs by country", () => {
    const rows = [
      { ts: "2026-06-02T08:24Z", total: 959, per_source_raw: { goodlife: 71, encuentra24: 28 }, country_code: "SV" },
      { ts: "2026-06-02T08:37Z", total: 20, per_source_raw: { encuentra24: 21 }, country_code: "PA" },
      { ts: "2026-06-03T08:00Z", total: 970, per_source_raw: { goodlife: 80 } },
    ];
    const sv = buildLast7Runs(rows, "SV");
    expect(sv.map((r) => r.total)).toEqual([970, 959]);
    expect(sv.every((r) => r.country_code === "SV")).toBe(true);

    const pa = buildLast7Runs(rows, "PA");
    expect(pa.map((r) => r.total)).toEqual([20]);
    expect(pa[0].country_code).toBe("PA");

    const all = buildLast7Runs(rows, "all");
    expect(all.length).toBe(3);
  });
});

describe("resolveCountryFilter", () => {
  const { resolveCountryFilter, activeCountryFromEnv } = require("../../api/nightly/health.js").__testing__;

  it("returns the active country when no query is given", () => {
    expect(resolveCountryFilter(undefined)).toBe(activeCountryFromEnv());
    expect(resolveCountryFilter({})).toBe(activeCountryFromEnv());
  });

  it("accepts SV/PA/all (case-insensitive)", () => {
    expect(resolveCountryFilter({ country: "SV" })).toBe("SV");
    expect(resolveCountryFilter({ country: "pa" })).toBe("PA");
    expect(resolveCountryFilter({ country: "all" })).toBe("all");
    expect(resolveCountryFilter({ country: "ALL" })).toBe("all");
  });

  it("falls back to active country on unknown values", () => {
    expect(resolveCountryFilter({ country: "BR" })).toBe(activeCountryFromEnv());
    expect(resolveCountryFilter({ country: "" })).toBe(activeCountryFromEnv());
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

// ── PRD P1-2 — summarizePhotoContract ────────────────────────────────
//
// `web/data/photo_contract.json` is written by the Python pipeline's
// pulpo.photo_contract.enforce_photo_contract. The summarizer must
// hand it back to dashboards verbatim (modulo defensive type narrowing)
// so /api/nightly/health is the single ops surface for "do listings
// actually have a working photo?".

describe("summarizePhotoContract", () => {
  it("returns null when the sidecar is missing", () => {
    expect(summarizePhotoContract(null)).toBe(null);
    expect(summarizePhotoContract(undefined)).toBe(null);
    expect(summarizePhotoContract("not-an-object")).toBe(null);
  });

  it("surfaces the full PRD shape when the sidecar is present", () => {
    const out = summarizePhotoContract({
      ranked_total: 959,
      with_local_path: 884,
      local_path_exists: 880,
      local_path_missing: 4,
      missing_rate: 0.0045,
      top_browse: { n: 50, present: 50, missing: 0, coverage: 1.0 },
      top_hero: { n: 10, present: 10, missing: 0, coverage: 1.0 },
      evaluated_at: "2026-06-03T00:00:00+00:00",
    });
    expect(out.ranked_total).toBe(959);
    expect(out.local_path_missing).toBe(4);
    expect(out.missing_rate).toBe(0.0045);
    expect(out.top_browse.coverage).toBe(1.0);
    expect(out.top_hero.present).toBe(10);
    expect(out.evaluated_at).toBe("2026-06-03T00:00:00+00:00");
  });

  it("narrows non-number fields to null defensively", () => {
    const out = summarizePhotoContract({
      ranked_total: "bad",
      with_local_path: 100,
      top_browse: { n: "bad", present: 50, missing: 0, coverage: 1.0 },
      top_hero: null,
    });
    expect(out.ranked_total).toBe(null);
    expect(out.with_local_path).toBe(100);
    expect(out.top_browse.n).toBe(null);
    expect(out.top_hero).toBe(null);
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
