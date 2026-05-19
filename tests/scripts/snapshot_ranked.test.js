// Tests for scripts/snapshot_ranked_json.mjs + restore_ranked_json.mjs.
//
// Mocks the @vercel/blob SDK at the dependency-injection point so we
// never touch the network. Pins the contracts that a future regression
// would silently break:
//
//   - Snapshot key follows the snapshots/ranked-YYYY-MM-DD.json shape
//   - Missing BLOB_READ_WRITE_TOKEN is a no-op, not a crash (so a CI
//     environment without the secret still passes the workflow)
//   - Dry-run never calls the SDK
//   - Prune deletes only entries older than the cutoff, keeps fresher
//     ones, and leaves unrecognised filenames alone
//   - Restore validates JSON + array root before overwriting the target
//     (defends against a bad snapshot wiping prod)
//   - Restore writes atomically (tmpfile + rename)

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { existsSync, readFileSync, rmSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  uploadSnapshot,
  pruneOldSnapshots,
  _testing,
} from "../../scripts/snapshot_ranked_json.mjs";
import {
  listSnapshots,
  restoreSnapshot,
} from "../../scripts/restore_ranked_json.mjs";

// ── Mock Vercel Blob SDK ────────────────────────────────────────────────

function makeMockApi(initialBlobs = []) {
  const state = {
    blobs: [...initialBlobs],
    putCalls: [],
    delCalls: [],
    listCalls: [],
  };
  const api = {
    put: async (key, bytes, opts) => {
      state.putCalls.push({ key, size: bytes.length, opts });
      const url = `https://blob.vercel-storage.com/${key}`;
      const idx = state.blobs.findIndex((b) => b.pathname === key);
      const entry = { pathname: key, url, size: bytes.length };
      if (idx >= 0) state.blobs[idx] = entry;
      else state.blobs.push(entry);
      return { url, pathname: key };
    },
    list: async (opts) => {
      state.listCalls.push(opts);
      const prefix = opts?.prefix || "";
      return { blobs: state.blobs.filter((b) => b.pathname.startsWith(prefix)) };
    },
    del: async (url) => {
      state.delCalls.push(url);
      const idx = state.blobs.findIndex((b) => b.url === url);
      if (idx >= 0) state.blobs.splice(idx, 1);
    },
  };
  return { api, state };
}

// Sample ranked.json content for the source/restore round-trip tests.
const SAMPLE_RANKED = [
  { id: "lst_1", title: "Sample", price_usd: 100000 },
  { id: "lst_2", title: "Another", price_usd: 250000 },
];

// ── _testing helpers ────────────────────────────────────────────────────

describe("snapshot key + arg parsing", () => {
  it("today's snapshot key is snapshots/ranked-YYYY-MM-DD.json", () => {
    const today = _testing.todayUtcIso();
    expect(today).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(_testing.snapshotKey()).toBe(`snapshots/ranked-${today}.json`);
  });

  it("snapshotKey rejects malformed dates", () => {
    expect(() => _testing.snapshotKey("2026-13-99")).not.toThrow(); // regex passes
    expect(() => _testing.snapshotKey("2026-5-1")).toThrow();
    expect(() => _testing.snapshotKey("yesterday")).toThrow();
  });

  it("parseArgs honors --dry-run, --prune-older-than, --file", () => {
    expect(_testing.parseArgs(["--dry-run"]).dryRun).toBe(true);
    expect(_testing.parseArgs(["--prune-older-than", "30"]).pruneOlderThanDays).toBe(30);
    expect(_testing.parseArgs(["--file", "/x/y.json"]).file).toBe("/x/y.json");
  });

  it("parseArgs throws on bogus --prune-older-than values", () => {
    expect(() => _testing.parseArgs(["--prune-older-than", "0"])).toThrow();
    expect(() => _testing.parseArgs(["--prune-older-than", "-5"])).toThrow();
    expect(() => _testing.parseArgs(["--prune-older-than", "abc"])).toThrow();
  });
});


// ── uploadSnapshot — happy path + edge cases ────────────────────────────

describe("uploadSnapshot", () => {
  let tmpDir;
  let sourcePath;
  beforeEach(() => {
    tmpDir = mkdtempSync(join(tmpdir(), "pulpo-snapshot-test-"));
    sourcePath = join(tmpDir, "ranked.json");
    writeFileSync(sourcePath, JSON.stringify(SAMPLE_RANKED));
  });
  afterEach(() => {
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it("uploads bytes to the dated key with public access + no random suffix", async () => {
    const { api, state } = makeMockApi();
    const result = await uploadSnapshot({
      sourcePath,
      date: "2026-05-19",
      token: "vercel_blob_rw_test",
      blobApi: api,
    });
    expect(result.uploaded).toBe(true);
    expect(result.key).toBe("snapshots/ranked-2026-05-19.json");
    expect(state.putCalls).toHaveLength(1);
    const call = state.putCalls[0];
    expect(call.opts.access).toBe("public");
    expect(call.opts.addRandomSuffix).toBe(false);
    expect(call.opts.contentType).toBe("application/json");
    // Bytes round-trip — what we read on disk equals what got uploaded
    expect(call.size).toBe(readFileSync(sourcePath).length);
  });

  it("missing source file throws (operator must see it)", async () => {
    await expect(
      uploadSnapshot({
        sourcePath: join(tmpDir, "does-not-exist.json"),
        token: "x",
        blobApi: makeMockApi().api,
      }),
    ).rejects.toThrow(/not found/);
  });

  it("--dry-run never touches the SDK", async () => {
    const { api, state } = makeMockApi();
    const result = await uploadSnapshot({
      sourcePath,
      dryRun: true,
      token: "x",
      blobApi: api,
    });
    expect(result.uploaded).toBe(false);
    expect(result.reason).toBe("dry_run");
    expect(state.putCalls).toHaveLength(0);
  });

  it("missing token is a no-op (CI environments without Blob still pass)", async () => {
    const { api, state } = makeMockApi();
    const result = await uploadSnapshot({
      sourcePath,
      token: undefined,
      blobApi: api,
    });
    expect(result.uploaded).toBe(false);
    expect(result.reason).toBe("no_token");
    expect(state.putCalls).toHaveLength(0);
  });
});


// ── pruneOldSnapshots — retention semantics ─────────────────────────────

describe("pruneOldSnapshots", () => {
  it("deletes entries older than the cutoff, keeps the rest", async () => {
    const { api, state } = makeMockApi([
      { pathname: "snapshots/ranked-2024-01-01.json", url: "u/old", size: 100 },
      { pathname: "snapshots/ranked-2025-06-01.json", url: "u/mid", size: 100 },
      { pathname: "snapshots/ranked-2026-05-19.json", url: "u/new", size: 100 },
    ]);
    const result = await pruneOldSnapshots({
      olderThanDays: 90,
      token: "x",
      blobApi: api,
      now: new Date("2026-05-19T00:00:00Z"),
    });
    expect(result.pruned).toBe(2);          // 2024 + 2025 both >90 days old
    expect(result.kept).toBe(1);            // 2026-05-19 stays
    expect(state.delCalls).toContain("u/old");
    expect(state.delCalls).toContain("u/mid");
    expect(state.delCalls).not.toContain("u/new");
  });

  it("leaves unrecognised filenames alone (no silent destruction)", async () => {
    const { api, state } = makeMockApi([
      { pathname: "snapshots/manual-backup.json", url: "u/manual", size: 100 },
      { pathname: "snapshots/ranked-2020-01-01.json", url: "u/ancient", size: 100 },
    ]);
    const result = await pruneOldSnapshots({
      olderThanDays: 30,
      token: "x",
      blobApi: api,
      now: new Date("2026-05-19T00:00:00Z"),
    });
    expect(result.pruned).toBe(1);                // only the dated one
    expect(state.delCalls).toEqual(["u/ancient"]); // manual backup untouched
  });

  it("missing token is a no-op (matches uploadSnapshot's policy)", async () => {
    const result = await pruneOldSnapshots({
      olderThanDays: 30,
      token: undefined,
      blobApi: makeMockApi().api,
    });
    expect(result.pruned).toBe(0);
    expect(result.reason).toBe("no_token");
  });

  it("rejects non-positive olderThanDays at the boundary", async () => {
    await expect(
      pruneOldSnapshots({
        olderThanDays: 0,
        token: "x",
        blobApi: makeMockApi().api,
      }),
    ).rejects.toThrow(/positive integer/);
  });
});


// ── listSnapshots + restoreSnapshot — recovery path ─────────────────────

describe("listSnapshots", () => {
  it("returns snapshots sorted newest-first with date/url/size", async () => {
    const { api } = makeMockApi([
      { pathname: "snapshots/ranked-2026-05-01.json", url: "u/01", size: 100 },
      { pathname: "snapshots/ranked-2026-05-19.json", url: "u/19", size: 200 },
      { pathname: "snapshots/ranked-2026-05-10.json", url: "u/10", size: 150 },
    ]);
    const result = await listSnapshots({ token: "x", blobApi: api });
    expect(result.map((s) => s.date)).toEqual(["2026-05-19", "2026-05-10", "2026-05-01"]);
    expect(result[0].url).toBe("u/19");
    expect(result[0].size).toBe(200);
  });

  it("filters out non-snapshot files quietly", async () => {
    const { api } = makeMockApi([
      { pathname: "snapshots/ranked-2026-05-19.json", url: "u/r", size: 100 },
      { pathname: "snapshots/manual.json", url: "u/m", size: 100 },
    ]);
    const result = await listSnapshots({ token: "x", blobApi: api });
    expect(result).toHaveLength(1);
    expect(result[0].date).toBe("2026-05-19");
  });

  it("requires a token", async () => {
    await expect(listSnapshots({ token: undefined, blobApi: makeMockApi().api }))
      .rejects.toThrow(/required/);
  });
});


describe("restoreSnapshot", () => {
  let tmpDir;
  let target;
  beforeEach(() => {
    tmpDir = mkdtempSync(join(tmpdir(), "pulpo-restore-test-"));
    target = join(tmpDir, "ranked.json");
  });
  afterEach(() => {
    rmSync(tmpDir, { recursive: true, force: true });
  });

  function fakeFetch(payload, opts = {}) {
    return async () => ({
      ok: opts.ok !== false,
      status: opts.status || 200,
      async text() { return typeof payload === "string" ? payload : JSON.stringify(payload); },
    });
  }

  it("restores the latest snapshot when no date is given", async () => {
    const { api } = makeMockApi([
      { pathname: "snapshots/ranked-2026-05-19.json", url: "https://x/19", size: 100 },
      { pathname: "snapshots/ranked-2026-05-18.json", url: "https://x/18", size: 100 },
    ]);
    const result = await restoreSnapshot({
      target, token: "x", blobApi: api,
      fetchImpl: fakeFetch(SAMPLE_RANKED),
    });
    expect(result.restored).toBe(true);
    expect(result.date).toBe("2026-05-19");
    expect(result.entries).toBe(2);
    // File written + atomic (no .tmp lingering)
    const written = JSON.parse(readFileSync(target, "utf8"));
    expect(written).toEqual(SAMPLE_RANKED);
    expect(existsSync(`${target}.tmp.${process.pid}`)).toBe(false);
  });

  it("restores a specific date when --date is given", async () => {
    const { api } = makeMockApi([
      { pathname: "snapshots/ranked-2026-05-19.json", url: "https://x/19", size: 100 },
      { pathname: "snapshots/ranked-2026-05-12.json", url: "https://x/12", size: 100 },
    ]);
    const result = await restoreSnapshot({
      date: "2026-05-12",
      target, token: "x", blobApi: api,
      fetchImpl: fakeFetch(SAMPLE_RANKED),
    });
    expect(result.date).toBe("2026-05-12");
  });

  it("rejects a missing date with a helpful message", async () => {
    const { api } = makeMockApi([
      { pathname: "snapshots/ranked-2026-05-19.json", url: "https://x/19", size: 100 },
    ]);
    await expect(restoreSnapshot({
      date: "2026-04-01",
      target, token: "x", blobApi: api,
      fetchImpl: fakeFetch(SAMPLE_RANKED),
    })).rejects.toThrow(/No snapshot for date 2026-04-01/);
  });

  it("dry-run validates without writing", async () => {
    const { api } = makeMockApi([
      { pathname: "snapshots/ranked-2026-05-19.json", url: "https://x/19", size: 100 },
    ]);
    const result = await restoreSnapshot({
      dryRun: true, target, token: "x", blobApi: api,
      fetchImpl: fakeFetch(SAMPLE_RANKED),
    });
    expect(result.restored).toBe(false);
    expect(result.reason).toBe("dry_run");
    expect(existsSync(target)).toBe(false);
  });

  it("refuses to overwrite target with non-JSON payload", async () => {
    const { api } = makeMockApi([
      { pathname: "snapshots/ranked-2026-05-19.json", url: "https://x/19", size: 100 },
    ]);
    await expect(restoreSnapshot({
      target, token: "x", blobApi: api,
      fetchImpl: fakeFetch("<<not json>>"),
    })).rejects.toThrow(/not valid JSON/);
    expect(existsSync(target)).toBe(false);
  });

  it("refuses to overwrite target with non-array root (wrong shape)", async () => {
    const { api } = makeMockApi([
      { pathname: "snapshots/ranked-2026-05-19.json", url: "https://x/19", size: 100 },
    ]);
    await expect(restoreSnapshot({
      target, token: "x", blobApi: api,
      fetchImpl: fakeFetch({ not: "an array" }),
    })).rejects.toThrow(/expected array/);
    expect(existsSync(target)).toBe(false);
  });

  it("surfaces HTTP failures from the Blob URL", async () => {
    const { api } = makeMockApi([
      { pathname: "snapshots/ranked-2026-05-19.json", url: "https://x/19", size: 100 },
    ]);
    await expect(restoreSnapshot({
      target, token: "x", blobApi: api,
      fetchImpl: fakeFetch("", { ok: false, status: 404 }),
    })).rejects.toThrow(/HTTP 404/);
  });
});
