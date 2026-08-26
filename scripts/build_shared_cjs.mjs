// Compile the shared core into a single CommonJS bundle for the
// serverless functions.
//
// Vercel compiles TypeScript functions only for files inside api/, so a
// .ts function importing shared/ crashes at load (see
// shared/api-core.ts for the full story). CommonJS `require()` across
// that boundary works, so we hand the functions a prebuilt .cjs.
//
// Bundling rather than transpiling file-by-file is deliberate: the
// output has ZERO external imports, so nothing depends on Vercel's file
// tracer following a chain of relative requires out of api/.
//
// Runs from `npm run build`, before Vercel compiles the functions —
// confirmed by deploy logs, where function compilation happens after
// the build command completes.

import { build } from "esbuild";
import { mkdirSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const entry = resolve(root, "shared/api-core.ts");
const outfile = resolve(root, "shared/dist/api-core.cjs");

mkdirSync(dirname(outfile), { recursive: true });

await build({
  entryPoints: [entry],
  outfile,
  bundle: true,
  platform: "node",
  target: "node20",
  format: "cjs",
  // Self-contained on purpose: no externals, so the deployed function
  // needs nothing but this one file.
  external: [],
  logLevel: "warning",
});

const { size } = statSync(outfile);
console.log(`[build_shared_cjs] wrote ${outfile} — ${(size / 1024).toFixed(1)} kB`);
