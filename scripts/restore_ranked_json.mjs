#!/usr/bin/env node
/**
 * Restore web/data/ranked.json from a Vercel Blob snapshot.
 *
 * Companion to snapshot_ranked_json.mjs. Use when the most recent
 * nightly produced a corrupt or otherwise bad ranked.json and you
 * need to roll back to a known-good version. The snapshots are
 * public-read so this script doesn't need the write token — just the
 * snapshot date (or the latest, by default).
 *
 * The download writes to a tempfile in the same directory and then
 * `rename`s onto web/data/ranked.json so an interrupted run can't
 * leave the file half-written (matches the atomic-write pattern from
 * PR-1).
 *
 * Modes:
 *   node scripts/restore_ranked_json.mjs                  # latest snapshot
 *   node scripts/restore_ranked_json.mjs --date 2026-05-12
 *   node scripts/restore_ranked_json.mjs --list           # show available
 *   node scripts/restore_ranked_json.mjs --dry-run        # don't write
 *
 * For maintainers running this in an emergency: after the restore,
 * commit web/data/ranked.json and push directly (the data PR flow is
 * for nightly auto-pushes; an ops recovery is a manual commit).
 */
import { renameSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..");
const DEFAULT_TARGET = resolve(REPO_ROOT, "web/data/ranked.json");
const SNAPSHOT_PREFIX = "snapshots/";

const TOKEN_ENV = "BLOB_READ_WRITE_TOKEN";


function parseArgs(argv) {
  const out = { date: null, list: false, dryRun: false, target: DEFAULT_TARGET };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--date") out.date = argv[++i];
    else if (a === "--list") out.list = true;
    else if (a === "--dry-run") out.dryRun = true;
    else if (a === "--target") out.target = argv[++i];
    else if (a === "--help" || a === "-h") out.help = true;
    else throw new Error(`Unknown argument: ${a}`);
  }
  return out;
}


function printHelp() {
  console.log(
    [
      "Usage: restore_ranked_json.mjs [options]",
      "",
      "  (no args)                Restore from the most recent snapshot",
      "  --date YYYY-MM-DD        Restore from a specific date",
      "  --list                   Print available snapshots, newest first",
      "  --dry-run                Fetch + validate, do not write",
      "  --target PATH            Override write target (default: web/data/ranked.json)",
      "",
      `Environment: ${TOKEN_ENV} (only required for --list; reads are public)`,
    ].join("\n"),
  );
}


async function loadBlobSdk() {
  try {
    return await import("@vercel/blob");
  } catch (err) {
    throw new Error(
      "@vercel/blob is not installed. Run `npm install @vercel/blob`. " + err.message,
    );
  }
}


export async function listSnapshots({ token = process.env[TOKEN_ENV], blobApi = null } = {}) {
  if (!token) {
    throw new Error(`${TOKEN_ENV} required for listing snapshots`);
  }
  const api = blobApi || (await loadBlobSdk());
  const listing = await api.list({ prefix: SNAPSHOT_PREFIX, token });
  const snapshots = (listing.blobs || [])
    .map((b) => {
      const m = /ranked-(\d{4}-\d{2}-\d{2})\.json$/.exec(b.pathname);
      return m ? { date: m[1], url: b.url, size: b.size } : null;
    })
    .filter(Boolean)
    .sort((a, b) => (a.date < b.date ? 1 : -1));
  return snapshots;
}


export async function restoreSnapshot({
  date = null,
  target = DEFAULT_TARGET,
  dryRun = false,
  token = process.env[TOKEN_ENV],
  blobApi = null,
  fetchImpl = fetch,
} = {}) {
  let url;
  if (date) {
    // Reconstruct the public URL from the date. Vercel Blob public URLs
    // are deterministic when addRandomSuffix=false (the snapshot script
    // uses that), so we can build the URL without listing. If the
    // public URL pattern ever changes we fall through to listing.
    // For now we always list — it's one HTTP call and gives us the
    // exact URL Blob assigned.
    if (!token) {
      throw new Error(
        `${TOKEN_ENV} required to find a snapshot by date. ` +
          "(Set the env var or pass --date with a known public URL.)",
      );
    }
    const all = await listSnapshots({ token, blobApi });
    const hit = all.find((s) => s.date === date);
    if (!hit) {
      throw new Error(`No snapshot for date ${date}. Use --list to see what's available.`);
    }
    url = hit.url;
  } else {
    if (!token) {
      throw new Error(`${TOKEN_ENV} required to find the latest snapshot`);
    }
    const all = await listSnapshots({ token, blobApi });
    if (all.length === 0) throw new Error("No snapshots available");
    url = all[0].url;
    date = all[0].date;
  }

  console.log(`[restore] fetching ${url}`);
  const resp = await fetchImpl(url);
  if (!resp.ok) {
    throw new Error(`Fetch failed: HTTP ${resp.status} from ${url}`);
  }
  const text = await resp.text();
  // Validate it parses as an array (ranked.json shape) so we don't
  // overwrite the prod file with garbage.
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    throw new Error(`Snapshot ${url} is not valid JSON: ${err.message}`);
  }
  if (!Array.isArray(parsed)) {
    throw new Error(
      `Snapshot ${url} root is ${typeof parsed}, expected array (ranked.json shape)`,
    );
  }
  console.log(`[restore] snapshot validated: date=${date} entries=${parsed.length}`);

  if (dryRun) {
    console.log("[restore] dry-run — not writing");
    return { restored: false, date, entries: parsed.length, reason: "dry_run" };
  }

  mkdirSync(dirname(target), { recursive: true });
  const tmp = `${target}.tmp.${process.pid}`;
  writeFileSync(tmp, text, "utf8");
  renameSync(tmp, target);
  console.log(`[restore] wrote ${target} (${text.length} bytes)`);
  return { restored: true, date, entries: parsed.length, target };
}


async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return 0;
  }
  try {
    if (args.list) {
      const all = await listSnapshots();
      if (all.length === 0) {
        console.log("(no snapshots available)");
        return 0;
      }
      for (const s of all) {
        console.log(`${s.date}  ${s.size}B  ${s.url}`);
      }
      return 0;
    }
    await restoreSnapshot({ date: args.date, target: args.target, dryRun: args.dryRun });
    return 0;
  } catch (err) {
    console.error(`[restore] FAILED: ${err.message}`);
    return 1;
  }
}


if (import.meta.url === `file://${process.argv[1]}`) {
  main().then((code) => process.exit(code));
}
