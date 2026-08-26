// api/_core.js — the shared core, reachable from a serverless function.
//
// Vercel compiles TypeScript functions only for files INSIDE api/, so a
// .ts function that imports shared/ directly is never given the
// compiled dependency and dies at load with
// FUNCTION_INVOCATION_FAILED. A CommonJS `require()` across the same
// boundary works fine, because those are resolved by Vercel's file
// tracer rather than the TypeScript compiler.
//
// So this file is the doorway: CommonJS, inside api/, requiring the
// prebuilt bundle. Functions import from HERE, never from ../../shared.
//
//   api/v1/*.ts  --import-->  api/_core.js  --require-->  shared/dist/api-core.cjs
//
// The bundle is produced by scripts/build_shared_cjs.mjs during
// `npm run build` and is self-contained (no external imports), so
// nothing depends on the tracer following a chain of relative requires
// out of api/.
//
// Types come from _core.d.ts, which re-exports from the shared SOURCE.
// That is safe because type declarations are erased at compile time and
// never loaded at runtime — the boundary rule only applies to values.
//
// If this throws "Cannot find module", the build step did not run:
// check that `npm run build` still ends with build_shared_cjs.mjs.

module.exports = require("../shared/dist/api-core.cjs");
