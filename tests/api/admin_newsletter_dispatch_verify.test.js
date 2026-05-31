// Coverage for the post-dispatch verification added 2026-05-31 to
// trigger-preview.js + trigger-audience-send.js.
//
// Two layers:
//
//   1. Behavioural tests of api/admin/newsletter/_verify_dispatch.js
//      with `fetch` stubbed via vitest's global mock. Exercises the
//      poll-and-give-up path that catches GitHub's silent-drop failure
//      mode (POST /workflows/.../dispatches returns 204 but no run
//      materializes — bit us in prod on 2026-05-31, see the file
//      header of _verify_dispatch.js for background).
//
//   2. Shape tests on trigger-preview.js + trigger-audience-send.js
//      that the verification call wires in correctly and the
//      `dispatch_accepted_but_no_run_created` 502 path exists. Mirrors
//      the pattern in admin_newsletter_audience_send_shape.test.js —
//      cheap insurance that a future refactor doesn't silently drop
//      the verify hop and re-introduce the bug.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const VERIFY_PATH = path.resolve(__dirname, "../../api/admin/newsletter/_verify_dispatch.js");
const PREVIEW_PATH = path.resolve(__dirname, "../../api/admin/newsletter/trigger-preview.js");
const SEND_PATH = path.resolve(__dirname, "../../api/admin/newsletter/trigger-audience-send.js");

const verifySrc = fs.readFileSync(VERIFY_PATH, "utf8");
const previewSrc = fs.readFileSync(PREVIEW_PATH, "utf8");
const sendSrc = fs.readFileSync(SEND_PATH, "utf8");

// CommonJS module loaded via require for the behavioural tests. The
// Vercel handlers themselves are require-based modules too, so this
// matches the prod runtime exactly.
const { createRequire } = await import("node:module");
const requireCjs = createRequire(import.meta.url);
const { getLatestRunId, pollForNewerRun } = requireCjs(VERIFY_PATH);

describe("_verify_dispatch.js — getLatestRunId", () => {
  let fetchSpy;

  beforeEach(() => {
    fetchSpy = vi.spyOn(global, "fetch");
  });
  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("returns the most recent workflow_dispatch run id", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ workflow_runs: [{ id: 999 }, { id: 998 }] }),
    });
    const id = await getLatestRunId({
      repo: "x/y", workflowFile: "w.yml", token: "t",
    });
    expect(id).toBe(999);
    expect(fetchSpy).toHaveBeenCalledOnce();
    const calledUrl = fetchSpy.mock.calls[0][0];
    expect(calledUrl).toContain("/repos/x/y/actions/workflows/w.yml/runs");
    expect(calledUrl).toContain("event=workflow_dispatch");
    expect(calledUrl).toContain("per_page=1");
  });

  it("returns 0 when no runs exist yet", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ workflow_runs: [] }),
    });
    const id = await getLatestRunId({
      repo: "x/y", workflowFile: "w.yml", token: "t",
    });
    expect(id).toBe(0);
  });

  it("returns null when the GitHub API call fails (network)", async () => {
    fetchSpy.mockRejectedValue(new Error("ENOTFOUND"));
    const id = await getLatestRunId({
      repo: "x/y", workflowFile: "w.yml", token: "t",
    });
    expect(id).toBeNull();
  });

  it("returns null on non-2xx response so callers can soft-skip verify", async () => {
    fetchSpy.mockResolvedValue({ ok: false, status: 503, json: async () => ({}) });
    const id = await getLatestRunId({
      repo: "x/y", workflowFile: "w.yml", token: "t",
    });
    expect(id).toBeNull();
  });

  it("returns null on malformed body (no workflow_runs array)", async () => {
    fetchSpy.mockResolvedValue({
      ok: true, status: 200, json: async () => ({ message: "weird" }),
    });
    const id = await getLatestRunId({
      repo: "x/y", workflowFile: "w.yml", token: "t",
    });
    expect(id).toBeNull();
  });
});

describe("_verify_dispatch.js — pollForNewerRun", () => {
  let fetchSpy;

  beforeEach(() => {
    fetchSpy = vi.spyOn(global, "fetch");
  });
  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("returns the new run on the first poll when one exists", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ workflow_runs: [{ id: 1001, html_url: "x" }, { id: 1000 }] }),
    });
    const run = await pollForNewerRun({
      repo: "x/y", workflowFile: "w.yml", token: "t",
      baselineId: 1000,
      timeoutMs: 50, intervalMs: 10,
    });
    expect(run).toEqual({ id: 1001, html_url: "x" });
  });

  it("returns null when no newer run appears within the timeout (silent-drop path)", async () => {
    // GitHub keeps returning the same baseline run — the dispatch was
    // accepted but no new run was queued. This is the failure mode we
    // were missing prior to 2026-05-31.
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ workflow_runs: [{ id: 1000 }] }),
    });
    const run = await pollForNewerRun({
      repo: "x/y", workflowFile: "w.yml", token: "t",
      baselineId: 1000,
      timeoutMs: 50, intervalMs: 10,
    });
    expect(run).toBeNull();
    // Polled at least twice within the 50ms budget at 10ms interval.
    expect(fetchSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("swallows mid-poll errors and keeps trying", async () => {
    let n = 0;
    fetchSpy.mockImplementation(async () => {
      n += 1;
      if (n === 1) throw new Error("transient");
      if (n === 2) return { ok: false, status: 500, json: async () => ({}) };
      return {
        ok: true,
        status: 200,
        json: async () => ({ workflow_runs: [{ id: 2001 }, { id: 2000 }] }),
      };
    });
    const run = await pollForNewerRun({
      repo: "x/y", workflowFile: "w.yml", token: "t",
      baselineId: 2000,
      timeoutMs: 200, intervalMs: 10,
    });
    expect(run).toEqual({ id: 2001 });
    expect(n).toBeGreaterThanOrEqual(3);
  });

  it("treats a baseline of 0 (no prior runs) as a valid floor", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ workflow_runs: [{ id: 1 }] }),
    });
    const run = await pollForNewerRun({
      repo: "x/y", workflowFile: "w.yml", token: "t",
      baselineId: 0,
      timeoutMs: 50, intervalMs: 10,
    });
    expect(run).toEqual({ id: 1 });
  });
});

describe("trigger-preview.js — wires verification", () => {
  it("imports the verify helper", () => {
    expect(previewSrc).toMatch(
      /require\(['"]\.\/_verify_dispatch['"]\)/,
    );
    expect(previewSrc).toMatch(/getLatestRunId/);
    expect(previewSrc).toMatch(/pollForNewerRun/);
  });

  it("captures baseline BEFORE the dispatch fetch", () => {
    const baselineIdx = previewSrc.indexOf("getLatestRunId");
    const dispatchFetchIdx = previewSrc.indexOf("/actions/workflows/${WORKFLOW_FILE}/dispatches");
    expect(baselineIdx).toBeGreaterThan(-1);
    expect(dispatchFetchIdx).toBeGreaterThan(-1);
    expect(baselineIdx).toBeLessThan(dispatchFetchIdx);
  });

  it("polls AFTER the dispatch and 502s on a null result", () => {
    expect(previewSrc).toMatch(/pollForNewerRun\(\{/);
    expect(previewSrc).toMatch(/dispatch_accepted_but_no_run_created/);
    expect(previewSrc).toMatch(/return res\.status\(502\)\.json\(\{[\s\S]*?dispatch_accepted_but_no_run_created/);
  });

  it("returns verified:true with run_id in the success body", () => {
    expect(previewSrc).toMatch(/verified:\s*true/);
    expect(previewSrc).toMatch(/run_id:\s*newRun\.id/);
  });

  it("soft-skips verification when baseline lookup failed (returns 202 with verified:false)", () => {
    // baseline === null means GitHub runs API was unavailable; failing
    // closed in that case would block all dispatches during a wider
    // GitHub outage, which is worse than the rare missed verify.
    expect(previewSrc).toMatch(/baselineRunId !== null/);
    expect(previewSrc).toMatch(/verified:\s*false/);
    expect(previewSrc).toMatch(/baseline_unavailable/);
  });
});

describe("trigger-audience-send.js — wires verification", () => {
  it("imports the verify helper", () => {
    expect(sendSrc).toMatch(
      /require\(['"]\.\/_verify_dispatch['"]\)/,
    );
    expect(sendSrc).toMatch(/getLatestRunId/);
    expect(sendSrc).toMatch(/pollForNewerRun/);
  });

  it("captures baseline BEFORE the dispatch fetch", () => {
    const baselineIdx = sendSrc.indexOf("getLatestRunId");
    const dispatchFetchIdx = sendSrc.indexOf("/actions/workflows/${WORKFLOW_FILE}/dispatches");
    expect(baselineIdx).toBeGreaterThan(-1);
    expect(dispatchFetchIdx).toBeGreaterThan(-1);
    expect(baselineIdx).toBeLessThan(dispatchFetchIdx);
  });

  it("polls AFTER the dispatch and 502s on a null result", () => {
    expect(sendSrc).toMatch(/pollForNewerRun\(\{/);
    expect(sendSrc).toMatch(/dispatch_accepted_but_no_run_created/);
    expect(sendSrc).toMatch(/return res\.status\(502\)\.json\(\{[\s\S]*?dispatch_accepted_but_no_run_created/);
  });

  it("emits an audit event on the verify-failure path (not just the dispatch-failure paths)", () => {
    // The audience send is high-blast-radius — every Pro subscriber.
    // The PostHog audit trail needs the silent-drop case visible.
    const auditCalls = (sendSrc.match(/await emitAuditEvent\(/g) || []).length;
    expect(auditCalls).toBeGreaterThanOrEqual(4);
  });

  it("returns verified:true with run_id in the success body", () => {
    expect(sendSrc).toMatch(/verified:\s*true/);
    expect(sendSrc).toMatch(/run_id:\s*newRun\.id/);
  });
});

describe("_verify_dispatch.js — module shape", () => {
  it("exports both helpers", () => {
    expect(typeof getLatestRunId).toBe("function");
    expect(typeof pollForNewerRun).toBe("function");
  });

  it("sets the X-GitHub-Api-Version pin (2022-11-28) so a GitHub-side default change can't drift behavior", () => {
    expect(verifySrc).toMatch(/X-GitHub-Api-Version["']:\s*["']2022-11-28["']/);
  });

  it("default poll budget is bounded so we don't hit Vercel's 15s function timeout", () => {
    // Tightly coupled to the constant; if you bump it past ~10s also
    // bump Vercel's maxDuration for these functions.
    expect(verifySrc).toMatch(/timeoutMs\s*=\s*8000/);
  });
});
