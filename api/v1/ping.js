// GET /api/v1/ping — liveness probe AND the deploy-risk spike.
//
// Why this endpoint exists beyond "is it up":
//
// The repo has a documented module-format hazard. Root package.json is
// `"type": "module"`, and `api/package.json` deliberately overrides it
// back to `"commonjs"` because every `api/*.js` function is written in
// CJS (see the `_comment` field in that file for the incident). The v1
// API layer is TypeScript, which Vercel compiles with esbuild — and it
// needs to import BOTH:
//
//   1. `shared/*.ts`  — ESM TypeScript outside the api/ tree
//   2. `api/_*.js`    — the existing CommonJS helpers
//
// If that import chain does not survive Vercel's bundler, the entire
// API layer needs to be `.mjs` + JSDoc instead. This endpoint exercises
// both import styles on purpose, so one curl against a preview settles
// it before any real capability code is written on top.
//
// Response: { ok, version, runtime, now }
// Cache: none — a cached liveness probe tells you nothing.


// Generous: this is a probe, not a capability. The limiter exists so a
// scanner cannot spin up unbounded function invocations.

// CommonJS, not TypeScript: a .ts function cannot reach outside api/ at
// any depth, and this needs the shared core (docs/api-v1.md).
const { API_VERSION } = require("../_core.js");
const { makeRateLimiter, ipFromRequest, send429 } = require("../_rate_limit.js");
const { methodNotAllowed, logApi } = require("./_http.js");

const limiter = makeRateLimiter({
  windowMs: 60_000,
  maxAttempts: 120,
  name: "v1_ping",
});

module.exports = function handler(req, res) {
  const t0 = Date.now();

  if (req.method !== "GET") return methodNotAllowed(res, "GET");

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) return send429(res, rl, "v1_ping");

  // Proves the CJS helper actually executed, not just that it imported.
  res.setHeader("Cache-Control", "no-store");
  logApi("v1_ping", { status: 200, ms: Date.now() - t0 });

  return res.status(200).json({
    ok: true,
    version: API_VERSION,
    runtime: "node",
    now: new Date().toISOString(),
  });
};
