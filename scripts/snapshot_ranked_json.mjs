#!/usr/bin/env node
/**
 * Snapshot web/data/ranked.json to durable storage (Vercel Blob).
 *
 * Recovery path for the data pipeline. If a future nightly produces a
 * bad ranked.json that overwrites yesterday's good one, an immutable
 * dated snapshot in Vercel Blob lets us roll back without rebuilding
 * the full pipeline from scratch — git history alone is fragile because
 * the data-PR branches auto-delete and big-data commits on main are
 * painful to cherry-pick selectively.
 *
 * Storage layout in the configured Blob store:
 *   snapshots/ranked-YYYY-MM-DD.json     # last-write-wins per UTC day
 *
 * Retention is a separate command (`--prune-older-than DAYS`, default 90)
 * so the storage envelope stays trivial (~2 MB × 90 days × 1.5x churn ≈ 270 MB,
 * well inside the 1 GB free tier).
 *
 * Modes:
 *   node scripts/snapshot_ranked_json.mjs                     # upload today
 *   node scripts/snapshot_ranked_json.mjs --dry-run           # print intent, no upload
 *   node scripts/snapshot_ranked_json.mjs --prune-older-than 90
 *   node scripts/snapshot_ranked_json.mjs --file PATH         # alt source file
 *
 * Failure policy: this script is best-effort. A snapshot failure must
 * not fail the nightly — the pipeline already succeeded and corrupting
 * the run because backup didn't work is the kind of irony we don't
 * need. Exit code 0 even on upload failure, with the error printed to
 * stderr so the operator sees it in the workflow log. Missing token
 * (BLOB_READ_WRITE_TOKEN unset) is a no-op, not an error — the
 * pipeline runs the same in environments without Blob configured.
 */
import { readFileSync, existsSync, statSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..");
const DEFAULT_SOURCE = resolve(REPO_ROOT, "web/data/ranked.json");
const SNAPSHOT_PREFIX = "snapshots/";

const TOKEN_ENV = "BLOB_READ_WRITE_TOKEN";


function todayUtcIso() {
  return new Date().toISOString().slice(0, 10);
}


function snapshotKey(date = todayUtcIso()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error(`Invalid snapshot date: ${date}`);
  }
  return `${SNAPSHOT_PREFIX}ranked-${date}.json`;
}


function parseArgs(argv) {
  const out = { dryRun: false, pruneOlderThanDays: null, file: DEFAULT_SOURCE };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--dry-run") out.dryRun = true;
    else if (a === "--prune-older-than") {
      const n = Number(argv[++i]);
      if (!Number.isFinite(n) || n <= 0) {
        throw new Error("--prune-older-than requires a positive integer");
      }
      out.pruneOlderThanDays = n;
    } else if (a === "--file") {
      out.file = argv[++i];
    } else if (a === "--help" || a === "-h") {
      out.help = true;
    } else {
      throw new Error(`Unknown argument: ${a}`);
    }
  }
  return out;
}


function printHelp() {
  console.log(
    [
      "Usage: snapshot_ranked_json.mjs [options]",
      "",
      "  (no args)                Upload web/data/ranked.json as today's snapshot",
      "  --dry-run                Print intent, do not upload",
      "  --prune-older-than N     Delete snapshots older than N days",
      "  --file PATH              Override source file path",
      "  --help, -h               Show this help",
      "",
      `Environment: ${TOKEN_ENV} (required for upload; absent = no-op)`,
    ].join("\n"),
  );
}


// Resolve the Blob SDK lazily so the dry-run + help paths don't pay
// the import cost. The dependency is also optional in CI environments
// that don't have it installed yet.
async function loadBlobSdk() {
  try {
    return await import("@vercel/blob");
  } catch (err) {
    throw new Error(
      "@vercel/blob is not installed. Run `npm install @vercel/blob` " +
        "before invoking this script. " + err.message,
    );
  }
}


export async function uploadSnapshot({
  sourcePath = DEFAULT_SOURCE,
  date = todayUtcIso(),
  dryRun = false,
  token = process.env[TOKEN_ENV],
  blobApi = null,        // injectable for tests
} = {}) {
  if (!existsSync(sourcePath)) {
    throw new Error(`Source file not found: ${sourcePath}`);
  }
  const bytes = readFileSync(sourcePath);
  const size = statSync(sourcePath).size;
  const key = snapshotKey(date);

  console.log(
    `[snapshot] source=${sourcePath} size=${size}B key=${key} dryRun=${dryRun}`,
  );

  if (dryRun) {
    return { uploaded: false, key, size, reason: "dry_run" };
  }
  if (!token) {
    console.warn(
      `[snapshot] ${TOKEN_ENV} not set — skipping upload (no-op). ` +
        "Configure the secret to enable durable backups.",
    );
    return { uploaded: false, key, size, reason: "no_token" };
  }

  const api = blobApi || (await loadBlobSdk());
  // addRandomSuffix=false so the URL is deterministic (snapshots/ranked-YYYY-MM-DD.json),
  // allowAccess=public so the restore path doesn't need the token. The data is the
  // same ranked.json the frontend already reads — no new exposure surface.
  // contentType set so blob storage reports the right MIME for direct fetch.
  const result = await api.put(key, bytes, {
    access: "public",
    addRandomSuffix: false,
    contentType: "application/json",
    token,
  });
  console.log(`[snapshot] uploaded url=${result.url}`);
  return { uploaded: true, key, size, url: result.url };
}


export async function pruneOldSnapshots({
  olderThanDays,
  token = process.env[TOKEN_ENV],
  blobApi = null,
  now = new Date(),
} = {}) {
  if (!Number.isFinite(olderThanDays) || olderThanDays <= 0) {
    throw new Error("olderThanDays must be a positive integer");
  }
  if (!token) {
    console.warn(`[snapshot:prune] ${TOKEN_ENV} not set — skipping`);
    return { pruned: 0, kept: 0, reason: "no_token" };
  }
  const api = blobApi || (await loadBlobSdk());
  const cutoffMs = now.getTime() - olderThanDays * 24 * 60 * 60 * 1000;

  const listing = await api.list({ prefix: SNAPSHOT_PREFIX, token });
  let pruned = 0;
  let kept = 0;
  for (const blob of listing.blobs || []) {
    // Date is parsed from the filename, not from the blob's uploadedAt —
    // a re-uploaded snapshot for an older date should still be subject
    // to retention based on the date it REPRESENTS, not when it was
    // last written.
    const m = /ranked-(\d{4}-\d{2}-\d{2})\.json$/.exec(blob.pathname);
    if (!m) {
      // Unknown shape — leave it alone. Surfaces "what is this?" rather
      // than silently deleting a manually-uploaded file.
      console.warn(`[snapshot:prune] skipping unrecognised blob: ${blob.pathname}`);
      kept++;
      continue;
    }
    const dateMs = new Date(`${m[1]}T00:00:00Z`).getTime();
    if (dateMs < cutoffMs) {
      console.log(`[snapshot:prune] deleting ${blob.pathname}`);
      await api.del(blob.url, { token });
      pruned++;
    } else {
      kept++;
    }
  }
  console.log(`[snapshot:prune] pruned=${pruned} kept=${kept}`);
  return { pruned, kept };
}


// Test-only — exposed for the unit tests so they don't have to dig
// through default-arg defaults.
export const _testing = {
  parseArgs,
  snapshotKey,
  todayUtcIso,
};


async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return 0;
  }

  try {
    if (args.pruneOlderThanDays != null) {
      await pruneOldSnapshots({ olderThanDays: args.pruneOlderThanDays });
    } else {
      await uploadSnapshot({ sourcePath: args.file, dryRun: args.dryRun });
    }
    return 0;
  } catch (err) {
    // Best-effort: never fail the nightly because backup failed.
    console.error(`[snapshot] FAILED: ${err.message}`);
    return 0;
  }
}


// Run only when invoked as a CLI; importable for tests.
if (import.meta.url === `file://${process.argv[1]}`) {
  main().then((code) => process.exit(code));
}
